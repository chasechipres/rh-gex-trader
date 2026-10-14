import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import rhgex
from rhgex import check_source

SAVED = "https://x.com/Han_Akamatsu/status/2110049496042258673"


class CheckSource(unittest.TestCase):
    def setUp(self):
        self.posts = Path(tempfile.mkdtemp())
        (self.posts / "2026-10-13-0946-orcl.md").write_text(f"- Link: {SAVED} (Oct 13 09:46 PT)\n", encoding="utf-8")

    def check(self, action, source):
        check_source(action, source, self.posts)

    def test_saved_post_passes(self):
        self.check("trade", SAVED)

    def test_unsaved_post_refused(self):
        with self.assertRaisesRegex(ValueError, "2109671468208640366"):
            self.check("skip", "https://x.com/Han_Akamatsu/status/2109671468208640366")

    def test_every_linked_post_must_be_saved(self):
        with self.assertRaises(ValueError):
            self.check("watch", f"{SAVED} and https://x.com/Han_Akamatsu/status/1")

    def test_decisions_need_a_post_link(self):
        for source in ("", "own research"):
            with self.assertRaisesRegex(ValueError, "must link"):
                self.check("trade", source)

    def test_exits_may_omit_the_source(self):
        self.check("exit", "")


class TradeType(unittest.TestCase):
    def setUp(self):
        self.logs = Path(tempfile.mkdtemp())
        mock.patch.object(rhgex, "LOG_DIR", self.logs).start()
        mock.patch.object(rhgex, "check_source", lambda *a, **k: None).start()
        mock.patch.object(rhgex, "out", lambda *a, **k: None).start()
        self.addCleanup(mock.patch.stopall)

    def journal(self, action, type_=None):
        rhgex.cmd_journal(argparse.Namespace(symbol="nvda", action=action, thesis="t", confidence=0.6,
                                             source=SAVED, type=type_, pnl=None, pnl_pct=None))

    def test_trade_needs_type(self):
        with self.assertRaisesRegex(SystemExit, "--type"):
            self.journal("trade")
        self.assertFalse((self.logs / "journal.jsonl").exists())

    def test_trade_records_type(self):
        self.journal("trade", "spread")
        self.assertEqual(json.loads((self.logs / "journal.jsonl").read_text())["type"], "spread")

    def test_other_actions_skip_type(self):
        self.journal("watch")
        self.assertNotIn("type", json.loads((self.logs / "journal.jsonl").read_text()))


if __name__ == "__main__":
    unittest.main()
