#!/usr/bin/env python3
"""
cache_handler.py

Handles caching and syncing of poster images.
Images are named by their ID and converted to landscape orientation.
"""
from pathlib import Path
import os
import requests
from PIL import Image

# Configuration
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "10"))
SCRIPT_DIR = Path(__file__).parent
CACHE_DIR = SCRIPT_DIR / "eposter_cache"


def ensure_cache():
    """Creates cache directory if it doesn't exist."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def expected_filenames_from_posters(posters):
    """
    Extracts expected filenames from poster data (by ID).
    
    Args:
        posters: List of poster dicts with PosterId or id
    
    Returns:
        set: Set of expected filenames (e.g., {"6.png", "7.png"})
    """
    names = set()
    for poster in posters:
        if not isinstance(poster, dict):
            continue
        poster_id = poster.get("PosterId") or poster.get("id")
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
    width, height = img.size
    
    # If already landscape, return as is
    if width > height:
        return img
    
    # If portrait, rotate 90 degrees
    if height > width:
        return img.rotate(90, expand=True)
    
    # If square, return as is (or you could decide to rotate)
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
    
    expected_names = expected_filenames_from_posters(posters)

    # Delete extras (files not in expected list)
    for f in CACHE_DIR.iterdir():
        if not f.is_file():
            continue
        if f.name.startswith("."):
            continue
        if f.name not in expected_names:
            try:
                f.unlink()
                print("[sync_cache] deleted old file:", f.name)
            except Exception as e:
                print("[sync_cache] failed delete:", f.name, e)

    # Download and process images
    cached_paths = []
    for poster in posters:
        if not isinstance(poster, dict):
            continue
        
        # Get poster ID
        poster_id = poster.get("PosterId") or poster.get("id")
        if not poster_id:
            continue
        
        # Get image URL
        url = poster.get("eposter_file") or poster.get("file") or None
        if not url:
            continue
        
        # Create filename from ID
        fname = f"{poster_id}.png"
        dest = CACHE_DIR / fname
        
        # If file already exists, add to list and continue
        if dest.exists():
            cached_paths.append((poster_id, dest))
            continue
        
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
            img = convert_to_landscape(img)
            
            # Save as PNG
            img.save(dest, 'PNG', optimize=True)
            
            # Remove temp file
            if tmp.exists():
                tmp.unlink()
            
            print(f"[sync_cache] Saved: {fname} (landscape)")
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

