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

    def test_five_minute_window_and_expiry_are_exact(self):
        board = InformationBoard("/unused")
        board.records = directory_records(dict(data=[
            slot("expired", end=1000, screen_number=1),
            slot("running", screen_number=2),
            slot("upcoming", start=1300, screen_number=3),
            slot("too soon", start=1301, screen_number=4)]))
        rows = board.page(1000, 0, (1920,1080))["rows"]
        self.assertEqual([(r["paper"], r["status"]) for r in rows],
                         [("running","Presenting"), ("upcoming","Starts in 5 min")])
        rows = board.page(1240, 1, (1920,1080))["rows"]
        self.assertEqual(rows[1]["status"], "Starts in 1 min")
        rows = board.page(1300, 2, (1920,1080))["rows"]
        self.assertEqual(rows[1]["status"], "Presenting")

    def test_pages_wrap_fill_and_single_page_never_duplicates(self):
        board = InformationBoard("/unused")
        geometry = dict(capacity=10, top=100, headings=40, meta=40, row_height=80)
        with patch("helper.information_board.board_geometry", return_value=geometry):
            for count in (0, 5, 10, 25):
                board.records = directory_records(dict(data=[slot(str(i), screen_number=i) for i in range(count)]))
                pages = [board.page(1000, t, (1920,1080)) for t in (0,6,12,18)]
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
            self.assertEqual(board.page(2000,3,(1920,1080))["rows"],[])
            path.write_text('{"data":[]}')
            board.read(4)
            self.assertEqual(board.records,[])
