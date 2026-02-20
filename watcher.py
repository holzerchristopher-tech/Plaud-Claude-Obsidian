import time
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pipeline import process_audio_file

WATCH_DIR = "/watch/input"
SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".flac"}
PROCESSED = set()

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
            PROCESSED.discard(fname)

if __name__ == "__main__":
    print(f"[WATCHING] {WATCH_DIR} for audio files...")
    os.makedirs(WATCH_DIR, exist_ok=True)
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
