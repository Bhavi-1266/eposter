#!/usr/bin/env python3
"""
eposterNoMenu.py (Master Display Controller)
"""

import sys
import time
import pygame
from pathlib import Path
from datetime import datetime

# --- Custom Modules ---
from helper import wifi_connect
from helper import api_handler
from helper import cache_handler
from helper import display_handler
from helper.json_utils import load_json_file, update_json_file

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
    return load_json_file(CONFIG_FILE, {}) or {}

def update_config_mode(new_mode):
    try:
        def apply_mode(data):
            data = data or {}
            data.setdefault('display', {})['Mode'] = new_mode
            return data

        update_json_file(CONFIG_FILE, apply_mode, {})
        log(f"Config updated: Mode set to {new_mode}", "INFO")
    except Exception as e:
        log(f"Config write error: {e}", "ERROR")

def parse_datetime(date_str, fmt="%d-%m-%Y %H:%M:%S"):
    if not date_str:
        return None
    for candidate in (fmt, "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(date_str), candidate)
        except (TypeError, ValueError):
            pass
    try:
        return datetime.fromisoformat(str(date_str).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _cache_refresh_seconds(cfg):
    try:
        return max(30, int(cfg.get('display', {}).get('cache_refresh', 60)))
    except (TypeError, ValueError):
        return 60

# ---------------------------------------------------------
# DATA & SYNC HELPER
# ---------------------------------------------------------
def get_device_records(device_id):
    if not API_DATA_JSON.exists():
        return [], 5

    def _device_values(row):
        return [
            row.get("screen_number"),
            row.get("screen_id"),
            row.get("device_id"),
            row.get("screen"),
            row.get("display_id"),
        ]

    def _matches_device(row):
        for val in _device_values(row):
            if str(val) == str(device_id):
                return True
        return False

    try:
        data = load_json_file(API_DATA_JSON, {}) or {}
        records = []
        seen_records = set()
        minutes_per_record = 5  # default

        def _append_record(record):
            if not isinstance(record, dict):
                return
            start_dt = parse_datetime(record.get("start_date_time"))
            end_dt = parse_datetime(record.get("end_date_time"))
            if not start_dt or not end_dt or end_dt <= start_dt:
                return
            key = (
                str(record.get("id") or record.get("PosterId") or ""),
                start_dt,
                end_dt,
                _record_media_url(record),
            )
            if key in seen_records:
                return
            seen_records.add(key)
            parsed = dict(record)
            parsed["start_dt"] = start_dt
            parsed["end_dt"] = end_dt
            records.append(parsed)

        # Try screens first (currently empty in API, but keep for future)
        screens = data.get("screens", [])
        my_screen = next((s for s in screens if _matches_device(s)), None)

        if my_screen:
            minutes_per_record = my_screen.get("minutes_per_record", 5)
            for r in my_screen.get("records", []):
                _append_record(r)

        # Always also check booking_slot for this screen
        bookings = data.get("booking_slot", [])
        for b in bookings:
            slot_records = b.get("records", [])
            if not isinstance(slot_records, list):
                continue
            booking_matches = _matches_device(b)
            for r in slot_records:
                if not booking_matches and not _matches_device(r):
                    continue
                _append_record(r)

        if not records and isinstance(data.get("data"), list):
            for r in data["data"]:
                if _matches_device(r):
                    _append_record(r)

        return records, minutes_per_record

    except Exception as e:
        log(f"Error parsing records: {e}", "ERROR")
        return [], 5


def _record_lookup(records, poster_id):
    for r in records:
        if str(r.get("id") or r.get("PosterId")) == str(poster_id):
            return r
    return None


def _record_media_url(record):
    return (record or {}).get("eposter_file") or (record or {}).get("file")


def _url_for_path(records, path):
    for r in records:
        media_url = _record_media_url(r)
        if not media_url:
            continue
        if cache_handler.get_media_path(media_url) == path:
            return r
    return None


def _is_video_record(record, path):
    media_type = (record.get("media_type") or "").lower() if isinstance(record, dict) else ""
    return media_type == "video" or display_handler.is_video_file(path)


def _display_duration_seconds(record, fallback):
    try:
        v = int(record.get("duration_seconds")) if record else None
        if v and v > 0:
            return v
    except Exception:
        pass
    return fallback

  
def refresh_data_and_cache(poster_token, device_id):
    
    log(f"--- Refreshing Data for Device: {device_id} ---", "INFO")
    if wifi_connect.ensure_wifi_connection():
        api_handler.fetch_posters(poster_token)
    records, duration = get_device_records(device_id)
    
    cache_handler.sync_cache((records or []))
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

    display_handler.show_screensaver_message(screen, scr_w, scr_h, "System Startup...\nChecking WiFi & Syncing Data", rotation)
    refresh_data_and_cache(token, dev_id)
    display_handler.show_screensaver_message(screen, scr_w, scr_h, "Startup Complete!\nStarting Mode...", rotation)
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
    sync_interval = _cache_refresh_seconds(cfg)
    next_sync_time = time.time() + sync_interval
    last_config_check = time.time()

    running = True
    while running:
        current_time = time.time()
    
        if current_time - last_config_check > 2:
            check_cfg = load_config()
            if check_cfg.get('display', {}).get('Mode') != "Time": return
            rotation = int(check_cfg.get('display', {}).get('rotation_degree', 0))
            token = check_cfg.get('api', {}).get('poster_token')
            sync_interval = _cache_refresh_seconds(check_cfg)
            new_id = check_cfg.get('display', {}).get('device_id')
            if str(new_id) != str(device_id):
                display_handler.show_screensaver_message(screen, scr_w, scr_h, "Device ID Changed\nRefetching Data...", rotation)
                device_id = new_id
                records, duration = refresh_data_and_cache(token, device_id)
                next_sync_time = current_time + sync_interval
                poster_end_time = 0 
            last_config_check = current_time

        if current_time > next_sync_time:
            records, duration = refresh_data_and_cache(token, device_id)
            next_sync_time = current_time + sync_interval
            poster_end_time = 0 

        for event in pygame.event.get():
            if event.type == pygame.QUIT: sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_q: sys.exit()

        if not records:
            print("<TIME>Records Empty Showing ScreenSaver")
            display_handler.show_screensaver_message(
                screen, scr_w, scr_h, "", rotation,
                animation_seconds=1,
                clock=clock,
            )
            continue
            
        if current_time >= poster_end_time:
            now = datetime.now()
            active = None
            for r in sorted(records, key=lambda item: item.get("start_dt") or now):
                if r["start_dt"] <= now <= r["end_dt"]:
                    active = r
                    break
            if active:
                pid = active.get("id") or active.get("PosterId")
                paper_id = active.get("paper_id")
                path = cache_handler.get_media_path(_record_media_url(active))
                if path and path.exists():
                    print("<TIME>displaying Image pid : " , pid)
                    slot_duration = max(1, min(
                        _display_duration_seconds(active, duration),
                        (active["end_dt"] - now).total_seconds(),
                    ))
                    if _is_video_record(active, path):
                        played = display_handler.display_video(
                            screen, path, scr_w, scr_h, rotation,
                            max_duration=slot_duration,
                            clock=clock,
                            poster_id=paper_id,
                        )
                        poster_end_time = time.time() + (0 if played else 5)
                    elif display_handler.is_animated_gif(path):
                        display_handler.display_animated_gif(
                            screen, path, scr_w, scr_h, rotation,
                            max_duration=slot_duration,
                            clock=clock,
                            poster_id=paper_id,
                        )
                        poster_end_time = time.time()
                    else:
                        display_handler.display_image(screen, path, scr_w, scr_h, rotation)
                        display_handler.display_url(screen, scr_w, scr_h, rotation, poster_id=paper_id)
                        pygame.display.flip()
                        poster_end_time = current_time + slot_duration
                else:
                    print("<TIME>NO Schedualted Showing ScreenSaver")
                    display_handler.show_screensaver_message(screen, scr_w, scr_h, f"Downloading ID: {pid}...", rotation)
                    pygame.display.flip()
                    cache_handler.sync_cache([active]) 
                    poster_end_time = current_time + 2
            else:
                print("<TIME>Activate False  / Did Not Find Any Image  , Showing ScreenSaver")
                display_handler.show_screensaver_message(
                    screen, scr_w, scr_h, "", rotation,
                    animation_seconds=5,
                    clock=clock,
                )
                poster_end_time = time.time()
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

    def get_valid_media_paths(recs):
        if not recs:
            return []
        media_paths = []
        seen = set()
        for r in recs:
            media_url = _record_media_url(r)
            if not media_url or media_url in seen:
                continue
            seen.add(media_url)
            p = cache_handler.get_media_path(media_url)
            if p is not None:
                media_paths.append(p)
        return media_paths

    records, _ = get_device_records(device_id)

    images = get_valid_media_paths(records)
    index = 0
    next_switch = 0
    sync_interval = _cache_refresh_seconds(cfg)
    next_sync_time = time.time() + sync_interval
    last_config_check = time.time()

    running = True
    while running:
        current_time = time.time()
        
        if current_time - last_config_check > 2:
            check_cfg = load_config()
            if check_cfg.get('display', {}).get('Mode') != "Scroll": return
            rotation = int(check_cfg.get('display', {}).get('rotation_degree', 0))
            scroll_delay = int(check_cfg.get('display', {}).get('Auto_Scroll', 5))
            token = check_cfg.get('api', {}).get('poster_token')
            sync_interval = _cache_refresh_seconds(check_cfg)
            new_id = check_cfg.get('display', {}).get('device_id')
            if str(new_id) != str(device_id):
                display_handler.show_screensaver_message(screen, scr_w, scr_h, "Device ID Changed...", rotation)
                device_id = new_id
                records, _ = refresh_data_and_cache(token, device_id)
                images = get_valid_media_paths(records)
                index = 0
                next_sync_time = current_time + sync_interval
            last_config_check = current_time

        if current_time > next_sync_time:
            records, _ = refresh_data_and_cache(token, device_id)
            images = get_valid_media_paths(records)
            index = min(index, max(0, len(images) - 1))
            next_sync_time = current_time + sync_interval

        for event in pygame.event.get():
            if event.type == pygame.QUIT: sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_q: sys.exit()

        if not images:
            display_handler.show_screensaver_message(
                screen, scr_w, scr_h, "", rotation,
                animation_seconds=2,
                clock=clock,
            )
            images = get_valid_media_paths(records)
            continue

        if current_time >= next_switch:
            if index >= len(images): index = 0
            if images[index].exists():
                image_path = images[index]
                current_record = _url_for_path(records, image_path)
                paper_id = (current_record.get("paper_id") if current_record else None) or image_path.stem
                if display_handler.is_animated_gif(image_path):
                    display_handler.display_animated_gif(
                        screen, image_path, scr_w, scr_h, rotation,
                        max_duration=max(1, scroll_delay),
                        clock=clock,
                        poster_id=paper_id,
                    )
                    next_switch = time.time()
                elif display_handler.is_video_file(image_path):
                    max_wait = _display_duration_seconds(current_record, scroll_delay)
                    display_handler.display_video(
                        screen, image_path, scr_w, scr_h, rotation,
                        max_duration=max_wait,
                        clock=clock,
                        poster_id=paper_id,
                    )
                    next_switch = time.time()
                else:
                    display_handler.display_image(screen, image_path, scr_w, scr_h, rotation)
                    display_handler.display_url(screen, scr_w, scr_h, rotation, poster_id=paper_id)
                    pygame.display.flip()
                    next_switch = current_time + scroll_delay
            index = (index + 1) % len(images)
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

    item_font = pygame.font.SysFont("arial", max(20, int(UI_H * 0.025)), bold=True)
    hint_font = pygame.font.SysFont("arial", max(16, int(UI_H * 0.018)))

    def make_video_tile(record):
        tile_w = max(240, IMAGE_MAX_WIDTH)
        tile_h = max(150, min(IMAGE_MAX_HEIGHT, int(UI_H * 0.28)))
        tile = pygame.Surface((tile_w, tile_h)).convert()
        tile.fill((17, 34, 48))
        center = (tile_w // 2, tile_h // 2 - 18)
        radius = max(32, min(tile_w, tile_h) // 6)
        pygame.draw.circle(tile, (27, 145, 170), center, radius)
        pygame.draw.polygon(tile, (245, 247, 240), [
            (center[0] - radius // 4, center[1] - radius // 2),
            (center[0] - radius // 4, center[1] + radius // 2),
            (center[0] + radius // 2, center[1]),
        ])
        title = str(record.get("paper_title") or record.get("poster_title") or "Video")
        if len(title) > 52:
            title = title[:49] + "..."
        title_surface = item_font.render(title, True, (245, 247, 240))
        hint_surface = hint_font.render("Tap to play video", True, (155, 211, 221))
        tile.blit(title_surface, title_surface.get_rect(center=(tile_w // 2, tile_h - 52)))
        tile.blit(hint_surface, hint_surface.get_rect(center=(tile_w // 2, tile_h - 24)))
        return tile

    def load_menu_items(menu_records):
        loaded_items = []
        if not menu_records:
            return []
        seen = set()
        for r in menu_records:
            media_url = _record_media_url(r)
            if not media_url or media_url in seen:
                continue
            seen.add(media_url)
            path = cache_handler.get_media_path(media_url)
            if path is None or not path.exists():
                continue
            try:
                if _is_video_record(r, path):
                    preview = make_video_tile(r)
                else:
                    preview = pygame.image.load(path).convert()
                    w, h = preview.get_size()
                    scale = min(1.0, IMAGE_MAX_WIDTH / w, IMAGE_MAX_HEIGHT / h)
                    if scale < 1.0:
                        preview = pygame.transform.smoothscale(
                            preview, (max(1, int(w * scale)), max(1, int(h * scale)))
                        )
                loaded_items.append({
                    "image": preview,
                    "path": path,
                    "record": r,
                    "height": preview.get_height() + TEXT_HEIGHT + ITEM_PADDING * 2,
                })
            except Exception as e:
                log(f"Menu preview failed for {path.name}: {e}", "WARNING")
        return loaded_items
    
    display_handler.show_screensaver_message(screen, PHY_W, PHY_H, "Loading Menu...", rotation)
    menu_records, _ = get_device_records(device_id)
    items = load_menu_items(menu_records)
    sync_interval = _cache_refresh_seconds(cfg)
    scroll_y, next_sync_time, last_config_check = 0, time.time() + sync_interval, time.time()
    drag_active = False
    drag_moved = False
    drag_start_x, drag_start_y = 0, 0
    drag_start_scroll_y = 0
    DRAG_THRESHOLD = 8

    def open_menu_item(item):
        menu_img_id = item['path'].stem
        menu_record = item.get('record')
        menu_paper_id = (menu_record.get("paper_id") if menu_record else None) or menu_img_id

        if display_handler.is_animated_gif(item['path']):
            display_handler.display_animated_gif(
                screen, item['path'], PHY_W, PHY_H, rotation,
                max_duration=60,
                clock=clock,
                poster_id=menu_paper_id,
                interrupt_on_input=True,
            )
        elif display_handler.is_video_file(item['path']):
            max_wait = _display_duration_seconds(menu_record, 60)
            display_handler.display_video(
                screen, item['path'], PHY_W, PHY_H, rotation,
                max_duration=max_wait,
                clock=clock,
                poster_id=menu_paper_id,
                interrupt_on_input=True,
            )
        else:
            display_handler.display_image(screen, item['path'], PHY_W, PHY_H, rotation)
            display_handler.display_url(screen, PHY_W, PHY_H, rotation, poster_id=menu_paper_id)
            pygame.display.flip()
            waiting = True
            t_start = time.time()
            while waiting:
                for e in pygame.event.get():
                    if e.type == pygame.QUIT:
                        raise SystemExit
                    if e.type in [pygame.MOUSEBUTTONDOWN, pygame.KEYDOWN]:
                        waiting = False
                if time.time() - t_start > 60: waiting = False
                clock.tick(30)

    def item_at_position(x, y):
        y_offset = scroll_y + TOPBAR_HEIGHT + 20
        for item in items:
            if y_offset + item['height'] > 0 and y_offset < UI_H:
                if pygame.Rect(40, y_offset, UI_W-80, item['height']).collidepoint(x, y):
                    return item
            y_offset += item['height'] + 25
        return None

    running = True
    while running:
        clock.tick(30)
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
            token = check_cfg.get('api', {}).get('poster_token')
            sync_interval = _cache_refresh_seconds(check_cfg)
            last_config_check = current_time

        if current_time >= next_sync_time:
            menu_records, _ = refresh_data_and_cache(token, device_id)
            items = load_menu_items(menu_records)
            next_sync_time = time.time() + sync_interval

        for event in pygame.event.get():
            if event.type == pygame.QUIT: sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_q: sys.exit()
            if event.type == pygame.MOUSEWHEEL:
                scroll_y += event.y * SCROLL_SPEED
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    drag_start_x, drag_start_y = map_mouse(*event.pos)
                    drag_start_scroll_y = scroll_y
                    drag_active = True
                    drag_moved = False
                elif event.button == 4: scroll_y += SCROLL_SPEED
                elif event.button == 5: scroll_y -= SCROLL_SPEED
            elif event.type == pygame.MOUSEMOTION and drag_active:
                drag_x, drag_y = map_mouse(*event.pos)
                total_dx = drag_x - drag_start_x
                total_dy = drag_y - drag_start_y
                if drag_moved or abs(total_dx) > DRAG_THRESHOLD or abs(total_dy) > DRAG_THRESHOLD:
                    drag_moved = True
                    scroll_y = drag_start_scroll_y + total_dy
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                release_x, release_y = map_mouse(*event.pos)
                was_click = drag_active and not drag_moved
                drag_active = False

                if was_click:
                    if button_rect.collidepoint(release_x, release_y):
                        update_config_mode("Time")
                        return

                    clicked_item = item_at_position(release_x, release_y)
                    if clicked_item:
                        open_menu_item(clicked_item)

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
        try:
            if mode in ("Time", "Scroll"):
                pygame.mouse.set_visible(False)
                if mode == "Time":
                    run_time_mode(screen, clock)
                else:
                    run_scroll_mode(screen, clock)
            elif mode == "Menu":
                pygame.mouse.set_visible(True)
                run_menu_mode(screen, clock)
            else:
                log(f"Unknown display mode {mode!r}; switching to Time", "WARNING")
                update_config_mode("Time")
        except SystemExit:
            raise
        except Exception as e:
            log(f"Display mode {mode!r} failed: {e}", "ERROR")
            display_handler.show_screensaver_message(
                screen, *screen.get_size(), "Display error\nRetrying...",
                int(cfg.get('display', {}).get('rotation_degree', 0)),
            )
            time.sleep(2)

if __name__ == "__main__":
    main()
