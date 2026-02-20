# Plaud → Claude → Obsidian Audio Pipeline

An automated pipeline that transcribes audio recordings from a Plaud device and converts them into structured Obsidian notes using AI.

## How It Works
```
Phone (Plaud) → iCloud AudioInbox → icloud_watcher.py → AudioProcessing → Docker/Whisper → Claude API → Obsidian
```

1. Audio recordings sync from the Plaud mobile app to an iCloud AudioInbox folder
2. A Mac-native watcher script monitors the iCloud folder, forces file downloads via brctl, and copies fully synced files to a local ~/AudioProcessing folder
3. A Docker container running Whisper detects new files and transcribes the audio to text
4. Claude (via the Anthropic API) takes the transcript and uses the Obsidian Local REST API to create a structured note including YAML frontmatter, a summary, key points, action items, and the full transcript
5. The finished note appears in the Obsidian vault under Plaud Notes and syncs to mobile via iCloud
6. The processed audio file is archived to a processed subfolder

## Stack

- Whisper — OpenAI's open source speech-to-text model (runs locally in Docker)
- Claude API — Anthropic's AI for summarization and note structuring
- Obsidian Local REST API — plugin that lets Claude write directly into the vault
- Docker — containerized runtime for Whisper and the pipeline
- iCloud — sync layer between Plaud mobile app and Mac
- Python — pipeline orchestration and file watching

## Requirements

- Mac with Docker Desktop installed
- Obsidian with the Local REST API plugin enabled
- Anthropic API key (console.anthropic.com)
- Node.js 18+ and mcp-obsidian installed globally
- Plaud device and mobile app

## Project Structure

- pipeline.py — Main pipeline: transcription and Claude note creation
- watcher.py — Docker file watcher for ~/AudioProcessing
- icloud_watcher.py — Mac-native iCloud monitor and file copier
- Dockerfile — Container definition
- docker-compose.yml — Docker service configuration
- mcp-config.json — Obsidian MCP server configuration
- .env — API keys and environment variables (not committed)

## Setup

### 1. Clone the repo
git clone https://github.com/holzerchristopher-tech/Plaud-Claude-Obsidian.git
cd Plaud-Claude-Obsidian

### 2. Create your .env file
ANTHROPIC_API_KEY=your_anthropic_key_here
OBSIDIAN_API_KEY=your_obsidian_rest_api_key_here
OBSIDIAN_HOST=host.docker.internal
OBSIDIAN_PORT=27124

### 3. Update mcp-config.json with your Obsidian API key and port

### 4. Install the Obsidian Local REST API plugin
- Open Obsidian → Settings → Community Plugins → Browse
- Search for Local REST API, install and enable it
- Copy the API key from Settings → Local REST API

### 5. Create required folders
mkdir ~/AudioProcessing
mkdir -p ~/Library/Mobile\ Documents/com~apple~CloudDocs/AudioInbox

### 6. Build and start Docker
docker-compose build
docker-compose up -d

### 7. Start the iCloud watcher
nohup caffeinate -i python3 icloud_watcher.py > icloud_watcher.log 2>&1 &

## Usage

1. Record audio on your Plaud device
2. Sync the recording to iCloud via the Plaud mobile app
3. The pipeline detects it automatically and processes it within a few minutes
4. Check your Obsidian vault under Obsidian Vault/Plaud Notes for the new note

## Notes

- Obsidian must be open on your Mac for the Local REST API plugin to be active
- Add Obsidian to Login Items to keep it running at startup
- Use Amphetamine to prevent your Mac from sleeping with the lid closed
- The .env file is excluded from git — never commit your API keys
