#!/bin/bash
echo "Starting audio pipeline..."
cd ~/audio-pipeline
docker-compose up -d
nohup caffeinate -i python3 -u ~/audio-pipeline/icloud_watcher.py > ~/audio-pipeline/icloud_watcher.log 2>&1 &
echo "Pipeline running. Docker and iCloud watcher are active."
