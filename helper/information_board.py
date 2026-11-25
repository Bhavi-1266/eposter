"""Public schedule directory and circular pages of grouped screens."""
from datetime import datetime
from itertools import groupby
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from helper.json_utils import load_json_file
from helper.schedule import parse_datetime

DEFAULT_INFO_PAGE_SECONDS = 11
BOARD_TIMEZONE = ZoneInfo("Asia/Kolkata")


def format_time(value):
    hour = value.hour % 12 or 12
    suffix = "AM" if value.hour < 12 else "PM"
    return f"{hour}:{value.minute:02d} {suffix}"


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
        # The input timezone and the time shown on the schedule are independent.
        local_start, local_end = start.astimezone(BOARD_TIMEZONE), end.astimezone(BOARD_TIMEZONE)
        start_day, end_day = local_start.date(), local_end.date()
        if start_day == end_day:
            session_date = f"{start_day:%d %b %Y}"
        elif start_day.year == end_day.year:
            session_date = f"{start_day:%d %b}–{end_day:%d %b %Y}"
        else:
            session_date = f"{start_day:%d %b %Y}–{end_day:%d %b %Y}"
        records.append(dict(identity=identity, screen=str(screen), paper=paper, author=author,
                            title=title, start=start.timestamp(), end=end.timestamp(),
                            start_day=start_day.isoformat(), end_day=end_day.isoformat(), session_date=session_date,
                            session=f"{format_time(local_start)}–{format_time(local_end)}"))

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
    """Logical pixel layout for the approved landscape and portrait frames."""
    width, height = size
    portrait = height > width
    unit = min(width, height * 16 / 9) / 100
    footer = round(48 * max(.75, min(size) / 1080))
    banner = round(unit * (15 if portrait else 8.75))
    top = banner + round(unit * (2 if portrait else 1))
    headings = round(unit * (8 if portrait else 3.2))
    meta = round(unit * (5.8 if portrait else 3.3))
    available = max(1, height - footer - top - headings - meta)
    row_min = unit * (11.5 if portrait else 4.7)
    capacity = max(1, int(available / row_min))
    return dict(unit=unit, banner=banner, top=top, headings=headings, meta=meta,
                capacity=capacity, row_height=available // capacity)


class InformationBoard:
    def __init__(self, path):
        self.path = Path(path)
        self.records = []
        self.stamp = None
        self.next_read = 0
        self.notice = "Waiting for schedule"
        self.order_source = None
        self.entries = []
        self.groups = []
        self.offset = 0
        self.next_offset = 0
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
            updated = datetime.fromtimestamp(stat.st_mtime, BOARD_TIMEZONE)
            self.notice = f"Saved schedule updated {updated:%d %b %H:%M}"
        except (OSError, ValueError, TypeError, ZoneInfoNotFoundError):
            self.notice = "Schedule unavailable · showing saved entries" if self.records else "Waiting for schedule"

    def rebuild_groups(self, capacity):
        anchor = self.groups[self.offset][1][0]["identity"] if self.groups else None
        if self.order_source is not self.records:
            self.entries = sorted(self.records, key=lambda row: (row["screen"].zfill(12), row["screen"],
                                                                 row["start"], row["end"], row["paper"]))
            self.order_source = self.records

        groups = []
        first = 0
        offset = 0
        for _, records in groupby(self.entries, key=lambda row: row["screen"]):
            sessions = list(records)
            # Split a screen only when its sessions cannot fit on one page.
            for start in range(0, len(sessions), capacity):
                chunk = sessions[start:start + capacity]
                if anchor is not None and any(row["identity"] == anchor for row in chunk):
                    offset = len(groups)
                groups.append((first, chunk))
                first += len(chunk)
        self.groups = groups
        self.offset = offset if len(self.entries) > capacity else 0

    def page(self, now, mono, size, hold=DEFAULT_INFO_PAGE_SECONDS):
        geometry = board_geometry(size)
        capacity = geometry["capacity"]
        layout = size, hold
        total = len(self.records)
        animate = False
        if self.order_source is not self.records or layout != self.layout:
            self.rebuild_groups(capacity)
            self.layout = layout
            self.next_page = mono + hold
            self.generation += 1
        elif total > capacity and mono >= self.next_page:
            self.offset = self.next_offset
            self.next_page = mono + hold
            self.generation += 1
            animate = True

        today = datetime.fromtimestamp(now, BOARD_TIMEZONE).date()
        today_key = today.isoformat()
        rows = []
        group_count = 0
        for step in range(len(self.groups)):
            _, group = self.groups[(self.offset + step) % len(self.groups)]
            if len(rows) + len(group) > capacity:
                break
            group_count += 1
            for index, entry in enumerate(group):
                row = {key: entry[key] for key in ("screen", "paper", "author", "title", "session")}
                row["session_date"] = ("" if entry["start_day"] == entry["end_day"] == today_key
                                       else entry["session_date"])
                row["screen_span"] = len(group) if index == 0 else 0
                rows.append(row)

        self.next_offset = (self.offset + group_count) % len(self.groups) if self.groups else 0
        label = "0 sessions"
        if rows:
            first = self.groups[self.offset][0] + 1
            end = first + len(rows) - 1
            label = (f"Showing {first}–{end} of {total}" if end <= total
                     else f"Showing {first}–{total} + 1–{end - total} of {total}")
        return dict(rows=rows, date=f"{today:%d %b %Y}", label=label, notice=self.notice, geometry=geometry,
                    generation=self.generation, animate=animate)
