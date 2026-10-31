import tempfile
import unittest
from datetime import date
from pathlib import Path

from rhgex import calls

POST = "https://x.com/Han_Akamatsu/status/111"
D = date.fromisoformat


class Calls(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "calls.json"

    def add(self, **kw):
        base = dict(symbol="qqq", direction="bearish", setup="breakdown", level=738, target=727, invalid=742,
                    source=POST, posted="2026-10-14", path=self.path)
        return calls.add(**{**base, **kw})

    def test_add_defaults_and_validation(self):
        c = self.add()
        self.assertEqual((c["symbol"], c["by"], c["result"]), ("QQQ", "2026-10-21", "open"))  # 5 trading days
        with self.assertRaises(ValueError):  # same post, same symbol
            self.add()
        with self.assertRaises(ValueError):
            self.add(symbol="ORCL", invalid=700)  # bearish invalidation below the target
        with self.assertRaises(ValueError):
            self.add(symbol="ORCL", setup="vibes")

    def test_atr_invalidation_when_he_names_none(self):
        self.assertEqual(self.add()["invalid_from"], "his")
        c = self.add(symbol="ASTS", direction="bullish", setup="downtrend-dip", level=40, target=45, invalid=None,
                     atr=4.51)
        self.assertEqual((c["invalid"], c["invalid_from"]), (37.74, "atr"))  # 40 - 2.255, half an ATR under his level
        c = self.add(symbol="CRWV", level=63, target=60, invalid=None, atr=4.0)  # bearish: above it
        self.assertEqual((c["invalid"], c["invalid_from"]), (65.0, "atr"))
        with self.assertRaises(ValueError):
            self.add(symbol="SMCI", invalid=None)  # no ATR to compute it from
        with self.assertRaisesRegex(ValueError, "ATR couldn't be fetched"):  # Yahoo's NaN ATR, not a target error
            self.add(symbol="SMCI", invalid=None, atr=float("nan"))

    def test_both_sides_of_a_pivot_from_one_post(self):
        # "hold 162 for 170, lose it for 155": one bullish and one bearish call from the same post
        bull = self.add(symbol="NBIS", direction="bullish", setup="uptrend-dip", level=162, target=170, invalid=158,
                        trigger=("above", 162.5))
        bear = self.add(symbol="NBIS", level=162, target=155, invalid=165, trigger=("below", 161.5))
        self.assertEqual((bull["direction"], bear["direction"]), ("bullish", "bearish"))
        with self.assertRaisesRegex(ValueError, "already logged"):  # a true repeat is still refused
            self.add(symbol="NBIS", level=162, target=155, invalid=165, trigger=("below", 161.5))

    def test_score(self):
        c = self.add()
        self.assertEqual(calls.score(c, [(D("2026-10-14"), 740, 726.4)], D("2026-10-14")), ("hit", "2026-10-14"))
        self.assertEqual(calls.score(c, [(D("2026-10-14"), 743, 730)], D("2026-10-14")), ("fail", "2026-10-14"))
        self.assertEqual(calls.score(c, [(D("2026-10-14"), 743, 726)], D("2026-10-14"))[0], "fail")  # both: fail
        self.assertEqual(calls.score(c, [(D("2026-10-14"), 740, 730)], D("2026-10-15")), ("open", None))
        self.assertEqual(calls.score(c, [(D("2026-10-22"), 740, 700)], D("2026-10-22")), ("expired", "2026-10-21"))
        self.assertEqual(calls.score(c, [(D("2026-10-13"), 800, 700)], D("2026-10-14"))[0], "open")  # before post

    def test_conditional_call_scores_after_its_trigger(self):
        # "lose 723 and it's 716", invalid back above 727: nothing counts until a session trades below 723
        c = self.add(symbol="NOK", level=723, target=716, invalid=727, trigger=("below", 723))
        quiet = [(D("2026-10-14"), 726.9, 724), (D("2026-10-15"), 726.5, 723.5)]
        self.assertEqual(calls.score(c, quiet, D("2026-10-15")), ("open", None))                 # 727 never counts
        self.assertEqual(calls.score(c, quiet, D("2026-10-22")), ("not_triggered", "2026-10-21"))
        broke = [(D("2026-10-14"), 726, 722.5), (D("2026-10-15"), 723, 715.8)]
        self.assertEqual(calls.score(c, broke, D("2026-10-15")), ("hit", "2026-10-15"))
        with self.assertRaises(ValueError):  # the trigger must sit between the invalidation and the target
            self.add(symbol="AMD", target=716, invalid=727, trigger=("below", 730))

    def test_gex_targets_are_tracked_apart(self):
        # he named 162 and "higher" but no target: the call wall at 170 stands in, marked as ours
        c = self.add(symbol="NBIS", direction="bullish", setup="uptrend-dip", level=162, target=170, invalid=158,
                     target_from="gex")
        self.assertEqual((c["target_from"], self.add(symbol="ASTS", direction="bullish", setup="uptrend-dip",
                          level=40, target=45, invalid=38)["target_from"]), ("gex", "his"))
        with self.assertRaises(ValueError):
            self.add(symbol="HOOD", target_from="vibes")
        s = calls.stats([c | {"result": "hit"}, {"setup": "uptrend-dip", "direction": "bullish", "result": "fail"}])
        self.assertEqual((s["target: gex"]["hit"], s["target: gex"]["hit_rate"], s["uptrend-dip"]["hit_rate"]),
                         (1, 1.0, 0.5))

    def test_not_triggered_is_left_out_of_the_rate(self):
        s = calls.stats([{"setup": "breakout", "direction": "bullish", "result": r}
                         for r in ("hit", "fail", "not_triggered", "not_triggered")])
        self.assertEqual((s["breakout"]["hit_rate"], s["breakout"]["not_triggered"]), (0.5, 2))

    def test_post_time_scores_the_post_day_from_the_post_on(self):
        c = self.add(symbol="INTC", direction="bearish", setup="breakdown", level=110, target=105, invalid=111.5,
                     posted="2026-10-08 08:45", by="2026-10-16")
        self.assertEqual(c["posted_at"], "2026-10-08T08:45")
        day = [(D("2026-10-08"), 111.6, 105.24)]  # the 111.6 high came before the post
        self.assertEqual(calls.score(c, day, D("2026-10-08"), post_day=(109.72, 104.9)), ("hit", "2026-10-08"))
        self.assertEqual(calls.score(c, day, D("2026-10-08"), post_day=None), ("open", None))  # no bars: skip the day
        later = day + [(D("2026-10-09"), 107, 104)]
        self.assertEqual(calls.score(c, later, D("2026-10-09")), ("hit", "2026-10-09"))

    def test_posted_defaults_to_now_and_a_date_alone_has_no_time(self):
        self.assertIn("posted_at", self.add(symbol="A", posted=None))
        self.assertNotIn("posted_at", self.add(symbol="B"))

    def test_check_passes_the_post_day_range(self):
        self.add(symbol="INTC", direction="bearish", setup="breakdown", level=110, target=105, invalid=111.5,
                 posted="2026-10-08 08:45")
        seen = []
        changed = calls.check(D("2026-10-08"), self.path, bars=lambda s, start: [(D("2026-10-08"), 111.6, 105.24)],
                              after=lambda s, at: seen.append(at) or (109.72, 104.9))
        self.assertEqual(([c["result"] for c in changed], seen), (["hit"], ["2026-10-08T08:45"]))

    def test_check_and_stats(self):
        self.add()
        self.add(symbol="ASTS", direction="bullish", setup="downtrend-dip", level=42, target=45, invalid=40)
        self.add(symbol="HOOD", direction="bullish", setup="uptrend-dip", level=105, target=110, invalid=100)
        bars = {"QQQ": [(D("2026-10-14"), 740, 726)], "ASTS": [(D("2026-10-15"), 43, 39.5)], "HOOD": []}
        changed = calls.check(D("2026-10-15"), self.path, bars=lambda s, start: bars[s])
        self.assertEqual({c["symbol"]: c["result"] for c in changed}, {"QQQ": "hit", "ASTS": "fail"})
        self.assertEqual(calls.check(D("2026-10-15"), self.path, bars=lambda s, start: bars[s]), [])  # resolved stay
        s = calls.stats(calls.load(self.path))
        self.assertEqual(s["breakdown"]["hit_rate"], 1.0)
        self.assertEqual(s["downtrend-dip"]["hit_rate"], 0.0)
        self.assertEqual((s["uptrend-dip"]["open"], s["uptrend-dip"]["hit_rate"]), (1, None))
        self.assertEqual(s["all bullish"]["fail"], 1)


if __name__ == "__main__":
    unittest.main()
