#!/usr/bin/env bash
set -euo pipefail

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="$SCRIPT_DIR"
CONFIG_FILE="$BASE/config.json"
PY_SCRIPT="$BASE/show_eposters.py"

# Check if config.json exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "[launcher] ERROR: config.json not found at $CONFIG_FILE"
    exit 1
fi

# Load configuration from config.json using Python
# This ensures we can parse JSON even if jq is not available
load_config() {
    python3 << 'PYTHON_EOF'
import json
import sys
import os

try:
    config_path = os.environ.get('CONFIG_FILE', 'config.json')
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # WiFi settings
    wifi = config.get('wifi', {})
    print(f"export WIFI_SSID=\"{wifi.get('ssid1', '')}\"")
    print(f"export WIFI_PSK=\"{wifi.get('password1', '')}\"")
    print(f"export WIFI_SSID_2=\"{wifi.get('ssid2', '')}\"")
    print(f"export WIFI_PSK_2=\"{wifi.get('password2', '')}\"")
    print(f"export WIFI_CONNECT_TIMEOUT={wifi.get('connect_timeout', 60)}")
    
    # API settings
    api = config.get('api', {})
    print(f"export POSTER_TOKEN=\"{api.get('poster_token', '')}\"")
    print(f"export API_BASE=\"{api.get('poster_api_url', '')}\"")
    print(f"export EVENT_API_URL=\"{api.get('event_api_url', '')}\"")
    print(f"export EVENT_API_TOKEN=\"{api.get('event_api_token', '')}\"")
    print(f"export REQUEST_TIMEOUT={api.get('request_timeout', 10)}")
    
    # Display settings
    display = config.get('display', {})
    print(f"export CACHE_REFRESH={display.get('cache_refresh', 60)}")
    print(f"export DISPLAY_TIME={display.get('display_time', 5)}")
    print(f"export ROTATION_DEGREE={display.get('rotation_degree', 0)}")
    
except Exception as e:
    print(f"# Error loading config: {e}", file=sys.stderr)
    sys.exit(1)
PYTHON_EOF
}

# Load and export configuration
eval "$(CONFIG_FILE="$CONFIG_FILE" load_config)"

# Validate required settings
if [ -z "${POSTER_TOKEN:-}" ]; then
    echo "[launcher] ERROR: POSTER_TOKEN not set in config.json"
    exit 1
fi

echo "[launcher] Starting ePoster viewer…"
echo "  Config loaded from: $CONFIG_FILE"
echo "  POSTER_TOKEN: [HIDDEN]"
echo "  CACHE_REFRESH=${CACHE_REFRESH:-60}"
echo "  DISPLAY_TIME=${DISPLAY_TIME:-5}"
echo "  ROTATION_DEGREE=${ROTATION_DEGREE:-0}"
echo "  WIFI_SSID: ${WIFI_SSID:+[SET]}"
echo "  WIFI_SSID_2: ${WIFI_SSID_2:+[SET]}"
echo "  API_BASE: ${API_BASE:-[DEFAULT]}"
echo "  EVENT_API_URL: ${EVENT_API_URL:-[DEFAULT]}"

# Change to the script directory to ensure relative imports work
cd "$BASE" || {
    echo "[launcher] ERROR: Cannot change to directory $BASE"
    exit 1
}

# Run the script
exec python3 show_eposters.py