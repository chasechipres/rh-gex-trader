import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from rhgex import lock

NOW = datetime(2026, 10, 14, 7, 13)


class Lock(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "session.lock"

    def test_acquire_and_release(self):
        lock.acquire(self.path, "pc", NOW)
        self.assertEqual(lock.read(self.path)["machine"], "pc")
        self.assertTrue(lock.release(self.path, "pc")["released"])
        self.assertIsNone(lock.read(self.path))

    def test_other_machine_blocked_while_fresh(self):
        lock.acquire(self.path, "pc", NOW)
        with self.assertRaisesRegex(ValueError, "pc holds the session lock"):
            lock.acquire(self.path, "mac", NOW + timedelta(minutes=150))
        self.assertEqual(lock.acquire(self.path, "mac", NOW + timedelta(hours=3))["machine"], "mac")  # stale

    def test_same_machine_refreshes(self):
        lock.acquire(self.path, "pc", NOW)
        self.assertEqual(lock.acquire(self.path, "pc", NOW + timedelta(minutes=5))["time"], "2026-10-14T07:18:00")

    def test_release_leaves_another_machines_lock(self):
        lock.acquire(self.path, "pc", NOW)
        self.assertEqual(lock.release(self.path, "mac"), {"released": False, "held_by": "pc"})
        self.assertEqual(lock.read(self.path)["machine"], "pc")


if __name__ == "__main__":
    unittest.main()
