import anthropic
import mlx_whisper
import os
import json
import tempfile
import subprocess
import numpy as np
import torch
import requests
import threading
import concurrent.futures
from datetime import datetime
import wave
from silero_vad import load_silero_vad, get_speech_timestamps, collect_chunks

MLX_WHISPER_MODEL = "mlx-community/whisper-small-mlx"

print("Loading Silero VAD model...")
vad_model = load_silero_vad()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
OBSIDIAN_API_KEY = os.environ["OBSIDIAN_API_KEY"]
OBSIDIAN_HOST = os.environ.get("OBSIDIAN_HOST", "localhost")
OBSIDIAN_PORT = os.environ.get("OBSIDIAN_PORT", "27123")
OBSIDIAN_BASE_URL = f"http://{OBSIDIAN_HOST}:{OBSIDIAN_PORT}"
BARK_KEY = os.environ.get("BARK_KEY", "")
BARK_SERVER = os.environ.get("BARK_SERVER", "https://api.day.app")
ARCHIVE_DIR = os.path.join(os.path.expanduser("~"), "AudioProcessing", "processed")

# Timeout settings — adjust these based on your audio file lengths
WHISPER_TIMEOUT_SECONDS = 5400  # 90 min max for transcription
CLAUDE_TIMEOUT_SECONDS = 900    # 15 min max for Claude response (allow for large transcripts)
OBSIDIAN_TIMEOUT_SECONDS = 30   # 30 sec max for Obsidian API calls

# Module-level Anthropic client (shared across all file processing)
anthropic_client = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY,
    timeout=anthropic.Timeout(
        connect=10.0,
        read=CLAUDE_TIMEOUT_SECONDS,
        write=30.0,
        pool=5.0
    )
)

# Module-level requests session for Obsidian API
obsidian_session = requests.Session()
obsidian_session.headers.update({"Authorization": f"Bearer {OBSIDIAN_API_KEY}"})


def load_audio_16k(file_path):
    """Load any audio format as a 16kHz mono float32 tensor via ffmpeg.

    Bypasses torchaudio audio I/O (broken in torchaudio >= 2.9) by piping
    raw PCM data directly from ffmpeg into a torch tensor.
    """
    cmd = [
        "ffmpeg", "-y", "-i", file_path,
        "-ar", "16000",   # resample to 16kHz
        "-ac", "1",       # mono
        "-f", "f32le",    # raw 32-bit float little-endian
        "-"               # output to stdout
    ]
    result = subprocess.run(cmd, capture_output=True, check=True)
    audio = np.frombuffer(result.stdout, dtype=np.float32).copy()
    return torch.from_numpy(audio)


def save_audio_wav(path, audio_tensor, sampling_rate=16000):
    """Save a 1D float32 torch tensor as a 16-bit WAV using stdlib wave module.

    Avoids torchaudio save (broken in torchaudio >= 2.9 without torchcodec).
    """
    audio_int16 = (np.clip(audio_tensor.numpy(), -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sampling_rate)
        wf.writeframes(audio_int16.tobytes())


def strip_silence(file_path):
    """Use Silero VAD to remove non-speech segments before transcription.

    Returns (path, is_temp) where path is either the original file or a
    cleaned temp WAV, and is_temp indicates whether the caller must delete it.
    Falls back to the original file on any error.
    """
    SAMPLING_RATE = 16000
    try:
        wav = load_audio_16k(file_path)
        speech_timestamps = get_speech_timestamps(
            wav,
            vad_model,
            sampling_rate=SAMPLING_RATE,
            threshold=0.5,
            min_speech_duration_ms=250,
            min_silence_duration_ms=200,
            speech_pad_ms=200,
        )

        if not speech_timestamps:
            print("[VAD] No speech detected, using original file")
            return file_path, False

        total_samples = len(wav)
        speech_samples = sum(ts["end"] - ts["start"] for ts in speech_timestamps)
        kept_pct = 100.0 * speech_samples / total_samples

        if kept_pct > 95:
            print(f"[VAD] Only {100 - kept_pct:.1f}% silence found, using original file")
            return file_path, False

        print(f"[VAD] Kept {kept_pct:.1f}% of audio ({len(speech_timestamps)} speech segments)")
        speech_audio = collect_chunks(speech_timestamps, wav)
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = tmp.name
        tmp.close()
        save_audio_wav(tmp_path, speech_audio, SAMPLING_RATE)
        return tmp_path, True

    except Exception as e:
        print(f"[VAD] Failed ({e}), using original file")
        return file_path, False


def transcribe_audio(file_path):
    """Run Whisper in a thread with a timeout so it can't hang forever."""
    print(f"[TRANSCRIBING] {file_path}")

    cleaned_path, is_temp = strip_silence(file_path)

    # mlx-whisper requires a WAV file; convert the original if VAD was skipped
    if not is_temp:
        try:
            wav = load_audio_16k(file_path)
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_path = tmp.name
            tmp.close()
            save_audio_wav(tmp_path, wav)
            cleaned_path = tmp_path
            is_temp = True
            print("[TRANSCRIBING] Converted to WAV for mlx-whisper")
        except Exception as e:
            print(f"[WARN] WAV conversion failed ({e}), proceeding with original")

    def run_whisper():
        try:
            result = mlx_whisper.transcribe(
                cleaned_path,
                path_or_hf_repo=MLX_WHISPER_MODEL,
                temperature=0,
                condition_on_previous_text=False,
                no_speech_threshold=0.8,
                compression_ratio_threshold=2.4,
            )
            return result["text"]
        finally:
            if is_temp and os.path.exists(cleaned_path):
                os.unlink(cleaned_path)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_whisper)
        try:
            transcript = future.result(timeout=WHISPER_TIMEOUT_SECONDS)
            print(f"[TRANSCRIBING] Complete. Length: {len(transcript)} characters")
            return transcript
        except concurrent.futures.TimeoutError:
            if is_temp and os.path.exists(cleaned_path):
                os.unlink(cleaned_path)
            print(f"[ERROR] Whisper timed out after {WHISPER_TIMEOUT_SECONDS} seconds")
            raise RuntimeError(f"Transcription timed out for {file_path}")


def list_obsidian_notes(folder="Audio Summaries"):
    """Fetch the list of notes in a vault folder directly via REST API."""
    try:
        response = obsidian_session.get(
            f"{OBSIDIAN_BASE_URL}/vault/{folder}/",
            timeout=OBSIDIAN_TIMEOUT_SECONDS
        )
        if response.status_code == 200:
            return response.json().get("files", [])
    except Exception as e:
        print(f"[OBSIDIAN] Failed to list notes in '{folder}': {e}")
    return []


def get_obsidian_note_content(vault_path):
    """Fetch the markdown content of a note by its vault path."""
    try:
        response = obsidian_session.get(
            f"{OBSIDIAN_BASE_URL}/vault/{vault_path}",
            timeout=OBSIDIAN_TIMEOUT_SECONDS
        )
        if response.status_code == 200:
            return response.text
    except Exception as e:
        print(f"[OBSIDIAN] Failed to fetch '{vault_path}': {e}")
    return None


def create_obsidian_note_via_mcp(filename, transcript):
    # Truncate very long transcripts as a safety guard
    MAX_TRANSCRIPT_CHARS = 100000
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        print(f"[WARNING] Transcript too long ({len(transcript)} chars), truncating to {MAX_TRANSCRIPT_CHARS}")
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n\n[Transcript truncated due to length]"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base_name = os.path.splitext(filename)[0]
    note_title = f"{datetime.now().strftime('%m-%d-%y')} - {base_name}"

    # Pre-fetch existing notes so Claude can add wiki-links without a tool call
    existing_notes = list_obsidian_notes("Audio Summaries")

    tools = [
        {
            "name": "obsidian_create_note",
            "description": "Create a new note in the Obsidian vault",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path within vault e.g. Audio Summaries/my-note.md"
                    },
                    "content": {
                        "type": "string",
                        "description": "Full markdown content of the note"
                    }
                },
                "required": ["path", "content"]
            }
        }
    ]

    def handle_tool_call(tool_name, tool_input):
        try:
            if tool_name == "obsidian_create_note":
                response = obsidian_session.put(
                    f"{OBSIDIAN_BASE_URL}/vault/{tool_input['path']}",
                    headers={"Content-Type": "text/markdown"},
                    data=tool_input["content"].encode("utf-8"),
                    timeout=OBSIDIAN_TIMEOUT_SECONDS
                )
                success = response.status_code in [200, 201, 204]
                print(f"[OBSIDIAN] create_note → HTTP {response.status_code} | path: {tool_input['path']}")
                if not success:
                    print(f"[OBSIDIAN] Error body: {response.text[:300]}")
                return {"success": success, "status": response.status_code}
        except requests.exceptions.Timeout:
            print(f"[ERROR] Obsidian API timed out on {tool_name}")
            return {"error": "timeout"}
        except requests.exceptions.ConnectionError:
            print(f"[ERROR] Cannot connect to Obsidian. Is it open?")
            return {"error": "connection_refused"}

    messages = [
        {
            "role": "user",
            "content": f"""You are an Obsidian note manager. Create a structured note for this audio recording.

Audio file: {filename}
Recorded: {timestamp}

Existing notes in Audio Summaries (use these for [[wiki-links]]):
{json.dumps(existing_notes, indent=2)}

Transcript:
{transcript}

Instructions:
1. Create a new note at: Audio Summaries/{note_title}.md
2. Include: YAML frontmatter, 2-3 sentence summary, key points, action items, [[wiki-links]] to related notes, full transcript at bottom
3. Be concise and efficient — complete this in a single tool call"""
        }
    ]

    print("[CLAUDE] Sending to Claude API...")
    max_iterations = 5  # Prevent infinite loops
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        try:
            response = anthropic_client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=45000,
                tools=tools,
                messages=messages
            )
        except anthropic.APITimeoutError:
            print(f"[ERROR] Claude API timed out on iteration {iteration}")
            raise RuntimeError("Claude API timed out")
        except anthropic.APIConnectionError as e:
            print(f"[ERROR] Claude API connection error: {e}")
            raise

        if response.stop_reason == "end_turn":
            print("[CLAUDE] Note creation complete.")
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"[TOOL] Calling: {block.name}")
                    result = handle_tool_call(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result)
                    })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            print(f"[WARNING] Unexpected stop reason: {response.stop_reason}")
            break


def _send_mac_notification(title, message, is_error=False):
    """Send a native macOS notification via osascript."""
    sound = "Basso" if is_error else "default"
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_message = message.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{safe_message}" with title "{safe_title}" sound name "{sound}"'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception:
        pass


def _send_bark_notification(title, body, is_error=False):
    """Send a push notification to iPhone via Bark."""
    if not BARK_KEY:
        return
    # timeSensitive breaks through iPhone Focus modes for errors
    level = "timeSensitive" if is_error else "active"
    try:
        requests.post(
            f"{BARK_SERVER}/push",
            json={"title": title, "body": body, "device_key": BARK_KEY, "level": level},
            timeout=10
        )
        print(f"[BARK] Notification sent: {title}")
    except Exception as e:
        print(f"[BARK] Failed to send notification: {e}")


def send_error_notification(filename, error_msg):
    _send_mac_notification("Audio Pipeline Error", f"Failed: {filename}", is_error=True)
    _send_bark_notification("Audio Pipeline Error", f"Failed: {filename}\n{error_msg}", is_error=True)


def send_success_notification(filename, note_title):
    _send_mac_notification("Audio Pipeline", f"Note created: {note_title}")
    _send_bark_notification("Audio Pipeline", f"Note created: {note_title}")


def archive_audio(file_path):
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    dest = os.path.join(ARCHIVE_DIR, os.path.basename(file_path))
    os.rename(file_path, dest)
    print(f"[ARCHIVED] {os.path.basename(file_path)}")


def process_audio_file(file_path):
    filename = os.path.basename(file_path)
    print(f"\n{'='*50}")
    print(f"[START] Processing: {filename}")
    print(f"[TIME] {datetime.now().strftime('%m-%d-%y %H:%M:%S')}")
    print(f"{'='*50}")

    try:
        transcript = transcribe_audio(file_path)
        create_obsidian_note_via_mcp(filename, transcript)
        archive_audio(file_path)
        print(f"[DONE] {filename} completed successfully.\n")
        note_title = f"{datetime.now().strftime('%m-%d-%y')} - {os.path.splitext(filename)[0]}"
        send_success_notification(filename, note_title)
    except Exception as e:
        print(f"[ERROR] Failed to process {filename}: {e}")
        send_error_notification(filename, str(e))
        # Move to an error folder instead of leaving it in the inbox
        error_dir = os.path.join(os.path.expanduser("~"), "AudioProcessing", "errors")
        os.makedirs(error_dir, exist_ok=True)
        try:
            os.rename(file_path, os.path.join(error_dir, filename))
            print(f"[ERROR] File moved to errors folder for review")
        except Exception:
            pass


def generate_daily_report():
    today_prefix = datetime.now().strftime("%m-%d-%y")
    report_path = f"Audio Summaries/{today_prefix} - Daily Report.md"
    today_str = datetime.now().strftime("%B %-d, %Y")

    print(f"[DAILY REPORT] Checking for today's notes ({today_prefix})...")

    all_notes = list_obsidian_notes("Audio Summaries")
    today_notes = [
        n for n in all_notes
        if isinstance(n, str) and n.startswith(today_prefix) and "Daily Report" not in n and n.endswith(".md")
    ]

    if len(today_notes) < 2:
        print(f"[DAILY REPORT] Only {len(today_notes)} note(s) today, skipping report generation")
        return

    print(f"[DAILY REPORT] Generating from {len(today_notes)} notes...")

    notes_content = {}
    for note in today_notes:
        content = get_obsidian_note_content(f"Audio Summaries/{note}")
        if content:
            notes_content[note] = content

    if not notes_content:
        print("[DAILY REPORT] Could not fetch any note contents, skipping")
        return

    combined = "\n\n---\n\n".join(
        f"## Source: {name}\n\n{content}"
        for name, content in notes_content.items()
    )

    source_names = list(notes_content.keys())

    messages = [
        {
            "role": "user",
            "content": f"""You are an Obsidian note manager. Combine these audio notes from today into a single Daily Report.

Date: {today_str}
Report path: {report_path}

Source notes:
{combined}

Instructions:
1. Create a note at: {report_path}
2. Structure it with:
   - YAML frontmatter (date, tags: [daily-report], sources listing the source filenames)
   - Brief overview (2-3 sentences summarizing the day)
   - One section per source note with its key points and action items
   - A consolidated "All Action Items" checklist at the end
   - Wiki-links back to all source notes
3. Be thorough but concise. Complete this in a single tool call."""
        }
    ]

    tools = [
        {
            "name": "obsidian_create_note",
            "description": "Create a new note in the Obsidian vault",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path within vault"},
                    "content": {"type": "string", "description": "Full markdown content"}
                },
                "required": ["path", "content"]
            }
        }
    ]

    print("[DAILY REPORT] Sending to Claude API...")
    max_iterations = 3
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        try:
            response = anthropic_client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=45000,
                tools=tools,
                messages=messages
            )
        except Exception as e:
            print(f"[DAILY REPORT] Claude API error: {e}")
            return

        if response.stop_reason == "end_turn":
            print("[DAILY REPORT] Report created successfully.")
            _send_mac_notification("Daily Report", f"{len(source_names)} notes combined")
            _send_bark_notification("Daily Report", f"{len(source_names)} notes combined")
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use" and block.name == "obsidian_create_note":
                    print(f"[TOOL] Calling: {block.name}")
                    resp = obsidian_session.put(
                        f"{OBSIDIAN_BASE_URL}/vault/{block.input['path']}",
                        headers={"Content-Type": "text/markdown"},
                        data=block.input["content"].encode("utf-8"),
                        timeout=OBSIDIAN_TIMEOUT_SECONDS
                    )
                    success = resp.status_code in [200, 201, 204]
                    print(f"[OBSIDIAN] create_note → HTTP {resp.status_code} | path: {block.input['path']}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps({"success": success, "status": resp.status_code})
                    })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            print(f"[DAILY REPORT] Unexpected stop reason: {response.stop_reason}")
            break
