"""Create the local ESP-NOW master key once, keeping working pairs compatible."""
import json
import os
import re
import secrets
import sys

from setup_board import DATA, KEY_FILE


def create_private(path, text):
    with open(path, "x", encoding="ascii", opener=lambda name, flags: os.open(name, flags, 0o600)) as output:
        output.write(text)


def main():
    DATA.mkdir(exist_ok=True)
    setup = DATA / "setup.json"
    legacy_key = None
    if setup.exists():
        cfg = json.loads(setup.read_text(encoding="utf-8-sig"))
        if not isinstance(cfg, dict):
            raise ValueError("Expected a JSON object in data/setup.json")
        legacy_key = cfg.get("master_key")
        if "master_key" in cfg and (not isinstance(legacy_key, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", legacy_key)):
            raise ValueError("Invalid existing master_key in data/setup.json")
    if KEY_FILE.exists():
        saved = KEY_FILE.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[0-9a-fA-F]{32}", saved):
            raise ValueError("Existing data/encryption_key.txt must contain 32 hexadecimal digits")
        if legacy_key and saved.lower() != legacy_key.lower():
            raise ValueError("data/setup.json and data/encryption_key.txt contain different keys")
        print("Using existing data/encryption_key.txt")
    else:
        create_private(KEY_FILE, (legacy_key or secrets.token_hex(16)) + "\n")
        print("Created data/encryption_key.txt")
    if not setup.exists():
        create_private(setup, json.dumps(dict(device_id="remote-001", channel=11, role="sender"), indent=2) + "\n")
        print("Created data/setup.json")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))
