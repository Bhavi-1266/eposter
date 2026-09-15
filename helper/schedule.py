"""API schedule times are absolute deadlines, independent of media duration."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def parse_datetime(value, api_timezone=None):
    if not value:
        return None
    parsed = None
    for fmt in ("%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(str(value), fmt)
            break
        except ValueError:
            pass
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        # Legacy timestamps use the OS timezone, unless an API zone is set.
        parsed = (parsed.replace(tzinfo=ZoneInfo(api_timezone))
                  if api_timezone else parsed.astimezone())
    return parsed.astimezone(timezone.utc)


def active_record(records, now):
    """Stable ordering and half-open slots avoid ambiguity at adjacent boundaries."""
    candidates = [r for r in records if r["start_dt"].timestamp() <= now < r["end_dt"].timestamp()]
    return min(candidates, key=lambda r: (r["start_dt"], str(r.get("id", "")))) if candidates else None


def record_deadline(record):
    return record["end_dt"].timestamp() if record else None
