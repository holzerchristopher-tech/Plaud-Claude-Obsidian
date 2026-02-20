import time
import os
import shutil
import subprocess

ICLOUD_DIR = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/AudioInbox")
LOCAL_DIR = os.path.expanduser("~/AudioProcessing")
SUPPORTED = {".mp3", ".m4a", ".wav", ".ogg", ".flac"}
seen = set()

os.makedirs(LOCAL_DIR, exist_ok=True)
print(f"[MAC WATCHER] Monitoring iCloud for new audio files...")

while True:
    try:
        files = os.listdir(ICLOUD_DIR)
        for fname in files:
            if fname.startswith(".") or fname in seen:
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SUPPORTED:
                continue
            src = os.path.join(ICLOUD_DIR, fname)
            print(f"[FOUND] {fname} - forcing iCloud download...")
            subprocess.run(["brctl", "download", src], capture_output=True)
            for _ in range(24):
                try:
                    size1 = os.path.getsize(src)
                    time.sleep(5)
                    size2 = os.path.getsize(src)
                    if size1 == size2 and size1 > 0:
                        with open(src, "rb") as f:
                            f.read(1024)
                        dst = os.path.join(LOCAL_DIR, fname)
                        shutil.copy2(src, dst)
                        seen.add(fname)
                        print(f"[COPIED] {fname} → AudioProcessing")
                        break
                except Exception as e:
                    print(f"[WAITING] {fname}: {e}")
    except Exception as e:
        print(f"[ERROR] {e}")
    time.sleep(10)
