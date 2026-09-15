#!/usr/bin/env python3
"""
api_handler.py

Handles API calls to fetch poster data and saves it to JSON file.
"""
from pathlib import Path
import requests
from datetime import datetime
from helper.json_utils import atomic_write_json, load_json_file

# Configuration
ROOT_DIR = Path(__file__).resolve().parent.parent

SCRIPT_DIR = ROOT_DIR
API_DATA_JSON = SCRIPT_DIR / "api_data.json"


def _api_settings():
    config = load_json_file(ROOT_DIR / "config.json", {}) or {}
    api_config = config.get("api", {})
    try:
        timeout = max(3, int(api_config.get("request_timeout", 10)))
    except (TypeError, ValueError):
        timeout = 10
    return api_config.get("poster_api_url"), timeout


def ensure_api_json():
    """
    Creates the API JSON file with empty structure if it doesn't exist.
    """
    try:
        if not API_DATA_JSON.exists():
            # Create parent directory if it doesn't exist
            API_DATA_JSON.parent.mkdir(parents=True, exist_ok=True)
            # Create empty JSON structure
            empty_data = {}
            atomic_write_json(API_DATA_JSON, empty_data)
            print(f"[ensure_api_json] Created empty API data file: {API_DATA_JSON}")
        else :
            print(f"[ensure_api_json] API data file already exists: {API_DATA_JSON}")
    except Exception as e:
        print(f"[ensure_api_json] Failed to create API data file: {e}")


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


def _without_fetch_metadata(data):
    if not isinstance(data, dict):
        return data
    return {
        key: value for key, value in data.items()
        if key not in {"fetched_at", "fetched_date", "fetched_time"}
    }


def fetch_posters(token, api=None, timeout=None):
    """
    Fetches poster data from API and saves it to api_data.json.
    Handles the new API response structure with status, message, and data array.
    
    Args:
        token: API authentication token
    
    Returns:
        list: List of poster dicts or None on failure
    """
    configured_api, configured_timeout = _api_settings()
    api = api or configured_api
    timeout = configured_timeout if timeout is None else timeout
    if not api:
        print("[fetch_posters] Poster API URL is not configured")
        return None

    try:
        params = {"key": token} if token else {}
        with requests.get(api, params=params, timeout=timeout) as response:
            response.raise_for_status()
            data = response.json()
        if (not isinstance(data, dict) or data.get("status") is False
                or not any(isinstance(data.get(key), list) for key in ("screens", "booking_slot", "data"))):
            raise ValueError("API response must contain a successful schedule with a records list")
        print( f"[fetch_posters] Successfully fetched posters from API")
        previous_data = load_json_file(API_DATA_JSON, None)
        content_changed = _without_fetch_metadata(previous_data) != _without_fetch_metadata(data)

        # Add timestamps only when persisting changed content. This avoids
        # rewriting a large, unchanged schedule to flash every refresh cycle.
        current_dt = get_current_datetime()
        
        # Add timestamp to response
        if isinstance(data, dict):
            data["fetched_at"] = current_dt["datetime"]
            data["fetched_date"] = current_dt["date"]
            data["fetched_time"] = current_dt["time"]
        
        if content_changed:
            try:
                atomic_write_json(API_DATA_JSON, data)
                print(f"[fetch_posters] Saved changed API response to {API_DATA_JSON}")
            except Exception as e:
                print(f"[fetch_posters] Failed to save API data to JSON: {e}")
        else:
            print("[fetch_posters] API content unchanged; keeping existing file")
        
        return data
        
    except (requests.RequestException, ValueError, OSError) as e:
        print(f"[fetch_posters] error: {e}")
        return None


def load_api_data():
    """
    Loads previously saved API data from JSON file.
    
    Returns:
        dict: API data or None on failure
    """
    try:
        if not API_DATA_JSON.exists():
            return None
        
        return load_json_file(API_DATA_JSON, None)
    except Exception as e:
        print(f"[load_api_data] Error loading API data: {e}")
        return None
