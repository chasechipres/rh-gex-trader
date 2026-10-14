import unittest

from rhgex import dailyloss

T = "2026-10-14"


class Record(unittest.TestCase):
    def test_first_value_of_the_day_is_the_start(self):
        rec = dailyloss.record(None, 1400.0, T, "07:00")
        self.assertEqual((rec["start_value"], rec["total_value"]), (1400.0, 1400.0))
        rec = dailyloss.record(rec, 1300.0, T, "09:00")
        self.assertEqual((rec["start_value"], rec["total_value"]), (1400.0, 1300.0))

    def test_new_day_resets_the_start(self):
        rec = dailyloss.record({"date": "2026-10-13", "total_value": 1100.0, "start_value": 1400.0}, 1100.0, T, "07:00")
        self.assertEqual(rec["start_value"], 1100.0)

    def test_record_without_start_value_adopts_current(self):
        rec = dailyloss.record({"date": T, "total_value": 999.0}, 1000.0, T, "09:00")
        self.assertEqual(rec["start_value"], 1000.0)


class Peak(unittest.TestCase):
    def test_peak_carries_across_days_and_only_rises(self):
        rec = dailyloss.record(None, 1400.0, "2026-10-13", "09:00")
        rec = dailyloss.record(rec, 2000.0, "2026-10-14", "09:00")
        rec = dailyloss.record(rec, 1500.0, "2026-10-15", "09:00")
        self.assertEqual((rec["peak_value"], rec["start_value"]), (2000.0, 1500.0))

    def test_drawdown_pause(self):
        rec = {"date": T, "total_value": 1400, "start_value": 1400, "peak_value": 2000}  # -30%, 0% today
        ok, reason = dailyloss.check(rec, T, drawdown_pct=30)
        self.assertFalse(ok)
        self.assertIn("drawdown pause", reason)
        self.assertTrue(dailyloss.check({**rec, "total_value": 1401, "start_value": 1401}, T, drawdown_pct=30)[0])

    def test_reset_peak_resumes(self):
        rec = dailyloss.reset_peak({"date": T, "total_value": 1400, "start_value": 1400, "peak_value": 2000})
        self.assertEqual(rec["peak_value"], 1400)
        self.assertTrue(dailyloss.check(rec, T, drawdown_pct=30)[0])


class Check(unittest.TestCase):
    def rec(self, start, now, day=T):
        return {"date": day, "total_value": now, "start_value": start}

    def test_under_the_limit_is_ok(self):
        self.assertTrue(dailyloss.check(self.rec(1000, 801), T)[0])

    def test_at_the_limit_blocks(self):
        ok, reason = dailyloss.check(self.rec(1000, 800), T)
        self.assertFalse(ok)
        self.assertIn("down 20.0%", reason)

    def test_custom_pct(self):
        self.assertFalse(dailyloss.check(self.rec(1000, 890), T, pct=10)[0])

    def test_gains_are_ok(self):
        self.assertTrue(dailyloss.check(self.rec(1000, 1500), T)[0])

    def test_stale_or_missing_record_is_not_this_checks_job(self):
        self.assertTrue(dailyloss.check(None, T)[0])
        self.assertTrue(dailyloss.check(self.rec(1000, 500, day="2026-10-13"), T)[0])
        self.assertTrue(dailyloss.check({"date": T, "total_value": 500}, T)[0])


if __name__ == "__main__":
    unittest.main()
