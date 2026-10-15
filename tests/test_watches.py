import tempfile
import unittest
from datetime import date
from pathlib import Path

from rhgex import watches

TODAY = date(2026, 10, 14)  # Wednesday


class Watches(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "watches.json"

    def test_default_until_is_two_trading_days(self):
        w = watches.add("spx", "above", 7720, "bottom confirm", today=date(2026, 10, 15), path=self.path)
        self.assertEqual((w["symbol"], w["until"]), ("SPX", "2026-10-19"))  # Thu -> Mon

    def test_triggers_each_side(self):
        watches.add("SPX", "above", 7720, "reclaim", today=TODAY, path=self.path)
        watches.add("NVDA", "below", 220, "lose 220", today=TODAY, path=self.path)
        got = {r["symbol"]: r["state"] for r in watches.check({"SPX": 7725, "nvda": 221}, TODAY, self.path)}
        self.assertEqual(got, {"SPX": "TRIGGERED", "NVDA": "WAITING"})
        got = {r["symbol"]: r["state"] for r in watches.check({"SPX": 7700}, TODAY, self.path)}
        self.assertEqual(got, {"SPX": "WAITING", "NVDA": "NO_PRICE"})

    def test_expired_watches_close(self):
        watches.add("META", "above", 750, "reclaim", until="2026-10-14", today=TODAY, path=self.path)
        self.assertEqual(watches.check({"META": 760}, date(2026, 10, 15), self.path)[0]["state"], "EXPIRED")
        self.assertEqual(watches.check({"META": 760}, date(2026, 10, 15), self.path), [])

    def test_new_trigger_replaces_old_and_close(self):
        watches.add("NVDA", "above", 222, "bounce", today=TODAY, path=self.path)
        watches.add("NVDA", "above", 225, "reclaim", today=TODAY, path=self.path)
        self.assertEqual([w["level"] for w in watches.open_watches(watches.load(self.path))], [225])
        watches.close("NVDA", "entered", path=self.path)
        self.assertEqual(watches.open_watches(watches.load(self.path)), [])
        with self.assertRaises(ValueError):
            watches.close("NVDA", "again", path=self.path)

    def test_validation(self):
        with self.assertRaises(ValueError):
            watches.add("X", "near", 1, "", today=TODAY, path=self.path)
        with self.assertRaises(ValueError):
            watches.add("X", "above", 1, "", until="2026-10-01", today=TODAY, path=self.path)


if __name__ == "__main__":
    unittest.main()
