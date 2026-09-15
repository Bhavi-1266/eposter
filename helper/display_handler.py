"""Persistent media display, bounded image preparation, and menu rendering.

The existing on-disk media cache is only read here. Prepared frames and transition
snapshots are temporary presentation assets, removed when the display exits.
"""
import logging
import queue
import socket
import tempfile
import threading
import time
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from helper.mpv_player import MpvPlayer, PlayerError
from helper.playback_timer import format_remaining

LOG = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parent.parent
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".webm", ".mkv", ".avi"}


def is_video_file(path):
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def is_animated_gif(path):
    return Path(path).suffix.lower() == ".gif"


def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


@lru_cache(maxsize=16)
def font(size):
    for name in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def logical_size(size, rotation):
    return size[::-1] if rotation % 180 else size


def overlay_scale(size):
    """Pixel scale shared with player.lua: 1080p=1, UHD=2, either orientation."""
    return max(0.75, min(size)/1080)


def footer_height(size):
    return round(56*overlay_scale(size))


def media_size(size, rotation):
    w, h = logical_size(size, rotation)
    return w, max(1, h-footer_height(size))


def media_margins(size, rotation, menu=False):
    margins = dict.fromkeys(("left", "right", "top", "bottom"), 0.0)
    if not menu:
        side = {0: "bottom", 90: "left", 180: "top", 270: "right"}[rotation % 360]
        extent = size[0] if rotation % 180 else size[1]
        margins[side] = footer_height(size)/extent
    return margins


def menu_scale(size):
    return max(1, min(size)/1080)


def logical_point(x, y, size, rotation):
    w, h = size
    return {0: (x, y), 90: (y, w-x), 180: (w-x, h-y), 270: (h-y, x)}[rotation % 360]


def menu_geometry(size):
    scale = menu_scale(size)
    top, row, count = _menu_geometry(tuple(round(value/scale) for value in size))
    return round(top*scale), round(row*scale), count


def _menu_geometry(size):
    w, h = size
    top = max(82, int(h * 0.09))
    row = max(100, min(220, int(h * 0.18)))
    count = max(1, (h-top-104)//row)
    return top, row, count


def render_menu(items, offset, selected, size):
    scale = menu_scale(size)
    base = tuple(round(value/scale) for value in size)
    image = _render_menu(items, offset, selected, base)
    return image.resize(size, Image.Resampling.LANCZOS) if base != size else image


def _render_menu(items, offset, selected, size):
    w, h = size
    image = Image.new("RGB", size, (245, 245, 240))
    draw = ImageDraw.Draw(image)
    top, row, count = menu_geometry(size)
    draw.rectangle((0, 0, w, top), fill=(234, 234, 228))
    draw.rounded_rectangle((20, 15, min(w-20, 270), top-15), radius=8, fill=(30, 117, 133))
    draw.text((34, 25), "Start Schedule", font=font(24), fill="white")
    if not items:
        draw.text((30, top+40), "No cached media available", font=font(24), fill=(55, 55, 55))
    for index, item in enumerate(items[offset:offset+count], offset):
        y = top + (index-offset)*row + 10
        fill = (219, 239, 239) if selected == index else (255, 255, 255)
        draw.rounded_rectangle((20, y, w-20, y+row-18), radius=12, fill=fill)
        thumb_w, thumb_h = min(200, w//3), row-38
        try:
            if is_video_file(item["path"]):
                draw.rectangle((34, y+10, 34+thumb_w, y+10+thumb_h), fill=(27, 80, 93))
                cx, cy = 34+thumb_w//2, y+10+thumb_h//2
                draw.polygon([(cx-12, cy-20), (cx-12, cy+20), (cx+20, cy)], fill="white")
            else:
                with Image.open(item["path"]) as source:
                    source.thumbnail((thumb_w, thumb_h))
                    thumb = ImageOps.exif_transpose(source).convert("RGB")
                    image.paste(thumb, (34+(thumb_w-thumb.width)//2, y+10+(thumb_h-thumb.height)//2))
        except (OSError, ValueError):
            draw.text((34, y+20), "Unavailable", font=font(16), fill=(80, 80, 80))
        label = f"Paper ID: {item.get('paper_id') or item['path'].stem}"
        while draw.textlength(label, font=font(22)) > w-thumb_w-90 and len(label) > 4:
            label = label[:-4] + "..."
        draw.text((thumb_w+55, y+24), label, font=font(22), fill=(45, 45, 45))
        kind = "Video" if is_video_file(item["path"]) else "GIF" if is_animated_gif(item["path"]) else "Image"
        draw.text((thumb_w+55, y+58), kind + "  /  Tap to view", font=font(16), fill=(85, 85, 85))
    draw.text((24, h-90), f"{min(offset+1, len(items))}-{min(offset+count, len(items))} of {len(items)}   Scroll to browse", font=font(20), fill=(65, 65, 65))
    return image


class PreparedImages:
    """At most three decoded/resized stills on temporary storage; no frame arrays."""
    def __init__(self, directory, limit=3):
        self.directory = Path(directory)
        self.limit = limit
        self.entries = OrderedDict()
        self.sequence = 0

    def prepare(self, path, size):
        path = Path(path)
        if is_video_file(path) or is_animated_gif(path):
            return path
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size, size)
        if key in self.entries:
            self.entries.move_to_end(key)
            return self.entries[key]
        with Image.open(path) as source:
            # JPEG draft reduces decode memory for very large uploaded posters.
            source.draft("RGB", size)
            image = ImageOps.exif_transpose(source)
            # Fill the actual display, including upscaling. Stretch instead of
            # cropping so titles/labels at poster edges remain visible.
            image = image.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", size, "black")
        canvas.paste(image, (0, 0), image)
        self.sequence += 1
        output = self.directory / f"prepared-{self.sequence}.png"
        canvas.save(output, compress_level=1)
        self.entries[key] = output
        while len(self.entries) > self.limit:
            _, old = self.entries.popitem(last=False)
            old.unlink(missing_ok=True)
        return output


def uncover_overlays(image, rotation, show_timer=True, timer_text="00:00"):
    """Bitmap holds sit above ASS; leave the live timer and footer uncovered."""
    image = image.convert("RGBA")
    size = logical_size(image.size, rotation)
    mask = Image.new("L", size, 255)
    draw = ImageDraw.Draw(mask)
    scale = overlay_scale(image.size)
    if show_timer:
        margin = round(16*scale)
        width = max(120*scale, len(timer_text)*int(28*scale)*0.65+24*scale)
        draw.rounded_rectangle((margin, margin, margin+round(width), margin+round(48*scale)), radius=round(16*scale), fill=0)
    draw.rectangle((0, size[1]-footer_height(image.size), size[0], size[1]), fill=0)
    if rotation:
        mask = mask.rotate(-rotation, expand=True)
    image.putalpha(mask)
    # Zero RGB for transparent pixels: mpv expects premultiplied alpha.
    blank = Image.new("RGBA", image.size)
    blank.paste(image, mask=mask)
    return blank


class Display:
    def __init__(self, hwdec="auto", player=None):
        self.player = player or MpvPlayer(hwdec=hwdec)
        self.temp = tempfile.TemporaryDirectory(prefix="eposter-frames-")
        self.directory = Path(self.temp.name)
        self.prepared = PreparedImages(self.directory)
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stopping = False
        self.pending = None
        self.preload = None
        self.requested = None
        self.shown = None
        self.error = None
        self.retry_at = 0
        self.rotation = 0
        self.menu_serial = 0
        self.overlay_state = None
        self.viewport = None
        self.worker = threading.Thread(target=self._work, name="media-display", daemon=True)
        self.worker.start()

    @property
    def size(self):
        dims = self.player.properties.get("osd-dimensions") or {}
        return (int(dims.get("w") or 1920), int(dims.get("h") or 1080))

    def show(self, path, rotation=0, menu=None):
        path = Path(path) if path else None
        try:
            stat = path.stat() if path else None
            stamp = (stat.st_mtime_ns, stat.st_size) if stat else None
        except OSError:
            stamp = None
        key = (str(path), stamp, rotation, self.size, menu["key"] if menu else None)
        with self.lock:
            if key == self.requested and (not self.error or time.monotonic() < self.retry_at):
                return
            self.requested = key
            self.pending = (key, path, rotation, self.size, menu)
            self.error = None
        # Stop outgoing audio immediately, but let the video output finish any
        # pending loop/seek before the worker captures its transition frame.
        if self.shown is not None:
            self.player.command("set_property", "mute", True)
        self.wake.set()

    def prefetch(self, path, rotation=0):
        if path and not is_video_file(path) and not is_animated_gif(path):
            with self.lock:
                self.preload = (Path(path), media_size(self.size, rotation))
            self.wake.set()

    def overlay(self, deadline=None, paper_id=None, ip="", status="", rotation=0, menu=False):
        state = {"deadline": deadline, "rotation": rotation, "status": status,
                 "footer_left": f"Paper ID: {paper_id}" if paper_id is not None else "",
                 "footer_right": ip}
        if state != self.overlay_state:
            self.player.set_overlay(**state)
            self.overlay_state = state
        desired_cursor = "no" if menu else "1000"
        if getattr(self, "cursor", None) != desired_cursor:
            self.player.command("set_property", "cursor-autohide", desired_cursor)
            self.cursor = desired_cursor

    def _set_viewport(self, size, rotation, menu=False):
        key = (size, rotation, menu)
        if key != self.viewport:
            for side, ratio in media_margins(size, rotation, menu).items():
                self.player.command("set_property", f"video-margin-ratio-{side}", ratio)
            self.viewport = key

    def _hold_frame(self, rotation):
        if self.shown is None or self.player.headless:
            return False
        try:
            snapshot = self.directory / "hold.png"
            self.player.command("screenshot-to-file", str(snapshot), "window", timeout=2)
            with Image.open(snapshot) as frame:
                deadline = (self.overlay_state or {}).get("deadline")
                self.player.bitmap(uncover_overlays(frame, rotation, deadline is not None,
                                                   format_remaining((deadline or 0)-time.time())))
            return True
        except (PlayerError, OSError, ValueError) as error:
            LOG.debug("Frame hold unavailable: %s", error)
            return False

    def _work(self):
        while not self.stopping:
            self.wake.wait(0.2)
            self.wake.clear()
            with self.lock:
                job, self.pending = self.pending, None
                preload = None
                if job is None:
                    preload, self.preload = self.preload, None
            if job:
                key, path, rotation, size, menu = job
                held = False
                try:
                    if menu:
                        self.menu_serial += 1
                        prepared = self.directory / f"menu-{self.menu_serial % 2}.png"
                        render_menu(menu["items"], menu["offset"], menu["selected"], logical_size(size, rotation)).save(prepared, compress_level=1)
                    else:
                        prepared = self.prepared.prepare(path, media_size(size, rotation))
                    with self.lock:
                        if key != self.requested:
                            continue
                    held = self._hold_frame(rotation)
                    # Pause the outgoing clip before its replacement can load.
                    self.player.command("set_property", "pause", True)
                    self._set_viewport(size, rotation, bool(menu))
                    self.player.load(prepared, rotation, start_paused=True)
                    # Expose the decoded first frame before advancing the clip.
                    if held:
                        self.player.remove_bitmap()
                        held = False
                    with self.lock:
                        superseded = key != self.requested
                    if superseded:
                        self.player.command("set_property", "pause", True)
                    else:
                        self.player.command("set_property", "mute", False)
                        self.player.command("set_property", "pause", False)
                    self.shown, self.rotation = key, rotation
                    LOG.info("Showing %s at rotation %s", "menu" if menu else path.name, rotation)
                except (PlayerError, OSError, ValueError) as error:
                    LOG.error("Display failed: %s", error)
                    if self.player.alive:
                        try:
                            self._set_viewport(size, rotation)
                            content_size = media_size(size, rotation)
                            fallback = self.directory / f"unavailable-{content_size[0]}x{content_size[1]}.png"
                            if not fallback.exists():
                                Image.new("RGB", content_size, (25, 30, 32)).save(fallback)
                            self.player.load(fallback, rotation, timeout=3)
                        except (PlayerError, OSError):
                            LOG.warning("Could not load the unavailable-media background")
                    with self.lock:
                        if key == self.requested:
                            self.error = str(error)
                            self.retry_at = time.monotonic() + 15
                finally:
                    if held and self.player.alive:
                        try:
                            self.player.remove_bitmap()
                        except PlayerError:
                            pass
            elif preload:
                try:
                    self.prepared.prepare(*preload)
                except (OSError, ValueError):
                    pass

    def inputs(self):
        while True:
            try:
                yield self.player.inputs.get_nowait()
            except queue.Empty:
                return

    def close(self):
        self.stopping = True
        self.wake.set()
        self.player.close()
        self.worker.join(timeout=12)
        if not self.worker.is_alive():
            self.temp.cleanup()
