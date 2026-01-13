#!/usr/bin/env python3
"""
master_display.py

Unified ePoster Controller.
- Checks config.json to determine mode (Time, Menu, Scroll).
- dynamically switches modes without restarting.
"""

import os
import sys
import time
import json
import pygame
from pathlib import Path
from datetime import datetime

# Custom Modules (Assumed to exist based on your prompt)
import wifi_connect
import api_handler
import cache_handler
import display_handler

# -----------------------------------------------------------------------------
# GLOBAL CONFIGURATION & UTILS
# -----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / 'config.json'
API_DATA_JSON = SCRIPT_DIR / "api_data.json"
CACHE_DIR = SCRIPT_DIR / "eposter_cache"

# Colors & Fonts
COLORS = {
    "BG": (18, 18, 18),
    "TOPBAR": (28, 28, 28),
    "BTN": (50, 90, 160),
    "BTN_HOVER": (70, 120, 200),
    "TEXT": (230, 230, 230),
    "ITEM_BG": (35, 35, 35),
    "HOVER": (60, 60, 60)
}

def log(message, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")

def load_config():
    """Reads the full config dictionary."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        log(f"Config read error: {e}", "ERROR")
        return {}

def save_config_mode(new_mode):
    """Updates just the mode in config.json."""
    try:
        data = load_config()
        if "display" not in data:
            data["display"] = {}
        data["display"]["Mode"] = new_mode
        with open(CONFIG_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        log(f"Config updated: Mode set to {new_mode}", "INFO")
    except Exception as e:
        log(f"Config write error: {e}", "ERROR")

def get_current_mode():
    """Returns 'Time', 'Menu', or 'Scroll'."""
    cfg = load_config()
    return cfg.get('display', {}).get('Mode', 'Menu')

def get_rotation():
    cfg = load_config()
    return int(cfg.get('display', {}).get('rotation_degree', 0))

# -----------------------------------------------------------------------------
# MODE 1: TIME BASED (Original Logic Refined)
# -----------------------------------------------------------------------------
def parse_datetime(date_str):
    try:
        return datetime.strptime(date_str, "%d-%m-%Y %H:%M:%S")
    except:
        return None

def run_time_mode(screen, clock):
    log(">>> Starting TIME Mode", "INFO")
    
    # Initial Config Load
    config = load_config()
    poster_token = config.get('api', {}).get('poster_token')
    device_id = config.get('display', {}).get('device_id')
    rotation = config.get('display', {}).get('rotation_degree', 0)
    
    scr_w, scr_h = screen.get_size()
    
    # Connect WiFi & Fetch
    wifi_connect.ensure_wifi_connection()
    # (Assuming api_handler logic here matches your previous script)
    try:
        poster_data = api_handler.fetch_posters(poster_token)
        if poster_data:
            with open(API_DATA_JSON, 'w') as f: json.dump(poster_data, f)
    except:
        pass # Fallback to existing cache

    # Load Records
    records = []
    display_time = 5
    if API_DATA_JSON.exists():
        with open(API_DATA_JSON, 'r') as f:
            data = json.load(f)
            screens = data.get("screens", [])
            my_screen = next((s for s in screens if s.get("screen_number") == device_id), None)
            if my_screen:
                records = my_screen.get("records", [])
                display_time = my_screen.get("minutes_per_record", 5)

    # Process Dates
    valid_records = []
    for r in records:
        s = parse_datetime(r.get("start_date_time"))
        e = parse_datetime(r.get("end_date_time"))
        if s and e:
            r["start_dt"] = s
            r["end_dt"] = e
            valid_records.append(r)
            
    cache_handler.sync_cache(valid_records, device_id)

    # Loop Vars
    poster_end_time = 0
    next_config_check = time.time() + 2
    
    running = True
    while running:
        current_time = time.time()
        
        # 1. Check for Mode Switch (Every 2 seconds)
        if current_time > next_config_check:
            if get_current_mode() != "Time":
                return # Exit function to let Main switch modes
            next_config_check = current_time + 2

        # 2. Event Handling
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                # Optional: ESC in Time mode goes to Menu? 
                # For now, let's make ESC switch to Menu mode in config
                save_config_mode("Menu")
                return

        # 3. Logic
        if current_time >= poster_end_time:
            now = datetime.now()
            # Find active poster
            active = None
            # (Simplified logic from your script)
            for r in valid_records:
                if r["start_dt"] <= now <= r["end_dt"]:
                    active = r; break
            
            # Fallback logic if needed (upcoming/past)...
            if not active and valid_records:
                active = valid_records[0] # simplistic fallback

            screen.fill(COLORS["BG"])
            
            if active:
                pid = active.get('id')
                img_path = CACHE_DIR / f"{pid}.png"
                if img_path.exists():
                    display_handler.display_image(screen, img_path, scr_w, scr_h, rotation)
                    poster_end_time = current_time + display_time
                else:
                    display_handler.show_waiting_message(screen, scr_w, scr_h, f"Missing: {pid}", rotation)
                    poster_end_time = current_time + 2
            else:
                display_handler.show_waiting_message(screen, scr_w, scr_h, "No Schedule", rotation)
                poster_end_time = current_time + 2
            
            pygame.display.flip()

        clock.tick(30)

# -----------------------------------------------------------------------------
# MODE 2: AUTO SCROLL (New Feature)
# -----------------------------------------------------------------------------
def run_scroll_mode(screen, clock):
    log(">>> Starting SCROLL Mode", "INFO")
    
    config = load_config()
    scroll_delay = int(config.get('display', {}).get('Auto_Scroll', 5))
    rotation = int(config.get('display', {}).get('rotation_degree', 0))
    scr_w, scr_h = screen.get_size()

    # Load Images
    images = sorted([f for f in CACHE_DIR.glob('*') if f.suffix.lower() in ['.png', '.jpg', '.jpeg']])
    
    if not images:
        display_handler.show_waiting_message(screen, scr_w, scr_h, "No Images in Cache", rotation)
        pygame.display.flip()
        time.sleep(2)
        return # Return to main to re-check

    index = 0
    next_switch = 0
    next_config_check = time.time() + 2

    running = True
    while running:
        current_time = time.time()

        # 1. Config Check
        if current_time > next_config_check:
            if get_current_mode() != "Scroll": return
            # Also refresh image list periodically?
            next_config_check = current_time + 2

        # 2. Events
        for event in pygame.event.get():
            if event.type == pygame.QUIT: pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                save_config_mode("Menu")
                return

        # 3. Render
        if current_time >= next_switch:
            img_path = images[index]
            display_handler.display_image(screen, img_path, scr_w, scr_h, rotation)
            pygame.display.flip()
            
            index = (index + 1) % len(images)
            next_switch = current_time + scroll_delay

        clock.tick(30)

# -----------------------------------------------------------------------------
# MODE 3: MENU (GUI Interaction)
# -----------------------------------------------------------------------------
def run_menu_mode(screen, clock):
    log(">>> Starting MENU Mode", "INFO")
    
    font = pygame.font.SysFont("arial", 22)
    btn_font = pygame.font.SysFont("arial", 24, bold=True)
    
    WIDTH, HEIGHT = screen.get_size()
    TOPBAR_HEIGHT = 70
    
    # Button to switch back to Time Mode
    btn_rect = pygame.Rect(30, 15, 220, 45)
    
    # Load List
    items = []
    if CACHE_DIR.exists():
        for f in sorted(CACHE_DIR.iterdir()):
            if f.suffix.lower() in ['.png', '.jpg']:
                try:
                    img = pygame.image.load(str(f)).convert_alpha()
                    # Scale thumb
                    iw, ih = img.get_size()
                    scale = min(200/ih, 200/iw) # Thumbnail size
                    thumb = pygame.transform.smoothscale(img, (int(iw*scale), int(ih*scale)))
                    items.append({"path": f, "thumb": thumb, "name": f.name})
                except: pass

    scroll_y = 0
    next_config_check = time.time() + 1
    
    running = True
    while running:
        current_time = time.time()

        # 1. External Config Check
        if current_time > next_config_check:
            if get_current_mode() != "Menu": return
            next_config_check = current_time + 1

        mx, my = pygame.mouse.get_pos()
        
        # 2. Events
        for event in pygame.event.get():
            if event.type == pygame.QUIT: pygame.quit(); sys.exit()
            
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    # Clicked "Timed Poster" button
                    if btn_rect.collidepoint(mx, my):
                        save_config_mode("Time") # Write to config
                        return # Exit to main loop
                
                # Mouse Wheel
                if event.button == 4: scroll_y = min(0, scroll_y + 30)
                if event.button == 5: scroll_y -= 30

        # 3. Draw UI
        screen.fill(COLORS["BG"])
        
        # Draw Items
        start_y = TOPBAR_HEIGHT + 20 + scroll_y
        row_h = 220
        
        for i, item in enumerate(items):
            # Simple list layout
            y_pos = start_y + (i * (row_h + 10))
            if -row_h < y_pos < HEIGHT:
                r = pygame.Rect(50, y_pos, WIDTH-100, row_h)
                pygame.draw.rect(screen, COLORS["ITEM_BG"], r, border_radius=10)
                screen.blit(item["thumb"], (60, y_pos + 10))
                
                txt = font.render(item["name"], True, COLORS["TEXT"])
                screen.blit(txt, (300, y_pos + 100))

        # Top Bar (drawn last to stay on top)
        pygame.draw.rect(screen, COLORS["TOPBAR"], (0,0,WIDTH, TOPBAR_HEIGHT))
        
        # Button
        b_col = COLORS["BTN_HOVER"] if btn_rect.collidepoint(mx, my) else COLORS["BTN"]
        pygame.draw.rect(screen, b_col, btn_rect, border_radius=8)
        
        btxt = btn_font.render("Start Time Mode", True, COLORS["TEXT"])
        screen.blit(btxt, (btn_rect.centerx - btxt.get_width()//2, btn_rect.centery - btxt.get_height()//2))

        pygame.display.flip()
        clock.tick(60)

# -----------------------------------------------------------------------------
# MAIN CONTROLLER
# -----------------------------------------------------------------------------
def main():
    log("System Initializing...", "INFO")
    
    # One-time Pygame Init
    pygame.init()
    pygame.mouse.set_visible(True)
    
    # Assuming Fullscreen
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    clock = pygame.time.Clock()
    
    while True:
        # 1. Read Mode
        current_mode = get_current_mode()
        
        # 2. Dispatch to correct function
        if current_mode == "Time":
            run_time_mode(screen, clock)
        elif current_mode == "Menu":
            run_menu_mode(screen, clock)
        elif current_mode == "Scroll":
            run_scroll_mode(screen, clock)
        else:
            log(f"Unknown mode '{current_mode}', defaulting to Menu", "WARN")
            run_menu_mode(screen, clock)
        
        # When a function returns, the loop repeats, 
        # re-reading the config and starting the new mode.

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")