#!/usr/bin/env python3
"""
show_eposters.py

Main script that orchestrates WiFi connection, API calls, and poster display.
Divided into separate modules for better organization.
"""
import os
import sys
import time
from pathlib import Path
import pygame

# Import our modules
import wifi_connect
import api_handler
import cache_handler
import display_handler
import fetch_event_data

# -------------------------
# Configuration (via env)
# -------------------------
POSTER_TOKEN = os.environ.get("POSTER_TOKEN")              # required
CACHE_REFRESH = int(os.environ.get("CACHE_REFRESH", "60"))  # seconds
DISPLAY_TIME = int(os.environ.get("DISPLAY_TIME", "5"))     # seconds

SCRIPT_DIR = Path(__file__).parent
EVENT_DATA_JSON = SCRIPT_DIR / "event_data.json"  # JSON file with event data


def load_event_data():
    """
    Loads event data from event_data.json file.
    Returns a single event dict or None on failure.
    """
    import json
    try:
        if not EVENT_DATA_JSON.exists():
            print(f"[load_event_data] Event data file not found: {EVENT_DATA_JSON}")
            return None
        with open(EVENT_DATA_JSON, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # If it's already a dict with event fields, return it directly
            if isinstance(data, dict) and ("event_id" in data or "status" in data):
                return data
            # Otherwise return None
            return None
    except Exception as e:
        print(f"[load_event_data] Error loading event data: {e}")
        return None


def print_event_info(event, image_index):
    """
    Prints event information to console.
    Handles both old format (event_id) and new API format (status/data).
    """
    print("\n" + "="*60)
    print(f"Displaying Image #{image_index + 1}")
    print("="*60)
    
    # Handle new API format with status/data structure
    if isinstance(event, dict) and "status" in event and "data" in event:
        print(f"Status:          {event.get('status', 'N/A')}")
        print(f"Message:         {event.get('message', 'N/A')}")
        data_list = event.get("data", [])
        if data_list and len(data_list) > 0:
            first_poster = data_list[0]
            print(f"Poster ID:       {first_poster.get('PosterId', 'N/A')}")
            print(f"Poster Title:    {first_poster.get('poster_title', 'N/A')}")
            print(f"Topic:           {first_poster.get('topic', 'N/A')}")
            print(f"Presenter:       {first_poster.get('main_presenter', 'N/A')}")
            print(f"Institute:       {first_poster.get('institute', 'N/A')}")
            print(f"Start DateTime:  {first_poster.get('StartDateTime', 'N/A')}")
            print(f"End DateTime:    {first_poster.get('EndDateTime', 'N/A')}")
    else:
        # Handle old format
        print(f"Event ID:        {event.get('event_id', 'N/A')}")
        print(f"Event Name:      {event.get('event_name', 'N/A')}")
        print(f"Date:            {event.get('date', 'N/A')}")
        print(f"Time:            {event.get('time', 'N/A')}")
        print(f"Venue:           {event.get('venue', 'N/A')}")
        print(f"Organizer:       {event.get('organizer', 'N/A')}")
        print(f"Category:        {event.get('category', 'N/A')}")
        print(f"Description:     {event.get('description', 'N/A')}")
    
    print("="*60 + "\n")


# -------------------------
# Main
# -------------------------
def main():
    if not POSTER_TOKEN:
        print("ERROR: POSTER_TOKEN environment variable not set.")
        sys.exit(1)

    # Step 1: Ensure WiFi connection
    print("[main] Step 1: Ensuring WiFi connection...")
    if not wifi_connect.ensure_wifi_connection():
        print("[main] WiFi connection failed. Exiting.")
        sys.exit(1)

    # Step 2: Initialize API handler (creates JSON file if needed)
    print("[main] Step 2: Initializing API handler...")
    api_handler.ensure_api_json()

    # Step 3: Initialize display
    print("[main] Step 3: Initializing display...")
    display_result = display_handler.init_display()
    if display_result is None:
        print("[main] Failed to initialize display. Exiting.")
        sys.exit(1)
    
    screen, clock, scr_w, scr_h = display_result

    # Step 4: Load or fetch event data
    print("[main] Step 4: Loading event data...")
    event_data = load_event_data()
    
    # If event data doesn't exist, try to fetch it
    if event_data is None:
        print("[main] Event data not found. Attempting to fetch from API...")
        event_api_token = os.environ.get("EVENT_API_TOKEN")
        fetched_data = fetch_event_data.fetch_event_data(token=event_api_token)
        if fetched_data:
            # Add timestamp
            current_dt = fetch_event_data.get_current_datetime()
            fetched_data["fetched_at"] = current_dt["datetime"]
            fetched_data["fetched_date"] = current_dt["date"]
            fetched_data["fetched_time"] = current_dt["time"]
            # Save it
            if fetch_event_data.save_event_data(fetched_data):
                event_data = fetched_data
                print("[main] Event data fetched and saved successfully")
    
    if event_data:
        print(f"[main] Loaded event data from {EVENT_DATA_JSON}")
        if "status" in event_data:
            print(f"[main] Event API Status: {event_data.get('status')}")
        else:
            print(f"[main] Event: {event_data.get('event_name', 'N/A')}")
    else:
        print(f"[main] No event data available. Continuing without event info.")

    # Main loop
    last_sync = 0
    image_paths = []
    idx = 0
    running = True

    try:
        while running:
            # Sync cache if needed
            now = time.time()
            if now - last_sync >= CACHE_REFRESH:
                print("[main] Fetching posters from API...")
                posters = api_handler.fetch_posters(POSTER_TOKEN)

                if posters is None:
                    print("[main] API fetch error; will retry later.")
                else:
                    # Sort posters newest → oldest using id or PosterId
                    posters = sorted(
                        posters, 
                        key=lambda x: x.get("PosterId") or x.get("id", 0), 
                        reverse=True
                    )

                    # Sync cache (pass full poster data, not just URLs)
                    # Cache handler will name files by ID and convert to landscape
                    image_paths = cache_handler.sync_cache(posters)

                    if not image_paths:
                        print("[main] No poster images found in API.")
                    else:
                        print(f"[main] Cached {len(image_paths)} images (newest → oldest).")
                last_sync = now

            if not image_paths:
                # Show waiting message
                display_handler.show_waiting_message(screen, scr_w, scr_h)
                time.sleep(1)
                # Handle quit events while waiting
                if not display_handler.handle_events():
                    running = False
                continue

            # Display current image
            path = image_paths[idx % len(image_paths)]
            current_image_idx = idx % len(image_paths)
            
            # Print event information if available
            if event_data:
                print_event_info(event_data, current_image_idx)
            
            # Display the image
            if not display_handler.display_image(screen, path, scr_w, scr_h):
                idx += 1
                continue

            # Show for DISPLAY_TIME while checking events and early-sync
            start = time.time()
            while time.time() - start < DISPLAY_TIME:
                if not display_handler.handle_events():
                    running = False
                    break
                # If it's time to refresh cache mid-display, break early to pick new images
                if time.time() - last_sync >= CACHE_REFRESH:
                    break
                clock.tick(30)

            idx += 1

    except KeyboardInterrupt:
        print("[main] KeyboardInterrupt, exiting.")
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
