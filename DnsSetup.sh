#!/bin/bash

# --- CONFIGURATION ---
IFACE="wlp8s0"         # Updated to match your hardware
CON_NAME="ePosterSetup"
# ---------------------

echo "--------------------------------"
echo "   MANUAL SETUP MODE STARTED    "
echo "--------------------------------"

# 1. Create the Hotspot profile if it doesn't exist
if ! nmcli connection show "$CON_NAME" > /dev/null 2>&1; then
    echo "[*] First time setup: Creating Hotspot Profile..."
    # Create connection
    sudo nmcli con add type wifi ifname "$IFACE" con-name "$CON_NAME" autoconnect yes ssid "ePoster_Config"
    # Set mode to Access Point (Shared)
    sudo nmcli con modify "$CON_NAME" 802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared
    # Set Security (WPA2)
    sudo nmcli con modify "$CON_NAME" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "setup1234"
fi

# 2. Disconnect current WiFi so we can host
echo "[*] Disconnecting current WiFi..."
sudo nmcli device disconnect "$IFACE"

# 3. Start the Hotspot
echo "[*] Starting Hotspot (SSID: ePoster_Config)..."
sudo nmcli connection up "$CON_NAME"

# 4. Wait for NetworkManager to assign the IP (10.42.0.1)
echo "[*] Waiting for network initialization..."
sleep 5

# 5. Run the Python Portal
echo "--------------------------------"
echo "-> Connect to WiFi: 'ePoster_Config'"
echo "-> Password:        'setup1234'"
echo "-> Browse to:       http://10.42.0.1 (or wait for popup)"
echo "--------------------------------"

# Use sudo because we need port 53 (DNS) and 80 (HTTP)
sudo python3 /home/bhavy/Projects/eposter/config_portal.py