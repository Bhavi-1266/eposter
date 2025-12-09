#!/usr/bin/env python3
"""
api_handler.py

Handles API calls to fetch poster data and saves it to JSON file.
"""
from pathlib import Path
import os
import json
import requests
from datetime import datetime

# Configuration
with open(os.environ.get("CONFIG_FILE", "$BASE/config.json")) as f:
    config = json.load(f)

API_BASE = config.get("api", {}).get("poster_api_url", "https://posterbridge.incandescentsolution.com/api/v1/eposter-list")
REQUEST_TIMEOUT = config.get("api", {}).get("request_timeout", 10)


SCRIPT_DIR = Path(__file__).parent
API_DATA_JSON = SCRIPT_DIR / "api_data.json"


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
            with open(API_DATA_JSON, 'w', encoding='utf-8') as f:
                json.dump(empty_data, f, indent=2, ensure_ascii=False)
            print(f"[ensure_api_json] Created empty API data file: {API_DATA_JSON}")
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


def fetch_posters(token):
    """
    Fetches poster data from API and saves it to api_data.json.
    Handles the new API response structure with status, message, and data array.
    
    Args:
        token: API authentication token
    
    Returns:
        list: List of poster dicts or None on failure
    """
    try:
        r = requests.get(API_BASE, params={"key": token}, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            print(f"[fetch_posters] API returned status {r.status_code}")
            return None
        
        data = r.json()
        
        # Get current system date/time
        current_dt = get_current_datetime()
        
        # Add timestamp to response
        if isinstance(data, dict):
            data["fetched_at"] = current_dt["datetime"]
            data["fetched_date"] = current_dt["date"]
            data["fetched_time"] = current_dt["time"]
        
        # Save the raw API response to JSON file
        try:
            ensure_api_json()  # Ensure file exists
            with open(API_DATA_JSON, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"[fetch_posters] Saved API response to {API_DATA_JSON}")
        except Exception as e:
            print(f"[fetch_posters] Failed to save API data to JSON: {e}")
        
        # Handle new API response structure: {status, message, data: [...]}
        if isinstance(data, dict):
            # Check for new structure with status and data array
            if "status" in data and "data" in data:
                posters = data.get("data", [])
                if isinstance(posters, list):
                    return posters
            
            # Fallback to old structure
            arr = data.get("data") or data.get("eposters") or []
            if isinstance(arr, list):
                return arr
        
        if isinstance(data, list):
            return data
        
        return []
        
    except Exception as e:
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
        
        with open(API_DATA_JSON, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data
    except Exception as e:
        print(f"[load_api_data] Error loading API data: {e}")
        return None

