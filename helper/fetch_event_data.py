#!/usr/bin/env python3
"""
fetch_event_data.py

Fetches event data from an API endpoint and saves it to event_data.json.
The API URL is configurable via environment variable EVENT_API_URL.
"""
from pathlib import Path
import os
import sys
import requests
from datetime import datetime
from helper.json_utils import atomic_write_json, load_json_file

# Configuration
ROOT_DIR = Path(__file__).resolve().parent.parent

SCRIPT_DIR = ROOT_DIR
EVENT_DATA_JSON = SCRIPT_DIR / "event_data.json"


def _event_api_settings():
    config = load_json_file(ROOT_DIR / "config.json", {}) or {}
    api_config = config.get("api", {})
    api_url = api_config.get(
        "event_api_url",
        "https://posterbridge.incandescentsolution.com/api/v1/event-data",
    )
    try:
        timeout = max(3, int(api_config.get("request_timeout", 10)))
    except (TypeError, ValueError):
        timeout = 10
    return api_url, timeout


def fetch_event_data(api_url=None, token=None):
    """
    Fetches event data from the API.
    
    Args:
        api_url: API endpoint URL (defaults to EVENT_API_URL env var)
        token: Optional authentication token
    
    Returns:
        dict: Event data or None on failure
    """
    configured_url, timeout = _event_api_settings()
    if api_url is None:
        api_url = configured_url
    
    try:
        params = {}
        if token:
            params["key"] = token
        
        print(f"[fetch_event_data] Fetching from: {api_url}")
        r = requests.get(api_url, params=params, timeout=timeout)
        
        if r.status_code != 200:
            print(f"[fetch_event_data] API returned status {r.status_code}")
            return None
        
        data = r.json()
        print(f"[fetch_event_data] Successfully fetched event data")
        return data
        
    except Exception as e:
        print(f"[fetch_event_data] Error fetching event data: {e}")
        return None


def save_event_data(event_data, file_path=None):
    """
    Saves event data to JSON file.
    
    Args:
        event_data: Dictionary containing event data
        file_path: Path to save file (defaults to EVENT_DATA_JSON)
    
    Returns:
        bool: True if successful, False otherwise
    """
    if file_path is None:
        file_path = EVENT_DATA_JSON
    
    try:
        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        atomic_write_json(file_path, event_data)
        
        print(f"[save_event_data] Saved event data to {file_path}")
        return True
        
    except Exception as e:
        print(f"[save_event_data] Error saving event data: {e}")
        return False


def get_current_datetime():
    """
    Gets current date and time from system (Raspberry Pi).
    
    Returns:
        dict: Contains 'date' and 'time' strings
    """
    now = datetime.now()
    return {
        "date": now.strftime("%d-%m-%Y"),
        "time": now.strftime("%H:%M:%S"),
        "datetime": now.strftime("%d-%m-%Y-%H:%M:%S")
    }


def main():
    """Main function to fetch and save event data."""
    token = os.environ.get("EVENT_API_TOKEN")
    
    # Fetch event data
    event_data = fetch_event_data(token=token)
    
    if event_data is None:
        print("[main] Failed to fetch event data")
        sys.exit(1)
    
    # Add current system date/time
    current_dt = get_current_datetime()
    event_data["fetched_at"] = current_dt["datetime"]
    event_data["fetched_date"] = current_dt["date"]
    event_data["fetched_time"] = current_dt["time"]
    
    # Save to file
    if save_event_data(event_data):
        print("[main] Event data successfully fetched and saved")
        sys.exit(0)
    else:
        print("[main] Failed to save event data")
        sys.exit(1)


if __name__ == "__main__":
    main()
