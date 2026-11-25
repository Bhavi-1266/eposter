"""Public schedule directory and circular, fixed-capacity pages."""
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from helper.json_utils import load_json_file
from helper.schedule import parse_datetime


def screen_number(row):
    if "screen_number" in row:
        return row["screen_number"]
    return next((row[k] for k in ("hardware_ID", "screen_id", "device_id", "screen", "display_id")
                 if row.get(k) is not None), None)


def public_text(value, fallback="Not supplied"):
    if isinstance(value, (str, int, float)) and str(value).strip():
        return " ".join(str(value).split())[:240]
    return fallback


def directory_records(data, api_timezone=None):
    """Only expose public author/paper fields, never contact details or URLs."""
    if (not isinstance(data, dict) or data.get("status") is False
            or not any(isinstance(data.get(k), list) for k in ("screens", "booking_slot", "data"))):
        raise ValueError("No valid schedule in saved API data")
    records, seen = [], set()

    def append(record, parent_screen=None):
        if not isinstance(record, dict):
            return
        screen = screen_number(record)
        screen = parent_screen if screen is None else screen
        if screen is None or str(screen).strip() == "":
            return
        start = parse_datetime(record.get("start_date_time"), api_timezone)
        end = parse_datetime(record.get("end_date_time"), api_timezone)
        if not start or not end or end <= start:
            return
        paper = public_text(record.get("paper_id"), "Unavailable")
        author = public_text(record.get("corresponding_author"))
        title = public_text(record.get("paper_title"))
        identity = (str(screen), paper, start.timestamp(), end.timestamp(), author, title)
        if identity in seen:
            return
        seen.add(identity)
        # Schedule times use the API timezone if provided, otherwise the board's.
        zone = ZoneInfo(api_timezone) if api_timezone else None
        records.append(dict(identity=identity, screen=str(screen), paper=paper, author=author,
                            title=title, start=start.timestamp(), end=end.timestamp(),
                            session=start.astimezone(zone).strftime("%H:%M") + "–" + end.astimezone(zone).strftime("%H:%M")))

    for key in ("screens", "booking_slot"):
        groups = data.get(key)
        for group in groups if isinstance(groups, list) else []:
            if not isinstance(group, dict):
                continue
            children = group.get("records")
            if isinstance(children, list):
                for record in children:
                    append(record, screen_number(group))
    flat = data.get("data")
    for record in flat if isinstance(flat, list) else []:
        append(record)
    return records


def board_geometry(size):
    """Logical pixel layout, shared with player.lua; no scroll or shrunken last page."""
    width, height = size
    scale = max(.75, min(size) / 1080)
    footer = round(48 * scale)
    top = round(max(width * .10, width * .03 + 96 * scale))
    headings = round(42 * scale)
    meta = round(48 * scale)
    row_min = max(84 * scale, width * .048)
    capacity = max(1, int((height - footer - top - headings - meta) / row_min))
    row_height = max(1, int((height - footer - top - headings - meta) / capacity))
    return dict(top=top, headings=headings, meta=meta, capacity=capacity, row_height=row_height)


class InformationBoard:
    def __init__(self, path):
        self.path = Path(path)
        self.records = []
        self.stamp = None
        self.next_read = 0
        self.notice = "Waiting for schedule"
        self.entries = []
        self.offset = 0
        self.next_page = 0
        self.layout = None
        self.generation = 0

    def read(self, mono, api_timezone=None):
        if mono < self.next_read:
            return
        self.next_read = mono + 1
        try:
            stat = self.path.stat()
            stamp = stat.st_mtime_ns, stat.st_size, api_timezone
            if stamp != self.stamp:
                records = directory_records(load_json_file(self.path), api_timezone)
                self.records, self.stamp = records, stamp
            self.notice = "Saved schedule updated " + datetime.fromtimestamp(stat.st_mtime).astimezone().strftime("%d %b %H:%M")
        except (OSError, ValueError, TypeError, ZoneInfoNotFoundError):
            self.notice = "Schedule unavailable · showing saved entries" if self.records else "Waiting for schedule"

    def page(self, now, mono, size, hold=6):
        geometry = board_geometry(size)
        capacity = geometry["capacity"]
        eligible = sorted((r for r in self.records if r["end"] > now and r["start"] <= now + 300),
                          key=lambda r: (r["start"] > now, r["start"], r["screen"].zfill(12), r["paper"]))
        identities = [r["identity"] for r in eligible]
        old_ids = [r["identity"] for r in self.entries]
        layout = size, hold
        animate = False
        if identities != old_ids or layout != self.layout:
            first = old_ids[self.offset] if old_ids else None
            self.offset = identities.index(first) if first in identities else 0
            if len(eligible) <= capacity:
                self.offset = 0
            self.entries, self.layout = eligible, layout
            self.next_page = mono + hold
            self.generation += 1
        elif len(eligible) > capacity and mono >= self.next_page:
            self.offset = (self.offset + capacity) % len(eligible)
            self.next_page = mono + hold
            self.generation += 1
            animate = True
        count = min(capacity, len(eligible))
        visible = [eligible[(self.offset + i) % len(eligible)] for i in range(count)]
        rows = [{k: r[k] for k in ("screen", "paper", "author", "title", "session")} |
                {"status": "Presenting" if r["start"] <= now else "Starts in " + str(math.ceil((r["start"] - now) / 60)) + " min"}
                for r in visible]
        end = self.offset + count
        label = "0 entries"
        if count:
            label = (f"Showing {self.offset + 1}–{end} of {len(eligible)}" if end <= len(eligible)
                     else f"Showing {self.offset + 1}–{len(eligible)} + 1–{end % len(eligible)} of {len(eligible)}")
        return dict(rows=rows, label=label, notice=self.notice, geometry=geometry,
                    generation=self.generation, animate=animate)
