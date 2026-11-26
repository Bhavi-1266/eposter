"""Local staff interface to the process which already owns the station UART."""
import os
from pathlib import Path
import re
import secrets
import socket
import time

try:
    from .uart_protocol import DEVICE_ID, confirm_config, decode_message, encode_message, valid_config
except ImportError:  # Standalone scripts on the board.
    from uart_protocol import DEVICE_ID, confirm_config, decode_message, encode_message, valid_config

RESULT = re.compile(rb"CHANNEL ([0-9a-f]{8}) ([A-Z_]+) ([0-9]{1,2})")
CONFIG_RESULT = re.compile(rb"RCFG ([0-9a-f]{8}) ([A-Z_]+) ([0-9a-f]{0,1200}|-)")
CONFIG_REQUEST = re.compile(rb"RCFG (GET|PEER|PAIR|BRIDGE|END|SCAN|IDENTIFY|SPARE) ([0-9a-f]{2,320}|-)")
def socket_path():
    return Path(os.environ.get("XDG_RUNTIME_DIR", str(Path.home() / ".cache"))) / "radxa-remote" / "control.sock"


class ControlSocket:
    def __init__(self, write):
        self.write = write
        self.path = socket_path()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        # Call after obtaining the exclusive UART lock. Only one listener per station.
        self.path.unlink(missing_ok=True)
        self.server.bind(str(self.path))
        self.path.chmod(0o600)
        self.server.listen(4)
        self.server.setblocking(False)
        self.client = None
        self.token = None
        self.json_request = None
        self.buffer = b""

    def finish(self, response):
        if self.client:
            try:
                self.client.sendall(response + b"\n")
            except OSError:
                pass
            self.client.close()
        self.client = self.token = self.json_request = None
        self.buffer = b""

    def poll(self):
        if self.client is None:
            try:
                self.client, _ = self.server.accept()
            except BlockingIOError:
                return True
            self.client.setblocking(False)
            self.deadline = time.monotonic() + 3
        if time.monotonic() > self.deadline:
            self.finish(b"TIMEOUT: check station power, firmware and UART")
        elif self.token is None and self.json_request is None:
            try:
                chunk = self.client.recv(512)
            except BlockingIOError:
                return True
            except OSError:
                chunk = b""
            self.buffer += chunk
            if not chunk or len(self.buffer) > 360:
                self.finish(b"INVALID")
            elif b"\n" in self.buffer:
                if self.buffer.lstrip().startswith(b"{"):
                    request = decode_message(self.buffer)
                    if request is None or not valid_config(request):
                        self.finish(b"INVALID")
                    else:
                        self.json_request = request
                        self.deadline = time.monotonic() + 40
                        self.write(encode_message(request))
                    return True
                config = CONFIG_REQUEST.fullmatch(self.buffer.strip())
                if config:
                    if config[2] != b'-' and len(config[2]) % 2:
                        self.finish(b"INVALID")
                        return True
                    self.token = f"{secrets.randbelow(0xffffffff)+1:08x}".encode()
                    self.deadline = time.monotonic() + 40
                    self.write(b"RCFG " + self.token + b" " + config[1] + b" " + config[2] + b"\n")
                    return True
                fields = self.buffer.decode("ascii", errors="replace").strip().split()
                if len(fields) != 2 or not DEVICE_ID.fullmatch(fields[0]) or fields[1] not in map(str, range(12)):
                    self.finish(b"INVALID")
                else:
                    self.token = f"{secrets.randbelow(0xffffffff)+1:08x}".encode()
                    self.deadline = time.monotonic() + 16
                    self.write(b"CHANNEL " + self.token + b" " + self.buffer.strip() + b"\n")
        return True

    def reply(self, line):
        config = CONFIG_RESULT.fullmatch(line.strip())
        if config and self.token == config[1]:
            self.finish(config[2] + b" " + config[3])
            return
        match = RESULT.fullmatch(line.strip())
        if match and self.token == match[1]:
            self.finish(match[2] + b" channel=" + match[3])

    def reply_json(self, message):
        request = self.json_request
        if request is None or message["id"] != request["id"]:
            return
        if not confirm_config(request, message):
            self.finish(b"INVALID CONFIG_RESULT")
            return
        self.finish(encode_message(message).rstrip(b"\n"))

    def close(self):
        self.finish(b"RECEIVER_STOPPED")
        self.server.close()
        self.path.unlink(missing_ok=True)


def change_channel(device_id, channel):
    if not DEVICE_ID.fullmatch(device_id) or channel not in range(12):
        raise ValueError("Expected device ID and channel 1 through 11")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(21)
        client.connect(str(socket_path()))
        client.sendall(f"{device_id} {channel}\n".encode())
        with client.makefile("rb") as stream:
            return stream.readline(160).decode().strip()


def configure_request(operation, data=b""):
    request = b"RCFG " + operation.encode("ascii") + b" " + (data.hex().encode() if data else b"-")
    if not CONFIG_REQUEST.fullmatch(request):
        raise ValueError("Invalid configuration request")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(45)
        client.connect(str(socket_path()))
        client.sendall(request + b"\n")
        with client.makefile("rb") as stream:
            response = stream.readline(1400).decode("ascii").strip().split(" ", 1)
    if len(response) != 2 or not re.fullmatch(r"[A-Z_]+", response[0]):
        raise OSError("Configuration result not confirmed: " + " ".join(response))
    status, payload = response
    try:
        return status, b"" if payload == "-" else bytes.fromhex(payload)
    except ValueError:
        raise OSError("Invalid configuration response") from None


def set_remote_settings(target, device_id=None, channel=None):
    data = {key: value for key, value in (("device_id", device_id), ("channel", channel)) if value is not None}
    request = {"v": 1, "type": "config", "id": secrets.token_hex(4), "op": "set", "target": target, "data": data}
    if not valid_config(request):
        raise ValueError("Supply the current device ID and a new device ID, channel 1–11, or both")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(45)
        client.connect(str(socket_path()))
        client.sendall(encode_message(request))
        with client.makefile("rb") as stream:
            line = stream.readline(1401)
    result = decode_message(line)
    if len(line) > 1400 or result is None or not confirm_config(request, result):
        raise OSError("Configuration not confirmed: " + (line[:160].decode("ascii", errors="replace").strip() or "no result"))
    return result
