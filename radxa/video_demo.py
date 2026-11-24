"""Run the OK and hold-to-AIM test in a video window on the ROCK 5C X11 desktop."""
import argparse
import os
import signal
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst, Gtk

from channel_control import ControlSocket
from radxa_receiver import Receiver, StationFrames, openLinuxUart, writeUart


def run(port, video):
    Gst.init(None)
    window = Gtk.Window(title="Radxa remote | Video test")
    window.set_default_size(800, 520)
    layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    window.add(layout)
    if video:
        pipeline = Gst.ElementFactory.make("playbin", None)
        sink = Gst.ElementFactory.make("gtksink", None)
        pipeline.set_property("uri", video.resolve().as_uri())
        pipeline.set_property("video-sink", sink)
    else:
        pipeline = Gst.parse_launch(
            "videotestsrc pattern=ball ! video/x-raw,width=640,height=360,framerate=30/1 "
            "! timeoverlay ! videoconvert ! gtksink name=video"
        )
        sink = pipeline.get_by_name("video")
    widget = sink.get_property("widget")
    layout.pack_start(widget, True, True, 0)
    status = Gtk.Label()
    layout.pack_start(status, False, False, 5)
    playing = True
    error = None
    motion_count = 0

    def set_playing(value):
        nonlocal playing
        state = Gst.State.PLAYING if value else Gst.State.PAUSED
        if pipeline.set_state(state) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("GStreamer could not change playback state")
        playing = value
        label = "Playing" if playing else "Paused"
        status.set_text(f"{label}    ·    OK: play/pause    ·    Hold AIM and rotate to point")
        print(label, flush=True)

    def accept(event):
        nonlocal motion_count
        if event["type"] == "button":
            print(f"Button {event['key']} received", flush=True)
        if event["type"] == "button" and event["key"] == "OK":
            set_playing(not playing)
        elif event["type"] == "motion" and window.is_active():
            pointer = window.get_display().get_default_seat().get_pointer()
            screen, x, y = pointer.get_position()
            _, wx, wy = window.get_window().get_origin()
            origin = widget.translate_coordinates(window, 0, 0)
            if origin is None:
                return
            left, top = wx + origin[0], wy + origin[1]
            x = max(left, min(x + event["dx"], left + widget.get_allocated_width() - 1))
            y = max(top, min(y + event["dy"], top + widget.get_allocated_height() - 1))
            pointer.warp(screen, x, y)
            motion_count += 1
            if motion_count == 1:
                print("First AIM movement received", flush=True)

    def fail(message):
        nonlocal error
        error = message
        Gtk.main_quit()

    def media_message(bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            fail(str(msg.parse_error()[0]))
        elif msg.type == Gst.MessageType.EOS and video:
            pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 0)

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", media_message)
    receiver = Receiver(accept)
    with openLinuxUart(port) as fd:
        control = ControlSocket(lambda msg: writeUart(fd, msg))
        frames = StationFrames(receiver, control)
        staff_watch = GLib.timeout_add(50, control.poll)
        def receive(_source, condition):
            try:
                if condition & (GLib.IO_ERR | GLib.IO_HUP):
                    raise OSError("Station UART disconnected")
                data = os.read(fd, 4096)
                if not data:
                    raise OSError("Station UART closed")
                frames.feed(data, lambda ack: writeUart(fd, ack))
            except (OSError, RuntimeError) as exc:
                fail(str(exc))
            return True

        watch = GLib.io_add_watch(fd, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP, receive)
        window.connect("destroy", lambda *_: Gtk.main_quit())
        window.show_all()
        window.present()
        try:
            set_playing(True)
            print(f"Video test ready on {port}", flush=True)
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, Gtk.main_quit)
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
            Gtk.main()
        finally:
            pipeline.set_state(Gst.State.NULL)
            GLib.source_remove(watch)
            GLib.source_remove(staff_watch)
            control.close()
            bus.remove_signal_watch()
            print(f"Final accepted={receiver.count} duplicates={receiver.duplicates} motion={motion_count}", flush=True)
    if error:
        raise RuntimeError(error)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", default="/dev/ttyS6")
    parser.add_argument("--video", type=Path, help="play a local video instead of the moving test pattern")
    args = parser.parse_args()
    if args.video and not args.video.is_file():
        parser.error("video file does not exist")
    run(args.port, args.video)
