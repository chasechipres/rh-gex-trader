import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rhgex import guardrails, hook, init, paths

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, env=init.clean_env())


class Base(unittest.TestCase):
    def setUp(self):
        # Run inside a git hook (pre-commit runs these tests), git's GIT_DIR / GIT_INDEX_FILE would aim every
        # command here at the real repo. Tests use only temp repos.
        mock.patch.dict(os.environ, {**init.clean_env(), **GIT_ENV}, clear=True).start()
        self.addCleanup(mock.patch.stopall)
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.private = self.root / "private"
        self.template = paths.TEMPLATE

    def init(self, **kw):
        return init.init(root=self.root, private=self.private, template=self.template, **kw)


class NewPrivateFolder(Base):
    def test_creates_every_template_file_and_a_git_repo(self):
        res = self.init()
        for rel in ("CLAUDE.md", "guardrails.toml", "README.md", ".gitignore", "notes/insights.md"):
            self.assertTrue((self.private / rel).exists(), rel)
        st = res["status"]
        self.assertTrue(st["git_repo"] and st["guardrails"])
        self.assertEqual(st["missing_template_files"], [])
        self.assertIn("local only", st["sync"])

    def test_rerun_never_overwrites(self):
        self.init()
        (self.private / "guardrails.toml").write_text("[limits]\nmax_order_pct = 1\n")
        res = self.init()
        self.assertEqual(res["created"], [])
        self.assertIn("max_order_pct = 1", (self.private / "guardrails.toml").read_text())

    def test_reports_limits_added_to_the_template_later(self):
        self.init()
        (self.private / "guardrails.toml").write_text("[limits]\nmax_order_pct = 1\n")
        self.assertIn("max_drawdown_pct", init.status(self.private, self.template)["new_limits_to_add"])

    def test_template_guardrails_load_and_cover_every_limit_the_code_reads(self):
        lim = guardrails.load(self.template / "guardrails.toml")["limits"]
        for key in ("max_order_pct", "max_option_premium_pct", "max_daily_deployed_pct", "max_daily_loss_pct",
                    "max_drawdown_pct", "min_option_dte", "max_new_positions_per_day", "require_limit_orders"):
            self.assertIn(key, lim)

    def test_account_values_carried_over(self):
        (self.root / "state").mkdir()
        (self.root / "state" / "account.json").write_text('{"X": {}}')
        self.init()
        self.assertEqual((self.private / "state" / "account.json").read_text(), '{"X": {}}')

    def test_account_values_stay_out_of_git(self):
        (self.root / "state").mkdir()
        (self.root / "state" / "account.json").write_text("{}")
        self.init()
        tracked = subprocess.run(["git", "ls-files"], cwd=self.private, capture_output=True, text=True).stdout
        self.assertNotIn("account.json", tracked)


class Migrate(Base):
    def test_copies_files_from_disk(self):
        (self.root / "notes" / "posts").mkdir(parents=True)
        (self.root / "notes" / "posts" / "a.md").write_text("post")
        (self.root / "guardrails.toml").write_text("[limits]\nmax_order_pct = 9\n")
        res = self.init(migrate=True)
        self.assertIn("notes/posts/a.md", res["migrated"])
        self.assertIn("max_order_pct = 9", (self.private / "guardrails.toml").read_text())

    def test_replaces_an_untouched_template_but_never_an_edited_file(self):
        self.init()  # plain init first: template guardrails and insights
        (self.private / "notes" / "insights.md").write_text("my edits")
        (self.root / "guardrails.toml").write_text("[limits]\nmax_order_pct = 9\n")
        (self.root / "notes").mkdir()
        (self.root / "notes" / "insights.md").write_text("old insights")
        self.init(migrate=True)
        self.assertIn("max_order_pct = 9", (self.private / "guardrails.toml").read_text())
        self.assertEqual((self.private / "notes" / "insights.md").read_text(), "my edits")

    def test_merge_commit_recovers_main_s_file_not_a_side_branch_s(self):
        run("git", "init", "-q", "-b", "main", cwd=self.root)
        (self.root / "state").mkdir()
        (self.root / "state" / "plans.json").write_text('[{"symbol": "REAL"}]')
        run("git", "add", "-A", cwd=self.root)
        run("git", "commit", "-q", "-m", "real", cwd=self.root)
        run("git", "checkout", "-q", "-b", "split", cwd=self.root)
        (self.root / "state" / "plans.json").write_text('[{"symbol": "FAKE"}]')
        run("git", "commit", "-q", "-am", "junk", cwd=self.root)
        run("git", "rm", "-q", "state/plans.json", cwd=self.root)
        run("git", "commit", "-q", "-m", "split", cwd=self.root)
        run("git", "checkout", "-q", "main", cwd=self.root)
        run("git", "merge", "-q", "--no-ff", "-m", "merge split", "split", cwd=self.root)
        self.init(migrate=True)
        self.assertEqual(json.loads((self.private / "state" / "plans.json").read_text()), [{"symbol": "REAL"}])

    def test_fills_the_private_readme_track_record(self):
        (self.root / "logs").mkdir()
        (self.root / "logs" / "journal.jsonl").write_text(
            '{"time": "2026-10-10T10:00:00", "symbol": "NKE", "action": "trade", "confidence": 0.7}\n'
            '{"time": "2026-10-12T10:00:00", "symbol": "NKE", "action": "exit", "confidence": 1, "pnl": 12.5, "pnl_pct": 20}\n')
        (self.root / "state").mkdir()
        (self.root / "state" / "account.json").write_text(
            '{"X": {"date": "2026-10-12", "time": "15:00:00", "total_value": 1000.0}}')
        res = self.init(migrate=True)
        readme = (self.private / "README.md").read_text()
        self.assertEqual(res["track_record_account_value"], 1000.0)
        self.assertIn("$1,000.00", readme)
        self.assertIn("| 2026-10-12 | NKE | $12.50 | +20.0% |", readme)
        self.assertNotIn("No closed trades yet", readme)

    def test_recovers_files_a_pull_already_deleted(self):
        run("git", "init", "-q", "-b", "main", cwd=self.root)
        (self.root / "state").mkdir()
        (self.root / "state" / "plans.json").write_text('[{"symbol": "ORCL"}]')
        run("git", "add", "-A", cwd=self.root)
        run("git", "commit", "-q", "-m", "plans", cwd=self.root)
        run("git", "rm", "-q", "state/plans.json", cwd=self.root)
        run("git", "commit", "-q", "-m", "split", cwd=self.root)
        self.init(migrate=True)
        self.assertEqual(json.loads((self.private / "state" / "plans.json").read_text()), [{"symbol": "ORCL"}])

    def test_names_the_source_commit_and_from_overrides_it(self):
        # A file overwritten with bad data and then deleted on the same line (a rebase merge, or a migrate run
        # from the branch): auto picks the bad version, the report says so, and --from picks the right one.
        run("git", "init", "-q", "-b", "main", cwd=self.root)
        (self.root / "state").mkdir()
        (self.root / "state" / "plans.json").write_text('[{"symbol": "REAL"}]')
        run("git", "add", "-A", cwd=self.root)
        run("git", "commit", "-q", "-m", "real", cwd=self.root)
        run("git", "tag", "before-split", cwd=self.root)
        (self.root / "state" / "plans.json").write_text('[{"symbol": "FAKE"}]')
        run("git", "commit", "-q", "-am", "junk", cwd=self.root)
        run("git", "rm", "-q", "state/plans.json", cwd=self.root)
        run("git", "commit", "-q", "-m", "split", cwd=self.root)
        res = self.init(migrate=True)
        self.assertTrue(res["from_history"]["state/plans.json"].endswith(" junk"))

        other = self.root / "private2"
        res = init.init(root=self.root, private=other, template=self.template, migrate=True, rev="before-split")
        self.assertEqual(json.loads((other / "state" / "plans.json").read_text()), [{"symbol": "REAL"}])
        self.assertTrue(res["from_history"]["state/plans.json"].endswith(" real"))

    def test_from_an_unknown_commit_is_refused(self):
        run("git", "init", "-q", "-b", "main", cwd=self.root)
        with self.assertRaises(ValueError):
            self.init(migrate=True, rev="nope")


class UsernameDefault(Base):
    def test_clone_defaults_to_the_gh_login(self):
        with mock.patch.object(init, "gh_user", return_value="someone"):
            self.assertEqual(init.clone_url(init.AUTO), "https://github.com/someone/rh-gex-trader-private.git")

    def test_an_explicit_url_wins(self):
        self.assertEqual(init.clone_url("https://example.com/x.git"), "https://example.com/x.git")

    def test_gh_not_logged_in_asks_for_a_url(self):
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="not logged in")
        with mock.patch.object(init.subprocess, "run", return_value=failed), self.assertRaises(ValueError) as e:
            init.gh_user()
        self.assertIn("gh auth login", str(e.exception))

    def test_cli_flags_without_values_use_the_defaults(self):
        import rhgex
        seen = {}
        with mock.patch.object(rhgex, "cmd_init", lambda a: seen.update(vars(a))), \
                mock.patch("sys.argv", ["rhgex", "init", "--github"]):
            rhgex.main()
        self.assertEqual((seen["github"], seen["clone"]), (init.REPO_NAME, ""))
        with mock.patch("sys.argv", ["rhgex", "init", "--clone"]):
            parsed = {}
            with mock.patch.object(rhgex, "cmd_init", lambda a: parsed.update(vars(a))):
                rhgex.main()
        self.assertEqual(parsed["clone"], init.AUTO)


class Sync(Base):
    def test_local_only_commits(self):
        self.init()
        (self.private / "notes" / "posts" / "b.md").write_text("x")
        res = init.sync("t", private=self.private)
        self.assertEqual((res["committed"], res["remote"]), (True, "none (local only)"))

    def test_pushes_to_a_remote_and_a_second_machine_clones_it(self):
        bare = self.root / "remote.git"
        run("git", "init", "-q", "--bare", "-b", "main", str(bare), cwd=self.root)
        self.init()
        run("git", "remote", "add", "origin", str(bare), cwd=self.private)
        run("git", "push", "-q", "-u", "origin", "main", cwd=self.private)
        (self.private / "notes" / "posts" / "c.md").write_text("x")
        self.assertTrue(init.sync("t", private=self.private)["pushed"])

        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        init.init(clone=str(bare), root=other, private=other / "private", template=self.template)
        self.assertTrue((other / "private" / "notes" / "posts" / "c.md").exists())

    def test_refuses_without_private(self):
        with self.assertRaises(ValueError):
            init.sync("t", private=self.private)


class HookEnvironment(Base):
    def test_git_ignores_a_hook_s_repo_variables(self):
        decoy = self.root / "decoy"
        run("git", "init", "-q", str(decoy), cwd=self.root)
        with mock.patch.dict(os.environ, {"GIT_DIR": str(decoy / ".git"), "GIT_INDEX_FILE": str(decoy / ".git" / "index")}):
            self.init()
        self.assertTrue((self.private / ".git").exists())
        self.assertEqual(subprocess.run(["git", "log", "--oneline"], cwd=decoy, capture_output=True, text=True,
                                        env=init.clean_env()).stdout, "")

    def test_uses_git_s_own_list_of_repo_variables(self):
        listed = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True).stdout.split()
        self.assertTrue(set(listed) <= init.repo_env())

    def test_falls_back_to_the_built_in_list_without_git(self):
        init.repo_env.cache_clear()
        self.addCleanup(init.repo_env.cache_clear)
        with mock.patch.object(init.subprocess, "run", side_effect=FileNotFoundError):
            self.assertEqual(init.repo_env(), frozenset(init.REPO_ENV))


class FailClosed(unittest.TestCase):
    def test_missing_guardrails_names_the_fix(self):
        with self.assertRaises(FileNotFoundError) as e:
            guardrails.load(Path(tempfile.mkdtemp()) / "guardrails.toml")
        self.assertIn("rhgex init", str(e.exception))

    def test_hook_denies_orders_without_private(self):
        missing = Path(tempfile.mkdtemp()) / "guardrails.toml"
        event = {"tool_name": "mcp__robinhood-trading__place_equity_order",
                 "tool_input": {"account_number": "X", "symbol": "NKE", "side": "sell", "type": "limit",
                                "quantity": "1", "limit_price": "34"}}
        real_load, printed = guardrails.load, []
        with mock.patch.object(guardrails, "load", lambda: real_load(missing)), \
                mock.patch.object(hook.json, "load", return_value=event), \
                mock.patch("builtins.print", side_effect=lambda s: printed.append(json.loads(s))):
            hook.main("pre")
        out = printed[-1]["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("rhgex init", out["permissionDecisionReason"])

    def test_hook_post_records_nothing_without_private(self):
        missing = Path(tempfile.mkdtemp()) / "private"
        state = missing / "state"
        portfolio = {"tool_name": "mcp__robinhood-trading__get_portfolio", "tool_input": {"account_number": "X"},
                     "tool_response": {"data": {"total_value": "1000"}}}
        order = {"tool_name": "mcp__robinhood-trading__place_equity_order",
                 "tool_input": {"account_number": "X", "symbol": "NKE", "side": "sell", "type": "limit",
                                "quantity": "1", "limit_price": "34"}}
        with mock.patch.object(paths, "PRIVATE", missing),                 mock.patch.object(hook, "ACCOUNT", state / "account.json"),                 mock.patch.object(hook, "LEDGER", state / "ledger.jsonl"):
            hook.post(portfolio)
            hook.post(order)
        self.assertFalse(missing.exists())

    def test_writers_refuse_without_private_instead_of_creating_it(self):
        missing = Path(tempfile.mkdtemp()) / "private"
        with mock.patch.object(paths, "PRIVATE", missing), self.assertRaises(FileNotFoundError) as e:
            paths.ensure(missing / "state")
        self.assertIn("rhgex init", str(e.exception))
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
