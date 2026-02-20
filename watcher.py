import time
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pipeline import process_audio_file

WATCH_DIR = "/watch/input"
SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".wav", ".ogg", ".flac"}

class AudioHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        filepath = event.src_path
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return
        print(f"[DETECTED] New audio file: {filepath}")
        time.sleep(5)  # Wait for file to finish syncing from iCloud
        process_audio_file(filepath)

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
