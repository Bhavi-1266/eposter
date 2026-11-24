"""Generate the private pair partition used by the normal ESP-IDF build/flash flow."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import struct
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parent
PROFILES = ("presenter-two-button", "presenter-matrix", "crowd", "presenter-one-button")
ROLES = ("sender", "receiver")
DATA = ROOT / "data"
KEY_FILE = DATA / "encryption_key.txt"

def board_record(cfg, generation=None):
    if not isinstance(cfg, dict):
        raise ValueError("Expected a JSON setup object")
    name = cfg["device_id"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name):
        raise ValueError("Use a unique device ID of 1–64 letters, numbers, dashes, dots or underscores")
    target = cfg.get("target", "esp32c3")
    if target not in ("esp32", "esp32c3"):
        raise ValueError("target must be esp32 or esp32c3")
    if cfg.get("role") not in ROLES or cfg.get("profile") not in PROFILES:
        raise ValueError(f"Choose role from {ROLES} and profile from {PROFILES}")
    role = ROLES.index(cfg["role"])
    profile = PROFILES.index(cfg["profile"])
    key = cfg.get("master_key")
    if not isinstance(key, str) or not re.fullmatch(r"[0-9a-fA-F]{32}",key):
        raise ValueError("master_key must be 32 hexadecimal digits")
    ch = cfg.get("channel", 11)
    if ch == "auto":
        suffix = re.search(r"[0-9]+$", name)
        slot = int(suffix.group())-1 if suffix else int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "big")
        ch = (1,6,11)[slot % 3]
    if type(ch) is not int or not 1 <= ch <= 11:
        raise ValueError("Use channel 1–11 or auto")
    digest = hashlib.sha256(b"radxa-control/espnow/address/v1/" + name.encode()).digest()
    sender = bytes([(digest[0] & 0xf8) | 2]) + digest[1:6]
    receiver = bytes([sender[0] | 4]) + sender[1:]
    endpoints = (sender, receiver)
    keys = [hmac.digest(bytes.fromhex(key), f"radxa-control/espnow/v1/{name}/{purpose}".encode(), "sha256")[:16] for purpose in ("pmk","lmk")]
    record = struct.pack("<4sBB6s6s16s16sB4s65s", b"RCF2", role+1, ch, endpoints[role], endpoints[1-role],
                         *keys, profile, secrets.token_bytes(4) if generation is None else generation, name.encode())
    return target, ch, record

def read_setup(path, *, target=None):
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ValueError(f"Missing {path}. Run python generate_key.py to create the initial setup.") from None
    if not isinstance(cfg, dict):
        raise ValueError("Expected a JSON setup object")
    if target is not None:
        cfg["target"] = target  # idf.py set-target selects the chip for native flashing.
    cfg.setdefault("profile", "presenter-matrix")
    if "master_key" not in cfg:
        try:
            cfg["master_key"] = KEY_FILE.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            raise ValueError("Missing data/encryption_key.txt. Run python generate_key.py once.") from None
    return cfg

def build_partition(path, target, output):
    cfg = read_setup(path, target=target)
    # The firmware hashes the entire record to identify the saved radio channel.
    # Use a stable generation so rebuilding identical settings preserves that identity.
    _, channel, record = board_record(cfg, generation=bytes(4))
    setup_key = hmac.digest(bytes.fromhex(cfg['master_key']), b'radxa-control/setup/v1', 'sha256')[:16]
    record += b'\xff' * (256 - len(record)) + b'SET1' + setup_key + struct.pack('<I', zlib.crc32(setup_key))
    if not output.exists() or output.read_bytes() != record:
        fd, name = tempfile.mkstemp(dir=output.parent)
        tmp = Path(name)
        try:
            with os.fdopen(fd, "wb") as staged:
                staged.write(record)
            os.replace(tmp, output)
        finally:
            tmp.unlink(missing_ok=True)
    print(f"Pair settings: {cfg['device_id']} | {cfg['role']} | {target} | {cfg['profile']} | channel {channel}")

def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest="command", required=True)
    part = commands.add_parser("partition", help="Generate the private partition for the ESP-IDF build")
    part.add_argument("--target", choices=("esp32", "esp32c3"), required=True)
    part.add_argument("--output", type=Path, required=True)
    part.add_argument("--file", type=Path, default=ROOT/"data/setup.json")
    args=p.parse_args()
    build_partition(args.file, args.target, args.output)

if __name__ == "__main__":
    try: main()
    except (ValueError, KeyError, OSError) as exc: sys.exit(str(exc))
