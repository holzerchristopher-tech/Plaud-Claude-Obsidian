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
2. A Mac-native watcher script monitors the iCloud folder, forces file downloads via brctl, and moves fully synced files to a local ~/AudioProcessing folder
3. A Docker container running Whisper detects new files, strips silence with Silero VAD, and transcribes the audio to text
4. Claude (via the Anthropic API) takes the transcript and uses the Obsidian Local REST API to create a structured note
5. The finished note appears in your Obsidian vault under Audio Summaries and syncs to mobile via iCloud
6. The processed audio file is archived to a processed subfolder

Every Tuesday at 10am, a weekly report job synthesizes all Daily Report notes from the past 7 days into a single formatted report, saves it to Obsidian, emails it as styled HTML, and archives the daily notes to Plaud Notes Archive.

## Note Template

- User Preferred Template

You can customize this template in pipeline.py to match your own workflow.

## Stack

- Whisper - OpenAI's open source speech-to-text model (runs locally in Docker)
- Silero VAD - strips silence from audio before transcription to improve speed and accuracy
- Claude API - Anthropic's AI for summarization and note structuring
- Obsidian Local REST API - plugin that lets Claude write directly into your vault
- Docker - containerized runtime for Whisper and the pipeline
- iCloud - sync layer between Plaud mobile app and Mac
- Python - pipeline orchestration and file watching
- launchd - runs the iCloud watcher and weekly report on a schedule, auto-starts on login

## Requirements

- Mac with Docker Desktop installed
- Obsidian with the Local REST API plugin enabled
- Anthropic API key (console.anthropic.com)
- SMTP credentials for HTML email (Yahoo, Gmail, or iCloud app password)
- Plaud device and mobile app
- Amphetamine (App Store) — optional, recommended for MacBook users to keep the Mac awake with the lid closed

## Cost

This pipeline is very affordable to run. Each recording costs approximately:

- Input tokens (prompt + transcript): ~$0.004
- Output tokens (structured note): ~$0.010
- Total per recording: roughly $0.01 - $0.02

For 50 recordings a month, expect around $0.50 - $1.00 in API costs.

## Project Structure

- pipeline.py - Main pipeline: VAD silence stripping, Whisper transcription, Claude note creation
- watcher.py - Docker file watcher for ~/AudioProcessing, processes files present at startup
- icloud_watcher.py - Mac-native iCloud monitor, forces downloads via brctl, moves files to ~/AudioProcessing
- weekly_report.py - Weekly synthesis job: fetches daily notes, summarizes with Claude, emails HTML report, archives daily notes
- ICloudWatcher.app - Minimal app bundle so macOS grants iCloud Drive access to the watcher
- Dockerfile - Container definition
- docker-compose.yml - Docker service configuration (mounts ~/AudioProcessing)
- com.chrisholzer.audio-pipeline.watcher.plist - launchd agent: runs icloud_watcher.py at login
- com.chrisholzer.audio-pipeline.docker.plist - launchd agent: starts Docker container at login
- com.chrisholzer.audio-pipeline.weekly-report.plist - launchd agent: runs weekly report every Tuesday at 10am
- .env - API keys and environment variables (not committed)
- .gitignore - Excludes API keys and log files from version control

## Setup

### 1. Clone the repo
```
git clone https://github.com/holzerchristopher-tech/Plaud-Claude-Obsidian.git
cd Plaud-Claude-Obsidian
```

### 2. Install the Obsidian Local REST API plugin
- Open Obsidian → Settings → Community Plugins → Browse
- Search for Local REST API, install and enable it
- Go to Settings → Local REST API and copy your API key and port number

### 3. Create your .env file
```
ANTHROPIC_API_KEY=your_anthropic_key_here
OBSIDIAN_API_KEY=your_obsidian_rest_api_key_here
OBSIDIAN_HOST=host.docker.internal
OBSIDIAN_PORT=27123

SMTP_HOST=smtp.mail.yahoo.com
SMTP_PORT=587
SMTP_USER=your_email@yahoo.com
SMTP_PASSWORD=your_app_password
SMTP_FROM=your_email@yahoo.com
```

For Gmail use `smtp.gmail.com`, for iCloud use `smtp.mail.me.com`. Generate an app password in your email provider's account security settings — do not use your regular login password.

### 4. Create required folders
```
mkdir ~/AudioProcessing
mkdir -p ~/Library/Mobile\ Documents/com~apple~CloudDocs/AudioInbox
```

### 5. Create the required Obsidian folders
In Obsidian, create the following folders inside your vault:
- `Audio Summaries` — daily transcribed notes land here
- `Audio Summaries/Weekly Report Summaries` — weekly reports saved here
- `Plaud Notes Archive` — daily notes are moved here after the weekly report runs

### 6. Build and start Docker
```
docker-compose build
docker-compose up -d
```

### 7. Install the launchd agents
```
cp com.chrisholzer.audio-pipeline.watcher.plist ~/Library/LaunchAgents/
cp com.chrisholzer.audio-pipeline.docker.plist ~/Library/LaunchAgents/
cp com.chrisholzer.audio-pipeline.weekly-report.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.chrisholzer.audio-pipeline.watcher.plist
launchctl load ~/Library/LaunchAgents/com.chrisholzer.audio-pipeline.docker.plist
launchctl load ~/Library/LaunchAgents/com.chrisholzer.audio-pipeline.weekly-report.plist
```

### 8. Grant iCloud Drive access to ICloudWatcher.app
- System Settings → Privacy & Security → Full Disk Access → +
- Press Cmd+Shift+G and navigate to `~/audio-pipeline`
- Select `ICloudWatcher.app` and toggle it on

## Usage

1. Record audio on your Plaud device
2. Sync the recording to iCloud via the Plaud mobile app
3. The pipeline detects it automatically and processes it within a few minutes
4. Check your Obsidian vault under Audio Summaries for the new structured note
5. Every Tuesday at 10am a weekly report is emailed and daily notes are archived

## Monitoring

Check Docker logs:
```
cd ~/audio-pipeline && docker-compose logs -f
```

Check iCloud watcher logs:
```
tail -f /Users/Shared/audio-pipeline-watcher.log
```

Check if watcher is running:
```
ps aux | grep icloud_watcher | grep -v grep
```

Check weekly report logs:
```
tail -f ~/audio-pipeline/weekly_report.log
```

## After a Reboot

All components start automatically via launchd and the ICloudWatcher login item. To verify everything is running:
```
launchctl list | grep audio-pipeline
docker ps | grep audio-pipeline
ps aux | grep icloud_watcher | grep -v grep
```

## Known Limitations

- Obsidian must be open on your Mac for the Local REST API plugin to be active
- The pipeline requires your Mac to be on and awake — if running on a MacBook, use Amphetamine (App Store) to keep it awake with the lid closed
- Whisper runs on CPU inside Docker which is slower than GPU — a 9 minute recording takes 2-3 minutes to transcribe
- iCloud sync speed depends on your internet connection — the watcher waits up to 3 minutes for files to fully download before processing
- If SMTP credentials are not set in .env, the weekly report email falls back to Apple Mail plain text

## Security

- .env is excluded from version control via .gitignore — never commit it
- The Obsidian Local REST API only accepts connections from localhost so your vault is not exposed to the internet
