import anthropic
import whisper
import os
import json
import tempfile
import requests
import threading
import concurrent.futures
from datetime import datetime
from silero_vad import load_silero_vad, read_audio as vad_read_audio, get_speech_timestamps, collect_chunks, save_audio as vad_save_audio

print("Loading Whisper model...")
whisper_model = whisper.load_model("base")

print("Loading Silero VAD model...")
vad_model = load_silero_vad()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
OBSIDIAN_API_KEY = os.environ["OBSIDIAN_API_KEY"]
OBSIDIAN_HOST = os.environ.get("OBSIDIAN_HOST", "host.docker.internal")
OBSIDIAN_PORT = os.environ.get("OBSIDIAN_PORT", "27123")
OBSIDIAN_BASE_URL = f"http://{OBSIDIAN_HOST}:{OBSIDIAN_PORT}"
ARCHIVE_DIR = "/watch/input/processed"

# Timeout settings — adjust these based on your audio file lengths
WHISPER_TIMEOUT_SECONDS = 900   # 15 min max for transcription
CLAUDE_TIMEOUT_SECONDS = 900    # 15 min max for Claude response (allow for large transcripts)
OBSIDIAN_TIMEOUT_SECONDS = 30   # 30 sec max for Obsidian API calls


def strip_silence(file_path):
    """Use Silero VAD to remove non-speech segments before transcription.

    Returns (path, is_temp) where path is either the original file or a
    cleaned temp WAV, and is_temp indicates whether the caller must delete it.
    Falls back to the original file on any error.
    """
    SAMPLING_RATE = 16000
    try:
        wav = vad_read_audio(file_path, sampling_rate=SAMPLING_RATE)
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
        vad_save_audio(tmp_path, speech_audio, sampling_rate=SAMPLING_RATE)
        return tmp_path, True

    except Exception as e:
        print(f"[VAD] Failed ({e}), using original file")
        return file_path, False


def transcribe_audio(file_path):
    """Run Whisper in a thread with a timeout so it can't hang forever."""
    print(f"[TRANSCRIBING] {file_path}")

    cleaned_path, is_temp = strip_silence(file_path)

    def run_whisper():
        try:
            result = whisper_model.transcribe(
                cleaned_path,
                fp16=False,
                temperature=0,
                beam_size=1,
                best_of=1,
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


def create_obsidian_note_via_mcp(filename, transcript):
    """Call Claude with explicit timeouts on every request."""

    # Truncate very long transcripts as a safety guard
    MAX_TRANSCRIPT_CHARS = 100000
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        print(f"[WARNING] Transcript too long ({len(transcript)} chars), truncating to {MAX_TRANSCRIPT_CHARS}")
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n\n[Transcript truncated due to length]"

    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        timeout=anthropic.Timeout(
            connect=10.0,       # 10 seconds to connect
            read=CLAUDE_TIMEOUT_SECONDS,
            write=30.0,
            pool=5.0
        )
    )

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base_name = os.path.splitext(filename)[0]
    note_title = f"{datetime.now().strftime('%m-%d-%y')} - {base_name}"

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
        },
        {
            "name": "obsidian_list_notes",
            "description": "List existing notes in a vault folder",
            "input_schema": {
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Folder path to list"
                    }
                },
                "required": ["folder"]
            }
        }
    ]

    def handle_tool_call(tool_name, tool_input):
        auth_header = {"Authorization": f"Bearer {OBSIDIAN_API_KEY}"}
        try:
            if tool_name == "obsidian_create_note":
                response = requests.put(
                    f"{OBSIDIAN_BASE_URL}/vault/{tool_input['path']}",
                    headers={**auth_header, "Content-Type": "text/markdown"},
                    data=tool_input["content"].encode("utf-8"),
                    timeout=OBSIDIAN_TIMEOUT_SECONDS
                )
                success = response.status_code in [200, 201, 204]
                print(f"[OBSIDIAN] create_note → HTTP {response.status_code} | path: {tool_input['path']}")
                if not success:
                    print(f"[OBSIDIAN] Error body: {response.text[:300]}")
                return {"success": success, "status": response.status_code}

            elif tool_name == "obsidian_list_notes":
                response = requests.get(
                    f"{OBSIDIAN_BASE_URL}/vault/{tool_input['folder']}/",
                    headers={**auth_header, "Content-Type": "application/json"},
                    timeout=OBSIDIAN_TIMEOUT_SECONDS
                )
                print(f"[OBSIDIAN] list_notes → HTTP {response.status_code} | folder: {tool_input['folder']}")
                return response.json() if response.status_code == 200 else {"files": []}

        except requests.exceptions.Timeout:
            print(f"[ERROR] Obsidian API timed out on {tool_name}")
            return {"error": "timeout", "files": []}
        except requests.exceptions.ConnectionError:
            print(f"[ERROR] Cannot connect to Obsidian. Is it open?")
            return {"error": "connection_refused", "files": []}

    messages = [
        {
            "role": "user",
            "content": f"""You are an Obsidian note manager. Create a structured note for this audio recording.

Audio file: {filename}
Recorded: {timestamp}

Transcript:
{transcript}

Instructions:
1. List existing notes in "Audio Summaries" folder first
2. Create a new note at: Audio Summaries/{note_title}.md
3. Include: YAML frontmatter, 2-3 sentence summary, key points, action items, [[wiki-links]] to related notes, full transcript at bottom
4. Be concise and efficient — complete this in as few tool calls as possible"""
        }
    ]

    print("[CLAUDE] Sending to Claude API...")
    max_iterations = 5  # Prevent infinite loops
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        try:
            response = client.messages.create(
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
    except Exception as e:
        print(f"[ERROR] Failed to process {filename}: {e}")
        # Move to an error folder instead of leaving it in the inbox
        error_dir = "/watch/input/errors"
        os.makedirs(error_dir, exist_ok=True)
        try:
            os.rename(file_path, os.path.join(error_dir, filename))
            print(f"[ERROR] File moved to errors folder for review")
        except Exception:
            pass
