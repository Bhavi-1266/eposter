"""Compact, rotation-aware countdown shared by posters and external players."""
import math
import time
import ctypes
import ctypes.util
from functools import lru_cache

import pygame


# Warm translucent cream with dark digits for a discreet TV overlay.
SURFACE_COLOR = (248, 240, 222)
SURFACE_ALPHA = 150
TEXT_COLOR = (65, 56, 44)


@lru_cache(maxsize=8)
def _fonts(size):
    return pygame.font.SysFont("DejaVu Sans Mono", size)


def format_remaining(seconds):
    seconds = max(0, math.ceil(seconds))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


class PlaybackTimer:
    def __init__(self, duration, screen_size, rotation=0):
        self.duration = max(0.001, float(duration))
        self.deadline = time.monotonic() + self.duration
        self.screen_size = screen_size
        self.rotation = int(rotation) % 360
        self.scale = max(0.75, min(1.5, min(screen_size) / 900))
        self.background = None
        self.last_key = None
        self.cached_badge = None

    @property
    def remaining(self):
        return max(0, self.deadline - time.monotonic())

    def badge(self):
        remaining = self.remaining
        scale = self.scale
        number = _fonts(round(18 * scale))
        formatted = format_remaining(remaining)
        inset = round(10 * scale)
        width = max(round(84 * scale), number.size(format_remaining(self.duration))[0] + inset * 2)
        height = round(32 * scale)
        key = formatted
        if self.cached_badge is not None and self.cached_badge[2] == key:
            return self.cached_badge
        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        pygame.draw.rect(surface, (*SURFACE_COLOR, SURFACE_ALPHA), surface.get_rect(),
                         border_radius=height // 2)
        text = number.render(formatted, True, TEXT_COLOR)
        surface.blit(text, text.get_rect(center=(width // 2, height // 2)))
        if self.rotation:
            surface = pygame.transform.rotate(surface, -self.rotation)
        sw, sh = self.screen_size
        margin = round(16 * scale)
        rect = surface.get_rect()
        if self.rotation == 90:
            rect.topright = (sw - margin, margin)
        elif self.rotation == 180:
            rect.bottomright = (sw - margin, sh - margin)
        elif self.rotation == 270:
            rect.bottomleft = (margin, sh - margin)
        else:
            rect.topleft = (margin, margin)
        self.cached_badge = (surface, rect, key)
        return self.cached_badge

    def capture(self, screen):
        """Save just the badge area, after the media and other overlays are drawn."""
        _, rect, _ = self.badge()
        self.background = screen.subsurface(rect).copy()
        self.last_key = None

    def paint(self, screen):
        surface, rect, key = self.badge()
        if key == self.last_key:
            return
        if self.background is not None:
            screen.blit(self.background, rect)
        screen.blit(surface, rect)
        pygame.display.update(rect)
        self.last_key = key


def _shape_video_window(root, surface):
    """Clip both Tk's client and wrapper to the badge using the X11 Shape API."""
    class XRectangle(ctypes.Structure):
        _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short),
                    ("width", ctypes.c_ushort), ("height", ctypes.c_ushort)]

    x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
    xext = ctypes.CDLL(ctypes.util.find_library("Xext") or "libXext.so.6")
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.restype = ctypes.c_int
    x11.XQueryTree.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
        ctypes.POINTER(ctypes.c_uint),
    ]
    x11.XQueryTree.restype = ctypes.c_int
    x11.XFree.argtypes = [ctypes.c_void_p]
    x11.XFree.restype = ctypes.c_int
    xext.XShapeQueryExtension.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                                        ctypes.POINTER(ctypes.c_int)]
    xext.XShapeQueryExtension.restype = ctypes.c_int
    xext.XShapeCombineRectangles.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(XRectangle), ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ]
    xext.XShapeCombineRectangles.restype = None
    display = x11.XOpenDisplay(root.winfo_screen().encode())
    if not display:
        raise RuntimeError("Cannot connect to the video overlay's X11 display")
    try:
        event, error = ctypes.c_int(), ctypes.c_int()
        if not xext.XShapeQueryExtension(display, ctypes.byref(event), ctypes.byref(error)):
            raise RuntimeError("X11 Shape extension is unavailable")
        # Read the already-rotated alpha silhouette, so portrait displays match too.
        rows = []
        for y in range(surface.get_height()):
            pixels = [x for x in range(surface.get_width()) if surface.get_at((x, y)).a]
            if pixels:
                rows.append(XRectangle(pixels[0], y, pixels[-1] - pixels[0] + 1, 1))
        rectangles = (XRectangle * len(rows))(*rows)
        client = root.winfo_id()
        desktop, parent = ctypes.c_ulong(), ctypes.c_ulong()
        children = ctypes.POINTER(ctypes.c_ulong)()
        count = ctypes.c_uint()
        try:
            if not x11.XQueryTree(display, client, ctypes.byref(desktop), ctypes.byref(parent),
                                  ctypes.byref(children), ctypes.byref(count)):
                raise RuntimeError("Cannot find the video overlay's X11 wrapper")
        finally:
            if children:
                x11.XFree(children)
        # With overrideredirect, Tk's wm_frame() can return the client itself.
        # Its real X11 parent is still a separate rectangular wrapper. Clip it
        # as well, but never modify the desktop root window.
        windows = {client}
        if parent.value and parent.value != desktop.value:
            windows.add(parent.value)
        for window in windows:
            # ShapeBounding, ShapeSet, Unsorted: replace the actual window outline.
            xext.XShapeCombineRectangles(display, window, 0, 0, 0,
                                        rectangles, len(rows), 0, 0)
    finally:
        # Closing flushes the shape requests and releases this short-lived connection.
        x11.XCloseDisplay(display)


class VideoTimerWindow:
    """Small X11 overlay above any external player; never requests keyboard focus."""
    def __init__(self, timer, interrupt_on_input=False):
        import tkinter as tk

        self.timer = timer
        self.closed = False
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.wm_attributes("-type", "tooltip")
        # Uses the existing desktop compositor when available; no extra package.
        self.root.wm_attributes("-alpha", 0.65)
        self.label = tk.Label(self.root, borderwidth=0, highlightthickness=0, takefocus=False)
        self.label.pack()
        self.photo_class = tk.PhotoImage
        if interrupt_on_input:
            self.label.bind("<Button-1>", lambda event: setattr(self, "closed", True))
        self.next_refresh = 0
        self.last_key = None
        self.shaped_size = None

    def tick(self):
        now = time.monotonic()
        if now < self.next_refresh:
            return
        self.next_refresh = now + 0.1
        surface, rect, key = self.timer.badge()
        if key != self.last_key:
            # PPM cannot carry alpha. Flatten onto the same neutral background;
            # the window manager supplies translucency for external video.
            video_surface = pygame.Surface(surface.get_size())
            video_surface.fill(SURFACE_COLOR)
            video_surface.blit(surface, (0, 0))
            header = f"P6\n{rect.width} {rect.height}\n255\n".encode("ascii")
            self.photo = self.photo_class(data=header + pygame.image.tobytes(video_surface, "RGB"), format="PPM", master=self.root)
            self.label.configure(image=self.photo)
            self.root.geometry(f"{rect.width}x{rect.height}+{rect.x}+{rect.y}")
            self.last_key = key
        self.root.deiconify()
        if self.shaped_size != surface.get_size():
            # Finish mapping before querying the native parent window.
            self.root.update()
            _shape_video_window(self.root, surface)
            self.shaped_size = surface.get_size()
        self.root.lift()
        self.root.update()

    def close(self):
        try:
            self.root.destroy()
        except Exception:
            pass
