#!/usr/bin/env python3
"""
eposterNoMenu.py (Master Display Controller)
"""

import os
import sys
import time
import json
import pygame
from pathlib import Path
from datetime import datetime
import socket

# --- Custom Modules ---
import wifi_connect
import api_handler
import cache_handler
import display_handler

# -------------------------
# Configuration & Constants
# -------------------------
SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / 'config.json'
API_DATA_JSON = SCRIPT_DIR / "api_data.json"
CACHE_DIR = SCRIPT_DIR / "eposter_cache"

# -------------------------
# Utility Functions
# -------------------------
def log(message, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f: return json.load(f)
    except: return {}

def update_config_mode(new_mode):
    try:
        data = load_config()
        if 'display' not in data: data['display'] = {}
        data['display']['Mode'] = new_mode
        with open(CONFIG_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        log(f"Config updated: Mode set to {new_mode}", "INFO")
    except Exception as e:
        log(f"Config write error: {e}", "ERROR")

def parse_datetime(date_str, fmt="%d-%m-%Y %H:%M:%S"):
    try: return datetime.strptime(date_str, fmt)
    except: return None

# ---------------------------------------------------------
# DATA & SYNC HELPER
# ---------------------------------------------------------
def get_device_records(device_id):
    if not API_DATA_JSON.exists(): return [], 5
    try:
        with open(API_DATA_JSON, 'r') as f: data = json.load(f)
        screens = data.get("screens", [])
        my_screen = next((s for s in screens if str(s.get("screen_number")) == str(device_id)), None)
        if not my_screen: return [], 5
        records = []
        for r in my_screen.get("records", []):
            s = parse_datetime(r.get("start_date_time"))
            e = parse_datetime(r.get("end_date_time"))
            if s and e:
                r["start_dt"] = s
                r["end_dt"] = e
                records.append(r)
        return records, my_screen.get("minutes_per_record", 5)
    except Exception as e:
        log(f"Error parsing records: {e}", "ERROR")
        return [], 5

def get_booking_records():
    if not API_DATA_JSON.exists():
        return []
    try:
        with open(API_DATA_JSON, 'r') as f:
            data = json.load(f)
        bookings = data.get("booking_slot", [])
        records = []
        for b in bookings:
            details = b.get("paper_details") or {}
            if details:
                records.append(details)
        return records
    except Exception as e:
        log(f"Error parsing booking slots: {e}", "ERROR")
        return []

def refresh_data_and_cache(poster_token, device_id):
    log(f"--- Refreshing Data for Device: {device_id} ---", "INFO")
    if wifi_connect.ensure_wifi_connection():
        new_data = api_handler.fetch_posters(poster_token)
        if new_data:
            with open(API_DATA_JSON, 'w') as f: json.dump(new_data, f)
    records, duration = get_device_records(device_id)
    booking_records = get_booking_records()
    cache_handler.sync_cache((records or []) + (booking_records or []))
    return records, duration

# ---------------------------------------------------------
# STARTUP SEQUENCE
# ---------------------------------------------------------
def system_startup_check(screen):
    scr_w, scr_h = screen.get_size()
    cfg = load_config()
    rotation = int(cfg.get('display', {}).get('rotation_degree', 0))
    token = cfg.get('api', {}).get('poster_token')
    dev_id = cfg.get('display', {}).get('device_id')

    display_handler.show_waiting_message(screen, scr_w, scr_h, "System Startup...\nChecking WiFi & Syncing Data", rotation)
    refresh_data_and_cache(token, dev_id)
    display_handler.show_waiting_message(screen, scr_w, scr_h, "Startup Complete!\nStarting Mode...", rotation)
    time.sleep(1)

# ---------------------------------------------------------
# MODE 1: TIME (Nearest/Active Logic)
# ---------------------------------------------------------
def run_time_mode(screen, clock):
    log(">>> Entering TIME Mode", "INFO")
    cfg = load_config()
    device_id = cfg.get('display', {}).get('device_id')
    token = cfg.get('api', {}).get('poster_token')
    rotation = int(cfg.get('display', {}).get('rotation_degree', 0))
    scr_w, scr_h = screen.get_size()
    records, duration = get_device_records(device_id)
    
    poster_end_time = 0
    next_sync_time = time.time() + 30 
    last_config_check = time.time()

    running = True
    while running:
        current_time = time.time()
    
        if current_time - last_config_check > 2:
            check_cfg = load_config()
            if check_cfg.get('display', {}).get('Mode') != "Time": return
            rotation = int(check_cfg.get('display', {}).get('rotation_degree', 0))
            new_id = check_cfg.get('display', {}).get('device_id')
            if str(new_id) != str(device_id):
                display_handler.show_waiting_message(screen, scr_w, scr_h, "Device ID Changed\nRefetching Data...", rotation)
                device_id = new_id
                records, duration = refresh_data_and_cache(token, device_id)
                poster_end_time = 0 
            last_config_check = current_time

        if current_time > next_sync_time:
            records, duration = refresh_data_and_cache(token, device_id)
            next_sync_time = current_time + 30
            poster_end_time = 0 

        for event in pygame.event.get():
            if event.type == pygame.QUIT: sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_q: sys.exit()

        if not records:
            display_handler.show_waiting_message(screen, scr_w, scr_h, f"No Schedule for Device {device_id}", rotation)
            display_handler.display_url(screen, scr_w, scr_h, rotation)
            pygame.display.flip()
            time.sleep(1)
            continue
            
        if current_time >= poster_end_time:
            now = datetime.now()
            def get_dist(r):
                if r["start_dt"] <= now <= r["end_dt"]: return 0
                elif now < r["start_dt"]: return (r["start_dt"] - now).total_seconds()
                else: return (now - r["end_dt"]).total_seconds()
            
            active = min(records, key=get_dist)
            if active:
                pid = active.get("id") or active.get("PosterId")
                path = cache_handler.get_image_path(pid)
                if path and path.exists():
                    display_handler.display_image(screen, path, scr_w, scr_h, rotation)
                    display_handler.display_url(screen, scr_w, scr_h, rotation)
                    pygame.display.flip()
                    poster_end_time = current_time + (max(5, min(duration, (active["end_dt"]-now).total_seconds())) if get_dist(active)==0 else 5)
                else:
                    display_handler.show_waiting_message(screen, scr_w, scr_h, f"Downloading ID: {pid}...", rotation)
                    display_handler.display_url(screen, scr_w, scr_h, rotation)
                    pygame.display.flip()
                    cache_handler.sync_cache([active]) 
                    poster_end_time = current_time + 2
            else:
                display_handler.show_waiting_message(screen, scr_w, scr_h, "No Posters Scheduled", rotation)
                display_handler.display_url(screen, scr_w, scr_h, rotation)
                pygame.display.flip()
                poster_end_time = current_time + 5
        clock.tick(30)

# ---------------------------------------------------------
# MODE 2: SCROLL
# ---------------------------------------------------------
def run_scroll_mode(screen, clock):
    log(">>> Entering SCROLL Mode", "INFO")
    cfg = load_config()
    device_id = cfg.get('display', {}).get('device_id')
    token = cfg.get('api', {}).get('poster_token')
    scroll_delay = int(cfg.get('display', {}).get('Auto_Scroll', 5))
    rotation = int(cfg.get('display', {}).get('rotation_degree', 0))
    scr_w, scr_h = screen.get_size()

    def get_valid_images(recs):
        if recs:
            ids = [str(r.get("id") or r.get("PosterId")) for r in recs]
            imgs = [p for i in ids if (p := cache_handler.get_image_path(i))]
            return imgs
        return sorted([f for f in CACHE_DIR.glob('*') if f.suffix.lower() in ['.png', '.jpg', '.jpeg']])

    records, _ = get_device_records(device_id)
    images = get_valid_images(records)
    index = 0
    next_switch = 0
    next_sync_time = time.time() + 30
    last_config_check = time.time()

    running = True
    while running:
        current_time = time.time()
        
        if current_time - last_config_check > 2:
            check_cfg = load_config()
            if check_cfg.get('display', {}).get('Mode') != "Scroll": return
            rotation = int(check_cfg.get('display', {}).get('rotation_degree', 0))
            scroll_delay = int(check_cfg.get('display', {}).get('Auto_Scroll', 5))
            new_id = check_cfg.get('display', {}).get('device_id')
            if str(new_id) != str(device_id):
                display_handler.show_waiting_message(screen, scr_w, scr_h, "Device ID Changed...", rotation)
                device_id = new_id
                records, _ = refresh_data_and_cache(token, device_id)
                images = get_valid_images(records)
                index = 0
            last_config_check = current_time

        if current_time > next_sync_time:
            records, _ = refresh_data_and_cache(token, device_id)
            images = get_valid_images(records)
            next_sync_time = current_time + 30

        for event in pygame.event.get():
            if event.type == pygame.QUIT: sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_q: sys.exit()

        if not images:
            display_handler.show_waiting_message(screen, scr_w, scr_h, f"No Images (ID: {device_id})", rotation)
            display_handler.display_url(screen, scr_w, scr_h, rotation)
            pygame.display.flip()
            time.sleep(2)
            images = get_valid_images(records)
            continue

        if current_time >= next_switch:
            if index >= len(images): index = 0
            if images[index].exists():
                display_handler.display_image(screen, images[index], scr_w, scr_h, rotation)
                display_handler.display_url(screen, scr_w, scr_h, rotation)
                pygame.display.flip()
            index = (index + 1) % len(images)
            next_switch = current_time + scroll_delay
        clock.tick(30)

# ---------------------------------------------------------
# MODE 3: MENU (Rotated Interactive)
# ---------------------------------------------------------
def run_menu_mode(screen, clock):
    log(">>> Entering MENU Mode", "INFO")
    cfg = load_config()
    device_id = cfg.get('display', {}).get('device_id')
    token = cfg.get('api', {}).get('poster_token')
    rotation = int(cfg.get('display', {}).get('rotation_degree', 0))
    PHY_W, PHY_H = screen.get_size()

    if rotation in [90, 270]: UI_W, UI_H = PHY_H, PHY_W
    else: UI_W, UI_H = PHY_W, PHY_H

    ui_surface = pygame.Surface((UI_W, UI_H))
    BG_COLOR, TOPBAR_COLOR = (18, 18, 18), (28, 28, 28)
    BUTTON_COLOR, BUTTON_HOVER = (50, 90, 160), (70, 120, 200)
    ITEM_BG, HOVER_COLOR, TEXT_COLOR = (35, 35, 35), (60, 60, 60), (230, 230, 230)
    
    IMAGE_MAX_WIDTH, IMAGE_MAX_HEIGHT = int(UI_W * 0.8), int(UI_H * 0.5)
    TOPBAR_HEIGHT, BUTTON_WIDTH, BUTTON_HEIGHT = 70, 220, 45
    ITEM_PADDING, TEXT_HEIGHT, SCROLL_SPEED = 25, 30, 50
    button_font = pygame.font.SysFont("arial", 24, bold=True)
    button_rect = pygame.Rect(30, TOPBAR_HEIGHT//2 - BUTTON_HEIGHT//2, BUTTON_WIDTH, BUTTON_HEIGHT)

    def map_mouse(px, py):
        if rotation == 0: return px, py
        if rotation == 90: return py, PHY_W - px
        if rotation == 180: return PHY_W - px, PHY_H - py
        if rotation == 270: return PHY_H - py, px
        return px, py

    def load_menu_images():
        loaded_items = []
        files = sorted([f for f in CACHE_DIR.glob('*') if f.suffix.lower() in ['.png', '.jpg', '.jpeg']])
        for path in files:
            try:
                img = pygame.image.load(path).convert_alpha()
                w, h = img.get_size()
                scale = min(IMAGE_MAX_WIDTH / w, IMAGE_MAX_HEIGHT / h)
                img = pygame.transform.smoothscale(img, (int(w * scale), int(h * scale)))
                loaded_items.append({"image": img, "path": path, "height": img.get_height() + TEXT_HEIGHT + ITEM_PADDING * 2})
            except: pass
        return loaded_items
    
    display_handler.show_waiting_message(screen, PHY_W, PHY_H, "Loading Menu...", rotation)
    items = load_menu_images()
    scroll_y, next_sync_time, last_config_check = 0, time.time() + 30, time.time()

    running = True
    while running:
        clock.tick(60)
        ui_surface.fill(BG_COLOR)
        raw_mx, raw_my = pygame.mouse.get_pos()
        mx, my = map_mouse(raw_mx, raw_my)
        current_time = time.time()

        if current_time - last_config_check > 2:
            check_cfg = load_config()
            if check_cfg.get('display', {}).get('Mode') != "Menu": return
            if str(check_cfg.get('display', {}).get('device_id')) != str(device_id):
                return # Restart mode
            if int(check_cfg.get('display', {}).get('rotation_degree', 0)) != rotation:
                return 
            last_config_check = current_time

        for event in pygame.event.get():
            if event.type == pygame.QUIT: sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_q: sys.exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    if button_rect.collidepoint(mx, my):
                        update_config_mode("Time")
                        return
                    y_offset = scroll_y + TOPBAR_HEIGHT + 20
                    for item in items:
                        if y_offset + item['height'] > 0 and y_offset < UI_H:
                            if pygame.Rect(40, y_offset, UI_W-80, item['height']).collidepoint(mx, my):
                                display_handler.display_image(screen, item['path'], PHY_W, PHY_H, rotation)
                                # URL on top of preview
                                display_handler.display_url(screen, PHY_W, PHY_H, rotation)
                                pygame.display.flip()
                                waiting = True
                                t_start = time.time()
                                while waiting:
                                    for e in pygame.event.get():
                                        if e.type in [pygame.MOUSEBUTTONDOWN, pygame.KEYDOWN]: waiting = False
                                    if time.time() - t_start > 60: waiting = False
                                    clock.tick(30)
                                break
                        y_offset += item['height'] + 25
                elif event.button == 4: scroll_y += SCROLL_SPEED
                elif event.button == 5: scroll_y -= SCROLL_SPEED

        total_h = sum(i["height"] + 25 for i in items)
        if total_h > 0:
            scroll_y = max(-max(0, total_h - (UI_H - TOPBAR_HEIGHT)), min(0, scroll_y))
        
        pygame.draw.rect(ui_surface, TOPBAR_COLOR, (0, 0, UI_W, TOPBAR_HEIGHT))
        c = BUTTON_HOVER if button_rect.collidepoint(mx, my) else BUTTON_COLOR
        pygame.draw.rect(ui_surface, c, button_rect, border_radius=8)
        txt = button_font.render("Start Schedule", True, TEXT_COLOR)
        ui_surface.blit(txt, (button_rect.centerx - txt.get_width()//2, button_rect.centery - txt.get_height()//2))

        y = scroll_y + TOPBAR_HEIGHT + 20
        for item in items:
            if y + item["height"] > 0 and y < UI_H:
                rect = pygame.Rect(40, y, UI_W-80, item["height"])
                bg = HOVER_COLOR if rect.collidepoint(mx, my) else ITEM_BG
                pygame.draw.rect(ui_surface, bg, rect, border_radius=12)
                ui_surface.blit(item["image"], (UI_W//2 - item["image"].get_width()//2, y + ITEM_PADDING))
            y += item["height"] + 25

        if rotation == 0: screen.blit(ui_surface, (0, 0))
        else:
            rot_s = pygame.transform.rotate(ui_surface, -rotation)
            screen.blit(rot_s, ((PHY_W - rot_s.get_width()) // 2, (PHY_H - rot_s.get_height()) // 2))

        display_handler.display_url(screen, PHY_W, PHY_H, rotation)
        pygame.display.flip()

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    log("========== Master Controller Started ==========", "INFO")
    pygame.init()
    pygame.mouse.set_visible(True)
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    clock = pygame.time.Clock()
    system_startup_check(screen)
    
    while True:
        cfg = load_config()
        mode = cfg.get('display', {}).get('Mode', 'Time')
        for event in pygame.event.get():
            if event.type == pygame.QUIT: sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_q: sys.exit()
        if mode == "Time" or mode == "Scroll":
            pygame.mouse.set_visible(False)
            if mode == "Time": run_time_mode(screen, clock)
            elif mode == "Scroll": run_scroll_mode(screen, clock)
            else: update_config_mode("Time")
            
        else:
            pygame.mouse.set_visible(True)
            run_menu_mode(screen, clock)

if __name__ == "__main__":
    main()