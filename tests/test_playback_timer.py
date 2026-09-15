"""API deadlines must survive late starts, loops, refreshes and clock changes."""
import unittest
from unittest.mock import patch
from helper.playback_timer import PlaybackTimer, format_remaining
from helper.schedule import parse_datetime, active_record


class TimerTests(unittest.TestCase):
    def test_rounds_up_and_never_goes_negative(self):
        self.assertEqual(format_remaining(60.1), "01:01")
        self.assertEqual(format_remaining(0.1), "00:01")
        self.assertEqual(format_remaining(-5), "00:00")

    def test_absolute_deadline_survives_late_start_and_restart(self):
        with patch('helper.playback_timer.time.time', return_value=180):
            first = PlaybackTimer(300)
            self.assertEqual(first.text, '02:00')
        with patch('helper.playback_timer.time.time', return_value=240):
            restarted = PlaybackTimer(300)
            self.assertEqual(first.text, restarted.text)
            self.assertEqual(first.text, '01:00')
        with patch('helper.playback_timer.time.time', return_value=350):
            self.assertEqual(first.text, '00:00')

    def test_timezone_offsets_are_preserved_and_converted(self):
        local = parse_datetime('2026-09-15T10:00:00+05:30')
        utc = parse_datetime('2026-09-15T04:30:00Z')
        self.assertEqual(local, utc)
        self.assertEqual(parse_datetime('15-09-2026 10:00:00', 'Asia/Kolkata'), utc)
        self.assertIsNone(parse_datetime('not a date'))

    def test_adjacent_slots_have_one_owner_at_boundary(self):
        def record(start,end):
            return {'start_dt':parse_datetime(start),'end_dt':parse_datetime(end)}
        first=record('2026-09-15T10:00:00Z','2026-09-15T10:05:00Z')
        second=record('2026-09-15T10:05:00Z','2026-09-15T10:10:00Z')
        self.assertIs(active_record([first,second],first['end_dt'].timestamp()),second)
        self.assertIsNone(active_record([first,second],second['end_dt'].timestamp()))
