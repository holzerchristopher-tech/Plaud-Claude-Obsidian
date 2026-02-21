# Plaud → Claude → Obsidian Audio Pipeline

Automatically transcribe Plaud audio recordings and convert them into structured Obsidian notes using AI — fully local, no third-party cloud services required beyond the Anthropic API.

## Why This Exists

Plaud recordings are great for capturing meetings, field notes, and voice memos — but getting that content into a usable, searchable format is tedious. This pipeline eliminates that friction entirely:

1. Record on your Plaud device
2. Sync to iCloud
3. Find a structured, summarized note in Obsidian within minutes — automatically

No manual steps. No copy-pasting. No subscription services beyond what you already use.

## How It Works

Plaud → iCloud AudioInbox → icloud_watcher.py → AudioProcessing → Docker/Whisper → Claude API → Obsidian

1. Audio recordings sync from the Plaud mobile app to an iCloud AudioInbox folder
2. A Mac-native watcher script monitors the iCloud folder, forces file downloads via brctl, and copies fully synced files to a local ~/AudioProcessing folder
3. A Docker container running Whisper detects new files and transcribes the audio to text
4. Claude (via the Anthropic API) takes the transcript and uses the Obsidian Local REST API to create a structured note
5. The finished note appears in your Obsidian vault and syncs to mobile via iCloud
6. The processed audio file is archived to a processed subfolder

## Note Template

Each note is created using this structure. If nothing is identified for a section, Claude writes "Nothing to report":

-User Preferred Template

You can customize this template in pipeline.py to match your own workflow.

## Stack

- Whisper - OpenAI's open source speech-to-text model (runs locally in Docker)
- Claude API - Anthropic's AI for summarization and note structuring
- Obsidian Local REST API - plugin that lets Claude write directly into your vault
- Docker - containerized runtime for Whisper and the pipeline
- iCloud - sync layer between Plaud mobile app and Mac
- Python - pipeline orchestration and file watching

## Requirements

- Mac with Docker Desktop installed
- Obsidian with the Local REST API plugin enabled
- Anthropic API key (console.anthropic.com)
- Node.js 18+ and mcp-obsidian installed globally
- Plaud device and mobile app
- Amphetamine (App Store) - keeps Mac awake with lid closed

## Cost

This pipeline is very affordable to run. Each recording costs approximately:

- Input tokens (prompt + transcript): ~$0.004
- Output tokens (structured note): ~$0.010
- Total per recording: roughly $0.01 - $0.02

For 50 recordings a month, expect around $0.50 - $1.00 in API costs.

## Project Structure

- pipeline.py - Main pipeline: transcription and Claude note creation
- watcher.py - Docker file watcher for ~/AudioProcessing
- icloud_watcher.py - Mac-native iCloud monitor and file copier
- Dockerfile - Container definition
- docker-compose.yml - Docker service configuration
- mcp-config.example.json - Template for Obsidian MCP server configuration
- start.sh - Single command to restart the full pipeline after reboot
- .env - API keys and environment variables (not committed)
- .gitignore - Excludes API keys and log files from version control

## Setup

### 1. Clone the repo
git clone https://github.com/holzerchristopher-tech/Plaud-Claude-Obsidian.git
cd Plaud-Claude-Obsidian

### 2. Install Node.js and mcp-obsidian
Download Node.js 18+ from nodejs.org, then run:
mkdir -p ~/.npm-global
npm config set prefix '~/.npm-global'
echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.zshrc
source ~/.zshrc
npm install -g mcp-obsidian

### 3. Install the Obsidian Local REST API plugin
- Open Obsidian, go to Settings, Community Plugins, Browse
- Search for Local REST API, install and enable it
- Go to Settings, Local REST API and copy your API key and port number

### 4. Create your .env file
ANTHROPIC_API_KEY=your_anthropic_key_here
OBSIDIAN_API_KEY=your_obsidian_rest_api_key_here
OBSIDIAN_HOST=host.docker.internal
OBSIDIAN_PORT=27124

### 5. Create your mcp-config.json from the example
cp mcp-config.example.json mcp-config.json
Edit mcp-config.json and replace the placeholder values with your real Obsidian API key and port.

### 6. Create required folders
mkdir ~/AudioProcessing
mkdir -p ~/Library/Mobile\ Documents/com~apple~CloudDocs/AudioInbox

### 7. Create the Plaud Notes folder in Obsidian
In Obsidian, create a folder called Plaud Notes inside your vault. This is where all transcribed notes will be saved.

### 8. Build and start Docker
docker-compose build
docker-compose up -d

### 9. Start the full pipeline
~/audio-pipeline/start.sh

## Usage

1. Record audio on your Plaud device
2. Sync the recording to iCloud via the Plaud mobile app
3. The pipeline detects it automatically and processes it within a few minutes
4. Check your Obsidian vault under Plaud Notes for the new structured note

## Monitoring

Check Docker logs:
cd ~/audio-pipeline && docker-compose logs -f

Check iCloud watcher logs:
tail -f ~/audio-pipeline/icloud_watcher.log

Check if watcher is running:
pgrep -a -f icloud_watcher.py

Stop the watcher:
pkill -f icloud_watcher.py && pkill caffeinate

## After Every Reboot

~/audio-pipeline/start.sh

## Known Limitations

- Obsidian must be open on your Mac for the Local REST API plugin to be active
- The pipeline requires your Mac to be on and awake - use Amphetamine to keep it running with the lid closed
- Whisper runs on CPU inside Docker which is slower than GPU - a 9 minute recording takes 2-3 minutes to transcribe
- iCloud sync speed depends on your internet connection - the watcher waits for files to fully download before processing

## Security

- .env and mcp-config.json are excluded from version control via .gitignore
- Never commit your API keys - use mcp-config.example.json as a template
- The Obsidian Local REST API only accepts connections from localhost so your vault is not exposed to the internet
