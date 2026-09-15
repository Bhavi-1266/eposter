"""Responsive scheduling for Time, Scroll and Menu using one display backend."""
import logging
import signal
import threading
import time
from pathlib import Path

from helper import cache_handler
from helper.display_handler import Display, get_local_ip, logical_point, logical_size, menu_geometry, menu_scale
from helper.schedule import active_record, record_deadline
from helper.json_utils import atomic_write_json

LOG = logging.getLogger(__name__)


def media_url(record):
    return (record or {}).get("eposter_file") or (record or {}).get("file")


def positive_seconds(value, fallback, minimum=1):
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return fallback


def refresh_key(config):
    display, api = config.get("display", {}), config.get("api", {})
    return (str(display.get("hardware_ID", "")), api.get("poster_token"), api.get("poster_api_url"), api.get("timezone"))


class RefreshWorker:
    """One worker calls the existing cache routine; no overlapping cache cleanup."""
    def __init__(self, refresh):
        self.refresh = refresh
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self.pending = None
        self.snapshot = None
        self.version = 0
        self.stopping = False
        self.thread = threading.Thread(target=self._run, name="cache-refresh", daemon=True)
        self.thread.start()

    def request(self, key):
        with self.lock:
            self.pending = key
        self.wake.set()

    def read(self):
        with self.lock:
            return self.snapshot, self.version

    def _publish(self, key, records, duration):
        with self.lock:
            self.snapshot = key, records, duration
            self.version += 1

    def _run(self):
        while not self.stopping:
            self.wake.wait(0.2)
            self.wake.clear()
            with self.lock:
                key, self.pending = self.pending, None
            if key is None:
                continue
            try:
                records, duration = self.refresh(key[1], key[0], lambda r, d: self._publish(key, r, d))
                self._publish(key, records, duration)
            except Exception:
                LOG.exception("Background refresh failed; retaining the saved schedule")

    def close(self):
        self.stopping = True
        self.wake.set()
        # Network calls retain their existing timeouts; don't block display exit.
        self.thread.join(timeout=0.2)


class Controller:
    def __init__(self, root, load_config, read_records, refresh, set_mode, display=None):
        self.root = Path(root)
        self.load_config = load_config
        self.read_records = read_records
        self.refresh_fn = refresh
        self.set_mode = set_mode
        self.display = display
        self.config = load_config()
        self.records, self.default_duration = read_records(self.config.get("display", {}).get("hardware_ID"))
        self.items = []
        self.mode = None
        self.rotation = 0
        self.offset = 0
        self.selected = 0
        self.preview = None
        self.preview_deadline = None
        self.scroll_path = None
        self.scroll_until = 0
        self.scroll_index = 0
        self.ip = "127.0.0.1"
        self.running = True
        self.revision = 0
        self.last_prefetch = None
        self.worker = None
        self.applied_hwdec = None
        self.idle = self.root / "ScreenSaver.gif"
        if not self.idle.exists():
            self.idle = self.root / "ScreenSaver.png"

    def rebuild_items(self):
        by_url = {}
        for record in self.records:
            url = media_url(record)
            if url and url not in by_url:
                path = cache_handler.get_media_path(url)
                if path:
                    by_url[url] = {"path": path, "url": url, "paper_id": record.get("paper_id")}
        self.items = list(by_url.values())
        self.selected = min(self.selected, max(0, len(self.items)-1))
        self.offset = min(self.offset, max(0, len(self.items)-1))
        self.revision += 1

    def record_for_url(self, url, now):
        return active_record([r for r in self.records if media_url(r) == url], now)

    def apply_config(self, config):
        old_key = refresh_key(self.config)
        self.config = config
        settings = config.get("display", {})
        mode = settings.get("Mode", "Time")
        if mode not in ("Time", "Scroll", "Menu"):
            mode = "Time"
        try:
            rotation = int(settings.get("rotation_degree", 0)) % 360
        except (TypeError, ValueError):
            rotation = 0
        if rotation not in (0, 90, 180, 270):
            rotation = 0
        if self.mode != mode or old_key != refresh_key(config):
            self.preview = None
            self.preview_deadline = None
            self.scroll_until = 0
            self.scroll_path = None
            self.offset = self.selected = self.scroll_index = 0
        self.mode, self.rotation = mode, rotation
        hwdec = str(settings.get("video_hwdec", "auto"))
        if hwdec != self.applied_hwdec and self.display:
            self.display.player.command("set_property", "hwdec", hwdec)
            self.applied_hwdec = hwdec

    def input(self, event, now):
        key = event[0]
        if key == "q":
            self.running = False
            return
        if self.mode != "Menu":
            return
        if self.preview:
            self.preview = None
            self.preview_deadline = None
            return
        size = logical_size(self.display.size, self.rotation)
        top, row, count = menu_geometry(size)
        if key in ("DOWN", "WHEEL_DOWN", "PGDWN"):
            step = count if key == "PGDWN" else 1
            self.selected = min(max(0, len(self.items)-1), self.selected+step)
        elif key in ("UP", "WHEEL_UP", "PGUP"):
            step = count if key == "PGUP" else 1
            self.selected = max(0, self.selected-step)
        elif key == "DRAG":
            dx, dy = float(event[1]), float(event[2])
            delta = {0: dy, 90: -dx, 180: -dy, 270: dx}[self.rotation]
            self.selected = max(0, min(len(self.items)-1, self.selected-int(delta/row or (1 if delta > 0 else -1))))
        elif key in ("ENTER", "SPACE") and self.items:
            self.preview = self.items[self.selected]
        elif key == "CLICK":
            x, y = logical_point(float(event[1]), float(event[2]), self.display.size, self.rotation)
            scale = menu_scale(size)
            if 20*scale <= x <= min(size[0]-20*scale, 270*scale) and 15*scale <= y <= top-15*scale:
                try:
                    self.set_mode("Time")
                except (OSError, ValueError):
                    LOG.exception("Could not save mode; retaining the current settings")
                    return
                config = dict(self.config, display=dict(self.config.get("display", {}), Mode="Time"))
                self.apply_config(config)
                return
            local = y-top-10*scale
            index = self.offset + int(local//row)
            if 20*scale <= x < size[0]-20*scale and local >= 0 and local % row < row-18*scale and index < min(len(self.items), self.offset+count):
                self.selected = index
                self.preview = self.items[index]
        if self.preview:
            self.preview_deadline = record_deadline(self.record_for_url(self.preview["url"], now))
        self.offset = min(self.offset, self.selected)
        if self.selected >= self.offset+count:
            self.offset = self.selected-count+1

    def choose(self, now):
        """Return path, API deadline, paper ID, status, menu specification."""
        if self.mode == "Time":
            record = active_record(self.records, now)
            if not record:
                return self.idle, None, None, "", None
            path = cache_handler.get_media_path(media_url(record))
            if not path:
                return self.idle, record_deadline(record), record.get("paper_id"), "Waiting for scheduled media", None
            return path, record_deadline(record), record.get("paper_id"), "", None
        if self.mode == "Menu":
            if self.preview_deadline is not None and now >= self.preview_deadline:
                self.preview = None
                self.preview_deadline = None
            if self.preview:
                record = self.record_for_url(self.preview["url"], now)
                if self.preview_deadline is not None and record is None:
                    self.preview = None
                    self.preview_deadline = None
                    return self.choose(now)
                self.preview_deadline = record_deadline(record)
                return self.preview["path"], self.preview_deadline, self.preview.get("paper_id"), "", None
            menu = {"key": (self.revision, self.offset, self.selected), "items": self.items,
                    "offset": self.offset, "selected": self.selected}
            return None, None, None, "", menu
        if not self.items:
            return self.idle, None, None, "", None
        urls = {item["url"] for item in self.items}
        if now >= self.scroll_until or not self.scroll_path or self.scroll_path["url"] not in urls:
            self.scroll_index %= len(self.items)
            self.scroll_path = self.items[self.scroll_index]
            self.scroll_index = (self.scroll_index+1) % len(self.items)
            record = self.record_for_url(self.scroll_path["url"], now)
            duration = positive_seconds((record or {}).get("duration_seconds"), positive_seconds(self.config.get("display", {}).get("Auto_Scroll"), 5))
            self.scroll_until = now+duration
            if record:
                self.scroll_until = min(self.scroll_until, record_deadline(record))
        record = self.record_for_url(self.scroll_path["url"], now)
        return self.scroll_path["path"], record_deadline(record), self.scroll_path.get("paper_id"), "", None

    def tick(self, now):
        for event in self.display.inputs():
            self.input(event, now)
        path, deadline, paper, status, menu = self.choose(now)
        if self.display.error:
            status = "Media unavailable; retrying"
        self.display.overlay(deadline=deadline, paper_id=paper, ip=self.ip, status=status,
                             rotation=self.rotation, menu=self.mode == "Menu")
        self.display.show(path, self.rotation, menu)
        upcoming = None
        if self.mode == "Time":
            future = [r for r in self.records if r["start_dt"].timestamp() > now]
            if future:
                upcoming = cache_handler.get_media_path(media_url(min(future, key=lambda r: r["start_dt"])))
        elif self.mode == "Scroll" and self.items:
            upcoming = self.items[self.scroll_index % len(self.items)]["path"]
        prefetch_key = (str(upcoming), self.rotation, self.display.size, self.revision)
        if upcoming and prefetch_key != self.last_prefetch:
            self.display.prefetch(upcoming, self.rotation)
            self.last_prefetch = prefetch_key

    def run(self):
        self.display = self.display or Display(hwdec=self.config.get("display", {}).get("video_hwdec", "auto"))
        self.worker = RefreshWorker(self.refresh_fn)
        previous_handlers = {}
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[signum] = signal.signal(signum, lambda *_: setattr(self, "running", False))
        try:
            self.apply_config(self.config)
            self.rebuild_items()
            next_config = next_refresh = next_ip = next_health = 0
            version = 0
            while self.running:
                mono, now = time.monotonic(), time.time()
                if not self.display.player.alive:
                    raise RuntimeError("Player exited; the display service will restart it")
                if mono >= next_config:
                    try:
                        config = self.load_config()
                        changed = refresh_key(config) != refresh_key(self.config)
                        self.apply_config(config)
                        if changed:
                            self.records = []
                            self.rebuild_items()
                            next_refresh = 0
                    except (OSError, ValueError):
                        LOG.exception("Could not reload configuration; retaining the current settings")
                    next_config = mono+1
                if mono >= next_refresh:
                    self.worker.request(refresh_key(self.config))
                    next_refresh = mono+positive_seconds(self.config.get("display", {}).get("cache_refresh"), 60, 30)
                snapshot, new_version = self.worker.read()
                if snapshot and version != new_version and snapshot[0] == refresh_key(self.config):
                    self.records, self.default_duration = snapshot[1:]
                    self.rebuild_items()
                    version = new_version
                if mono >= next_ip:
                    self.ip = get_local_ip()
                    next_ip = mono+60
                self.tick(now)
                if mono >= next_health:
                    try:
                        atomic_write_json(self.root / ".playback-status.json", {
                            "checked_at": now, "hardware_ID": self.config.get("display", {}).get("hardware_ID"),
                            "player": "mpv", "pid": self.display.player.proc.pid, "mode": self.mode,
                            "hardware_decoder": self.display.player.properties.get("hwdec-current"),
                            "video_renderer": self.display.player.properties.get("current-vo"),
                            "display_size": list(self.display.size),
                            "error": self.display.error, "ready": self.display.player.ready > 0,
                        })
                    except OSError:
                        LOG.warning("Could not write playback status")
                    next_health = mono+(30 if self.display.player.ready > 0 else 1)
                time.sleep(0.05)
        finally:
            self.worker.close()
            self.display.close()
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
