#!/usr/bin/env python3
"""
show_eposters.py

Streamlined ePoster display system with time-based scheduling.
Displays posters based on their start/end times, falls back to cache if WiFi unavailable.
"""
import os
import sys
import time
from pathlib import Path
import pygame
import json
from datetime import datetime, timedelta


#importing module menu 
from menu import run_menu


# Import our modules
import wifi_connect
import api_handler
import cache_handler
import display_handler

# -------------------------
# Configuration
# -------------------------
SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / 'config.json'
API_DATA_JSON = SCRIPT_DIR / "api_data.json"

# Load configuration
with open(CONFIG_FILE, 'r') as f:
    config = json.load(f)

POSTER_TOKEN = config.get('api', {}).get('poster_token')
API_REFRESH_INTERVAL = 30  # Fetch from API every 30 seconds if WiFi connected
DEFAULT_DISPLAY_TIME = int(config.get('display', {}).get('display_time', 5))
DEVICE_ID = config.get('display', {}).get('device_id', 'default_device')

# -------------------------
# Utility Functions
# -------------------------


def log(message, level="INFO"):
    """
    Centralized logging function with timestamp and level.
    
    Args:
        message: Log message
        level: Log level (INFO, ERROR, DEBUG, WARNING)
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")


def parse_datetime(date_str, fmt="%d-%m-%Y %H:%M:%S"):
    """
    Parse datetime string safely.
    
    Args:
        date_str: DateTime string to parse
        fmt: Format string
    
    Returns:
        datetime object or None if parsing fails
    """
    try:
        return datetime.strptime(date_str, fmt)
    except Exception as e:
        log(f"[parse_datetime] Failed to parse '{date_str}': {e}", "ERROR")
        return None


def load_cached_api_data():
    """
    Load previously cached API data from api_data.json.
    
    Returns:
        dict: Cached API data or None if not available
    """
    func_name = "load_cached_api_data"
    try:
        if not API_DATA_JSON.exists():
            log(f"[{func_name}] No cached API data found", "DEBUG")
            return None
        
        with open(API_DATA_JSON, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        log(f"[{func_name}] Loaded cached API data", "DEBUG")
        return data
        
    except Exception as e:
        log(f"[{func_name}] Error loading cached API data: {e}", "ERROR")
        return None


def get_screen_config(poster_data, device_id):
    """
    Extract screen configuration for this device.
    
    Args:
        poster_data: Full API response data
        device_id: This device's ID
    
    Returns:
        tuple: (records, display_time) or (None, default_time)
    """
    func_name = "get_screen_config"
    try:
        screens = poster_data.get("screens", [])
        my_screen = next((s for s in screens if s.get("screen_number") == device_id), None)
        
        if not my_screen:
            log(f"[{func_name}] No configuration found for device: {device_id}", "WARNING")
            return None, DEFAULT_DISPLAY_TIME
        
        records = my_screen.get("records", [])
        display_time = my_screen.get("minutes_per_record", DEFAULT_DISPLAY_TIME)
        
        log(f"[{func_name}] Found {len(records)} records, display_time={display_time}s", "DEBUG")
        return records, display_time
        
    except Exception as e:
        log(f"[{func_name}] Error extracting screen config: {e}", "ERROR")
        return None, DEFAULT_DISPLAY_TIME


def parse_poster_times(records):
    """
    Parse start and end datetime strings in poster records.
    
    Args:
        records: List of poster records
    
    Returns:
        list: Records with parsed datetime objects
    """
    func_name = "parse_poster_times"
    parsed_records = []
    
    for record in records:
        start_str = record.get("start_date_time")
        end_str = record.get("end_date_time")
        
        start_dt = parse_datetime(start_str)
        end_dt = parse_datetime(end_str)
        
        if start_dt and end_dt:
            record["start_dt"] = start_dt
            record["end_dt"] = end_dt
            parsed_records.append(record)
        else:
            log(f"[{func_name}] Skipping record {record.get('id')} due to invalid dates", "WARNING")
    
    log(f"[{func_name}] Parsed {len(parsed_records)}/{len(records)} records successfully", "DEBUG")
    return parsed_records


def find_current_poster(records):
    """
    Find the poster that should be displayed right now based on time.
    
    Args:
        records: List of poster records with parsed datetimes
    
    Returns:
        dict: Current poster record or None
    """
    func_name = "find_current_poster"
    now = datetime.now()
    
    # First pass: find any poster that's currently active
    for record in records:
        if record.get("start_dt") <= now <= record.get("end_dt"):
            log(f"[{func_name}] Active poster found: ID={record.get('id')}, Title={record.get('poster_title', 'N/A')}", "INFO")
            return record
    
    log(f"[{func_name}] No active poster at {now.strftime('%H:%M:%S')}, finding closest", "DEBUG")
    
    # Second pass: find the closest upcoming poster
    upcoming = [r for r in records if r.get("start_dt") > now]
    if upcoming:
        closest = min(upcoming, key=lambda r: r.get("start_dt"))
        time_until = (closest.get("start_dt") - now).total_seconds()
        log(f"[{func_name}] Closest upcoming poster: ID={closest.get('id')}, starts in {time_until:.0f}s", "INFO")
        return closest
    
    # Third pass: find the most recent past poster
    past = [r for r in records if r.get("end_dt") < now]
    if past:
        closest = max(past, key=lambda r: r.get("end_dt"))
        log(f"[{func_name}] Using most recent past poster: ID={closest.get('id')}", "INFO")
        return closest
    
    log(f"[{func_name}] No suitable poster found", "WARNING")
    return None


def fetch_and_cache_posters(wifi_connected):
    """
    Fetch posters from API if WiFi is connected, otherwise use cache.
    
    Args:
        wifi_connected: Boolean indicating WiFi status
    
    Returns:
        tuple: (records, display_time, data_source)
               data_source is 'api' or 'cache'
    """
    func_name = "fetch_and_cache_posters"
    
    if wifi_connected:
        log(f"[{func_name}] WiFi connected, fetching from API...", "INFO")
        try:
            # Fetch from API
            poster_data = api_handler.fetch_posters(POSTER_TOKEN)
            
            if poster_data:
                # Save to cache
                with open(API_DATA_JSON, 'w', encoding='utf-8') as f:
                    json.dump(poster_data, f, indent=2)
                
                # Extract screen config
                records, display_time = get_screen_config(poster_data, DEVICE_ID)
                
                if records:
                    # Parse times
                    records = parse_poster_times(records)
                    # Sync image cache
                    image_paths = cache_handler.sync_cache(records)
                    log(f"[{func_name}] API fetch successful: {len(records)} records, {len(image_paths)} images cached", "INFO")
                    return records, display_time, 'api'
            
            log(f"[{func_name}] API fetch failed, falling back to cache", "WARNING")
        
        except Exception as e:
            log(f"[{func_name}] Exception during API fetch: {e}, falling back to cache", "ERROR")
    
    # Fall back to cached data
    log(f"[{func_name}] Using cached data", "INFO")
    cached_data = load_cached_api_data()
    
    if cached_data:
        records, display_time = get_screen_config(cached_data, DEVICE_ID)
        if records:
            records = parse_poster_times(records)
            log(f"[{func_name}] Loaded {len(records)} records from cache", "INFO")
            return records, display_time, 'cache'
    
    log(f"[{func_name}] No data available (API or cache)", "ERROR")
    return None, DEFAULT_DISPLAY_TIME, 'none'


def print_poster_info(poster, image_index):
    """
    Print current poster information to console.
    
    Args:
        poster: Poster record dictionary
        image_index: Current image index
    """
    print("\n" + "="*70)
    print(f"DISPLAYING POSTER #{image_index}")
    print("="*70)
    print(f"Poster ID:       {poster.get('id', 'N/A')}")
    print(f"Title:           {poster.get('poster_title', 'N/A')}")
    print(f"Topic:           {poster.get('topic', 'N/A')}")
    print(f"Presenter:       {poster.get('main_presenter', 'N/A')}")
    print(f"Institute:       {poster.get('institute', 'N/A')}")
    print(f"Start Time:      {poster.get('start_date_time', 'N/A')}")
    print(f"End Time:        {poster.get('end_date_time', 'N/A')}")
    
    now = datetime.now()
    start_dt = poster.get('start_dt')
    end_dt = poster.get('end_dt')
    
    if start_dt and end_dt:
        if start_dt <= now <= end_dt:
            remaining = (end_dt - now).total_seconds()
            print(f"Status:          ACTIVE (ends in {remaining/60:.1f} minutes)")
        elif start_dt > now:
            until_start = (start_dt - now).total_seconds()
            print(f"Status:          UPCOMING (starts in {until_start/60:.1f} minutes)")
        else:
            print(f"Status:          PAST")
    
    print("="*70 + "\n")


def calculate_poster_display_duration(current_poster, display_time):
    """
    Calculate how long the current poster should be displayed.
    
    Optimizes display duration based on poster schedule:
    - Active posters: show until end time or display_time (whichever is shorter)
    - Upcoming posters: show until start time or display_time
    - Past posters: show for display_time
    
    Args:
        current_poster: Current poster dictionary with start_dt and end_dt
        display_time: Default display time in seconds
    
    Returns:
        float: Duration in seconds to display this poster
    """
    func_name = "calculate_poster_display_duration"
    now_dt = datetime.now()
    start_dt = current_poster.get('start_dt')
    end_dt = current_poster.get('end_dt')
    
    # Calculate duration based on poster timing status
    if start_dt <= now_dt <= end_dt:
        # Currently active - show until end time or display_time, whichever is shorter
        time_until_end = (end_dt - now_dt).total_seconds()
        show_duration = min(display_time, time_until_end)
        log(f"[{func_name}] Active poster: showing for {show_duration:.0f}s (until end or display_time)", "DEBUG")
    elif start_dt > now_dt:
        # Upcoming - show until start time or display_time
        time_until_start = (start_dt - now_dt).total_seconds()
        show_duration = min(display_time, time_until_start)
        log(f"[{func_name}] Upcoming poster: showing for {show_duration:.0f}s (until start or display_time)", "DEBUG")
    else:
        # Past - just show for display_time
        show_duration = display_time
        log(f"[{func_name}] Past poster: showing for {show_duration:.0f}s", "DEBUG")
    
    return show_duration


def display_manual_image(screen, image_path, scr_w, scr_h):
    """
    Display a manually selected image from the menu.
    
    Args:
        screen: Pygame screen surface
        image_path: Path to image file
        scr_w: Screen width
        scr_h: Screen height
    
    Returns:
        bool: True if image displayed successfully, False if not found
    """
    func_name = "display_manual_image"
    
    if image_path.exists():
        display_handler.display_image(screen, image_path, scr_w, scr_h)
        pygame.display.flip()
        log(f"[{func_name}] Manual image displayed: {image_path.name}", "INFO")
        return True
    else:
        display_handler.show_waiting_message(screen, scr_w, scr_h, message="Image not found")
        pygame.display.flip()
        log(f"[{func_name}] Manual image not found: {image_path}", "WARNING")
        time.sleep(2)
        return False


# -------------------------
# Main Function
# -------------------------

def main():
    """
    Main application loop with optimized timing and efficient event handling.
    
    Flow:
    1. Initialize display (essential first step)
    2. Attempt WiFi connection (non-blocking)
    3. Load data (API if WiFi, else cache)
    4. Display posters based on schedule
    5. Refresh data at calculated intervals (no redundant checks)
    
    Optimizations:
    - Pre-calculate next refresh time to avoid constant time checks
    - Pre-calculate poster display duration to avoid repeated datetime operations
    - Single main loop without nested sub-loops for better control flow
    - Event-driven menu handling via right-click
    """
    func_name = "main"
    log(f"[{func_name}] ========== ePoster Display System Starting ==========", "INFO")
    
    # Validate configuration
    if not POSTER_TOKEN:
        log(f"[{func_name}] ERROR: POSTER_TOKEN not configured", "ERROR")
        sys.exit(1)
    
    # -------------------------
    # STEP 1: Initialize Display (Priority)
    # -------------------------
    log(f"[{func_name}] STEP 1: Initializing display...", "INFO")
    display_result = display_handler.init_display()
    
    if display_result is None:
        log(f"[{func_name}] Failed to initialize display. Exiting.", "ERROR")
        sys.exit(1)
    
    screen, clock, scr_w, scr_h = display_result
    log(f"[{func_name}] Display initialized: {scr_w}x{scr_h}", "INFO")
    
    # -------------------------
    # STEP 2: Attempt WiFi Connection (Non-blocking)
    # -------------------------
    log(f"[{func_name}] STEP 2: Attempting WiFi connection...", "INFO")
    display_handler.show_waiting_message(screen, scr_w, scr_h, message="Connecting to WiFi...")
    pygame.display.flip()
    
    wifi_connected = wifi_connect.ensure_wifi_connection()
    
    if wifi_connected:
        log(f"[{func_name}] WiFi connected successfully", "INFO")
    else:
        log(f"[{func_name}] WiFi connection failed, will use cached data", "WARNING")
        display_handler.show_waiting_message(screen, scr_w, scr_h, message="WiFi unavailable - Using cached data")
        pygame.display.flip()
        time.sleep(2)
    
    # -------------------------
    # STEP 3: Initialize API Handler
    # -------------------------
    log(f"[{func_name}] STEP 3: Initializing API handler...", "INFO")
    api_handler.ensure_api_json()
    
    # -------------------------
    # STEP 4: Initial Data Load
    # -------------------------
    log(f"[{func_name}] STEP 4: Performing initial data load", "INFO")
    records, display_time, data_source = fetch_and_cache_posters(wifi_connected)
    
    # Calculate next refresh time (optimization: avoid checking time.time() every frame)
    next_refresh_time = time.time() + API_REFRESH_INTERVAL
    log(f"[{func_name}] Next data refresh scheduled at: {datetime.fromtimestamp(next_refresh_time).strftime('%H:%M:%S')}", "DEBUG")
    
    # -------------------------
    # Main Display Loop Variables
    # -------------------------
    log(f"[{func_name}] STEP 5: Entering main display loop", "INFO")
    
    running = True
    display_manual = False  # Flag: are we showing a manually selected image?
    manual_image_path = ""  # Path to manually selected image
    current_poster = None   # Current poster being displayed
    poster_display_end_time = 0  # When to switch to next poster (optimization)
    
    try:
        while running:
            # -------------------------
            # Event Handling (Must happen every frame)
            # -------------------------
            for event in pygame.event.get():
                # Window close event
                if event.type == pygame.QUIT:
                    running = False
                    break
                
                # Right-click: Open menu for manual control
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                    log(f"[{func_name}] Right-click detected, opening menu", "INFO")
                    
                    # Run menu and get user action
                    action, payload = run_menu()
                    
                    # Process menu action
                    if action == "TIMED_POSTER":
                        # Return to automatic time-based display
                        display_manual = False
                        manual_image_path = ""
                        display_handler.show_waiting_message(screen, scr_w, scr_h, message="Returning to timed poster display...")
                        log(f"[{func_name}] Returning to timed poster display", "INFO")
                    
                    elif action == "IMAGE_SELECTED":
                        # Switch to manual image display
                        display_manual = True
                        manual_image_path = payload
                        log(f"[{func_name}] Manual image selected: {payload}", "INFO")
                    
                    elif action == "EXIT":
                        # Exit application
                        log(f"[{func_name}] Exit requested from menu", "INFO")
                        running = False
                        break
            
            # Convert manual_image_path to Path object if needed
            manual_image_path = Path(manual_image_path) if manual_image_path else Path("")
            
            # -------------------------
            # Manual Image Display Mode
            # -------------------------
            if display_manual:
                # Display manually selected image
                # If display fails (image not found), mode will automatically switch off
                display_manual = display_manual_image(screen, manual_image_path, scr_w, scr_h)
                
                # Continue to next frame (skip automatic poster display logic)
                clock.tick(30)  # Limit to 30 FPS
                continue
            
            # -------------------------
            # Automatic Poster Display Mode
            # -------------------------
            
            # Check if it's time to refresh data from API
            # (Optimization: only check once per interval, not every frame)
            current_time = time.time()
            if current_time >= next_refresh_time:
                log(f"[{func_name}] Refresh interval reached, fetching new data", "DEBUG")
                
                # Check WiFi status
                wifi_connected = wifi_connect.ensure_wifi_connection()
                
                # Fetch and cache new data
                new_records, new_display_time, new_source = fetch_and_cache_posters(wifi_connected)
                
                # Update records if fetch was successful
                if new_records:
                    records = new_records
                    display_time = new_display_time
                    data_source = new_source
                    log(f"[{func_name}] Data refreshed from {data_source}: {len(records)} records", "INFO")
                    
                    # Force poster re-evaluation on next frame
                    poster_display_end_time = 0
                
                # Schedule next refresh
                next_refresh_time = current_time + API_REFRESH_INTERVAL
                log(f"[{func_name}] Next refresh scheduled at: {datetime.fromtimestamp(next_refresh_time).strftime('%H:%M:%S')}", "DEBUG")
            
            # -------------------------
            # Check if we have poster data
            # -------------------------
            if not records:
                log(f"[{func_name}] No poster data available", "WARNING")
                display_handler.show_waiting_message(
                    screen, scr_w, scr_h, 
                    message="No poster data available\nWaiting for data..."
                )
                pygame.display.flip()
                time.sleep(5)
                continue
            
            # -------------------------
            # Check if it's time to find/switch to next poster
            # (Optimization: only recalculate when display time expires)
            # -------------------------
            if current_time >= poster_display_end_time:
                # Find the poster that should be displayed right now
                current_poster = find_current_poster(records)
                
                if not current_poster:
                    log(f"[{func_name}] No suitable poster found for current time", "WARNING")
                    display_handler.show_waiting_message(
                        screen, scr_w, scr_h,
                        message="No posters scheduled at this time"
                    )
                    pygame.display.flip()
                    time.sleep(5)
                    continue
                
                # Get poster details
                poster_id = current_poster.get('id')
                image_path = SCRIPT_DIR / "eposter_cache" / f"{poster_id}.png"
                
                # Print poster info to console
                print_poster_info(current_poster, poster_id)
                
                # Check if image file exists
                if not image_path.exists():
                    log(f"[{func_name}] Image not found for poster {poster_id}: {image_path}", "ERROR")
                    display_handler.show_waiting_message(
                        screen, scr_w, scr_h,
                        message=f"Image not found for poster {poster_id}"
                    )
                    pygame.display.flip()
                    time.sleep(5)
                    continue
                
                # Display the poster image
                if not display_handler.display_image(screen, str(image_path), scr_w, scr_h):
                    log(f"[{func_name}] Failed to display image: {image_path}", "ERROR")
                    time.sleep(1)
                    continue
                
                pygame.display.flip()
                
                # Calculate how long to display this poster
                # (Optimization: calculate once, reuse until time expires)
                show_duration = calculate_poster_display_duration(current_poster, display_time)
                poster_display_end_time = current_time + show_duration
                
                log(f"[{func_name}] Poster display scheduled until: {datetime.fromtimestamp(poster_display_end_time).strftime('%H:%M:%S')}", "DEBUG")
            
            # -------------------------
            # Frame Rate Control
            # -------------------------
            # Limit frame rate to reduce CPU usage
            clock.tick(30)  # 30 FPS is sufficient for a display system
        
    except KeyboardInterrupt:
        log(f"[{func_name}] KeyboardInterrupt received, shutting down gracefully", "INFO")
    
    except Exception as e:
        log(f"[{func_name}] Unexpected error in main loop: {e}", "ERROR")
        import traceback
        traceback.print_exc()
    
    finally:
        log(f"[{func_name}] ========== ePoster Display System Shutting Down ==========", "INFO")
        pygame.quit()


if __name__ == "__main__":
    main()