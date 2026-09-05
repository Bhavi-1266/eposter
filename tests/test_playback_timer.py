"""Headless countdown rendering, timing, and external-player regression tests."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import subprocess
import unittest
from unittest.mock import Mock, patch

import pygame
from helper import display_handler as display
from helper.playback_timer import PlaybackTimer, format_remaining, _shape_video_window


class TimerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.screen = pygame.display.set_mode((960, 540))

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_rounds_up_and_never_goes_negative(self):
        self.assertEqual(format_remaining(60.1), "01:01")
        self.assertEqual(format_remaining(0.1), "00:01")
        self.assertEqual(format_remaining(-5), "00:00")

    def test_deadline_and_reset(self):
        with patch("helper.playback_timer.time.monotonic", return_value=100):
            first = PlaybackTimer(30, (960, 540))
        with patch("helper.playback_timer.time.monotonic", return_value=115):
            self.assertEqual(first.remaining, 15)
            second = PlaybackTimer(20, (960, 540))
            self.assertEqual(second.remaining, 20)
        with patch("helper.playback_timer.time.monotonic", return_value=200):
            self.assertEqual(first.remaining, 0)

    def test_rotations_stay_in_logical_top_left(self):
        for rotation, corner in ((0, "topleft"), (90, "topright"), (180, "bottomright"), (270, "bottomleft")):
            timer = PlaybackTimer(30, (960, 540), rotation)
            _, rect, _ = timer.badge()
            margin = round(16 * timer.scale)
            expected = {0: (margin, margin), 90: (960 - margin, margin),
                        180: (960 - margin, 540 - margin), 270: (margin, 540 - margin)}
            self.assertEqual(getattr(rect, corner), expected[rotation])
            self.assertTrue(self.screen.get_rect().contains(rect))

    def test_paint_preserves_pixels_outside_badge(self):
        self.screen.fill((220, 225, 230))
        timer = PlaybackTimer(20, self.screen.get_size())
        timer.capture(self.screen)
        timer.paint(self.screen)
        self.assertEqual(self.screen.get_at((500, 400))[:3], (220, 225, 230))
        self.assertEqual(timer.background.get_at((0, 0))[:3], (220, 225, 230))

    def test_clip_duration_capped_by_slot(self):
        with patch("helper.display_handler.subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout="12.5\n")):
            self.assertEqual(display.video_countdown_duration("test.mov", 60), 12.5)
            self.assertEqual(display.video_countdown_duration("test.mov", 5), 5)

    def test_probe_failure_or_invalid_value_uses_slot(self):
        with patch("helper.display_handler.subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(display.video_countdown_duration("test.mov", 15), 15)
        for value in ("N/A", "nan", "inf", "-4"):
            with patch("helper.display_handler.subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=value)):
                self.assertEqual(display.video_countdown_duration("test.mov", 15), 15)

    def test_video_timer_closes_with_player(self):
        proc = Mock(returncode=0)
        proc.poll.side_effect = [None, 0, 0]
        window = Mock(closed=False)
        with patch.object(display, "_resolve_video_player", return_value=["ffplay", "{path}"]), \
             patch.object(display, "video_countdown_duration", return_value=12), \
             patch.object(display, "_spawn_video_player", return_value=proc), \
             patch.object(display, "VideoTimerWindow", return_value=window), \
             patch.object(display, "_handle_playback_events", return_value=True):
            self.assertTrue(display.display_video(self.screen, "test.mov", 960, 540, max_duration=60, clock=Mock()))
        window.tick.assert_called_once()
        window.close.assert_called_once()

    def test_video_window_shape_matches_rotated_badge(self):
        for rotation in (0, 90, 180, 270):
            surface, _, _ = PlaybackTimer(30, (960, 540), rotation).badge()
            root = Mock()
            root.winfo_screen.return_value = ":0.0"
            root.winfo_id.return_value = 100
            # Tk reports the client here, concealing its separate native wrapper.
            root.wm_frame.return_value = "0x64"
            x11, xext = Mock(), Mock()
            x11.XOpenDisplay.return_value = 123
            def query_tree(display, window, desktop, parent, children, count):
                desktop._obj.value = 1
                parent._obj.value = 101
                return 1
            x11.XQueryTree.side_effect = query_tree
            xext.XShapeQueryExtension.return_value = 1
            with patch("helper.playback_timer.ctypes.CDLL", side_effect=[x11, xext]), \
                 patch("helper.playback_timer.ctypes.util.find_library", side_effect=lambda name: name):
                _shape_video_window(root, surface)
            calls = xext.XShapeCombineRectangles.call_args_list
            self.assertEqual({call.args[1] for call in calls}, {100, 101})
            rectangles, count = calls[0].args[5:7]
            shaped_pixels = {(rectangles[i].x + dx, rectangles[i].y)
                             for i in range(count) for dx in range(rectangles[i].width)}
            visible_pixels = {(x, y) for y in range(surface.get_height())
                              for x in range(surface.get_width()) if surface.get_at((x, y)).a}
            self.assertEqual(shaped_pixels, visible_pixels)
            self.assertNotIn((0, 0), shaped_pixels)
            x11.XCloseDisplay.assert_called_once_with(123)

    def test_video_shape_never_clips_desktop(self):
        surface, _, _ = PlaybackTimer(30, (960, 540)).badge()
        root = Mock()
        root.winfo_screen.return_value = ":0.0"
        root.winfo_id.return_value = 100
        x11, xext = Mock(), Mock()
        x11.XOpenDisplay.return_value = 123
        xext.XShapeQueryExtension.return_value = 1
        def query_tree(display, window, desktop, parent, children, count):
            desktop._obj.value = parent._obj.value = 1
            return 1
        x11.XQueryTree.side_effect = query_tree
        with patch("helper.playback_timer.ctypes.CDLL", side_effect=[x11, xext]), \
             patch("helper.playback_timer.ctypes.util.find_library", side_effect=lambda name: name):
            _shape_video_window(root, surface)
        self.assertEqual([call.args[1] for call in xext.XShapeCombineRectangles.call_args_list], [100])

    def test_long_gif_frame_updates_countdown_during_wait(self):
        ticks = Mock()
        with patch("helper.display_handler.time.monotonic", side_effect=[0, 0.1, 0.4, 1.1]), \
             patch.object(display, "_handle_playback_events", return_value=True):
            self.assertTrue(display._wait_for_playback(1, clock=Mock(), on_tick=ticks))
        self.assertEqual(ticks.call_count, 2)
