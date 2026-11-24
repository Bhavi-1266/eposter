"""Accept presenter events from the station C3 over a 3.3 V UART (115200 8N1)."""
import argparse
from contextlib import contextmanager
import json
import os
import re
try:
    from .channel_control import ControlSocket
except ImportError:  # Direct execution from the standalone radxa/ deployment.
    from channel_control import ControlSocket
from collections import OrderedDict
from time import monotonic

KEYS = ("BACK", "UP", "HOME", "LEFT", "OK", "RIGHT", "AIM", "DOWN")
FRAME = re.compile(rb"EV ([0-9a-f]{8}) ([0-9a-f]{8}) ([123]) (-?\d{1,6}) (-?\d{1,6}) (\d{1,5})")

class Receiver:
    def __init__(self, accept):
        self.accept = accept
        self.seen = OrderedDict()
        self.count = self.duplicates = 0

    def process(self, line):
        match = FRAME.fullmatch(line.strip())
        if not match:
            return None
        session, seq, kind, x, y, mv = match.groups()
        x, y, mv = int(x), int(y), int(mv)
        if int(session, 16) == 0 or int(seq, 16) == 0 or mv > 65535:
            return None
        if not (-32768 <= x <= 32767 and -32768 <= y <= 32767):
            return None
        event = {"session": session.decode(), "sequence": int(seq, 16), "battery_mv": mv}
        if kind == b"1" and 0 <= x < len(KEYS) and y == 0:
            event.update(type="button", key=KEYS[x])
        elif kind == b"2":
            event.update(type="motion", dx=x, dy=y)
        elif kind == b"3" and x == y == 0:
            event["type"] = "probe"
        else:
            return None
        event_id = (session, seq)
        if event_id not in self.seen:
            self.accept(event)
            self.count += 1
            self.seen[event_id] = None
            if len(self.seen) > 512:
                self.seen.popitem(last=False)
        else:
            self.duplicates += 1
        if kind != b"2":
            return b"ACK " + session + b" " + seq + b"\n"
        return None

@contextmanager
def openLinuxUart(name):
    import termios
    import tty
    fd = os.open(name, os.O_RDWR | os.O_NOCTTY)
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = termios.tcgetattr(fd)
        tty.setraw(fd, termios.TCSANOW)
        settings = termios.tcgetattr(fd)
        settings[2] &= ~(termios.CSIZE | termios.PARENB | termios.CSTOPB | getattr(termios, "CRTSCTS", 0))
        settings[2] |= termios.CS8 | termios.CREAD | termios.CLOCAL
        settings[4] = settings[5] = termios.B115200
        termios.tcsetattr(fd, termios.TCSANOW, settings)
        try:
            yield fd
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSANOW, previous)
            except termios.error:
                pass
    finally:
        os.close(fd)

@contextmanager
def openPort(name):
    if os.name == "nt":
        import serial
        with serial.Serial(name, 115200, timeout=0.2, write_timeout=0.3) as port:
            yield lambda: port.read(port.in_waiting or 1), port.write
        return
    import select
    with openLinuxUart(name) as fd:
        def read():
            if not select.select([fd], [], [], 0.2)[0]:
                return b""
            chunk = os.read(fd, 1024)
            if not chunk:
                raise OSError("Station serial port disconnected")
            return chunk
        yield read, lambda data: writeUart(fd, data)

def writeUart(fd, data):
    while data:
        data = data[os.write(fd, data):]

class StationFrames:
    def __init__(self, receiver, control=None):
        self.control = control
        self.receiver = receiver
        self.pending = b""
        self.discard = False

    def feed(self, chunk, write):
        lines = (self.pending + chunk).split(b"\n")
        self.pending = lines.pop()
        for line in lines:
            if not self.discard and len(line) < 1400:
                if self.control and line.startswith((b"CHANNEL ", b"RCFG ")):
                    self.control.reply(line)
                    continue
                ack = self.receiver.process(line)
                if ack:
                    write(ack)
            self.discard = False
        if len(self.pending) > 1400:
            self.pending = b""
            self.discard = True

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", default="/dev/ttyS6", help="ROCK 5C UART6-M1")
    parser.add_argument("--quiet", action="store_true", help="Suppress individual synthetic probes")
    parser.add_argument("--summary-only", action="store_true", help="Print only listener startup and final totals")
    args = parser.parse_args()
    def accept(event):
        if not (args.quiet and event["type"] == "probe"):
            print(json.dumps(event, separators=(",", ":")), flush=True)
    rx = Receiver((lambda event: None) if args.summary_only else accept)
    with openPort(args.port) as (read, write):
        print(f"Listening on {args.port} at 115200 8N1", flush=True)
        last = monotonic()
        control = ControlSocket(write)
        frames = StationFrames(rx, control)
        try:
            while True:
                control.poll()
                frames.feed(read(), write)
                if not args.summary_only and monotonic() - last >= 5:
                    print(f"accepted={rx.count} duplicates={rx.duplicates}", flush=True)
                    last = monotonic()
        except KeyboardInterrupt:
            print(f"Final accepted={rx.count} duplicates={rx.duplicates}", flush=True)

        finally:
            control.close()

if __name__ == "__main__":
    main()
