#!/usr/bin/env python3
import sys
import time
from pathlib import Path
from PIL import Image
import pygame

def scale_letterbox(img, target_w, target_h):
    """Scale the image to fit the screen while keeping aspect ratio."""
    iw, ih = img.size
    scale = min(target_w / iw, target_h / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    resized = img.resize((nw, nh), Image.LANCZOS)

    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 255))
    x = (target_w - nw) // 2
    y = (target_h - nh) // 2
    canvas.paste(resized, (x, y), resized)
    return canvas

def pil_to_surface(pil_img):
    """Convert PIL image → Pygame surface."""
    mode = pil_img.mode
    size = pil_img.size
    data = pil_img.tobytes()
    return pygame.image.fromstring(data, size, mode)

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 show_png.py image.png [seconds]")
        sys.exit(1)

    img_path = Path(sys.argv[1])
    if not img_path.exists():
        print("Image file not found:", img_path)
        sys.exit(1)

    seconds = 5
    if len(sys.argv) >= 3:
        seconds = float(sys.argv[2])

    # Load image
    try:
        pil_img = Image.open(img_path).convert("RGBA")
    except Exception as e:
        print("Failed to load image:", e)
        sys.exit(1)

    # Initialize pygame fullscreen
    pygame.init()
    pygame.display.init()

    info = pygame.display.Info()
    scr_w, scr_h = info.current_w, info.current_h
    print(f"Screen resolution: {scr_w}x{scr_h}")

    screen = pygame.display.set_mode((scr_w, scr_h), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)

    # Auto-rotate if image orientation mismatches screen orientation
    iw, ih = pil_img.size
    if (scr_h > scr_w and iw > ih) or (scr_w > scr_h and ih > iw):
        pil_img = pil_img.rotate(90, expand=True)

    # Scale & center
    canvas = scale_letterbox(pil_img, scr_w, scr_h)
    surface = pil_to_surface(canvas)

    # Display
    screen.blit(surface, (0, 0))
    pygame.display.flip()

    start = time.time()
    clock = pygame.time.Clock()
    try:
        while time.time() - start < seconds:
            for ev in pygame.event.get():
                if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_q):
                    raise KeyboardInterrupt()
            clock.tick(30)
    except KeyboardInterrupt:
        pass
    finally:
        pygame.quit()

if __name__ == "__main__":
    main()
