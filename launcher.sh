#!/usr/bin/env bash
set -euo pipefail

BASE="/home/bhavy/eposter"
PY_SCRIPT="$BASE/show_eposters.py"

# --- Settings ---
# Wi-Fi (optional) - set these if you want the device to auto-join a network at boot.
# If you don't want auto Wi-Fi, leave WIFI_SSID empty or comment the lines.
export WIFI_SSID="BHAVY"
export WIFI_PSK="Bms@1266"
export WIFI_CONNECT_TIMEOUT=60

# Poster settings
export POSTER_TOKEN="A9993E364706816ABA3E25717850C26C9CD0D89D"
export CACHE_REFRESH=60
export DISPLAY_TIME=5

echo "[launcher] Starting ePoster viewer…"
echo "  POSTER_TOKEN: [HIDDEN]"
echo "  CACHE_REFRESH=$CACHE_REFRESH"
echo "  DISPLAY_TIME=$DISPLAY_TIME"
echo "  WIFI_SSID: ${WIFI_SSID:+[SET]}"
exec python3 "$PY_SCRIPT"
