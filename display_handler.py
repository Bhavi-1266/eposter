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
import socket

def get_local_ip():
    """Dynamically find the local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def display_url(screen, scr_w, scr_h, rotation=0, poster_id=None):
    """
    Overlays a bottom bar with poster ID on left and IP on right.
    Removed .flip() to prevent flickering.
    """
    try:
        import socket
        def get_local_ip():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
                return ip
            except: return "127.0.0.1"

        ip_addr = get_local_ip()
        url_text = f"http://{ip_addr}"
        poster_text = f"Poster ID: {poster_id}" if poster_id else ""
        font = pygame.font.SysFont("Arial", 16, bold=True)
        
        if rotation in [90, 270]:
            logical_w = scr_h
        else:
            logical_w = scr_w

        bar_height = 25
        bar_surface = pygame.Surface((logical_w, bar_height), pygame.SRCALPHA)
        bar_surface.set_alpha(230)
        
        if poster_text:
            left_surf = font.render(poster_text, True, (90, 90, 90))
            bar_surface.blit(left_surf, (10, (bar_height - left_surf.get_height()) // 2))
        
        right_surf = font.render(url_text, True, (90, 90, 90))
        bar_surface.blit(right_surf, (logical_w - right_surf.get_width() - 10, (bar_height - right_surf.get_height()) // 2))
        
        if rotation == 0:
            screen.blit(bar_surface, (0, scr_h - bar_height))
        else:
            rotated_bar = pygame.transform.rotate(bar_surface, -rotation)
            if rotation == 90:
                screen.blit(rotated_bar, (0, 0))
            elif rotation == 180:
                screen.blit(rotated_bar, (0, 0))
            elif rotation == 270:
                screen.blit(rotated_bar, (scr_w - rotated_bar.get_width(), 0))
            else:
                screen.blit(rotated_bar, (0, scr_h - bar_height))
        # NO FLIP HERE
    except Exception as e:
        print(f"[display] Error overlaying URL: {e}")

    
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

def _draw_status_bar(screen, scr_w, scr_h, message, rotation=0):
    if rotation in [90, 270]:
        logical_w = scr_h
        logical_h = scr_w
    else:
        logical_w = scr_w
        logical_h = scr_h

    bar_height = max(30, int(logical_h * 0.1))
    bar_surface = pygame.Surface((logical_w, bar_height), pygame.SRCALPHA)
    bar_surface.fill((0, 0, 0, 0))

    lines = message.split('\n') if message else []
    font_size = max(14, int(bar_height * 0.18))
    font = pygame.font.SysFont("Arial", font_size, bold=True)
    text_color = (210, 210, 210)
    rendered = [font.render(line, True, text_color) for line in lines]
    total_h = sum(s.get_height() for s in rendered) + (4 * (len(rendered) - 1))

    while rendered and total_h > bar_height - 10 and font_size > 12:
        font_size -= 2
        font = pygame.font.SysFont("Arial", font_size, bold=True)
        rendered = [font.render(line, True, text_color) for line in lines]
        total_h = sum(s.get_height() for s in rendered) + (4 * (len(rendered) - 1))

    y = (bar_height - total_h) // 2
    for surf in rendered:
        x = (logical_w - surf.get_width()) // 2
        bar_surface.blit(surf, (x, y))
        y += surf.get_height() + 4

    if rotation == 0:
        screen.blit(bar_surface, (0, scr_h - bar_height))
    else:
        rotated_bar = pygame.transform.rotate(bar_surface, -rotation)
        if rotation == 90:
            screen.blit(rotated_bar, (0, 0))
        elif rotation == 180:
            screen.blit(rotated_bar, (0, 0))
        elif rotation == 270:
            screen.blit(rotated_bar, (scr_w - rotated_bar.get_width(), 0))
        else:
            screen.blit(rotated_bar, (0, scr_h - bar_height))

def show_screensaver_message(screen, scr_w, scr_h, message="Waiting...", rotation=0, image_path=None):
    screen.fill((0, 0, 0))
    try:
        if image_path is None:
            image_path = Path(__file__).parent / "ScreenSaver.png"

        if Path(image_path).exists():
            img = Image.open(image_path).convert("RGBA")
            canvas = make_landscape_and_fit(img, scr_w, scr_h, rotation=-rotation)
            surf = pil_to_surface(canvas)
            screen.blit(surf, (0, 0))

        _draw_status_bar(screen, scr_w, scr_h, message, rotation)
        display_url(screen, scr_w, scr_h, rotation)
        pygame.display.flip()
    except Exception as e:
        print(f"[display] Error showing screensaver: {e}")
        pygame.display.flip()

def display_image(screen, image_path, scr_w, scr_h, rotation=0):
    """Displays an image on the screen with a black background."""
    try:
        img = Image.open(image_path).convert("RGBA")

        canvas = make_landscape_and_fit(
            img, scr_w, scr_h, rotation=-rotation
        )

        # Create black background
        bg = Image.new("RGBA", canvas.size, (0, 0, 0, 255))
        bg.paste(canvas, (0, 0), canvas)

        # Convert to pygame surface
        surf = pil_to_surface(bg)

        screen.blit(surf, (0, 0))
        pygame.display.flip()

        bg.save("output.png")

        return True

    except Exception as e:
        print(f"[display] Failed to display image {image_path}: {e}")
        return False


def display_connecting_wifi(screen, scr_w, scr_h, rotation=0):
    """Wrapper to show wifi message with rotation."""
    show_waiting_message(screen, scr_w, scr_h, "Connecting to WiFi...", rotation)