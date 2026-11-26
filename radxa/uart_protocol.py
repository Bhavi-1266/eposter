"""Version 1 JSON lines sent between the presenter receiver and ePoster."""
from collections import OrderedDict
import json
import re


MESSAGE_TYPES = {"input", "ack", "config", "config_result"}
MESSAGE_ID = re.compile(r"[A-Za-z0-9_.:-]{1,100}")
DEVICE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
BUTTONS = ("AIM", "UP", "DOWN", "LEFT", "RIGHT", "OK", "HOME", "BACK", "MODE")


def reject_constant(value):
    raise ValueError(f"Invalid JSON number: {value}")


def decode_message(line):
    try:
        message = json.loads(line.decode("utf-8"), parse_constant=reject_constant)
    except (UnicodeError, ValueError, RecursionError):
        return None
    if not isinstance(message, dict) or type(message.get("v")) is not int or message["v"] != 1:
        return None
    kind, message_id = message.get("type"), message.get("id")
    if (not isinstance(kind, str) or kind not in MESSAGE_TYPES
            or not isinstance(message_id, str) or not MESSAGE_ID.fullmatch(message_id)):
        return None
    return message


def encode_message(message):
    return (json.dumps(message, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def valid_device_id(value):
    return isinstance(value, str) and bool(DEVICE_ID.fullmatch(value))


def valid_channel(value):
    return type(value) is int and 1 <= value <= 11


def valid_config(message):
    data = message.get("data")
    return (message.get("type") == "config" and message.get("op") == "set"
            and valid_device_id(message.get("target")) and isinstance(data, dict) and bool(data)
            and data.keys() <= {"device_id", "channel"}
            and ("device_id" not in data or valid_device_id(data["device_id"]))
            and ("channel" not in data or valid_channel(data["channel"])))


def confirm_config(request, result):
    """Only a matching receiver result can confirm the requested settings."""
    if result.get("type") != "config_result" or result.get("id") != request["id"]:
        return False
    status = result.get("status")
    if not isinstance(status, str) or not status:
        return False
    if status != "ok":
        return True
    data = result.get("data")
    wanted = request["data"]
    return (isinstance(data, dict) and data.get("device_id") == wanted.get("device_id", request["target"])
            and valid_channel(data.get("channel")) and ("channel" not in wanted or data["channel"] == wanted["channel"]))


class JsonInputReceiver:
    """Accept one array atomically and keep separate bounded replay histories."""

    def __init__(self, accept):
        self.accept = accept
        self.buttons_seen = OrderedDict()
        self.motion_seen = OrderedDict()
        self.count = self.duplicates = 0

    def process(self, message):
        data = message.get("data")
        if (not isinstance(data, list) or len(data) != 11
                or any(type(value) is not int or value not in (0, 1) for value in data[:9])
                or any(type(value) is not int or not -32768 <= value <= 32767 for value in data[9:])):
            return None
        message_id = message["id"]
        if message_id in self.buttons_seen or message_id in self.motion_seen:
            self.duplicates += 1
        else:
            buttons = tuple({"type": "button", "key": key}
                            for index, key in enumerate(BUTTONS[1:], 1) if data[index])
            # AIM gates signed relative movement. Nonzero deltas on an ordinary
            # button report do not move the cursor.
            motion = tuple(data[9:]) if data[0] and any(data[9:]) else None
            self.accept(buttons, motion)  # Raises if the application queue cannot accept it.
            history = self.buttons_seen if buttons else self.motion_seen
            history[message_id] = None
            if len(history) > 4096:
                history.popitem(last=False)
            self.count += 1
        return encode_message({"v": 1, "type": "ack", "id": message_id})
