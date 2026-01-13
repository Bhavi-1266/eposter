#!/usr/bin/env python3
"""
display_handler.py

Handles displaying poster images and status messages using pygame.
"""
from pathlib import Path
import os
import time
import json
from PIL import Image
import pygame

def get_rotation_degree():
    """
    Get the current rotation degree from config file.
    Reloads config each time to ensure fresh value.
    """
    try:
        config_path = Path(__file__).parent / 'config.json'
        with open(config_path, 'r') as f:
            config = json.load(f)
        rotation = int(config.get('display', {}).get('rotation_degree', 0))
        return rotation
    except Exception as e:
        print(f"[display] Error reading rotation from config: {e}")
        return 0

def make_landscape_and_fit(img: Image.Image, target_w: int, target_h: int, rotation: int = 0) -> Image.Image:
    """Rotates image and fits it to target dimensions."""
    iw, ih = img.size
    if rotation != 0:
        # Expand=True allows the canvas to grow to hold the rotated image
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
    """Converts PIL Image to pygame Surface."""
    return pygame.image.fromstring(pil_img.tobytes(), pil_img.size, pil_img.mode)

def init_display():
    """Initializes pygame display in fullscreen mode."""
    try:
        pygame.init()
        pygame.display.init()
        info = pygame.display.Info()
        scr_w, scr_h = info.current_w, info.current_h
        print(f"[display] Screen detected: {scr_w}x{scr_h}")

        screen = pygame.display.set_mode((scr_w, scr_h), pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
        clock = pygame.time.Clock()
        
        # Check rotation immediately for the first loading screen
        rot = get_rotation_degree()
        show_waiting_message(screen, scr_w, scr_h, message="Loading...", rotation=rot)
        
        return screen, clock, scr_w, scr_h
    except Exception as e:
        print(f"[display] Failed to initialize display: {e}")
        return None

def show_waiting_message(screen, scr_w, scr_h, message="Waiting...", rotation=0):
    """
    Displays a multi-line message centered and rotated.
    """
    screen.fill((0, 0, 0))
    try:
        font = pygame.font.SysFont("Arial", 32, bold=True)
        lines = message.split('\n')
        
        # 1. Render all lines to surfaces
        rendered_lines = [font.render(line, True, (255, 255, 255)) for line in lines]
        
        # 2. Calculate dimensions of the text block
        max_w = max(s.get_width() for s in rendered_lines) if rendered_lines else 0
        total_h = sum(s.get_height() for s in rendered_lines) + (5 * (len(lines) - 1)) # 5px padding
        
        # 3. Create a transparent container for the text
        text_container = pygame.Surface((max_w, total_h), pygame.SRCALPHA)
        
        # 4. Blit lines onto container centered
        current_y = 0
        for s in rendered_lines:
            x_pos = (max_w - s.get_width()) // 2
            text_container.blit(s, (x_pos, current_y))
            current_y += s.get_height() + 5
            
        # 5. Rotate the entire container
        # Pygame rotates counter-clockwise, so we use negative rotation
        if rotation != 0:
            text_container = pygame.transform.rotate(text_container, -rotation)
            
        # 6. Center the rotated container on the main screen
        final_rect = text_container.get_rect(center=(scr_w // 2, scr_h // 2))
        screen.blit(text_container, final_rect)
        
        pygame.display.flip()
    except Exception as e:
        print(f"[display] Error showing waiting message: {e}")
        pygame.display.flip()

def display_image(screen, image_path, scr_w, scr_h, rotation=0):
    """Displays an image on the screen with rotation applied."""
    try:
        img = Image.open(image_path).convert("RGBA")
        canvas = make_landscape_and_fit(img, scr_w, scr_h, rotation=rotation)
        surf = pil_to_surface(canvas)
        screen.blit(surf, (0, 0))
        pygame.display.flip()
        return True
    except Exception as e:
        print(f"[display] Failed to display image {image_path}: {e}")
        return False

def display_connecting_wifi(screen, scr_w, scr_h, rotation=0):
    """Wrapper to show wifi message with rotation."""
    show_waiting_message(screen, scr_w, scr_h, "Connecting to WiFi...", rotation)