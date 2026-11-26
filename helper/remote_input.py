"""Bounded, reconnecting owner for the presenter receiver UART.

The serial thread only parses, acknowledges and queues events.  Application
state is changed by :class:`helper.media_controller.Controller` on its own
thread.  Motion is coalesced separately so a burst cannot delay button input.
"""
import logging
import queue
import threading
import termios
import time

from radxa.channel_control import ControlSocket
from radxa.radxa_receiver import Receiver, StationFrames, openPort
from radxa.uart_protocol import JsonInputReceiver

LOG = logging.getLogger(__name__)


class RemoteInput:
    """Own one station UART and expose non-blocking application-thread reads."""

    def __init__(self, port="/dev/ttyS6", queue_size=64, reconnect_delay=2.0,
                 motion_limit=4096, motion_max_age=0.35):
        self.port = str(port)
        self.events = queue.Queue(maxsize=max(1, int(queue_size)))
        self.reconnect_delay = max(0.1, float(reconnect_delay))
        self.motion_limit = max(1, int(motion_limit))
        self.motion_max_age = max(0.05, float(motion_max_age))
        self.motion_lock = threading.Lock()
        self.motion = [0, 0]
        self.motion_at = 0.0
        self.stop = threading.Event()
        self.json_receiver = JsonInputReceiver(self._accept_json)
        self.thread = threading.Thread(target=self._run, name="presenter-uart", daemon=True)
        self.thread.start()

    def _accept(self, event):
        if event["type"] == "motion":
            with self.motion_lock:
                limit = self.motion_limit
                self.motion[0] = max(-limit, min(limit, self.motion[0] + event["dx"]))
                self.motion[1] = max(-limit, min(limit, self.motion[1] + event["dy"]))
                self.motion_at = time.monotonic()
            return
        if event["type"] == "probe":
            # A diagnostic probe has no application action and must not occupy
            # capacity needed by ordered presenter button presses.
            return
        self.events.put_nowait((event,))

    def _accept_json(self, buttons, motion):
        # Accept all presses in this line together. A failed enqueue leaves
        # everything untouched so a retry cannot repeat a partial action.
        if buttons:
            self.events.put_nowait(buttons)
        if motion:
            self._accept({"type": "motion", "dx": motion[0], "dy": motion[1]})

    def _feed_chunk(self, frames, chunk, write):
        """Keep parsing later frames if one button cannot enter the queue."""
        parts = chunk.split(b"\n")
        for part in parts[:-1]:
            try:
                frames.feed(part + b"\n", write)
            except queue.Full:
                # The rejected event was not remembered, so a sender retry can
                # be accepted after the controller makes queue space.
                LOG.warning("Presenter input queue full; withholding ACK")
        if parts[-1]:
            frames.feed(parts[-1], write)

    def _run_connection(self):
        receiver = Receiver(self._accept)
        with openPort(self.port) as (read, write):
            LOG.info("Presenter remote listening on %s at 115200 8N1", self.port)
            control = ControlSocket(write)
            frames = StationFrames(receiver, control, self.json_receiver)
            try:
                while not self.stop.is_set():
                    control.poll()
                    self._feed_chunk(frames, read(), write)
            finally:
                control.close()

    def _run(self):
        while not self.stop.is_set():
            try:
                self._run_connection()
            except (OSError, ValueError, termios.error) as error:
                if not self.stop.is_set():
                    LOG.warning("Presenter UART unavailable (%s); retrying", error)
            self.clear_motion()
            self.stop.wait(self.reconnect_delay)

    def read(self):
        """Yield queued buttons/probes followed by one fresh coalesced motion."""
        while True:
            try:
                yield from self.events.get_nowait()
            except queue.Empty:
                break
        with self.motion_lock:
            dx, dy = self.motion
            fresh = time.monotonic() - self.motion_at <= self.motion_max_age
            self.motion[:] = (0, 0)
        if fresh and (dx or dy):
            yield {"type": "motion", "dx": dx, "dy": dy}

    def clear_motion(self):
        with self.motion_lock:
            self.motion[:] = (0, 0)
            self.motion_at = 0.0

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2.0)
        if self.thread.is_alive():
            LOG.warning("Presenter UART worker did not stop before timeout")
