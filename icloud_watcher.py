import time
import os
import shutil
import subprocess

ICLOUD_DIR = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs/AudioInbox"
)
LOCAL_DIR = os.path.expanduser("~/AudioProcessing")
PROCESSED_LOG = os.path.expanduser("~/audio-pipeline/processed_files.log")
SUPPORTED = {".mp3", ".m4a", ".wav", ".ogg", ".flac"}

os.makedirs(LOCAL_DIR, exist_ok=True)
os.makedirs(ICLOUD_DIR, exist_ok=True)

def load_processed():
    """Load the list of already processed files from disk."""
    if not os.path.exists(PROCESSED_LOG):
        return set()
    with open(PROCESSED_LOG, "r") as f:
        return set(line.strip() for line in f if line.strip())

def mark_processed(fname):
    """Save a filename to the processed log so it survives restarts."""
    with open(PROCESSED_LOG, "a") as f:
        f.write(fname + "\n")

def is_fully_downloaded(path):
    """Check if iCloud has fully downloaded the file."""
    try:
        size1 = os.path.getsize(path)
        if size1 == 0:
            return False
        time.sleep(3)
        size2 = os.path.getsize(path)
        if size1 != size2:
            return False
        with open(path, "rb") as f:
            f.read(1024)
        return True
    except (OSError, IOError):
        return False

def already_handled(fname, processed):
    """Check if file has already been copied or processed."""
    if fname in processed:
        return True
    if os.path.exists(os.path.join(LOCAL_DIR, fname)):
        return True
    return False

# Load previously processed files on startup
processed = load_processed()
print(f"[ICLOUD WATCHER] Started. {len(processed)} files already processed.")
print(f"[ICLOUD WATCHER] Monitoring: {ICLOUD_DIR}")

while True:
    try:
        files = os.listdir(ICLOUD_DIR)
        for fname in files:
            # Skip hidden files and non-audio files
            if fname.startswith("."):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SUPPORTED:
                continue

            # Skip files already handled
            if already_handled(fname, processed):
                continue

            src = os.path.join(ICLOUD_DIR, fname)
            print(f"[FOUND] {fname} — forcing iCloud download...")

            # Force iCloud to download the file
            subprocess.run(["brctl", "download", src], capture_output=True)

            # Wait up to 2 minutes for file to be fully available
            ready = False
            for attempt in range(24):
                if is_fully_downloaded(src):
                    ready = True
                    break
                print(f"[WAITING] {fname} — attempt {attempt + 1}/24")
                time.sleep(5)

            if ready:
                dst = os.path.join(LOCAL_DIR, fname)
                shutil.copy2(src, dst)
                processed.add(fname)
                mark_processed(fname)
                print(f"[COPIED] {fname} → ~/AudioProcessing")
            else:
                print(f"[TIMEOUT] {fname} — will retry next cycle")

    except Exception as e:
        print(f"[ERROR] {e}")

    time.sleep(15)
