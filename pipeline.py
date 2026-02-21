import anthropic
import whisper
import os
import json
import requests
from datetime import datetime

print("Loading Whisper model...")
whisper_model = whisper.load_model("base")

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
OBSIDIAN_API_KEY = os.environ["OBSIDIAN_API_KEY"]
OBSIDIAN_HOST = os.environ.get("OBSIDIAN_HOST", "host.docker.internal")
OBSIDIAN_PORT = os.environ.get("OBSIDIAN_PORT", "27123")
OBSIDIAN_BASE_URL = f"http://{OBSIDIAN_HOST}:{OBSIDIAN_PORT}"
ARCHIVE_DIR = "/watch/input/processed"

def transcribe_audio(file_path):
    print(f"[TRANSCRIBING] {file_path}")
    result = whisper_model.transcribe(file_path)
    text = result["text"]
    print(f"[TRANSCRIPT] Length: {len(text)} chars — Preview: {text[:200]}")
    return text


def create_obsidian_note_via_mcp(filename, transcript):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base_name = os.path.splitext(filename)[0]
    note_title = datetime.now().strftime("%Y-%m-%d") + " - " + base_name

    tools = [
        {
            "name": "obsidian_create_note",
            "description": "Create a new note in the Obsidian vault",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path within the vault"},
                    "content": {"type": "string", "description": "Full markdown content of the note"}
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
                    "folder": {"type": "string", "description": "Folder path to list"}
                },
                "required": ["folder"]
            }
        }
    ]

    def handle_tool_call(tool_name, tool_input):
        if tool_name == "obsidian_create_note":
            path = tool_input["path"]
            content = tool_input["content"]
            note_headers = {
                "Authorization": f"Bearer {OBSIDIAN_API_KEY}",
                "Content-Type": "text/markdown"
            }
            response = requests.put(
                f"{OBSIDIAN_BASE_URL}/vault/{path}",
                headers=note_headers,
                data=content.encode("utf-8")
            )
            print(f"[API RESPONSE] Status: {response.status_code}, Body: {response.text}")
            return {"success": response.status_code in [200, 201, 204], "status": response.status_code}
        elif tool_name == "obsidian_list_notes":
            folder = tool_input["folder"]
            list_headers = {
                "Authorization": f"Bearer {OBSIDIAN_API_KEY}",
                "Content-Type": "application/json"
            }
            response = requests.get(
                f"{OBSIDIAN_BASE_URL}/vault/{folder}/",
                headers=list_headers
            )
            if response.status_code == 200:
                return response.json()
            return {"files": []}

    messages = [
        {
            "role": "user",
            "content": f"""You are an Obsidian note manager. Create a well-structured note for this audio recording.

Audio file: {filename}
Recorded: {timestamp}

Transcript:
{transcript}

Instructions:
1. First list the existing notes in Obsidian Vault/Plaud Notes to understand context
2. Create a new note at path: Obsidian Vault/Plaud Notes/{note_title}.md
3. The note should include:
   - YAML frontmatter with created date, source filename, and relevant tags
   - The full transcript at the bottom under a Transcript heading
4. Use the following template for the note body. If nothing is identified for a section write Nothing to report:

## Notable Recognitions for Safety, Environmental, or Reliability - Impacting Performance this week:

## Significant Operational Upsets, Releases, or notable events this week:

## Any needs for additional support, including manpower constraints:

## Upcoming events, including maintenance tasks for the next week or major maintenance coming up that needs to be communicated:

## Additional Comments:

5. Use proper Obsidian markdown including wiki-links where appropriate"""
        }
    ]

    print("[CLAUDE MCP] Claude is creating your Obsidian note...")

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            tools=tools,
            messages=messages
        )
        if response.stop_reason == "end_turn":
            print("[CLAUDE MCP] Note creation complete.")
            break
        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"[TOOL] Claude is calling: {block.name}")
                    result = handle_tool_call(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result)
                    })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            break

def archive_audio(file_path):
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    dest = os.path.join(ARCHIVE_DIR, os.path.basename(file_path))
    os.rename(file_path, dest)
    print(f"[ARCHIVED] Audio moved to: {dest}")

def process_audio_file(file_path):
    filename = os.path.basename(file_path)
    try:
        transcript = transcribe_audio(file_path)
        create_obsidian_note_via_mcp(filename, transcript)
        archive_audio(file_path)
        print(f"[DONE] {filename} processed successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to process {filename}: {e}")
