#!/usr/bin/env python3
"""Local poster API and media server for ePoster development."""
import argparse
import copy
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = PROJECT_DIR / "local_test" / "api_data.json"
DEFAULT_EXAMPLE_FILE = Path(__file__).with_name("local_api_data.example.json")
DEFAULT_MEDIA_DIR = PROJECT_DIR / "local_test" / "media"
DATE_FORMAT = "%d-%m-%Y %H:%M:%S"

app = Flask(__name__)
DATA_FILE = DEFAULT_DATA_FILE
MEDIA_DIR = DEFAULT_MEDIA_DIR
API_TOKEN = ""


def _load_source():
    source_path = DATA_FILE if DATA_FILE.exists() else DEFAULT_EXAMPLE_FILE
    with source_path.open("r", encoding="utf-8") as handle:
        source = json.load(handle)
    if not isinstance(source, dict):
        raise ValueError("API data must be a JSON object")
    return source, source_path


def _absolute_media_url(value):
    if not isinstance(value, str) or not value.startswith("/"):
        return value
    return request.host_url.rstrip("/") + value


def _normalize_media_urls(payload):
    payload = copy.deepcopy(payload)
    for screen in payload.get("screens", []):
        for record in screen.get("records", []):
            for field in ("eposter_file", "file"):
                if field in record:
                    record[field] = _absolute_media_url(record[field])
    for booking in payload.get("booking_slot", []):
        for record in booking.get("records", []):
            for field in ("eposter_file", "file"):
                if field in record:
                    record[field] = _absolute_media_url(record[field])
    return payload


def _positive_int(value, default, maximum):
    try:
        return min(maximum, max(1, int(value)))
    except (TypeError, ValueError):
        return default


def _generate_schedule(source, source_path):
    templates = source.get("records", [])
    if not isinstance(templates, list) or not templates:
        raise ValueError("Simple API data requires a non-empty 'records' list")

    device_id = source.get("hardware_ID", source.get("device_id", source.get("screen_number", 1)))
    horizon_minutes = _positive_int(source.get("repeat_for_minutes"), 120, 1440)
    durations = [
        _positive_int(record.get("duration_seconds"), 15, 3600)
        for record in templates
    ]
    cycle_seconds = sum(durations)
    now = datetime.now().replace(microsecond=0)
    anchor = datetime.fromtimestamp(source_path.stat().st_mtime).replace(microsecond=0)

    cycles_since_anchor = math.floor((now - anchor).total_seconds() / cycle_seconds)
    cycle_start = anchor + timedelta(seconds=cycles_since_anchor * cycle_seconds)
    while cycle_start > now:
        cycle_start -= timedelta(seconds=cycle_seconds)

    records = []
    cursor = cycle_start
    sequence = 1
    end_limit = now + timedelta(minutes=horizon_minutes)
    while cursor < end_limit and len(records) < 5000:
        for template, duration in zip(templates, durations):
            end = cursor + timedelta(seconds=duration)
            record = copy.deepcopy(template)
            base_id = record.get("id", sequence)
            record["id"] = f"local-{base_id}-{sequence}"
            record.setdefault("paper_id", f"LOCAL-{sequence:04d}")
            record.setdefault("paper_title", f"Local test item {sequence}")
            record.setdefault("media_type", "video" if str(record.get("eposter_file", "")).lower().endswith((".mov", ".mp4", ".m4v", ".webm", ".mkv", ".avi")) else "image")
            record["duration_seconds"] = duration
            record["start_date_time"] = cursor.strftime(DATE_FORMAT)
            record["end_date_time"] = end.strftime(DATE_FORMAT)
            for field in ("eposter_file", "file"):
                if field in record:
                    record[field] = _absolute_media_url(record[field])
            records.append(record)
            cursor = end
            sequence += 1
            if cursor >= end_limit or len(records) >= 5000:
                break

    return {
        "status": True,
        "message": "Local ePoster test data",
        "date": now.strftime("%d-%m-%Y"),
        "total_screen": 1,
        "screens": [{
            "screen_number": device_id,
            "screen_start_time": records[0]["start_date_time"],
            "screen_end_time": records[-1]["end_date_time"],
            "no_of_records_in_screen": len(records),
            "records": records,
        }],
        "booking_slot": [],
    }


def _build_response():
    source, source_path = _load_source()
    if "screens" in source or "booking_slot" in source:
        return _normalize_media_urls(source)
    return _generate_schedule(source, source_path)


def _authorized():
    return not API_TOKEN or request.args.get("key") == API_TOKEN


@app.get("/")
def index():
    return jsonify({
        "service": "ePoster local test API",
        "poster_api": "/api/posters",
        "health": "/health",
        "media": "/media/<filename>",
    })


@app.get("/health")
def health():
    source_path = DATA_FILE if DATA_FILE.exists() else DEFAULT_EXAMPLE_FILE
    return jsonify({
        "status": "ok",
        "data_file": str(source_path),
        "media_directory": str(MEDIA_DIR),
    })


@app.get("/api/posters")
def posters():
    if not _authorized():
        return jsonify({"status": False, "message": "Invalid API key"}), 401
    try:
        return jsonify(_build_response())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return jsonify({"status": False, "message": str(error)}), 500


@app.get("/media/<path:filename>")
def media(filename):
    return send_from_directory(MEDIA_DIR, filename, conditional=True)


def main():
    global DATA_FILE, MEDIA_DIR, API_TOKEN

    parser = argparse.ArgumentParser(description="Serve local ePoster API test data")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data-file", type=Path, default=DEFAULT_DATA_FILE)
    parser.add_argument("--media-dir", type=Path, default=DEFAULT_MEDIA_DIR)
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    DATA_FILE = args.data_file.expanduser().resolve()
    MEDIA_DIR = args.media_dir.expanduser().resolve()
    API_TOKEN = args.token
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    source_path = DATA_FILE if DATA_FILE.exists() else DEFAULT_EXAMPLE_FILE
    print(f"[local-api] Data: {source_path}")
    print(f"[local-api] Media: {MEDIA_DIR}")
    print(f"[local-api] URL: http://{args.host}:{args.port}/api/posters")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
