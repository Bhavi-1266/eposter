"""One long-lived mpv process and a private JSON IPC connection.

No shell commands, network media URLs, or per-item player processes. A reader
thread dispatches replies so loading a file cannot block countdown/input events.
"""
import json
import logging
import queue
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

LOG = logging.getLogger(__name__)
SCRIPT = Path(__file__).with_name("player.lua")


class PlayerError(RuntimeError):
    pass


class MpvPlayer:
    def __init__(self, hwdec="auto", headless=False, startup_timeout=10, script=SCRIPT, software_rendering=False):
        binary = shutil.which("mpv")
        if not binary:
            raise PlayerError("mpv is missing. Run sudo python3 installer.py on the board.")
        self.temp = tempfile.TemporaryDirectory(prefix="eposter-player-")
        self.directory = Path(self.temp.name)
        self.socket_path = self.directory / "ipc"
        self.pending = {}
        self.lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.condition = threading.Condition()
        self.inputs = queue.Queue(maxsize=128)
        self.properties = {}
        self.sequence = 0
        self.started = 0
        self.ready = 0
        self.playback_restarts = 0
        self.failed = 0
        self.closed = False
        self.sock = None
        self.reader = None
        self.proc = None
        self.headless = headless
        args = [binary, "--no-config", "--load-scripts=no", f"--script={script}",
                f"--input-ipc-server={self.socket_path}", "--idle=yes",
                "--force-window=immediate", "--fullscreen", "--keep-open=always",
                "--image-display-duration=inf", "--loop-file=inf", "--osc=no",
                "--osd-level=0", "--input-default-bindings=no", "--input-terminal=no",
                "--cursor-autohide=1000", "--stop-screensaver=yes", "--border=no",
                "--audio-display=no", "--save-position-on-quit=no", "--resume-playback=no",
                "--screenshot-format=png", "--screenshot-png-compression=0",
                "--msg-level=all=warn", f"--hwdec={hwdec}"]
        args += ["--vo=null", "--ao=null", "--force-window=no"] if headless else ["--vo=gpu-next,gpu", "--gpu-api=opengl"]
        if software_rendering:
            args.append("--gpu-sw=yes")
        try:
            # Errors go to the service journal, never silently to DEVNULL.
            self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL)
            end = time.monotonic() + startup_timeout
            while time.monotonic() < end:
                if self.proc.poll() is not None:
                    raise PlayerError(f"mpv exited during startup ({self.proc.returncode}); inspect the service journal")
                candidate = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    candidate.connect(str(self.socket_path))
                    self.sock = candidate
                    break
                except OSError:
                    candidate.close()
                    time.sleep(0.025)
            if self.sock is None:
                raise PlayerError("mpv IPC startup timed out")
            self.reader = threading.Thread(target=self._read, name="mpv-ipc", daemon=True)
            self.reader.start()
            for index, prop in enumerate(("osd-dimensions", "hwdec-current", "video-codec", "path", "current-vo")):
                self.command("observe_property", index, prop)
            while time.monotonic() < end:
                try:
                    self.command("script-message", "eposter-ping")
                    if self.properties.get("eposter-ready") == "1":
                        break
                except PlayerError:
                    pass
                time.sleep(0.025)
            else:
                raise PlayerError("mpv countdown/input script did not initialize")
        except Exception:
            self.close()
            raise

    @property
    def alive(self):
        return not self.closed and self.proc is not None and self.proc.poll() is None

    def _read(self):
        buffer = b""
        try:
            while not self.closed:
                chunk = self.sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
                if len(buffer) > 4 * 1024 * 1024:
                    raise PlayerError("mpv IPC message exceeded the size limit")
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    self._dispatch(json.loads(line))
        except (OSError, ValueError, PlayerError) as error:
            if not self.closed:
                LOG.warning("mpv connection ended: %s", error)
        finally:
            with self.lock:
                for reply in self.pending.values():
                    reply.put({"error": "player disconnected"})
                self.pending.clear()
            with self.condition:
                self.closed = True
                self.condition.notify_all()

    def _dispatch(self, message):
        if "request_id" in message:
            with self.lock:
                reply = self.pending.pop(message["request_id"], None)
            if reply is not None:
                reply.put(message)
            return
        event = message.get("event")
        with self.condition:
            if event == "start-file":
                self.started += 1
            elif event == "playback-restart":
                self.playback_restarts += 1
                self.ready = self.started
            elif event == "end-file" and message.get("reason") == "error":
                self.failed = self.started
            elif event == "property-change":
                self.properties[message["name"]] = message.get("data")
                if message["name"] == "hwdec-current":
                    LOG.info("Video decoder: %s", message.get("data") or "software / no video")
                elif message["name"] == "current-vo":
                    LOG.info("Video renderer: %s", message.get("data") or "not initialized")
            elif event == "client-message":
                args = message.get("args", [])
                if len(args) >= 3 and args[0] == "eposter-state":
                    self.properties["eposter-" + args[1]] = args[2]
                if args and args[0] == "eposter-input":
                    try:
                        self.inputs.put_nowait(args[1:])
                    except queue.Full:
                        pass
            self.condition.notify_all()

    def command(self, *args, timeout=3):
        reply = queue.Queue()
        with self.lock:
            if not self.alive:
                raise PlayerError("mpv is not running")
            self.sequence += 1
            request_id = self.sequence
            self.pending[request_id] = reply
        try:
            encoded = json.dumps({"command": list(args), "request_id": request_id}).encode() + b"\n"
            with self.send_lock:
                self.sock.sendall(encoded)
            result = reply.get(timeout=timeout)
            if result.get("error") != "success":
                raise PlayerError(f"mpv {args[0]}: {result.get('error')}")
            return result.get("data")
        except queue.Empty:
            raise PlayerError(f"mpv {args[0]} timed out") from None
        except OSError as error:
            raise PlayerError(f"mpv connection failed: {error}") from error
        finally:
            with self.lock:
                self.pending.pop(request_id, None)

    def load(self, path, rotation=0, timeout=10, start_paused=False):
        path = Path(path).resolve()
        if not path.is_file():
            raise PlayerError("Cached media is missing")
        if start_paused:
            self.command("set_property", "pause", True)
        self.command("set_property", "video-rotate", int(rotation) % 360)
        with self.condition:
            previous = self.started
        self.command("loadfile", str(path), "replace")
        end = time.monotonic() + timeout
        with self.condition:
            while self.alive:
                if self.started > previous and self.failed == self.started:
                    raise PlayerError("mpv could not decode the cached media")
                if self.started > previous and self.ready == self.started:
                    break
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise PlayerError("Timed out waiting for the first media frame")
                self.condition.wait(min(remaining, 0.1))
            else:
                raise PlayerError("mpv exited while loading media")
        # Resume only the replacement. Resuming the outgoing still/loop before
        # loadfile can race its seek/restart with the new file's first frame.
        if not start_paused:
            self.command("set_property", "pause", False)

    def set_overlay(self, **state):
        self.command("script-message", "eposter-overlay", json.dumps(state))

    def bitmap(self, image, overlay_id=0):
        path = self.directory / f"overlay-{overlay_id}.bgra"
        rgba = image.convert("RGBA")
        # mpv expects premultiplied BGRA. Holds are opaque except for cutouts.
        path.write_bytes(rgba.tobytes("raw", "BGRA"))
        self.command("overlay-add", overlay_id, 0, 0, str(path), 0, "bgra", rgba.width, rgba.height, rgba.width * 4)

    def remove_bitmap(self, overlay_id=0):
        self.command("overlay-remove", overlay_id)

    def close(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                if self.alive and self.sock is not None:
                    self.command("quit", timeout=1)
            except PlayerError:
                pass
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=2)
        self.closed = True
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()
        if self.reader is not None and self.reader is not threading.current_thread():
            self.reader.join(timeout=1)
        self.temp.cleanup()
