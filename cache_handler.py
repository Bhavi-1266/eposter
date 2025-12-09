#!/usr/bin/env python3
"""
cache_handler.py

Handles caching and syncing of poster images.
Images are named by their ID and converted to landscape orientation.
"""
from pathlib import Path
import os
import requests
import json
from PIL import Image

# Configuration
with open(os.environ.get("CONFIG_FILE", "config.json")) as f:
    config = json.load(f)

REQUEST_TIMEOUT = config.get("api", {}).get("request_timeout", 10)
DEVICE_ID = config.get("display", {}).get("device_id", "default_device")
SCRIPT_DIR = Path(__file__).parent
CACHE_DIR = SCRIPT_DIR / "eposter_cache"    


def ensure_cache():
    """Creates cache directory if it doesn't exist."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def expected_filenames_from_posters(records):
    """
    Extracts expected filenames from poster data (by ID).
    
    Args:
        posters: List of poster dicts with PosterId or id
    
    Returns:
        set: Set of expected filenames (e.g., {"6.png", "7.png"})
    """
    names = set()
    if not records:
        return names
    for record in records:
        poster_id = record.get("PosterId") or record.get("id")
        if poster_id:
            names.add(f"{poster_id}.png")
    return names



def convert_to_landscape(img):
    """
    Converts image to landscape orientation (width > height).
    Rotates if necessary.
    
    Args:
        img: PIL Image object
    
    Returns:
        PIL Image: Landscape-oriented image
    """
    # width, height = img.size
    
    # If already landscape, return as is
    # if width > height:
    #     return img
    
    # # If portrait, rotate 90 degrees counter-clockwise (expand=True keeps full image)
    # if height > width:
    #     rotated = img.rotate(-90, expand=True)
    #     print(f"[convert_to_landscape] Rotated from {width}x{height} to {rotated.size[0]}x{rotated.size[1]}")
    #     return rotated
    
    # If square, return as is
    return img


def sync_cache(posters):
    """
    Syncs cache directory with poster data.
    Downloads images, names them by ID, and converts to landscape.
    
    Args:
        posters: List of poster dicts with PosterId/id and eposter_file/file URL
    
    Returns:
        list: List of cached file paths, sorted by ID (newest first)
    """
    ensure_cache()
    
    if not posters:
        return []
    
    screens = posters.get("screens", [])
    myScreen = screens.get(DEVICE_ID, {})
    records = myScreen.get("records", [])
    
    expected_names = expected_filenames_from_posters(records)

    # Delete extras (files not in expected list)
    for f in CACHE_DIR.iterdir():
        if not f.is_file():
            continue
        if f.name.startswith("."):
            continue
        if f.name not in expected_names:
            try:
                os.remove(f) 
                print("[sync_cache] deleted old file:", f.name)
            except Exception as e:
                print("[sync_cache] failed delete:", f.name, e)

    # Download and process images
    cached_paths = []
    print(f"[sync_cache] Processing {len(posters)} posters...")
    for poster in records:
        if not isinstance(poster, dict):
            print(f"[sync_cache] Warning: Poster is not a dict: {type(poster)}")
            continue
        
        # Debug: print poster keys to help diagnose
        if len(cached_paths) == 0:  # Only print for first poster
            print(f"[sync_cache] Sample poster keys: {list(poster.keys())}")
        
        # Get poster ID (convert to string/int for consistency)
        poster_id = poster.get("PosterId") or poster.get("id")
        if poster_id is None:
            print(f"[sync_cache] Warning: No ID found for poster: {poster}")
            continue
        
        # Convert ID to int then string for consistent naming
        try:
            poster_id = int(poster_id)
        except (ValueError, TypeError):
            print(f"[sync_cache] Warning: Invalid ID '{poster_id}', skipping")
            continue
        
        # Get image URL
        url = poster.get("eposter_file") or poster.get("file") or None
        if not url:
            print(f"[sync_cache] Warning: No URL found for poster ID {poster_id}")
            continue
        
        # Create filename from ID
        fname = f"{poster_id}.png"
        dest = CACHE_DIR / fname
        
        # Always reprocess to ensure landscape (remove old file if exists)
        if dest.exists():
            try:
               
                    # Already landscape, just add to list
                cached_paths.append((poster_id, dest))
                continue
            except Exception as e:
                print(f"[sync_cache] Error checking existing file {fname}: {e}, will reprocess")
                try:
                    dest.unlink()
                except:
                    pass
        
        # Download and process image
        tmp = None
        try:
            print(f"[sync_cache] Downloading poster ID {poster_id}...")
            r = requests.get(url, stream=True, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            
            # Save to temporary file first
            tmp = dest.with_suffix(".tmp")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(8192):
                    if chunk:
                        fh.write(chunk)
            
            # Open image, convert to landscape, and save as PNG
            img = Image.open(tmp)
            original_size = img.size
            print(f"[sync_cache] Original image size: {original_size[0]}x{original_size[1]}")
            
            # Convert to RGB if necessary (for PNG compatibility)
            if img.mode in ('RGBA', 'LA', 'P'):
                # Create white background for transparency
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode in ('RGBA', 'LA'):
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = rgb_img
            else:
                img = img.convert('RGB')
            
            # Convert to landscape
            # img = convert_to_landscape(img)
            final_size = img.size
            print(f"[sync_cache] Final image size: {final_size[0]}x{final_size[1]} (landscape: {final_size[0] > final_size[1]})")
            
            # Save as PNG
            img.save(dest, 'PNG', optimize=True)
            
            # Remove temp file
            if tmp.exists():
                tmp.unlink()
            
            print(f"[sync_cache] Saved: {fname} (ID: {poster_id}, size: {final_size[0]}x{final_size[1]})")
            cached_paths.append((poster_id, dest))
            
        except Exception as e:
            print(f"[sync_cache] Failed to process poster ID {poster_id}: {e}")
            try:
                if tmp and tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
    
    # Sort by ID (newest first) and return just the paths
    cached_paths.sort(key=lambda x: x[0], reverse=True)
    return [path for _, path in cached_paths]

