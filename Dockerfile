FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir \
    anthropic \
    openai-whisper \
    watchdog \
    requests

RUN pip install --no-cache-dir \
    torch torchaudio --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir \
    silero-vad

COPY watcher.py pipeline.py ./

CMD ["python", "-u", "watcher.py"]
