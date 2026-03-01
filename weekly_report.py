#!/usr/bin/env python3
"""Weekly report generator — runs on host Mac, not in Docker.

1. Finds Daily Report notes from the past 7 days in Obsidian.
2. Synthesizes them with Claude into a formatted weekly report.
3. Saves the report to Obsidian (Audio Summaries/Weekly Report Summaries/).
4. Emails it as styled HTML via Yahoo SMTP.

Schedule: every Tuesday at 10:00 AM via launchd.
"""

import os
import re
import sys
import logging
import smtplib
import subprocess
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests
import anthropic

# ---------------------------------------------------------------------------
# Logging — stdout is redirected to weekly_report.log by launchd
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

OBSIDIAN_FOLDER         = "Audio Summaries"
WEEKLY_REPORT_SUBFOLDER = "Weekly Report Summaries"

RECIPIENT  = "Christopher.Holzer@Williams.com"
SMTP_HOST  = os.environ.get("SMTP_HOST", "")
SMTP_PORT  = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER  = os.environ.get("SMTP_USER", "")
SMTP_PASS  = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM  = os.environ.get("SMTP_FROM", SMTP_USER)

LOOKBACK_DAYS = 7
CLAUDE_MODEL  = "claude-sonnet-4-6"

# Compute date window once at startup
NOW           = datetime.now()
START_DATE    = NOW - timedelta(days=LOOKBACK_DAYS)
END_DATE      = NOW - timedelta(days=1)
START_DATE_STR = START_DATE.strftime("%m-%d-%Y")
END_DATE_STR   = END_DATE.strftime("%m-%d-%Y")

REPORT_TITLE    = f"Weekly Report \u2014 {START_DATE_STR} to {END_DATE_STR}"
REPORT_FILENAME = f"Weekly Report - {NOW.strftime('%m-%d-%Y')}.md"
REPORT_VAULT_PATH = (
    f"{OBSIDIAN_FOLDER}/{WEEKLY_REPORT_SUBFOLDER}/{REPORT_FILENAME}"
)


# ---------------------------------------------------------------------------
# Claude synthesis prompt
# ---------------------------------------------------------------------------
def make_synthesis_prompt(start: str, end: str) -> str:
    return f"""You are synthesizing daily operational reports into a single weekly report.

Compile all daily reports provided into a single markdown document using the following exact format:

# Weekly Report \u2014 {start} to {end}

## Notable Recognitions from Team
[Summarize any team member shoutouts, achievements, or recognition mentioned across the daily reports]

## Significant Operational Events
[Summarize major incidents, outages, changes, or notable operational happenings from the week]

## Team Support Needs
[List only current or upcoming support needs, active blockers, or resource requests that are still open. Do not report on past support events that have already been resolved.]

## Upcoming Maintenance or Major Tasks
[Summarize any scheduled maintenance, planned work, or major upcoming tasks mentioned]

## Additional Information
[Include only information that is directly relevant to the report \u2014 operational, team, or task-related \u2014 that does not fit the above categories. Omit anything that is not pertinent to the work being reported on.]

Writing rules (apply to every section):
- Each entry is a short paragraph, no more than 4 sentences.
- Follow this structure for every paragraph:
  - Topic: Begin with the date in Month-Day format (e.g., "Feb 22 \u2014"), followed by a brief description of the topic. Do not restate context already implied by the section heading.
  - Actions: State any actions taken or repairs made related to the topic.
  - Follow-up: State any actions mentioned that are still pending or will be completed. If none were mentioned, omit this sentence entirely.
- Do not add filler, restate the section heading, or pad with transitional phrases.
- In the Team Support Needs section specifically: Topic should describe the current need or active blocker, Actions should describe any steps already taken toward resolving it, and Follow-up should describe what is still required to close it out.
- If a section has no relevant content from the daily reports, write "No items reported this week."

Output only the markdown document. Do not include any preamble or explanation."""


# ---------------------------------------------------------------------------
# Obsidian REST API helpers
# ---------------------------------------------------------------------------
def _obsidian_headers():
    return {"Authorization": f"Bearer {OBSIDIAN_API_KEY}"}


def list_notes(folder: str) -> list:
    """Return list of bare filenames in the given vault folder."""
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
    """Fetch full markdown content of a note by its full vault path."""
    url = f"{OBSIDIAN_BASE_URL}/vault/{path}"
    try:
        resp = requests.get(url, headers=_obsidian_headers(), timeout=30)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        log.error("Failed to fetch note %s: %s", path, e)
        return ""


def move_note(src_path: str, dest_folder: str) -> bool:
    """Move a note to dest_folder by copying then deleting the original."""
    filename = os.path.basename(src_path)
    dest_path = f"{dest_folder}/{filename}"
    content = fetch_note(src_path)
    if not content:
        log.warning("Skipping move — could not fetch: %s", src_path)
        return False
    if not save_note(dest_path, content):
        log.warning("Skipping move — failed to write destination: %s", dest_path)
        return False
    url = f"{OBSIDIAN_BASE_URL}/vault/{src_path}"
    try:
        resp = requests.delete(url, headers=_obsidian_headers(), timeout=30)
        if resp.status_code in (200, 204):
            log.info("Moved %s → %s", src_path, dest_path)
            return True
        log.warning("Delete failed HTTP %d for: %s", resp.status_code, src_path)
        return False
    except Exception as e:
        log.error("Failed to delete %s: %s", src_path, e)
        return False


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
# Date filtering
# ---------------------------------------------------------------------------
def parse_date_from_filename(filename: str) -> Optional[datetime]:
    """Parse date prefix from: MM-DD-YYYY - name.md  or  MM-DD-YY - name.md"""
    basename = os.path.basename(filename)
    name = basename[:-3] if basename.endswith(".md") else basename
    parts = name.split(" - ", 1)
    if len(parts) < 2:
        return None
    prefix = parts[0].strip()
    for fmt in ("%m-%d-%Y", "%m-%d-%y"):
        try:
            return datetime.strptime(prefix, fmt)
        except ValueError:
            continue
    return None


def is_daily_report(filename: str) -> bool:
    return "daily report" in os.path.basename(filename).lower()


def is_within_lookback(dt: datetime) -> bool:
    return dt >= (NOW - timedelta(days=LOOKBACK_DAYS))


# ---------------------------------------------------------------------------
# Claude synthesis
# ---------------------------------------------------------------------------
def synthesize_with_claude(notes: list) -> str:
    combined = []
    for path, content in notes:
        combined.append(f"### {os.path.basename(path)}\n\n{content}")
    notes_text = "\n\n---\n\n".join(combined)

    prompt = make_synthesis_prompt(START_DATE_STR, END_DATE_STR)

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
    """Convert the structured report markdown to HTML for the email body."""
    html = []
    in_list = False

    for line in md.split("\n"):
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
        elif re.match(r"^[-*] ", line):
            if not in_list:
                html.append("<ul>"); in_list = True
            content = _inline(line[2:].strip())
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
    return text


def _build_html(subject: str, body_md: str) -> str:
    body_html = _markdown_to_html(body_md)
    generated = datetime.now().strftime("%B %d, %Y")
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
  <div class="footer">Audio Pipeline &mdash; Weekly Report</div>
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
        log.warning("SMTP not configured — falling back to plain text via Apple Mail")
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
        log.error("SMTP failed (%s) — falling back to Apple Mail", e)
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
    log.info("Weekly report job starting")
    log.info("Period: %s to %s", START_DATE_STR, END_DATE_STR)

    # 1. List all notes in Audio Summaries/
    all_files = list_notes(OBSIDIAN_FOLDER)
    log.info("Found %d total files in '%s'", len(all_files), OBSIDIAN_FOLDER)

    # 2. Filter to Daily Report notes within the lookback window
    matching = []
    for f in all_files:
        if not is_daily_report(f):
            continue
        dt = parse_date_from_filename(f)
        if dt is None:
            log.debug("Skipping (unrecognized date format): %s", f)
            continue
        if not is_within_lookback(dt):
            log.debug("Skipping (too old, %s): %s", dt.strftime("%Y-%m-%d"), f)
            continue
        matching.append((f, dt))

    if not matching:
        log.info(
            "No Daily Report notes found in the past %d days. Exiting without sending email.",
            LOOKBACK_DAYS,
        )
        return

    matching.sort(key=lambda x: x[1])
    log.info("Matched %d Daily Report note(s):", len(matching))
    for path, dt in matching:
        log.info("  %s  (%s)", os.path.basename(path), dt.strftime("%Y-%m-%d"))

    # 3. Fetch full content of each note (list_notes returns bare filenames)
    notes_with_content = []
    for path, _ in matching:
        vault_path = f"{OBSIDIAN_FOLDER}/{path}"
        content = fetch_note(vault_path)
        if content:
            notes_with_content.append((vault_path, content))
        else:
            log.warning("Empty or failed fetch for: %s", vault_path)

    if not notes_with_content:
        log.error("No note content could be fetched. Exiting without sending email.")
        sys.exit(1)

    # 4. Synthesize with Claude
    report_md = synthesize_with_claude(notes_with_content)
    log.info("Claude synthesis complete (%d chars)", len(report_md))

    # 5. Save synthesized report to Obsidian
    saved = save_note(REPORT_VAULT_PATH, report_md)
    if not saved:
        log.warning("Failed to save report to Obsidian \u2014 will still attempt email.")

    # 6. Archive the daily reports that were included in the weekly report
    log.info("Archiving %d daily report(s) to 'Plaud Notes Archive'...", len(notes_with_content))
    for vault_path, _ in notes_with_content:
        move_note(vault_path, "Plaud Notes Archive")

    # 7. Email the report (use the in-memory markdown, not a re-read from Obsidian)
    send_email(subject=REPORT_TITLE, body=report_md)
    log.info("Weekly report job complete.")


if __name__ == "__main__":
    main()
