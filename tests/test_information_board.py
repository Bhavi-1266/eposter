"""Directory data, timing, circular pages and retained cache behavior."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from helper.information_board import InformationBoard, directory_records, board_geometry


def slot(paper, start=900, end=2000, **extra):
    return dict(paper_id=paper, corresponding_author="Test Author", paper_title="Test Paper",
                start_date_time=datetime.fromtimestamp(start, timezone.utc).isoformat(),
                end_date_time=datetime.fromtimestamp(end, timezone.utc).isoformat(), **extra)


class DirectoryTests(unittest.TestCase):
    def test_all_screens_and_legacy_records_are_public_and_deduplicated(self):
        item = slot("0031", email="secret@example.org", mobile="private", eposter_file="private-url")
        rows = directory_records(dict(
            screens=[dict(screen_number=1, hardware_ID=99, records=[item]), dict(screen_number=2, records=[item])],
            booking_slot=[dict(screen_id=1, records=[item]), dict(records=[slot("P2", device_id=3)])],
            data=[slot("P3", screen_number=4)]))
        self.assertEqual([r["screen"] for r in rows], ["1", "2", "3", "4"])
        self.assertEqual(rows[0]["paper"], "0031")
        self.assertNotIn("secret", json.dumps(rows))
        self.assertNotIn("private", json.dumps(rows))

    def test_bad_rows_do_not_hide_valid_rows(self):
        rows = directory_records(dict(screens=42, booking_slot=None,
            data=[None, slot("invalid", end=800, screen_number=1), slot("valid", screen_number=2)]))
        self.assertEqual([r["paper"] for r in rows], ["valid"])

    def test_full_schedule_groups_each_screen_and_displays_kolkata_time(self):
        board = InformationBoard("/unused")
        board.records = directory_records(dict(data=[
            slot("tomorrow", start=87400, end=87800, screen_number=2),
            slot("running", screen_number=10),
            slot("later", start=1301, screen_number=1),
            slot("ended", end=1000, screen_number=2)]), "UTC")
        page = board.page(1000, 0, (1920,1080))
        rows = page["rows"]
        self.assertEqual([(row["screen"], row["paper"], row["screen_span"]) for row in rows],
                         [("1", "later", 1), ("2", "ended", 2), ("2", "tomorrow", 0), ("10", "running", 1)])
        self.assertEqual(rows[1]["session"], "5:45 AM–5:46 AM")
        self.assertEqual(rows[1]["session_date"], "")
        self.assertEqual(rows[2]["session_date"], "02 Jan 1970")
        self.assertEqual(page["date"], "01 Jan 1970")
        self.assertEqual(board.page(5000, 1, (1920,1080))["rows"], rows)

    def test_api_timezone_applies_before_display_conversion_across_midnight(self):
        record = slot("night", screen_number=1) | {
            "start_date_time": "2026-11-25 18:00:00", "end_date_time": "2026-11-25 19:30:00"}
        row, = directory_records({"data": [record]}, "UTC")
        self.assertEqual(row["session"], "11:30 PM–1:00 AM")
        self.assertEqual(row["session_date"], "25 Nov–26 Nov 2026")

    def test_pages_wrap_fill_and_single_page_never_duplicates(self):
        board = InformationBoard("/unused")
        geometry = dict(capacity=10, top=100, headings=40, meta=40, row_height=80)
        with patch("helper.information_board.board_geometry", return_value=geometry):
            for count in (0, 5, 10, 25):
                board.records = directory_records(dict(data=[slot(str(i), screen_number=i) for i in range(count)]))
                pages = [board.page(1000, t, (1920,1080)) for t in (0,11,22,33)]
                for page in pages:
                    self.assertEqual(len(page["rows"]), min(10,count))
                    self.assertEqual(len({r["paper"] for r in page["rows"]}), len(page["rows"]))
                if count<=10:
                    self.assertEqual(pages[0]["rows"], pages[-1]["rows"])
                    self.assertFalse(pages[-1]["animate"])
                else:
                    self.assertEqual([int(r["paper"]) for r in pages[2]["rows"]], list(range(20,25))+list(range(5)))
                    self.assertEqual([int(r["paper"]) for r in pages[3]["rows"]], list(range(5,15)))
                    self.assertTrue(pages[2]["animate"])

    def test_page_hold_and_screen_groups_only_split_when_too_large(self):
        board = InformationBoard("/unused")
        geometry = dict(capacity=5, top=100, headings=40, meta=40, row_height=80)
        board.records = directory_records({"data": [
            slot(f"{screen}-{i}", screen_number=screen)
            for screen, count in ((1, 2), (2, 3), (3, 7), (4, 2)) for i in range(count)]})
        with patch("helper.information_board.board_geometry", return_value=geometry):
            first = board.page(1000, 0, (1920,1080))
            self.assertEqual(board.page(1000, 10.99, (1920,1080))["rows"], first["rows"])
            self.assertEqual([r["screen_span"] for r in first["rows"]], [2, 0, 3, 0, 0])
            second = board.page(1000, 11, (1920,1080))
            self.assertTrue(second["animate"])
            self.assertEqual([r["screen_span"] for r in second["rows"]], [5, 0, 0, 0, 0])
            third = board.page(1000, 22, (1920,1080))
            self.assertEqual([r["paper"] for r in third["rows"]], ["3-5", "3-6", "4-0", "4-1"])
            self.assertEqual([r["screen_span"] for r in third["rows"]], [2, 0, 2, 0])

    def test_geometry_fits_and_does_not_depend_on_list_length(self):
        for size in ((1920,1080),(1080,1920),(3840,2160),(960,540)):
            g = board_geometry(size)
            footer=round(48*max(.75,min(size)/1080))
            self.assertLessEqual(g["top"]+g["headings"]+g["row_height"]*g["capacity"]+g["meta"]+footer,size[1])

    def test_invalid_cache_retains_last_good_entries_but_valid_empty_clears(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"api_data.json"
            path.write_text(json.dumps(dict(data=[slot("saved", screen_number=1)])))
            board=InformationBoard(path)
            board.read(0)
            path.write_text("{")
            board.read(2)
            self.assertEqual(board.page(1000,2,(1920,1080))["rows"][0]["paper"],"saved")
            self.assertIn("saved entries",board.notice)
            self.assertEqual(board.page(2000,3,(1920,1080))["rows"][0]["paper"],"saved")
            path.write_text('{"data":[]}')
            board.read(4)
            self.assertEqual(board.records,[])
            self.assertEqual(board.page(2001,4,(1920,1080))["rows"],[])
