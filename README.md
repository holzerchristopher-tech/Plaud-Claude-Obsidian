# Plaud → Claude → Obsidian Audio Pipeline

Automatically transcribe Plaud audio recordings and convert them into structured Obsidian notes using AI — fully native on Apple Silicon, no Docker required.

## Why This Exists

Plaud recordings are great for capturing meetings, field notes, and voice memos — but getting that content into a usable, searchable format is tedious. This pipeline eliminates that friction entirely:

1. Record on your Plaud device
2. Sync to iCloud
3. Find a structured, summarized note in Obsidian within minutes — automatically

No manual steps. No copy-pasting. No subscription services beyond what you already use.

## How It Works

```
Plaud → iCloud AudioInbox → icloud_watcher.py → AudioProcessing → mlx-whisper → Claude API → Obsidian
```

1. Audio recordings sync from the Plaud mobile app to an iCloud AudioInbox folder
2. A native watcher monitors the iCloud folder, forces downloads via `brctl`, and moves fully synced files to `~/AudioProcessing`
3. A native Python process detects new files, strips silence with Silero VAD, and transcribes with mlx-whisper (Apple Neural Engine)
4. Claude (via the Anthropic API) takes the transcript and writes a structured note directly into your Obsidian vault via the Local REST API
5. The finished note appears under Audio Summaries and syncs to mobile via iCloud
6. The processed audio file is archived to a processed subfolder
7. Every night at 11 PM, a daily report synthesizes all of that day's notes
8. Every Tuesday at 10 AM, a weekly report synthesizes the past 7 days of daily reports, emails it as styled HTML, and archives the daily notes

## Stack

- **mlx-whisper** — Apple Silicon-native Whisper using the Neural Engine and GPU cores for fast local transcription
- **Silero VAD** — strips silence from audio before transcription to improve speed and accuracy
- **Claude API** — Anthropic's AI for summarization and note structuring
- **Obsidian Local REST API** — plugin that lets Claude write directly into your vault
- **Bark** — free iOS app for iPhone push notifications on note completion and errors
- **Homebrew** — manages system dependencies (ffmpeg)
- **Python venv** — isolated native Python environment
- **launchd** — manages all scheduled jobs and auto-starts everything at login

## Requirements

- Apple Silicon Mac (M1/M2/M3/M4) — mlx-whisper is arm64 only
- macOS 13.3 (Ventura) or later
- Homebrew
- Obsidian with the Local REST API plugin enabled
- Anthropic API key — [console.anthropic.com](https://console.anthropic.com)
- Bark iOS app (free) — [App Store](https://apps.apple.com/us/app/bark-custom-notifications/id1403753865)
- SMTP credentials for HTML email (Yahoo, Gmail, or iCloud app password) — optional, falls back to Apple Mail
- Plaud device and mobile app

## Cost

Very affordable to run. Each recording costs approximately:

- Input tokens (prompt + transcript): ~$0.004
- Output tokens (structured note): ~$0.010
- **Total per recording: roughly $0.01 – $0.02**

For 50 recordings a month, expect around $0.50 – $1.00 in API costs. mlx-whisper, Bark, and Homebrew are all free.

## Project Structure

```
pipeline.py                                      # VAD silence stripping, mlx-whisper transcription, Claude note creation
watcher.py                                       # Native file watcher for ~/AudioProcessing
icloud_watcher.py                                # iCloud monitor — forces downloads, moves files to ~/AudioProcessing
daily_report.py                                  # Standalone daily report generator with HTML email
weekly_report.py                                 # Weekly synthesis — fetches daily notes, emails HTML report, archives
run_pipeline.sh                                  # Launch wrapper: loads .env, sets PATH, execs venv Python
ICloudWatcher.app                                # App bundle so macOS grants iCloud Drive access to the watcher
com.chrisholzer.audio-pipeline.native.plist      # launchd agent: runs pipeline at login, KeepAlive
com.chrisholzer.audio-pipeline.watcher.plist     # launchd agent: runs icloud_watcher at login
com.chrisholzer.audio-pipeline.daily-report.plist  # launchd agent: runs daily report at 11 PM
com.chrisholzer.audio-pipeline.weekly-report.plist # launchd agent: runs weekly report every Tuesday at 10 AM
Dockerfile                                       # Legacy Docker reference (no longer used for main pipeline)
docker-compose.yml                               # Legacy Docker reference
.env                                             # API keys and config (never committed)
```

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/G9KBytes-Labs/Plaud-Claude-Obsidian.git
cd Plaud-Claude-Obsidian
git checkout audio-pipeline-2.0
```

### 2. Install Homebrew
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/homebrew/install/HEAD/install.sh)"
```
After install, follow the printed instructions to add Homebrew to your PATH.

### 3. Install ffmpeg
```bash
brew install ffmpeg
```

### 4. Install the Obsidian Local REST API plugin
- Open Obsidian → Settings → Community Plugins → Browse
- Search for **Local REST API**, install and enable it
- Go to Settings → Local REST API and copy your API key and port number

### 5. Install Bark on iPhone
- Download [Bark](https://apps.apple.com/us/app/bark-custom-notifications/id1403753865) from the App Store (free)
- Open the app — it displays a URL like `https://api.day.app/YOURKEY/`
- Copy the key portion (everything between the second and third `/`)

### 6. Create your .env file
```bash
cp .env.example .env  # if available, or create manually
```

```
ANTHROPIC_API_KEY=your_anthropic_key_here
OBSIDIAN_API_KEY=your_obsidian_rest_api_key_here
OBSIDIAN_HOST=localhost
OBSIDIAN_PORT=27123
BARK_KEY=your_bark_device_key_here
BARK_SERVER=https://api.day.app

SMTP_HOST=smtp.mail.yahoo.com
SMTP_PORT=587
SMTP_USER=your_email@yahoo.com
SMTP_PASSWORD=your_app_password
SMTP_FROM=your_email@yahoo.com
```

For Gmail use `smtp.gmail.com`, for iCloud use `smtp.mail.me.com`. Generate an app password in your email provider's account security settings — do not use your regular login password. SMTP is optional; if not set the daily and weekly reports fall back to Apple Mail.

### 7. Create required folders
```bash
mkdir -p ~/AudioProcessing
mkdir -p ~/Library/Mobile\ Documents/com~apple~CloudDocs/AudioInbox
```

### 8. Create required Obsidian folders
In Obsidian, create these folders inside your vault:
- `Audio Summaries` — transcribed notes land here
- `Audio Summaries/Weekly Report Summaries` — weekly reports saved here
- `Plaud Notes Archive` — daily notes are moved here after the weekly report runs

### 9. Create the Python venv and install dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install mlx-whisper silero-vad torch anthropic watchdog requests
```

The first time a file is processed, mlx-whisper will download the `whisper-small-mlx` model (~460 MB) from Hugging Face. This only happens once.

### 10. Make the run script executable
```bash
chmod +x run_pipeline.sh
```

### 11. Grant iCloud Drive access to ICloudWatcher.app
- System Settings → Privacy & Security → Full Disk Access → +
- Press `Cmd+Shift+G` and navigate to `~/audio-pipeline`
- Select `ICloudWatcher.app` and toggle it on

### 12. Install the launchd agents
```bash
cp com.chrisholzer.audio-pipeline.native.plist ~/Library/LaunchAgents/
cp com.chrisholzer.audio-pipeline.watcher.plist ~/Library/LaunchAgents/
cp com.chrisholzer.audio-pipeline.daily-report.plist ~/Library/LaunchAgents/
cp com.chrisholzer.audio-pipeline.weekly-report.plist ~/Library/LaunchAgents/

launchctl load ~/Library/LaunchAgents/com.chrisholzer.audio-pipeline.native.plist
launchctl load ~/Library/LaunchAgents/com.chrisholzer.audio-pipeline.watcher.plist
launchctl load ~/Library/LaunchAgents/com.chrisholzer.audio-pipeline.daily-report.plist
launchctl load ~/Library/LaunchAgents/com.chrisholzer.audio-pipeline.weekly-report.plist
```

## Usage

1. Record audio on your Plaud device
2. Sync the recording to iCloud via the Plaud mobile app
3. The pipeline detects it automatically and processes it within minutes
4. Check your Obsidian vault under Audio Summaries for the new structured note
5. You'll receive a Bark push notification and a macOS notification when the note is ready
6. Every night at 11 PM a daily report is generated (requires 2+ notes that day)
7. Every Tuesday at 10 AM a weekly report is emailed and daily notes are archived

## Monitoring

```bash
# Live pipeline log (transcription, Claude, Obsidian, Bark)
tail -f ~/audio-pipeline/pipeline.log

# iCloud watcher log
tail -f /Users/Shared/audio-pipeline-watcher.log

# Daily report log
tail -f ~/audio-pipeline/daily_report.log

# Weekly report log
tail -f ~/audio-pipeline/weekly_report.log

# Verify all agents are running (non-zero PID = running)
launchctl list | grep audio-pipeline
```

## After a Reboot

All components start automatically via launchd at login. To manually verify:
```bash
launchctl list | grep audio-pipeline
```

To manually restart the pipeline:
```bash
launchctl stop com.chrisholzer.audio-pipeline.native
launchctl start com.chrisholzer.audio-pipeline.native
```

## Known Limitations

- Obsidian must be open on your Mac for the Local REST API plugin to accept connections
- Apple Silicon is required — mlx-whisper does not run on Intel Macs
- The first file processed triggers a one-time ~460 MB model download from Hugging Face
- The daily report requires at least 2 audio notes that day to generate
- iCloud sync speed depends on your internet connection — the watcher waits up to 3 minutes for files to fully download

## Security

- `.env` is excluded from version control via `.gitignore` — never commit it
- The Obsidian Local REST API only accepts connections from localhost — your vault is not exposed to the network
- Your Bark device key is private — do not share it publicly
