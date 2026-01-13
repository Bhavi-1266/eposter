#!/usr/bin/env python3
import cache_handler
import json
from pathlib import Path

# 1. Load data directly from api_data.json to see what Master Display sees
try:
    with open('api_data.json', 'r') as f:
        data = json.load(f)
        print("Loaded api_data.json successfully.")
except FileNotFoundError:
    print("!! api_data.json NOT FOUND. Run the master script once first to fetch data.")
    data = {}

# 2. Extract records for the device defined in config
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
        device_id = config.get("display", {}).get("device_id")
        print(f"Testing for Device ID: {device_id}")
except:
    device_id = "default_device"

# 3. Find records
records = []
if data:
    screens = data.get("screens", [])
    my_screen = next((s for s in screens if str(s.get("screen_number")) == str(device_id)), None)
    
    if my_screen:
        records = my_screen.get("records", [])
        print(f"Found {len(records)} records for this device.")
    else:
        print(f"!! Device ID {device_id} NOT FOUND in api_data.json")
        print(f"Available screens: {[s.get('screen_number') for s in screens]}")

# 4. Add a dummy test record to prove downloading works generally
print("\n--- Adding a TEST record (Google Logo) to verify internet ---")
test_record = {
    "id": 9999, 
    "file": "https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png"
}
records.append(test_record)

# 5. Run Sync
print("\n>>> RUNNING SYNC...")
cache_handler.sync_cache(records)