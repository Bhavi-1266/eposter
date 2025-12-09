#!/usr/bin/env python3
"""
display_handler.py

Handles displaying poster images using pygame.
"""
from pathlib import Path
import os
import time
import json
from PIL import Image
import pygame

# Configuration
with open(Path(__file__).parent / 'config.json', 'r') as f:
    config = json.load(f)
    ROTATION_DEGREE = int(config.get('display', {}).get('rotationDegree', 0))


def make_landscape_and_fit(img: Image.Image, target_w: int, target_h: int, rotation: int = None) -> Image.Image:
    """
    Rotates image and fits it to target dimensions.
    
    Args:
        img: PIL Image object
        target_w: Target width
        target_h: Target height
        rotation: Rotation degree (defaults to ROTATION_DEGREE env var)
    
    Returns:
        Image: Processed image
    """
    if rotation is None:
        rotation = ROTATION_DEGREE
    
    iw, ih = img.size
    if rotation != 0:
        img = img.rotate(rotation, expand=True)
        iw, ih = img.size
    scale = min(target_w / iw, target_h / ih)
    nw = max(1, int(iw * scale))
    nh = max(1, int(ih * scale))
    resized = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 255))
    x = (target_w - nw) // 2
    y = (target_h - nh) // 2
    canvas.paste(resized, (x, y))
    return canvas


def pil_to_surface(pil_img: Image.Image):
    """
    Converts PIL Image to pygame Surface.
    
    Args:
        pil_img: PIL Image object
    
    Returns:
        pygame.Surface: Pygame surface
    """
    return pygame.image.fromstring(pil_img.tobytes(), pil_img.size, pil_img.mode)


def init_display():
    """
    Initializes pygame display in fullscreen mode.
    
    Returns:
        tuple: (screen, clock, scr_w, scr_h) or None on failure
    """
    try:
        pygame.init()
        pygame.display.init()
        info = pygame.display.Info()
        scr_w, scr_h = info.current_w, info.current_h
        print(f"[display] Screen detected: {scr_w}x{scr_h}")

        screen = pygame.display.set_mode((scr_w, scr_h), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
        clock = pygame.time.Clock()
        # Start displaying loading
        show_waiting_message(screen, scr_w, scr_h, message="Loading...")
        pygame.display.flip()
        return screen, clock, scr_w, scr_h
    except Exception as e:
        print(f"[display] Failed to initialize display: {e}")
        return None


def show_waiting_message(screen, scr_w, scr_h, message="Waiting for posters..."):
    """
    Displays a waiting message on screen.
    
    Args:
        screen: Pygame screen surface
        scr_w: Screen width
        scr_h: Screen height
        message: Message to display
    """
    screen.fill((0, 0, 0))
    try:
        font = pygame.font.SysFont("Arial", 28)
        surf = font.render(message, True, (255, 255, 255))
        surf = pygame.transform.rotate(surf, -90)
        screen.blit(surf, ((scr_w - surf.get_width()) // 2, (scr_h - surf.get_height()) // 2))
        pygame.display.flip()
    except Exception:
        pygame.display.flip()


def display_image(screen, image_path, scr_w, scr_h):
    """
    Displays an image on the screen.
    
    Args:
        screen: Pygame screen surface
        image_path: Path to image file
        scr_w: Screen width
        scr_h: Screen height
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        img = Image.open(image_path).convert("RGBA")
        canvas = make_landscape_and_fit(img, scr_w, scr_h)
        surf = pil_to_surface(canvas)
        screen.blit(surf, (0, 0))
        pygame.display.flip()
        return True
    except Exception as e:
        print(f"[display] Failed to display image {image_path}: {e}")
        return False


def handle_events():
    """
    Handles pygame events (quit, escape, etc.).
    
    Returns:
        bool: False if should quit, True otherwise
    """
    for ev in pygame.event.get():
        if ev.type == pygame.QUIT:
            return False
        if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_ESCAPE, pygame.K_q):
            return False
    return True


def display_connecting_wifi(screen, scr_w, scr_h):
    """
    Displays 'Connecting to WiFi...' message on the screen.
    """
    screen.fill((0, 0, 0))
    try:
        import pygame
        font = pygame.font.SysFont("Arial", 36, bold=True)
        message = "Connecting to WiFi..."
        surf = font.render(message, True, (255, 255, 0))
        screen.blit(surf, ((scr_w - surf.get_width()) // 2, (scr_h - surf.get_height()) // 2))
        pygame.display.flip()
    except Exception:
        pygame.display.flip()

