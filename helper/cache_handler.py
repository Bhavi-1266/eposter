#!/usr/bin/env python3
"""
cache_handler.py
"""
from pathlib import Path
import os
import requests
from PIL import Image
from urllib.parse import urlparse
import hashlib

MEDIA_EXTENSIONS = {"png", "jpg", "jpeg", "bmp", "gif", "mov", "mp4", "m4v", "webm", "mkv", "avi"}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "bmp", "gif"}

# Configuration
ROOT_DIR = Path(__file__).resolve().parent.parent

SCRIPT_DIR = ROOT_DIR
CACHE_DIR = SCRIPT_DIR / "eposter_cache"    

def ensure_cache():
    """Creates cache directory if it doesn't exist."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _media_key_from_url(url):
    return hashlib.sha1(str(url).encode("utf-8")).hexdigest()


def get_image_path(poster_id):
    # Backward compatibility hook for older callers that still pass id as key.
    try:
        return get_media_path(poster_id)
    except Exception:
        return None


def get_media_path(url):
    """Finds cached media by URL key regardless of extension."""
    if not url:
        return None
    ensure_cache()
    media_key = _media_key_from_url(url)
    for ext in MEDIA_EXTENSIONS:
        path = CACHE_DIR / f"{media_key}.{ext}"
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def _infer_extension_from_url(url):
    try:
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        return suffix.lstrip(".")
    except Exception:
        return None


def _infer_extension_from_headers(headers):
    content_type = (headers.get("content-type") or "").lower()
    if not content_type:
        return None

    media_type = content_type.split(";")[0].strip()
    mapping = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/gif": "gif",
        "video/quicktime": "mov",
        "video/mp4": "mp4",
        "video/x-m4v": "m4v",
        "video/webm": "webm",
        "video/x-matroska": "mkv",
        "video/avi": "avi",
    }
    return mapping.get(media_type)

def _cache_limits():
    from helper.json_utils import load_json_file

    config = load_json_file(ROOT_DIR / "config.json", {}) or {}
    api_config = config.get("api", {})
    try:
        timeout = max(3, int(api_config.get("request_timeout", 20)))
    except (TypeError, ValueError):
        timeout = 20
    try:
        max_bytes = max(1, int(api_config.get("max_media_size_mb", 512))) * 1024 * 1024
    except (TypeError, ValueError):
        max_bytes = 512 * 1024 * 1024
    return timeout, max_bytes


def sync_cache(records, timeout=None):
    """
    Syncs cache directory. Downloads missing images.
    """
    ensure_cache()
    print(f"--- SYNC START: Received {len(records) if records else 0} records ---")
    
    if not records:
        print("[cache] No records provided to sync. Cache will not change.")
        return []

    configured_timeout, max_bytes = _cache_limits()
    timeout = configured_timeout if timeout is None else timeout

    # Schedule data may repeat the same few URLs hundreds of times.
    unique_media = {}
    for r in records:
        media_url = r.get("eposter_file") or r.get("file")
        if media_url and media_url not in unique_media:
            unique_media[media_url] = r
    valid_keys = {_media_key_from_url(url) for url in unique_media}
            
    # 2. Cleanup Old Files
    print(f"[cache] Cleaning up files not in: {len(valid_keys)} URLs")
    for f in CACHE_DIR.iterdir():
        if f.is_file() and not f.name.startswith("."):
            is_partial = f.suffix == ".part" or f.name.endswith("_temp")
            is_stale_media = f.suffix.lower().lstrip(".") in MEDIA_EXTENSIONS and f.stem not in valid_keys
            if is_partial or is_stale_media:
                try:
                    print(f"[cache] Deleting old file: {f.name}")
                    os.remove(f)
                except Exception as e:
                    print(f"[cache] Error deleting {f.name}: {e}")

    # 3. Download Process
    cached_paths = []
    
    session = requests.Session()
    for url, poster in unique_media.items():
        media_key = _media_key_from_url(url)
        
        # Check if exists
        existing_file = get_media_path(url)
        if existing_file:
            cached_paths.append(existing_file)
            continue

        poster_id = poster.get("PosterId") or poster.get("id")
        print(f"[cache] ID {poster_id}: Downloading from {url}...")

        # Download
        tmp_path = CACHE_DIR / f"{media_key}.part"
        try:
            with session.get(url, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                declared_size = int(response.headers.get("content-length") or 0)
                if declared_size > max_bytes:
                    raise ValueError(f"media is larger than the {max_bytes // (1024 * 1024)} MB limit")

                downloaded = 0
                with open(tmp_path, "wb") as fh:
                    for chunk in response.iter_content(64 * 1024):
                        if not chunk:
                            continue
                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            raise ValueError(f"media exceeded the {max_bytes // (1024 * 1024)} MB limit")
                        fh.write(chunk)

                response_headers = response.headers
            
            # Identify format (image or video). Keep unknown assets intact only with known extensions.
            final_ext = None
            final_ext = _infer_extension_from_url(url)
            if not final_ext:
                final_ext = _infer_extension_from_headers(response_headers)

            if not final_ext and poster.get("media_type", "").lower() == "video":
                final_ext = "mov"

            if final_ext:
                final_ext = final_ext.lstrip(".").lower()

            if final_ext in MEDIA_EXTENSIONS:
                if final_ext == "jpeg":
                    final_ext = "jpg"
                final_path = CACHE_DIR / f"{media_key}.{final_ext}"
                if final_ext in IMAGE_EXTENSIONS:
                    with Image.open(tmp_path) as image:
                        image.verify()
                os.replace(tmp_path, final_path)
                print(f"[cache] ID {poster_id}: Successfully saved as {final_path.name}")
                cached_paths.append(final_path)
            else:
                # Fallback for true images when extension is missing/unknown
                try:
                    img = Image.open(tmp_path)
                    ext = (img.format or "PNG").lower()
                    if ext == "jpeg":
                        ext = "jpg"
                    final_path = CACHE_DIR / f"{media_key}.{ext}"
                    img.close()
                    os.replace(tmp_path, final_path)
                    print(f"[cache] ID {poster_id}: Successfully saved as {final_path.name}")
                    cached_paths.append(final_path)
                except Exception as img_err:
                    print(f"[cache] ID {poster_id}: Downloaded file is not a recognized media format. {img_err}")
                    if tmp_path.exists():
                        os.remove(tmp_path)

        except requests.exceptions.Timeout:
            print(f"[cache] ID {poster_id}: Network/Write Error: Slow internet / request timed out after {timeout}s")
            if tmp_path.exists():
                try: os.remove(tmp_path)
                except: pass
                    
        except (requests.RequestException, OSError, ValueError) as e:
            print(f"[cache] ID {poster_id}: Network/Write Error: {e}")
            if tmp_path.exists():
                try: os.remove(tmp_path)
                except: pass
    
    session.close()
    print(f"--- SYNC END: {len(cached_paths)} unique media files ready ---")
    return cached_paths
