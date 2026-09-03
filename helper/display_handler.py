#!/usr/bin/env python3
"""
display_handler.py

Handles displaying poster images and status messages using pygame.
"""
from pathlib import Path
import time
import json
import subprocess
import shutil
from PIL import Image, ImageSequence
import pygame
import socket

ROOT_DIR = Path(__file__).resolve().parent.parent
_IP_CACHE = {"value": "127.0.0.1", "expires": 0.0}
_OVERLAY_CACHE = {}
_FONT_CACHE = {}

def is_animated_gif(path):
    return Path(path).suffix.lower() == ".gif"


def is_video_file(path):
    return Path(path).suffix.lower() in {".mov", ".mp4", ".m4v", ".webm", ".mkv", ".avi"}

def get_local_ip():
    """Dynamically find the local IP address."""
    now = time.monotonic()
    if now < _IP_CACHE["expires"]:
        return _IP_CACHE["value"]
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    _IP_CACHE.update(value=ip, expires=now + 60)
    return ip

def display_url(screen, scr_w, scr_h, rotation=0, poster_id=None):
    """
    Overlays a bottom bar with poster ID on left and IP on right.
    Removed .flip() to prevent flickering.
    """
    try:
        ip_addr = get_local_ip()
        url_text = f"{ip_addr}"
        poster_text = f"Paper ID: {poster_id}" if poster_id else ""
        if rotation in [90, 270]:
            logical_w = scr_h
        else:
            logical_w = scr_w

        bar_height = 25
        cache_key = (logical_w, rotation, poster_text, url_text)
        bar_surface = _OVERLAY_CACHE.get(cache_key)
        if bar_surface is None:
            font = _FONT_CACHE.setdefault(16, pygame.font.SysFont("Arial", 16, bold=True))
            bar_surface = pygame.Surface((logical_w, bar_height), pygame.SRCALPHA)
            bar_surface.fill((245, 245, 245, 225))
            if poster_text:
                left_surf = font.render(poster_text, True, (45, 45, 45))
                bar_surface.blit(left_surf, (10, (bar_height - left_surf.get_height()) // 2))
            right_surf = font.render(url_text, True, (45, 45, 45))
            bar_surface.blit(right_surf, (logical_w - right_surf.get_width() - 10, (bar_height - right_surf.get_height()) // 2))
            if len(_OVERLAY_CACHE) >= 64:
                _OVERLAY_CACHE.clear()
            _OVERLAY_CACHE[cache_key] = bar_surface
        
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
        config_path = ROOT_DIR / 'config.json'
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

def _handle_playback_events(interrupt_on_input=False):
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            raise SystemExit

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_q, pygame.K_ESCAPE):
                raise SystemExit
            if interrupt_on_input:
                return False

        if interrupt_on_input and event.type == pygame.MOUSEBUTTONDOWN:
            return False

    return True

def _wait_for_playback(seconds, clock=None, interrupt_on_input=False):
    end_time = time.monotonic() + max(0, seconds)
    while time.monotonic() < end_time:
        if not _handle_playback_events(interrupt_on_input):
            return False
        if clock:
            clock.tick(60)
        else:
            pygame.time.wait(10)
    return True


def _spawn_video_player(cmd, duration_seconds=None):
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    try:
        return subprocess.Popen(cmd, **kwargs)
    except Exception as e:
        print(f"[display] Could not start video player: {e}")
        return None


def _stop_video_player(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)
    except Exception as e:
        print(f"[display] Could not stop video player cleanly: {e}")


def _resolve_video_player(path):
    candidates = [
        ["ffplay", "-x", "{w}", "-y", "{h}", "-fs", "-alwaysontop", "-autoexit", "-loglevel", "error", "{path}"],
        ["omxplayer", "--no-osd", "--orientation", "0", "{path}"],
        ["mpv", "--fullscreen", "--no-terminal", "--keep-open=no", "{path}"],
        ["cvlc", "--fullscreen", "--play-and-exit", "--no-osd", "{path}"],
    ]

    for cmd_tmpl in candidates:
        binary = cmd_tmpl[0]
        binary_path = shutil.which(binary)
        if binary_path:
            return [binary_path] + cmd_tmpl[1:]

    return None


def _apply_video_rotation(cmd, rotation):
    """Apply the same clockwise rotation convention used for poster images."""
    try:
        rotation = int(rotation) % 360
    except (TypeError, ValueError):
        rotation = 0

    if rotation not in (90, 180, 270):
        return cmd

    player = Path(cmd[0]).name
    if player == "ffplay":
        filters = {
            90: "transpose=clock",
            180: "hflip,vflip",
            270: "transpose=cclock",
        }
        cmd[-1:-1] = ["-noautorotate", "-vf", filters[rotation]]
    elif player == "mpv":
        cmd.insert(1, f"--video-rotate={rotation}")
    elif player == "omxplayer":
        orientation_index = cmd.index("--orientation") + 1
        cmd[orientation_index] = str(rotation)
    elif player in ("cvlc", "vlc"):
        cmd[-1:-1] = ["--video-filter=transform", f"--transform-type={rotation}"]

    return cmd


def _suspend_pygame_display():
    """Minimize Pygame so an external fullscreen video player can take focus."""
    if not pygame.display.get_init() or pygame.display.get_surface() is None:
        return False

    try:
        pygame.event.pump()
        minimized = pygame.display.iconify()
        pygame.event.pump()
        time.sleep(0.15)
        return bool(minimized)
    except pygame.error as e:
        print(f"[display] Could not minimize Pygame before video playback: {e}")
        return False


def _restore_pygame_display(screen, scr_w, scr_h, mouse_was_visible=False):
    """Bring the existing Pygame display surface back after video playback."""
    try:
        flags = pygame.FULLSCREEN if screen.get_flags() & pygame.FULLSCREEN else 0
        pygame.display.set_mode((scr_w, scr_h), flags)
        pygame.mouse.set_visible(mouse_was_visible)
        pygame.event.clear()
        screen.fill((0, 0, 0))
        pygame.display.flip()
    except pygame.error as e:
        print(f"[display] Could not restore Pygame after video playback: {e}")


def display_video(screen, video_path, scr_w, scr_h, rotation=0, max_duration=None,
                  clock=None, poster_id=None, interrupt_on_input=False):
    if not is_video_file(video_path):
        return False

    cmd_tmpl = _resolve_video_player(video_path)
    if not cmd_tmpl:
        show_screensaver_message(screen, scr_w, scr_h, "No video player found. Install ffplay/omxplayer/mpv.")
        pygame.display.flip()
        _wait_for_playback(2, clock)
        return False

    cmd = [arg.format(w=scr_w, h=scr_h, path=str(video_path)) for arg in cmd_tmpl]
    cmd = _apply_video_rotation(cmd, rotation)
    if Path(cmd[0]).name == "ffplay" and interrupt_on_input:
        cmd[-1:-1] = ["-exitonkeydown", "-exitonmousedown"]
    proc = None
    display_suspended = False
    mouse_was_visible = pygame.mouse.get_visible()
    try:
        # Clear and minimize Pygame so the external player is not hidden behind it.
        screen.fill((0, 0, 0))
        if poster_id is not None:
            display_url(screen, scr_w, scr_h, rotation, poster_id=poster_id)
        pygame.display.flip()
        display_suspended = _suspend_pygame_display()

        proc = _spawn_video_player(cmd)
        if proc is None:
            return False

        start = time.monotonic()
        while True:
            if proc.poll() is not None:
                break

            if max_duration is not None and time.monotonic() - start >= max_duration:
                _stop_video_player(proc)
                return True

            if not _handle_playback_events(interrupt_on_input):
                _stop_video_player(proc)
                return True

            if clock:
                clock.tick(60)
            else:
                time.sleep(0.02)

        if proc.returncode not in (0, None):
            print(f"[display] Video player exited with status {proc.returncode}: {video_path}")
            return False
        return True
    except Exception as e:
        print(f"[display] Failed to play video {video_path}: {e}")
        return False
    finally:
        _stop_video_player(proc)
        if display_suspended:
            _restore_pygame_display(screen, scr_w, scr_h, mouse_was_visible)

def _draw_gif_frame(screen, pil_img, scr_w, scr_h, rotation=0, poster_id=None):
    img = pil_img.convert("RGBA")
    canvas = make_landscape_and_fit(img, scr_w, scr_h, rotation=-rotation)

    bg = Image.new("RGBA", canvas.size, (0, 0, 0, 255))
    bg.paste(canvas, (0, 0), canvas)

    surf = pil_to_surface(bg)
    screen.blit(surf, (0, 0))

    if poster_id is not None:
        display_url(screen, scr_w, scr_h, rotation, poster_id=poster_id)

    pygame.display.flip()
    return True

def _draw_screensaver_frame(screen, pil_img, scr_w, scr_h, message="", rotation=0):
    img = pil_img.convert("RGBA")
    canvas = make_landscape_and_fit(img, scr_w, scr_h, rotation=-rotation)
    surf = pil_to_surface(canvas)

    screen.blit(surf, (0, 0))
    _draw_status_bar(screen, scr_w, scr_h, message, rotation)
    display_url(screen, scr_w, scr_h, rotation)
    pygame.display.flip()
    return True

def _load_gif_frames(gif_path):
    frames = []
    durations = []

    with Image.open(gif_path) as gif:
        for frame in ImageSequence.Iterator(gif):
            frames.append(frame.convert("RGBA").copy())
            durations.append(max(20, int(frame.info.get("duration") or 100)))

    return frames, durations

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

def show_screensaver_message(screen, scr_w, scr_h, message="Waiting...", rotation=0, image_path=None,
                             animation_seconds=0, clock=None):
    screen.fill((0, 0, 0))
    try:
        if image_path is None:
            gif_path = ROOT_DIR / "ScreenSaver.gif"
            image_path = gif_path if gif_path.exists() else ROOT_DIR / "ScreenSaver.png"

        if Path(image_path).exists():
            if is_animated_gif(image_path):
                frames, durations = _load_gif_frames(image_path)

                if frames and animation_seconds > 0:
                    start_time = time.time()
                    while time.time() - start_time < animation_seconds:
                        for frame, duration_ms in zip(frames, durations):
                            if time.time() - start_time >= animation_seconds:
                                break
                            _draw_screensaver_frame(screen, frame, scr_w, scr_h, message, rotation)
                            wait_seconds = min(duration_ms / 1000, animation_seconds - (time.time() - start_time))
                            _wait_for_playback(wait_seconds, clock)
                    return

                if frames:
                    _draw_screensaver_frame(screen, frames[0], scr_w, scr_h, message, rotation)
                    return
            else:
                with Image.open(image_path) as source:
                    img = source.convert("RGBA")
                    _draw_screensaver_frame(screen, img, scr_w, scr_h, message, rotation)

                if animation_seconds > 0:
                    _wait_for_playback(animation_seconds, clock)
                return

        _draw_status_bar(screen, scr_w, scr_h, message, rotation)
        display_url(screen, scr_w, scr_h, rotation)
        pygame.display.flip()
    except Exception as e:
        print(f"[display] Error showing screensaver: {e}")
        pygame.display.flip()

def display_image(screen, image_path, scr_w, scr_h, rotation=0):
    """Displays an image on the screen with a black background."""
    try:
        with Image.open(image_path) as source:
            img = source.convert("RGBA")

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

        return True

    except Exception as e:
        print(f"[display] Failed to display image {image_path}: {e}")
        return False

def display_animated_gif(screen, gif_path, scr_w, scr_h, rotation=0, max_duration=None,
                         clock=None, poster_id=None, interrupt_on_input=False):
    try:
        frames, durations = _load_gif_frames(gif_path)

        if not frames:
            return display_image(screen, gif_path, scr_w, scr_h, rotation)

        start_time = time.time()

        while True:
            for frame, duration_ms in zip(frames, durations):
                if max_duration is not None and time.time() - start_time >= max_duration:
                    return True

                if not _handle_playback_events(interrupt_on_input):
                    return True

                _draw_gif_frame(screen, frame, scr_w, scr_h, rotation, poster_id=poster_id)

                wait_seconds = duration_ms / 1000
                if max_duration is not None:
                    remaining = max_duration - (time.time() - start_time)
                    wait_seconds = min(wait_seconds, max(0, remaining))

                if not _wait_for_playback(wait_seconds, clock, interrupt_on_input):
                    return True

            if max_duration is None:
                return True

    except Exception as e:
        print(f"[display] Failed to display animated GIF {gif_path}: {e}")
        return False

def display_connecting_wifi(screen, scr_w, scr_h, rotation=0):
    """Wrapper to show wifi message with rotation."""
    show_waiting_message(screen, scr_w, scr_h, "Connecting to WiFi...", rotation)
