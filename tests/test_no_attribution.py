"""The commit-msg hook and the pr-text workflow refuse Claude attribution (.githooks/no-attribution)."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / ".githooks" / "no-attribution"
SH = shutil.which("sh")


@unittest.skipUnless(SH, "needs sh (Git for Windows ships one)")
class NoAttribution(unittest.TestCase):
    def check(self, text: str) -> int:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(text)
        return subprocess.run([SH, str(SCRIPT), f.name], capture_output=True).returncode

    def test_refuses_attribution(self):
        for line in ("Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
                     "Co-authored-by: Claude <x@y.z>",
                     "Claude-Session: https://claude.ai/code/session_01ABC",
                     "https://claude.ai/code/session_01TDEscanYngXKnqsyrLPcwq",
                     "🤖 Generated with [Claude Code](https://claude.com/claude-code)"):
            self.assertEqual(self.check(f"Add a thing\n\n{line}\n"), 1, line)

    def test_allows_ordinary_text(self):
        self.assertEqual(self.check("Update CLAUDE.md pacing\n\nClaude confirms on Robinhood.\n"
                                    "Co-authored-by: A Person <person@example.com>\n"), 0)
        self.assertEqual(self.check("Fix it\n# Co-Authored-By: Claude <noreply@anthropic.com>\n"), 0)  # git comment


if __name__ == "__main__":
    unittest.main()
