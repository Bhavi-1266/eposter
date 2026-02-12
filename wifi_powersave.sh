#!/bin/bash

# Use absolute path to ensure Python can find the config regardless of where it's called
BASE_DIR=$(dirname "$(readlink -f "$0")")
CONFIG_FILE="$BASE_DIR/config.json"
COMMAND="${1:-status}"

# Check dependencies
if ! command -v jq &> /dev/null; then
    echo "ERROR: jq is not installed"
    exit 1
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "ERROR: config.json not found"
    exit 1
fi

# Read WiFi details
SSID1=$(jq -r '.wifi.ssid1' "$CONFIG_FILE")
SSID2=$(jq -r '.wifi.ssid2' "$CONFIG_FILE")

# Function to get current status
get_status() {
    local STATUS=$(nmcli -f 802-11-wireless.powersave connection show "$SSID1" 2>/dev/null | grep powersave | awk '{print $2}')
    # nmcli: 2 = disabled (OFF), 3 = enabled (ON)
    if [[ "$STATUS" == "3" ]]; then echo "ON"; else echo "OFF"; fi
}

case "$COMMAND" in
    status)
        get_status
        ;;
    on)
        sudo nmcli connection modify "$SSID1" 802-11-wireless.powersave 3
        [[ -n "$SSID2" && "$SSID2" != "null" ]] && sudo nmcli connection modify "$SSID2" 802-11-wireless.powersave 3
        # Apply changes immediately
        sudo nmcli connection up "$SSID1" &>/dev/null
        echo "ON"
        ;;
    off)
        sudo nmcli connection modify "$SSID1" 802-11-wireless.powersave 2
        [[ -n "$SSID2" && "$SSID2" != "null" ]] && sudo nmcli connection modify "$SSID2" 802-11-wireless.powersave 2
        # Apply changes immediately
        sudo nmcli connection up "$SSID1" &>/dev/null
        echo "OFF"
        ;;
    *)
        echo "Usage: $0 {status|on|off}"
        exit 1
        ;;
esac