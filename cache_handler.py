#!/usr/bin/env python3
"""
cache_handler.py
"""
from pathlib import Path
import os
import requests
import json
from PIL import Image
import shutil

# Configuration
try:
    with open(Path(__file__).parent / 'config.json', 'r') as f:
        config = json.load(f)
except Exception as e:
    print(f"!! CRITICAL: Could not load config.json: {e}")
    config = {}

REQUEST_TIMEOUT = config.get("api", {}).get("request_timeout", 20)
SCRIPT_DIR = Path(__file__).parent
CACHE_DIR = SCRIPT_DIR / "eposter_cache"    

def ensure_cache():
    """Creates cache directory if it doesn't exist."""
    if not CACHE_DIR.exists():
        print(f"[cache] Creating directory: {CACHE_DIR}")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

def get_image_path(poster_id):
    """Finds image for ID regardless of extension."""
    ensure_cache()
    # Check for specific extensions to avoid directory confusion
    for ext in ["png", "jpg", "jpeg", "bmp", "gif"]:
        path = CACHE_DIR / f"{poster_id}.{ext}"
        if path.exists() and path.is_file():
            return path
    return None

def sync_cache(records, timeout=REQUEST_TIMEOUT):
    """
    Syncs cache directory. Downloads missing images.
    """
    ensure_cache()
    print(f"--- SYNC START: Received {len(records) if records else 0} records ---")
    
    if not records:
        print("[cache] No records provided to sync. Cache will not change.")
        return []
    
    # 1. Valid IDs
    valid_ids = set()
    for r in records:
        pid = r.get("PosterId") or r.get("id")
        if pid:
            valid_ids.add(str(pid))
            
    # 2. Cleanup Old Files
    print(f"[cache] Cleaning up files not in: {valid_ids}")
    for f in CACHE_DIR.iterdir():
        if f.is_file() and not f.name.startswith("."):
            if f.stem not in valid_ids and "_temp" not in f.name:
                try:
                    print(f"[cache] Deleting old file: {f.name}")
                    os.remove(f)
                except Exception as e:
                    print(f"[cache] Error deleting {f.name}: {e}")

    # 3. Download Process
    cached_paths = []
    
    for poster in records:
        # Get ID
        poster_id = poster.get("PosterId") or poster.get("id")
        if not poster_id:
            print("[cache] Skipping record with missing ID")
            continue
            
        poster_id_str = str(poster_id)
        
        # Check if exists
        existing_file = get_image_path(poster_id_str)
        if existing_file:
            print(f"[cache] ID {poster_id}: Found existing file ({existing_file.name}). Skipping download.")
            cached_paths.append(existing_file)
            continue

        # Get URL
        url = poster.get("eposter_file") or poster.get("file")
        if not url:
            print(f"[cache] ID {poster_id}: No URL found in record!")
            continue

        print(f"[cache] ID {poster_id}: Downloading from {url}...")

        # Download
        tmp_path = CACHE_DIR / f"{poster_id}_temp"
        try:
            # Added verify=False in case of SSL issues, but use with caution
            r = requests.get(url, stream=True, timeout=timeout)
            
            if r.status_code != 200:
                print(f"[cache] ID {poster_id}: Download Failed (Status code {r.status_code})")
                continue

            with open(tmp_path, "wb") as fh:
                for chunk in r.iter_content(8192):
                    if chunk:
                        fh.write(chunk)
            
            # Identify format
            try:
                img = Image.open(tmp_path)
                ext = (img.format or "PNG").lower()
                if ext == "jpeg": ext = "jpg"
                
                final_path = CACHE_DIR / f"{poster_id_str}.{ext}"
                
                # Close image before moving
                img.close()
                
                shutil.move(str(tmp_path), str(final_path))
                print(f"[cache] ID {poster_id}: Successfully saved as {final_path.name}")
                cached_paths.append(final_path)
                
            except Exception as img_err:
                print(f"[cache] ID {poster_id}: Downloaded file is not a valid image. {img_err}")
                if tmp_path.exists(): os.remove(tmp_path)

        except requests.exceptions.Timeout:
            print(f"[cache] ID {poster_id}: Network/Write Error: Slow internet / request timed out after {timeout}s")
            if tmp_path.exists():
                try: os.remove(tmp_path)
                except: pass
                    
        except Exception as e:
            print(f"[cache] ID {poster_id}: Network/Write Error: {e}")
            if tmp_path.exists():
                try: os.remove(tmp_path)
                except: pass
    
    print(f"--- SYNC END: {len(cached_paths)} images ready ---")
    return cached_paths
