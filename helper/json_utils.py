"""Small, Linux-friendly helpers for reliable shared JSON state."""
import copy
import fcntl
import json
import os
import stat
import tempfile
from pathlib import Path


def load_json_file(path, default=None):
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return copy.deepcopy(default)


def atomic_write_json(path, data, indent=2):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing_stat = path.stat()
    except FileNotFoundError:
        existing_stat = None

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        if existing_stat is not None:
            os.fchmod(fd, stat.S_IMODE(existing_stat.st_mode))
            try:
                os.fchown(fd, existing_stat.st_uid, existing_stat.st_gid)
            except PermissionError:
                pass
        else:
            os.fchmod(fd, 0o640)

        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=indent, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def update_json_file(path, updater, default=None):
    """Lock, read, update, and atomically replace a JSON file."""
    path = Path(path)
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if not lock_path.exists():
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o660)
        os.close(lock_fd)
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        data = load_json_file(path, default)
        updated = updater(data)
        if updated is not None:
            data = updated
        atomic_write_json(path, data)
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    return data
