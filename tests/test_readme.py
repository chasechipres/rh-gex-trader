"""Doc facts that mirror the code or config (README.md, docs/*.md and CONTRIBUTING.md, checked as one text). Runs in
the pre-commit hook, so a change that makes the docs stale fails the commit; fix the docs (or the check) in the same
commit. The docs describe the defaults in templates/private/guardrails.toml, not anyone's private copy."""
import json
import re
import unittest
from pathlib import Path

from rhgex import dailyloss, exits, guardrails, lock, paths, sizing

ROOT = Path(__file__).resolve().parent.parent
DOC_FILES = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", *sorted((ROOT / "docs").glob("*.md"))]
DOCS = "\n".join(f.read_text(encoding="utf-8") for f in DOC_FILES)
CLAUDE_MD = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")


def table_row(label: str) -> str:
    m = re.search(rf"^\| {re.escape(label)} \|(.*)\|$", DOCS, re.M)
    if not m:
        raise AssertionError(f"docs limits table has no '{label}' row")
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
        self.assertEqual(set(re.findall(r"\brhgex (\w+)", DOCS)) - subcommands(), set())

    def test_claude_md_commands(self):
        self.assertEqual(set(re.findall(r"\brhgex (\w+)", CLAUDE_MD)) - subcommands(), set())

    def test_readme_tool_examples_name_real_subcommands(self):
        self.assertEqual(set(re.findall(r"-m rhgex (\w+)", DOCS)) - subcommands(), set())


class RepoLayout(unittest.TestCase):
    def test_every_module_listed(self):
        tree = DOCS.split("## Repo layout", 1)[1].split("```", 2)[1]
        listed = set(re.findall(r"([a-z_]+\.py)\b", tree.split("rhgex/", 1)[1].split("templates/", 1)[0]))
        actual = {p.name for p in (ROOT / "rhgex").glob("*.py")} - {"__main__.py"}
        self.assertEqual(listed, actual)

    def test_permission_lists_match(self):
        perms = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]
        deny, ask = perms["deny"], perms.get("ask", [])
        denied = re.search(r"Claude can't edit `([^`]+)`: it's on its deny list", DOCS)
        self.assertIsNotNone(denied, "docs should say what Claude can't edit")
        self.assertTrue(any(f"Edit(./{denied.group(1)}" in d for d in deny), f"{denied.group(1)} isn't denied")
        asks = re.search(r"Editing the hook\s+code \(([^)]*)\), your limits\s+\(`([^`]+)`\) or `([^`]+)` asks you first",
                         DOCS)
        self.assertIsNotNone(asks, "docs should say Claude asks before editing the hook code, limits and settings")
        hook_files = {Path(f).name for f in re.findall(r"`([\w./]+\.py)`", asks.group(1))}
        asked_code = {Path(m).name for a in ask for m in re.findall(r"Edit\(\./rhgex/([\w.]+)\)", a)}
        self.assertEqual(hook_files, asked_code)
        for path in [f"rhgex/{f}" for f in hook_files] + [asks.group(2), asks.group(3)]:
            self.assertIn(f"Edit(./{path})", ask)
            self.assertFalse(any(path in d for d in deny), f"{path} is on the ask list, not deny")


class ExitAndSizingFacts(unittest.TestCase):
    def test_exit_signals(self):
        code = set(re.findall(r'out\.append\("([A-Z_0-9]+)"\)', (ROOT / "rhgex" / "exits.py").read_text(encoding="utf-8")))
        code.discard("NO_PRICE")
        for sig in code:
            self.assertIn(sig, DOCS)

    def test_expiry_days(self):
        words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
        self.assertIn(f"closes options {words[exits.EXPIRY_EXIT_DAYS]} days before expiry", DOCS)

    def test_risk_per_trade(self):
        self.assertEqual(sizing.OPTION_RISK_PCT, sizing.SHARE_RISK_PCT)
        self.assertIn(f"**{sizing.OPTION_RISK_PCT:g}% of the account**", DOCS)

    def test_lock_hours(self):
        self.assertIn(f"under {lock.STALE_HOURS} hours old", DOCS)


if __name__ == "__main__":
    unittest.main()
