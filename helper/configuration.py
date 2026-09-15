"""Shared configuration migration; never change device identity or credentials."""
import copy
from pathlib import Path

from helper.json_utils import load_json_file, update_json_file


def normalize_config(config):
    if not isinstance(config, dict):
        raise ValueError("config.json must contain a valid JSON object")
    config = copy.deepcopy(config)
    for section in ("display", "api", "wifi"):
        if section in config and not isinstance(config[section], dict):
            raise ValueError(f"{section} must be an object")
    display = config.setdefault("display", {})
    if "hardware_ID" not in display and "device_id" in display:
        display["hardware_ID"] = display["device_id"]
    display.pop("device_id", None)
    return config


def load_config(path):
    # Reload failures must reach the controller, which retains its last config.
    # Substituting an empty object would clear its hardware ID and schedule.
    return normalize_config(load_json_file(path))


def migrate_config(path):
    """Atomic, idempotent migration under the same lock as the portal."""
    path = Path(path)
    config = load_json_file(path)
    if not isinstance(config, dict):
        raise ValueError("config.json must contain a valid JSON object")
    if normalize_config(config) != config:
        return update_json_file(path, normalize_config)
    return config
