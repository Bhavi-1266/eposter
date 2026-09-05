#!/usr/bin/env python3
"""
wifi_connect.py

Handles WiFi connection using nmcli.
"""
import sys
import time
import shutil
import subprocess
import requests
from pathlib import Path
from helper.json_utils import load_json_file

# Configuration
ROOT_DIR = Path(__file__).resolve().parent.parent

DEFAULT_API = 'https://posterbridge.incandescentsolution.com/api/v1/eposter-list'


def _network_settings():
    config = load_json_file(ROOT_DIR / 'config.json', {}) or {}
    wifi = config.get('wifi', {})
    api_url = config.get('api', {}).get('poster_api_url') or DEFAULT_API
    try:
        timeout = max(5, int(wifi.get('connect_timeout', 20)))
    except (TypeError, ValueError):
        timeout = 20
    return wifi, api_url, timeout

def is_online(check_url=None, timeout=3):
    """
    Checks if system is online by attempting to reach the API.
    
    Args:
        check_url: URL to check connectivity
        timeout: Timeout in seconds
    
    Returns:
        bool: True if online, False otherwise
    """
    if not check_url:
        _, check_url, _ = _network_settings()
    try:
        response = requests.get(check_url, timeout=timeout, stream=True)
        response.close()
        return True
    except Exception:
        return False


def connect_wifi_nmcli(ssid=None, psk=None, iface=None, timeout=None, check_url=None):
    """
    Use nmcli to connect to WiFi SSID. Returns True on success.
    Automatically enables WiFi radio if it's turned off.
    
    Args:
        ssid: WiFi SSID (defaults to WIFI_SSID env var)
        psk: WiFi password (defaults to WIFI_PSK env var)
        iface: Network interface name (optional)
        timeout: Connection timeout in seconds (defaults to WIFI_TIMEOUT)
        check_url: URL to verify internet connectivity
    
    Returns:
        bool: True if connected and online, False otherwise
    """
    wifi, configured_api, configured_timeout = _network_settings()
    if ssid is None:
        ssid = wifi.get('ssid1')
    if psk is None:
        psk = wifi.get('password1')
    if timeout is None:
        timeout = configured_timeout
    check_url = check_url or configured_api
    
    if not ssid:
        print("[wifi] No SSID provided")
        return False
    
    nmcli = shutil.which("nmcli")
    if not nmcli:
        print("[wifi] nmcli not found; cannot auto-connect.")
        return False

    # Check if WiFi radio is enabled, turn it on if disabled
    try:
        radio_status = subprocess.check_output(
            [nmcli, "radio", "wifi"], 
            text=True,
            timeout=5,
        ).strip()
        
        if radio_status == "disabled":
            print("[wifi] WiFi radio is OFF. Turning it ON...")
            subprocess.run([nmcli, "radio", "wifi", "on"], check=True, timeout=10)
            time.sleep(2)  # Give it a moment to initialize
            print("[wifi] WiFi radio enabled.")
        else:
            print("[wifi] WiFi radio is already ON.")
    except Exception as e:
        print(f"[wifi] Could not check/enable WiFi radio: {e}")
        # Continue anyway, maybe it's on

    # If already online, nothing to do
    if is_online(check_url=check_url):
        print("[wifi] Already online.")
        return True

    # If already connected to SSID, just verify internet
    try:
        out = subprocess.check_output(
            [nmcli, "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
            text=True, timeout=10,
        )
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[0] == "yes" and parts[1] == ssid:
                print(f"[wifi] Already connected to {ssid}.")
                return is_online(check_url=check_url)
    except Exception:
        pass

    print(f"[wifi] Attempting nmcli connect to SSID='{ssid}' (timeout {timeout}s)...")
    cmd = [nmcli, "device", "wifi", "connect", ssid]
    if psk:
        cmd += ["password", psk]
    if iface:
        cmd += ["ifname", iface]

    try:
        rc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, check=False, timeout=max(15, timeout),
        )
        print("[wifi] nmcli output:", rc.stdout.strip())
    except Exception as e:
        print("[wifi] nmcli connect failure:", e)
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_online(check_url=check_url):
            print("[wifi] Online!")
            return True
        time.sleep(1.0)

    print("[wifi] Timed out waiting for network to become online.")
    return False

def ensure_wifi_connection():
    """
    Ensures WiFi connection is established.
    Tries primary WiFi (WIFI_SSID) first, then fallback (WIFI_SSID_2) if configured.
    
    Returns:
        bool: True if connected or not needed, False on failure
    """

    wifi, api_url, wifi_timeout = _network_settings()
    ssid1, psk1 = wifi.get('ssid1'), wifi.get('password1')
    ssid2, psk2 = wifi.get('ssid2'), wifi.get('password2')

    if is_online(api_url):
        print("[wifi] Already online.")
        return True
    
    # If no WiFi configured at all, skip
    if not ssid1 and not ssid2:
        print("[wifi] No WIFI_SSID configured; skipping auto-connect. Ensure network is up before starting.")
        return True
    
    # Try primary WiFi network first
    if ssid1:
        print(f"[wifi] Attempting to connect to primary WiFi: {ssid1}")
        ok = connect_wifi_nmcli(ssid1, psk1, timeout=wifi_timeout, check_url=api_url)
        if ok:
            print("[wifi] Successfully connected to primary WiFi network.")
            return True
        else:
            print(f"[wifi] Failed to connect to primary WiFi: {ssid1}")
    
    # Try fallback WiFi network if primary failed
    if ssid2:
        print(f"[wifi] Attempting to connect to fallback WiFi: {ssid2}")
        ok = connect_wifi_nmcli(ssid2, psk2, timeout=wifi_timeout, check_url=api_url)
        if ok:
            print("[wifi] Successfully connected to fallback WiFi network.")
            return True
        else:
            print(f"[wifi] Failed to connect to fallback WiFi: {ssid2}")
    
    # Both failed
    print("[wifi] Could not connect to any configured WiFi network.")
    return False


if __name__ == "__main__":
    # Test WiFi connection
    if ensure_wifi_connection():
        print("[wifi] WiFi connection successful")
        sys.exit(0)
    else:
        print("[wifi] WiFi connection failed")
        sys.exit(1)
