#!/usr/bin/env bash

SERVICE="eposter-launch.service"

echo "🛑 Stopping PosterBridge Viewer Service..."
sudo systemctl stop $SERVICE
sudo systemctl disable $SERVICE

echo "❌ Service stopped and disabled on boot."
echo "📄 Status:"
sudo systemctl status $SERVICE --no-pager
