"""README facts that mirror the code or config. Runs in the pre-commit hook, so a change that makes the README
stale fails the commit; fix the README (or the check) in the same commit. The README describes the defaults in
templates/private/guardrails.toml, not anyone's private copy."""
import json
import re
import unittest
from pathlib import Path

from rhgex import dailyloss, exits, guardrails, lock, paths, sizing

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
CLAUDE_MD = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")


def table_row(label: str) -> str:
    m = re.search(rf"^\| {re.escape(label)} \|(.*)\|$", README, re.M)
    if not m:
        raise AssertionError(f"README limits table has no '{label}' row")
    return m.group(1)


def subcommands() -> set[str]:
    return set(re.findall(r'sub\.add_parser\("(\w+)"', (ROOT / "rhgex" / "__init__.py").read_text(encoding="utf-8")))


TEMPLATE_GUARDRAILS = guardrails.load(paths.TEMPLATE / "guardrails.toml")


class LimitsTable(unittest.TestCase):
    lim = TEMPLATE_GUARDRAILS["limits"]

    def assertPct(self, label, pct, before="≤ "):
        self.assertIn(f"{before}{pct:g}%", table_row(label), f"'{label}' row should say {before}{pct:g}%")

    def test_stock_order(self):
        self.assertPct("Stock order", self.lim["max_order_pct"])

    def test_options(self):
        self.assertPct("Options", self.lim["max_option_premium_pct"])
        self.assertIn(f"≥ {self.lim['min_option_dte']} days to expiry", table_row("Options"))

    def test_per_day(self):
        row = table_row("Per day")
        self.assertIn(f"≤ {self.lim['max_new_positions_per_day']} new positions", row)
        self.assertIn(f"≤ {self.lim['max_daily_deployed_pct']:g}% of the account deployed", row)

    def test_daily_loss(self):
        self.assertPct("Daily loss stop", self.lim["max_daily_loss_pct"], before="")

    def test_drawdown(self):
        pct = self.lim.get("max_drawdown_pct", dailyloss.DEFAULT_DRAWDOWN_PCT)
        self.assertPct("Drawdown pause", pct, before="")

    def test_blocked_symbols(self):
        listed = set(re.findall(r"\b[A-Z]{2,5}\b", table_row("Blocked both ways")))
        configured = {s for b in TEMPLATE_GUARDRAILS.get("blocked", []) for s in b["symbols"]}
        self.assertEqual(listed, configured)


class CommandsExist(unittest.TestCase):
    def test_readme_commands(self):
        self.assertEqual(set(re.findall(r"\brhgex (\w+)", README)) - subcommands(), set())

    def test_claude_md_commands(self):
        self.assertEqual(set(re.findall(r"\brhgex (\w+)", CLAUDE_MD)) - subcommands(), set())

    def test_readme_tool_examples_name_real_subcommands(self):
        self.assertEqual(set(re.findall(r"-m rhgex (\w+)", README)) - subcommands(), set())


class RepoLayout(unittest.TestCase):
    def test_every_module_listed(self):
        tree = README.split("## Repo layout", 1)[1].split("```", 2)[1]
        listed = set(re.findall(r"([a-z_]+\.py)\b", tree.split("rhgex/", 1)[1].split("templates/", 1)[0]))
        actual = {p.name for p in (ROOT / "rhgex").glob("*.py")} - {"__main__.py"}
        self.assertEqual(listed, actual)

    def test_deny_list_matches(self):
        perms = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]
        deny, ask = perms["deny"], perms.get("ask", [])
        denied = {Path(m).name for d in deny for m in re.findall(r"Edit\(\./rhgex/([\w.]+)\)", d)}
        line = re.search(r"Claude can't edit the hook code \(([^)]*)\),\s+`([^`]+)` or `([^`]+)`", README)
        self.assertIsNotNone(line, "README should list what Claude can't edit")
        self.assertEqual({Path(f).name for f in re.findall(r"`([\w./]+\.py)`", line.group(1))}, denied)
        for path in (line.group(2), line.group(3)):
            self.assertTrue(any(f"Edit(./{path}" in d for d in deny), f"{path} isn't on the deny list")
        limits = re.search(r"Editing your limits\s+\(`([^`]+)`\) asks you first", README)
        self.assertIsNotNone(limits, "README should say Claude asks before editing the limits")
        self.assertIn(f"Edit(./{limits.group(1)})", ask)
        self.assertFalse(any(limits.group(1) in d for d in deny), "the limits are on the ask list, not deny")


class ExitAndSizingFacts(unittest.TestCase):
    def test_exit_signals(self):
        code = set(re.findall(r'out\.append\("([A-Z_0-9]+)"\)', (ROOT / "rhgex" / "exits.py").read_text(encoding="utf-8")))
        code.discard("NO_PRICE")
        for sig in code:
            self.assertIn(sig, README)

    def test_expiry_days(self):
        words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
        self.assertIn(f"closes options {words[exits.EXPIRY_EXIT_DAYS]} days before expiry", README)

    def test_risk_per_trade(self):
        self.assertEqual(sizing.OPTION_RISK_PCT, sizing.SHARE_RISK_PCT)
        self.assertIn(f"**{sizing.OPTION_RISK_PCT:g}% of the account**", README)

    def test_lock_hours(self):
        self.assertIn(f"under {lock.STALE_HOURS} hours old", README)


if __name__ == "__main__":
    unittest.main()
