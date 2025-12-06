#!/usr/bin/env bash

SERVICE="eposter-launch.service"

echo "📡 Starting PosterBridge Viewer Service..."
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE
sudo systemctl start $SERVICE

echo "✅ Service started and enabled on boot."
echo "📄 Status:"
sudo systemctl status $SERVICE --no-pager
