#!/usr/bin/env python3
"""
show_folder_portrait.py

Slideshow: ensure each image is portrait and scaled so the whole image is always shown.
Usage:
    python3 show_folder_portrait.py images_folder [seconds_each]

Defaults to 5 seconds per image.
Press ESC or 'q' to exit.
"""
import sys
import time
from pathlib import Path
from PIL import Image
import pygame

def make_portrait_and_fit(img: Image.Image, target_w: int, target_h: int):
    """
    Ensure the image has portrait orientation (rotate if needed),
    then scale it to fit entirely within target_w x target_h while preserving aspect ratio.
    Returns a PIL RGBA image of size (target_w, target_h) with letterboxing (black bars).
    """
    iw, ih = img.size

    # If image is landscape, rotate 90 degrees to make it portrait
    if iw > ih:
        img = img.rotate(90, expand=True)
        iw, ih = img.size

    # Compute scaling factor to fit entire image inside target (contain)
    scale = min(target_w / iw, target_h / ih)
    nw = max(1, int(iw * scale))
    nh = max(1, int(ih * scale))
    resized = img.resize((nw, nh), Image.LANCZOS)

    # Create letterboxed canvas and paste centered
    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 255))
    x = (target_w - nw) // 2
    y = (target_h - nh) // 2
    # If the image has alpha, use it as mask; otherwise paste normally
    try:
        canvas.paste(resized, (x, y), resized if resized.mode == "RGBA" else None)
    except Exception:
        canvas.paste(resized, (x, y))
    return canvas

def pil_to_surface(pil_img: Image.Image):
    """Convert PIL image → Pygame surface."""
    mode = pil_img.mode
    size = pil_img.size
    data = pil_img.tobytes()
    return pygame.image.fromstring(data, size, mode)

def collect_image_files(folder: Path):
    exts = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp")
    files = []
    for e in exts:
        files.extend(sorted(folder.glob(e)))
    return files

def show_static(screen, surface):
    screen.blit(surface, (0, 0))
    pygame.display.flip()

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 show_folder_portrait.py images_folder [seconds_each]")
        sys.exit(1)

    folder = Path(sys.argv[1])
    if not folder.exists() or not folder.is_dir():
        print("Folder not found:", folder)
        sys.exit(1)

    seconds = 5.0
    if len(sys.argv) >= 3:
        try:
            seconds = float(sys.argv[2])
        except Exception:
            pass

    files = collect_image_files(folder)
    if not files:
        print("No images found in folder:", folder)
        sys.exit(1)

    print(f"Found {len(files)} images. Press ESC or 'q' to exit.")

    pygame.init()
    pygame.display.init()
    info = pygame.display.Info()
    scr_w, scr_h = info.current_w, info.current_h
    print(f"Screen resolution detected: {scr_w}x{scr_h}")

    screen = pygame.display.set_mode((scr_w, scr_h), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)

    clock = pygame.time.Clock()

    try:
        idx = 0
        while True:
            path = files[idx % len(files)]
            try:
                pil = Image.open(path).convert("RGBA")
            except Exception as e:
                print("Failed to open", path, e)
                idx += 1
                continue

            # Convert to portrait + fit whole image inside screen with letterbox
            canvas = make_portrait_and_fit(pil, scr_w, scr_h)

            # Convert to pygame surface and show
            surf = pil_to_surface(canvas)
            show_static(screen, surf)

            start = time.time()
            while time.time() - start < seconds:
                for ev in pygame.event.get():
                    if ev.type == pygame.QUIT:
                        raise KeyboardInterrupt
                    if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_q):
                        raise KeyboardInterrupt
                clock.tick(30)

            idx += 1
    except KeyboardInterrupt:
        pass
    finally:
        pygame.quit()

if __name__ == "__main__":
    main()
