#!/usr/bin/env python3
"""ePoster entry point. Cached API/media formats remain backward compatible."""
import logging
from pathlib import Path

from helper import api_handler, cache_handler, wifi_connect
from helper.configuration import load_config as read_config, migrate_config, normalize_config
from helper.json_utils import load_json_file, update_json_file
from helper.schedule import parse_datetime

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
API_DATA_JSON = SCRIPT_DIR / "api_data.json"
CACHE_DIR = SCRIPT_DIR / "eposter_cache"


def log(message, level="INFO"):
    logging.getLogger(__name__).log(getattr(logging, level, logging.INFO), message)


def load_config():
    return read_config(CONFIG_FILE)


def update_config_mode(new_mode):
    def apply_mode(data):
        data = normalize_config(data)
        data.setdefault("display", {})["Mode"] = new_mode
        return data
    update_json_file(CONFIG_FILE, apply_mode)


def get_device_records(screen_number):
    if screen_number is None or str(screen_number) == "":
        return [], 5
    api_timezone = load_config().get("api", {}).get("timezone")
    if not API_DATA_JSON.exists():
        return [], 5

    def _device_values(row):
        if "screen_number" in row:
            return [row["screen_number"]]
        return [
            row.get("hardware_ID"),
            row.get("screen_id"),
            row.get("device_id"),
            row.get("screen"),
            row.get("display_id"),
        ]

    def _matches_device(row):
        if not isinstance(row, dict):
            return False
        for val in _device_values(row):
            if val is not None and str(val) == str(screen_number):
                return True
        return False

    try:
        data = load_json_file(API_DATA_JSON, {}) or {}
        records = []
        seen_records = set()
        minutes_per_record = 5  # default

        def _rows(value):
            return value if isinstance(value, list) else []

        def _append_record(record):
            if not isinstance(record, dict):
                return
            url = record.get("eposter_file") or record.get("file")
            if url is not None and not isinstance(url, str):
                return
            start_dt = parse_datetime(record.get("start_date_time"), api_timezone)
            end_dt = parse_datetime(record.get("end_date_time"), api_timezone)
            if not start_dt or not end_dt or end_dt <= start_dt:
                return
            key = (
                str(record.get("id") or record.get("PosterId") or ""),
                start_dt,
                end_dt,
                (record.get("eposter_file") or record.get("file")),
            )
            if key in seen_records:
                return
            seen_records.add(key)
            parsed = dict(record)
            parsed["start_dt"] = start_dt
            parsed["end_dt"] = end_dt
            records.append(parsed)

        # Include every matching screen group; repeated slots are deduplicated.
        screens = _rows(data.get("screens"))
        for my_screen in screens:
            if not _matches_device(my_screen):
                continue
            minutes_per_record = my_screen.get("minutes_per_record", 5)
            for r in _rows(my_screen.get("records")):
                _append_record(r)

        # Always also check booking_slot for this screen
        bookings = _rows(data.get("booking_slot"))
        for b in bookings:
            if not isinstance(b, dict):
                continue
            slot_records = b.get("records", [])
            if not isinstance(slot_records, list):
                continue
            booking_matches = _matches_device(b)
            for r in slot_records:
                if not booking_matches and not _matches_device(r):
                    continue
                _append_record(r)

        if not records and isinstance(data.get("data"), list):
            for r in data["data"]:
                if _matches_device(r):
                    _append_record(r)

        return records, minutes_per_record

    except Exception as e:
        log(f"Error parsing records: {e}", "ERROR")
        return [], 5


def refresh_data_and_cache(poster_token, screen_number, publish=None):
    """The existing fetch/cache algorithm, executed by a single background worker."""
    if wifi_connect.ensure_wifi_connection():
        api_handler.fetch_posters(poster_token)
    records, duration = get_device_records(screen_number)
    if publish:
        publish(records, duration)
    cache_handler.sync_cache(records or [])
    return records, duration


def main():
    from helper.media_controller import Controller
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    migrate_config(CONFIG_FILE)
    Controller(SCRIPT_DIR, load_config, get_device_records, refresh_data_and_cache, update_config_mode).run()


if __name__ == "__main__":
    main()
