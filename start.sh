#!/bin/bash
echo "Starting audio pipeline..."

# Kill any existing watcher instances before starting fresh
pkill -f icloud_watcher.py 2>/dev/null
pkill caffeinate 2>/dev/null
sleep 1

cd ~/audio-pipeline
docker-compose up -d
nohup caffeinate -i python3 -u ~/audio-pipeline/icloud_watcher.py >> ~/audio-pipeline/icloud_watcher.log 2>&1 &
echo "Pipeline running. Docker and iCloud watcher are active."
