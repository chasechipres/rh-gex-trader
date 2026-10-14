import tempfile
import unittest
from datetime import date
from pathlib import Path

from rhgex import washlog


class WashLog(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "wash_sales.jsonl"

    def test_window_is_30_days_each_side(self):
        e = washlog.add("$arm", 12.5, "2026-10-08", "option", "ARM 2026-10-23 275P", path=self.path)
        self.assertEqual(e["symbol"], "ARM")
        self.assertEqual(e["window_start"], "2026-09-08")
        self.assertEqual(e["window_end"], "2026-11-07")

    def test_active_through_window_end(self):
        washlog.add("ARM", 12.5, "2026-10-08", path=self.path)
        self.assertEqual(len(washlog.active(date(2026, 11, 7), self.path)), 1)
        self.assertEqual(washlog.active(date(2026, 11, 8), self.path), [])
        self.assertEqual(len(washlog.load(self.path)), 1)  # ended windows stay in the record

    def test_gain_refused(self):
        with self.assertRaises(ValueError):
            washlog.add("ARM", 0, path=self.path)
        with self.assertRaises(ValueError):
            washlog.add("ARM", -5, path=self.path)

    def test_warning_uses_latest_window(self):
        washlog.add("KTOS", 3, "2026-10-20", path=self.path)
        washlog.add("KTOS", 4, "2026-10-08", path=self.path)
        w = washlog.warnings(date(2026, 10, 21), self.path)
        self.assertIn("2026-11-19", w["KTOS"])

    def test_empty_log(self):
        self.assertEqual(washlog.active(path=self.path), [])
        self.assertEqual(washlog.warnings(path=self.path), {})


if __name__ == "__main__":
    unittest.main()
