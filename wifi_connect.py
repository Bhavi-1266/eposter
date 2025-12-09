#!/usr/bin/env python3
"""
wifi_connect.py

Handles WiFi connection using nmcli.
"""
import os
import sys
import time
import shutil
import subprocess
import requests
from pathlib import Path
import json

# Configuration
with open(Path(__file__).parent / 'config.json', 'r') as f:
    config = json.load(f)

API_BASE = config.get('api', {}).get('poster_api_url', 'https://posterbridge.incandescentsolution.com/api/v1/eposter-list')
WIFI_SSID = config.get('wifi', {}).get('ssid1')
WIFI_PSK = config.get('wifi', {}).get('password1')
WIFI_SSID_2 = config.get('wifi', {}).get('ssid2')
WIFI_PSK_2 = config.get('wifi', {}).get('password2')
WIFI_TIMEOUT = int(config.get('wifi', {}).get('connect_timeout', 60))

def is_online(check_url=API_BASE, timeout=3):
    """
    Checks if system is online by attempting to reach the API.
    
    Args:
        check_url: URL to check connectivity
        timeout: Timeout in seconds
    
    Returns:
        bool: True if online, False otherwise
    """
    try:
        requests.get(check_url, timeout=timeout)
        return True
    except Exception:
        return False


def connect_wifi_nmcli(ssid=None, psk=None, iface=None, timeout=None, check_url=API_BASE):
    """
    Use nmcli to connect to WiFi SSID. Returns True on success.
    
    Args:
        ssid: WiFi SSID (defaults to WIFI_SSID env var)
        psk: WiFi password (defaults to WIFI_PSK env var)
        iface: Network interface name (optional)
        timeout: Connection timeout in seconds (defaults to WIFI_TIMEOUT)
        check_url: URL to verify internet connectivity
    
    Returns:
        bool: True if connected and online, False otherwise
    """
    if ssid is None:
        ssid = WIFI_SSID
    if psk is None:
        psk = WIFI_PSK
    if timeout is None:
        timeout = WIFI_TIMEOUT
    
    if not ssid:
        print("[wifi] No SSID provided")
        return False
    
    nmcli = shutil.which("nmcli")
    if not nmcli:
        print("[wifi] nmcli not found; cannot auto-connect.")
        return False

    # If already online, nothing to do
    if is_online(check_url=check_url):
        print("[wifi] Already online.")
        return True

    # If already connected to SSID, just verify internet
    try:
        out = subprocess.check_output([nmcli, "-t", "-f", "ACTIVE,SSID", "dev", "wifi"], text=True)
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
        rc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
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
    # If no WiFi configured at all, skip
    if not WIFI_SSID and not WIFI_SSID_2:
        print("[wifi] No WIFI_SSID configured; skipping auto-connect. Ensure network is up before starting.")
        return True
    
    # Try primary WiFi network first
    if WIFI_SSID:
        print(f"[wifi] Attempting to connect to primary WiFi: {WIFI_SSID}")
        ok = connect_wifi_nmcli(WIFI_SSID, WIFI_PSK, timeout=WIFI_TIMEOUT, check_url=API_BASE)
        if ok:
            print("[wifi] Successfully connected to primary WiFi network.")
            return True
        else:
            print(f"[wifi] Failed to connect to primary WiFi: {WIFI_SSID}")
    
    # Try fallback WiFi network if primary failed
    if WIFI_SSID_2:
        print(f"[wifi] Attempting to connect to fallback WiFi: {WIFI_SSID_2}")
        ok = connect_wifi_nmcli(WIFI_SSID_2, WIFI_PSK_2, timeout=WIFI_TIMEOUT, check_url=API_BASE)
        if ok:
            print("[wifi] Successfully connected to fallback WiFi network.")
            return True
        else:
            print(f"[wifi] Failed to connect to fallback WiFi: {WIFI_SSID_2}")
    
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

