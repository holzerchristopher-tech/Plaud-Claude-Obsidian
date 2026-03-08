#!/usr/bin/env python3
"""Daily report generator — runs on host Mac, not in Docker.

1. Finds all audio summary notes from today in Audio Summaries/.
2. Synthesizes them with Claude into a structured Daily Report.
3. Saves the report to Obsidian (Audio Summaries/).
4. Emails it as styled HTML.

Schedule: every day at 11:00 PM via launchd.
"""

import os
import re
import sys
import logging
import smtplib
import subprocess
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests
import anthropic

# ---------------------------------------------------------------------------
# Logging — stdout is redirected to daily_report.log by launchd
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# .env loader (no external deps)
# ---------------------------------------------------------------------------
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())
    except FileNotFoundError:
        log.warning(".env file not found at %s", env_path)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
load_env()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
OBSIDIAN_API_KEY  = os.environ["OBSIDIAN_API_KEY"]
OBSIDIAN_HOST     = "localhost"
OBSIDIAN_PORT     = os.environ.get("OBSIDIAN_PORT", "27123")
OBSIDIAN_BASE_URL = f"http://{OBSIDIAN_HOST}:{OBSIDIAN_PORT}"

OBSIDIAN_FOLDER = "Audio Summaries"

RECIPIENT = "Christopher.Holzer@Williams.com"
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)

CLAUDE_MODEL = "claude-sonnet-4-6"

# Compute date strings once at startup
# Override with REPORT_DATE=YYYY-MM-DD env var for backfills
_date_override = os.environ.get("REPORT_DATE")
NOW   = datetime.strptime(_date_override, "%Y-%m-%d") if _date_override else datetime.now()
TODAY     = NOW.date()
DATE_STR  = f"{NOW.month}-{NOW.day}-{NOW.year}"          # e.g. "3-7-2026"
DATE_LONG = f"{NOW.strftime('%B')} {NOW.day}, {NOW.year}" # e.g. "March 7, 2026"

REPORT_TITLE      = f"Daily Report \u2014 {DATE_LONG}"
REPORT_FILENAME   = f"{DATE_STR}-Daily Report.md"
REPORT_VAULT_PATH = f"{OBSIDIAN_FOLDER}/{REPORT_FILENAME}"


# ---------------------------------------------------------------------------
# Claude synthesis prompt
# ---------------------------------------------------------------------------
def make_synthesis_prompt() -> str:
    return f"""You are compiling multiple audio summary notes recorded today into a single structured Daily Report.

Today's date: {DATE_LONG}

Combine all notes provided into a single markdown document using this exact format:

# \U0001F4CB Daily Report \u2014 {DATE_LONG}

---

## \U0001F4DD Overview
[2-4 sentence summary of the day's key topics across all notes]

---

[For each distinct topic or source note, create a section:]

## [Relevant emoji] [Topic Title]

[Brief summary paragraph \u2014 1-3 sentences]

### Key Points
- [bullet points with specific details, numbers, unit names]

### Action Items
- [ ] [pending action items from this topic only]

---

## \u2705 All Action Items

[Consolidated, deduplicated list of every open action item from all sections, grouped by topic]

---

## \U0001F517 Related Notes

[Obsidian wiki-links for each source note, one per line, format: - [[filename without .md]]]

---

Writing rules:
- Be concise and direct \u2014 operational report, not an essay.
- Use relevant emojis for section headers (\U0001F6A8 incidents, \u2699\ufe0f equipment, \U0001F4B0 financial, \U0001F4DE calls, \U0001F4CC general notes).
- Preserve all specific numbers, unit IDs, facility names, dollar amounts, and dates exactly as stated.
- Consolidate duplicate action items; do not repeat them.
- If a note covers non-operational content (goals, brainstorming), include it but label it clearly.
- Do not add filler, preamble, or transitional phrases.
- Output only the markdown document \u2014 no explanation before or after."""


# ---------------------------------------------------------------------------
# Obsidian REST API helpers
# ---------------------------------------------------------------------------
def _obsidian_headers():
    return {"Authorization": f"Bearer {OBSIDIAN_API_KEY}"}


def list_notes(folder: str) -> list:
    """Return list of filenames in the given vault folder."""
    url = f"{OBSIDIAN_BASE_URL}/vault/{folder}/"
    try:
        resp = requests.get(url, headers=_obsidian_headers(), timeout=30)
        resp.raise_for_status()
        return resp.json().get("files", [])
    except requests.exceptions.ConnectionError:
        log.error("Cannot connect to Obsidian at %s \u2014 is Obsidian running?", OBSIDIAN_BASE_URL)
        sys.exit(1)
    except requests.exceptions.Timeout:
        log.error("Obsidian API timed out listing folder: %s", folder)
        sys.exit(1)
    except Exception as e:
        log.error("Obsidian list_notes error: %s", e)
        sys.exit(1)


def fetch_note(path: str) -> str:
    """Fetch full markdown content of a note by its vault path."""
    url = f"{OBSIDIAN_BASE_URL}/vault/{path}"
    try:
        resp = requests.get(url, headers=_obsidian_headers(), timeout=30)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        log.error("Failed to fetch note %s: %s", path, e)
        return ""


def save_note(path: str, content: str) -> bool:
    """Save markdown content to the vault at the given path."""
    url = f"{OBSIDIAN_BASE_URL}/vault/{path}"
    try:
        resp = requests.put(
            url,
            headers={**_obsidian_headers(), "Content-Type": "text/markdown"},
            data=content.encode("utf-8"),
            timeout=30,
        )
        success = resp.status_code in (200, 201, 204)
        log.info("Obsidian save \u2192 HTTP %d | %s", resp.status_code, path)
        if not success:
            log.error("Obsidian save error: %s", resp.text[:300])
        return success
    except Exception as e:
        log.error("Failed to save note %s: %s", path, e)
        return False


# ---------------------------------------------------------------------------
# Date / filename helpers
# ---------------------------------------------------------------------------
def parse_date_from_filename(filename: str) -> Optional[datetime]:
    """Parse date prefix from filenames like:
      M-D-YYYY-name.md
      M-D-YY-name.md
      M-D-YYYY - name.md
      M-D-YY - name.md
    """
    basename = os.path.basename(filename)
    name = basename[:-3] if basename.endswith(".md") else basename
    m = re.match(r'^(\d{1,2}-\d{1,2}-\d{2,4})(?:\s+-\s+|-(?=\D))', name)
    if not m:
        return None
    prefix = m.group(1)
    for fmt in ("%m-%d-%Y", "%m-%d-%y"):
        try:
            return datetime.strptime(prefix, fmt)
        except ValueError:
            continue
    return None


def is_today(filename: str) -> bool:
    dt = parse_date_from_filename(filename)
    return dt is not None and dt.date() == TODAY


def is_daily_report(filename: str) -> bool:
    return "daily report" in os.path.basename(filename).lower()


def is_markdown(filename: str) -> bool:
    return os.path.basename(filename).endswith(".md")


# ---------------------------------------------------------------------------
# Build final report with frontmatter
# ---------------------------------------------------------------------------
def build_report_with_frontmatter(body: str, source_paths: list) -> str:
    sources_yaml = "\n".join(
        f"  - {os.path.basename(p)}" for p in source_paths
    )
    frontmatter = (
        f"---\n"
        f'title: "Daily Report - {DATE_LONG}"\n'
        f"date: {TODAY.isoformat()}\n"
        f"tags:\n"
        f"  - daily-report\n"
        f"  - audio-summary\n"
        f"type: daily-report\n"
        f"sources:\n"
        f"{sources_yaml}\n"
        f"---\n\n"
    )
    return frontmatter + body


# ---------------------------------------------------------------------------
# Claude synthesis
# ---------------------------------------------------------------------------
def synthesize_with_claude(notes: list) -> str:
    combined = []
    for path, content in notes:
        combined.append(f"### {os.path.basename(path)}\n\n{content}")
    notes_text = "\n\n---\n\n".join(combined)

    prompt = make_synthesis_prompt()

    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        timeout=anthropic.Timeout(connect=10.0, read=300.0, write=30.0, pool=5.0),
    )

    log.info("Sending %d note(s) to Claude for synthesis...", len(notes))
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": f"{prompt}\n\n---\n\n{notes_text}"}],
        )
    except anthropic.APITimeoutError:
        log.error("Claude API timed out during synthesis")
        sys.exit(1)
    except anthropic.APIConnectionError as e:
        log.error("Claude API connection error: %s", e)
        sys.exit(1)
    except Exception as e:
        log.error("Claude API error: %s", e)
        sys.exit(1)

    return response.content[0].text


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def _markdown_to_html(md: str) -> str:
    html = []
    in_list = False

    for line in md.split("\n"):
        # Skip YAML frontmatter lines
        if line.startswith("---") or line.startswith("title:") or line.startswith("date:") \
                or line.startswith("tags:") or line.startswith("type:") \
                or line.startswith("sources:") or re.match(r"^  - ", line):
            continue
        if line.startswith("# "):
            if in_list:
                html.append("</ul>"); in_list = False
            html.append(f'<h1>{line[2:].strip()}</h1>')
        elif line.startswith("## "):
            if in_list:
                html.append("</ul>"); in_list = False
            html.append(f'<h2>{line[3:].strip()}</h2>')
        elif line.startswith("### "):
            if in_list:
                html.append("</ul>"); in_list = False
            html.append(f'<h3>{line[4:].strip()}</h3>')
        elif re.match(r"^-\s+\[.\]\s+", line) or re.match(r"^[-*]\s+", line):
            if not in_list:
                html.append("<ul>"); in_list = True
            content = _inline(re.sub(r"^[-*]\s+(\[.\]\s+)?", "", line))
            html.append(f"<li>{content}</li>")
        elif line.strip() == "":
            if in_list:
                html.append("</ul>"); in_list = False
            html.append("")
        else:
            if in_list:
                html.append("</ul>"); in_list = False
            html.append(f"<p>{_inline(line.strip())}</p>")

    if in_list:
        html.append("</ul>")
    return "\n".join(html)


def _inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         text)
    text = re.sub(r"\[\[(.+?)\]\]", r"\1", text)  # strip Obsidian wiki-links
    return text


def _build_html(subject: str, body_md: str) -> str:
    body_html = _markdown_to_html(body_md)
    generated = f"{NOW.strftime('%B')} {NOW.day}, {NOW.year} at {NOW.strftime('%-I:%M %p')}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body      {{ margin:0; padding:0; background:#f0f2f5; font-family:-apple-system,Arial,sans-serif; }}
  .wrap     {{ max-width:680px; margin:32px auto; background:#fff; border-radius:8px; overflow:hidden;
               box-shadow:0 2px 8px rgba(0,0,0,.12); }}
  .header   {{ background:#1a2332; padding:32px 40px; }}
  .header h1{{ margin:0; color:#fff; font-size:20px; font-weight:700; letter-spacing:.01em; }}
  .header p {{ margin:6px 0 0; color:#7a9cbf; font-size:13px; }}
  .body     {{ padding:28px 40px 36px; color:#1a1a1a; }}
  h1        {{ font-size:20px; color:#1a2332; margin-top:0; }}
  h2        {{ font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:.08em;
               color:#fff; background:#1a2332; padding:6px 12px; border-radius:4px;
               margin:32px 0 14px; }}
  h3        {{ font-size:14px; color:#1a2332; margin:20px 0 6px; }}
  p         {{ font-size:14px; line-height:1.7; color:#333; margin:0 0 12px; }}
  ul        {{ padding-left:20px; margin:0 0 12px; }}
  li        {{ font-size:14px; line-height:1.7; color:#333; margin-bottom:4px; }}
  strong    {{ color:#1a2332; }}
  .footer   {{ background:#f0f2f5; padding:14px 40px; text-align:center;
               color:#999; font-size:11px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>{subject}</h1>
    <p>Generated {generated}</p>
  </div>
  <div class="body">
    {body_html}
  </div>
  <div class="footer">Audio Pipeline &mdash; Daily Report</div>
</div>
</body>
</html>"""


def _send_via_apple_mail(subject: str, body: str) -> None:
    safe_subject = subject.replace("\\", "\\\\").replace('"', '\\"')
    safe_body    = body.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        'tell application "Mail"\n'
        f'    set msg to make new outgoing message with properties'
        f' {{subject:"{safe_subject}", content:"{safe_body}", visible:false}}\n'
        '    tell msg\n'
        f'        make new to recipient with properties {{address:"{RECIPIENT}"}}\n'
        '    end tell\n'
        '    send msg\n'
        'end tell'
    )
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True)


def send_email(subject: str, body: str) -> None:
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS]):
        log.warning("SMTP not configured \u2014 falling back to plain text via Apple Mail")
        try:
            _send_via_apple_mail(subject, body)
            log.info("Email sent via Apple Mail.")
        except subprocess.CalledProcessError as e:
            log.error("Apple Mail send failed: %s", e.stderr)
            sys.exit(1)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_FROM
    msg["To"]      = RECIPIENT
    msg.attach(MIMEText(body, "plain"))
    msg.attach(MIMEText(_build_html(subject, body), "html"))

    log.info("Sending HTML email to %s via %s...", RECIPIENT, SMTP_HOST)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, RECIPIENT, msg.as_string())
        log.info("Email sent successfully.")
    except Exception as e:
        log.error("SMTP failed (%s) \u2014 falling back to Apple Mail", e)
        try:
            _send_via_apple_mail(subject, body)
            log.info("Email sent via Apple Mail fallback.")
        except subprocess.CalledProcessError as ae:
            log.error("Apple Mail fallback also failed: %s", ae.stderr)
            sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info("=" * 60)
    log.info("Daily report job starting")
    log.info("Date: %s", DATE_LONG)

    # 1. List all files in Audio Summaries/
    all_files = list_notes(OBSIDIAN_FOLDER)
    log.info("Found %d total files in '%s'", len(all_files), OBSIDIAN_FOLDER)

    # 2. Filter to today's audio summary notes (exclude daily reports and non-markdown)
    matching = []
    for f in all_files:
        if not is_markdown(f):
            log.debug("Skipping (not a markdown file): %s", f)
            continue
        if is_daily_report(f):
            log.debug("Skipping (already a daily report): %s", f)
            continue
        if not is_today(f):
            log.debug("Skipping (not today): %s", f)
            continue
        matching.append(f)

    if not matching:
        log.info(
            "No audio summary notes found for today (%s). Exiting without sending email.",
            DATE_STR,
        )
        return

    matching.sort()
    log.info("Found %d note(s) for today:", len(matching))
    for f in matching:
        log.info("  %s", f)

    # 3. Fetch full content of each note
    notes_with_content = []
    for filename in matching:
        vault_path = f"{OBSIDIAN_FOLDER}/{filename}"
        content = fetch_note(vault_path)
        if content:
            notes_with_content.append((vault_path, content))
        else:
            log.warning("Empty or failed fetch: %s", vault_path)

    if not notes_with_content:
        log.error("No note content could be fetched. Exiting.")
        sys.exit(1)

    # 4. Synthesize with Claude
    report_body = synthesize_with_claude(notes_with_content)
    log.info("Claude synthesis complete (%d chars)", len(report_body))

    # 5. Prepend YAML frontmatter
    source_paths = [path for path, _ in notes_with_content]
    report_md = build_report_with_frontmatter(report_body, source_paths)

    # 6. Save to Obsidian
    saved = save_note(REPORT_VAULT_PATH, report_md)
    if not saved:
        log.warning("Failed to save report to Obsidian \u2014 will still attempt email.")

    # 7. Email the report
    send_email(subject=REPORT_TITLE, body=report_md)
    log.info("Daily report job complete.")


if __name__ == "__main__":
    main()
