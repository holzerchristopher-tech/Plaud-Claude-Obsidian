import time
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pipeline import process_audio_file

WATCH_DIR = "/watch/input"
SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".flac"}

def wait_for_file(filepath, timeout=120):
    """Wait until file is fully written and not locked by iCloud."""
    start = time.time()
    last_size = -1
    while time.time() - start < timeout:
        try:
            current_size = os.path.getsize(filepath)
            if current_size == last_size and current_size > 0:
                # Try opening the file to confirm it's not locked
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
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return
        print(f"[DETECTED] New audio file: {filepath}")
        if wait_for_file(filepath):
            process_audio_file(filepath)
        else:
            print(f"[SKIPPED] File never became ready: {filepath}")

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
