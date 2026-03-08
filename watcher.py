import time
import os
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pipeline import process_audio_file, generate_daily_report

WATCH_DIR = os.environ.get("WATCH_DIR", os.path.expanduser("~/AudioProcessing"))
SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".flac"}
PROCESSED = set()

def _daily_report_scheduler():
    """Background thread that runs generate_daily_report every day at 11pm."""
    from datetime import datetime, timedelta
    while True:
        now = datetime.now()
        target = now.replace(hour=23, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        print(f"[DAILY REPORT] Next report scheduled at {target.strftime('%m-%d-%y 23:00')}")
        time.sleep(wait_seconds)
        generate_daily_report()


def start_daily_report_scheduler():
    t = threading.Thread(target=_daily_report_scheduler, daemon=True)
    t.start()


def wait_for_file(filepath, timeout=120):
    """Wait until file is fully written and not locked."""
    start = time.time()
    last_size = -1
    while time.time() - start < timeout:
        try:
            if not os.path.exists(filepath):
                print(f"[WAITING] File not ready yet: {filepath}")
                time.sleep(5)
                continue
            current_size = os.path.getsize(filepath)
            if current_size == last_size and current_size > 0:
                with open(filepath, 'rb') as f:
                    f.read(1024)
                print(f"[READY] File is fully synced: {filepath}")
                return True
            last_size = current_size
            print(f"[WAITING] File still syncing... size={current_size} bytes")
        except (OSError, IOError) as e:
            print(f"[WAITING] File not ready yet: {e}")
        time.sleep(5)
    return False

class AudioHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        filepath = event.src_path
        fname = os.path.basename(filepath)
        ext = os.path.splitext(filepath)[1].lower()

        if ext not in SUPPORTED_EXTENSIONS:
            return

        # Skip if already processed or file no longer exists
        if fname in PROCESSED:
            print(f"[SKIPPED] Already processed: {fname}")
            return

        if not os.path.exists(filepath):
            print(f"[SKIPPED] File no longer exists: {fname}")
            return

        print(f"[DETECTED] New audio file: {filepath}")
        PROCESSED.add(fname)

        if wait_for_file(filepath):
            process_audio_file(filepath)
        else:
            print(f"[SKIPPED] File never became ready: {filepath}")

        # Prune from PROCESSED — file is now archived or errored, won't re-trigger
        PROCESSED.discard(fname)

if __name__ == "__main__":
    print(f"[WATCHING] {WATCH_DIR} for audio files...")
    os.makedirs(WATCH_DIR, exist_ok=True)

    # Process any files already present before the observer starts
    for fname in os.listdir(WATCH_DIR):
        ext = os.path.splitext(fname)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        filepath = os.path.join(WATCH_DIR, fname)
        if not os.path.isfile(filepath):
            continue
        print(f"[STARTUP] Found existing file: {fname}")
        PROCESSED.add(fname)
        if wait_for_file(filepath):
            process_audio_file(filepath)
        PROCESSED.discard(fname)

    start_daily_report_scheduler()

    event_handler = AudioHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_DIR, recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
