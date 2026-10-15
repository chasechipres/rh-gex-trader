# Setup and settings

Installing it, what lives in your private folder, and how to change the rules for yourself. The short version is
the README's [Quick start](../README.md#quick-start).

- [Install](#install) · [Your private folder](#your-private-folder) · [Make it yours](#make-it-yours)

## Install

| | macOS / Linux | Windows (PowerShell) |
|---|---|---|
| **1. Tools** | `brew install git gh uv gitleaks` | `winget install Git.Git GitHub.cli astral-sh.uv Gitleaks.Gitleaks Microsoft.PowerShell`, then **reopen the terminal** |

Install [Claude Code](https://claude.com/claude-code) too. The rest is the same on both:

```sh
gh auth login --web --git-protocol https
gh auth setup-git
gh repo clone chasechipres/rh-gex-trader
cd rh-gex-trader
claude                                     # then: /setup
```

`/setup` does the rest and can be re-run any time: it checks the tools (with the install line for your OS if
one is missing), runs `uv sync` and `git config core.hooksPath .githooks`, logs `gh` in with you, runs
`rhgex init` (below), and fills in your settings from a few questions. It finishes with the steps only you can
do: `/mcp` → robinhood-trading → Authenticate, Claude in Chrome, and the session-start command. By hand, those
middle steps are `uv sync`, `git config core.hooksPath .githooks` and `uv run python -m rhgex init --github`.

Then install [Claude in Chrome](https://claude.com/chrome) and log in to X in that Chrome profile (subscriber
posts need it). The hook finds the right venv Python on either OS, so `.claude/settings.json` is shared.

## Your private folder

Everything about you and your account lives in `private/`: its own git repo, ignored by this one, so nothing
personal lands in the shared repo.

| File | What it holds | Who edits it |
|---|---|---|
| `guardrails.toml` | your limits and blocked symbols (the hook enforces them) | you (Claude asks first) |
| `CLAUDE.md` | autonomy grant, account goal, time zone and cron times, why each symbol is blocked | you |
| `README.md` | your track record | `rhgex record --readme` |
| `notes/` | saved posts, insights about the source, weekly reviews | Claude |
| `logs/` | `journal.jsonl` (every decision), `wash_sales.jsonl` (loss exits) | Claude, via `rhgex` |
| `state/` | `plans.json`, `ledger.jsonl`, `session.lock` (synced); `account.json` (never leaves the machine) | `rhgex` and the hook |

**Pick how it's stored:**

- `rhgex init --github` **(recommended):** creates `github.com/<you>/rh-gex-trader-private`, private, and every
  cycle's `rhgex sync` pushes to it. A second machine or a dead disk loses nothing.
- `rhgex init`: local only. Still committed each cycle for history; back it up yourself. Add GitHub later with `--github`.
- `rhgex init --clone`: a second machine ([more](running.md#using-more-than-one-machine)).

Both flags take a name or URL (`--github my-data`, `--clone <URL>`). `init` never overwrites a file, and
`rhgex init --check` reports what's set up. Until `private/guardrails.toml` exists, the hook refuses every order.
The [templates](../templates/private) are a complete example; every line meant for you is marked `EDIT` with a
cautious alternative.

**Moving a setup from before the split:** run `rhgex init --migrate --github` once, outside market hours, on the
machine that ran the last cycle. It copies your old `guardrails.toml`, `state/`, `logs/` and `notes/` into
`private/` (from git history if a pull already deleted them) and rebuilds the track record. If `from_history`
names the wrong commit, re-run into an empty `private/` with `--from <commit>`. Then `rhgex init --clone` on
each other machine.

## Make it yours

Rules come in three layers, from hardest to softest:

| Layer | File | What goes in it | Enforced by |
|---|---|---|---|
| **Hard limits** | `private/guardrails.toml` | size per order and per day, daily loss stop, drawdown pause, blocked symbols | the hook, on every order |
| **Your instructions** | `private/CLAUDE.md` | autonomy, goal, time zone, standing preferences, in plain English | Claude; wins over the playbook |
| **The playbook** | `CLAUDE.md` (shared) | how Claude researches, enters, sizes and exits | Claude; the same for everyone |

```toml
[limits]
max_option_premium_pct = 5      # max loss per option order, % of the account
max_order_usd = 300             # also cap in dollars (any max_<name>_pct takes a _usd partner)
max_new_positions_per_day = 2

[[blocked]]                     # never trade these (or their options) in either direction
name = "held in my IRA"
symbols = ["AAPL", "MSFT"]
until = ""                      # or "YYYY-MM-DD" for a block that expires
```

Examples for `private/CLAUDE.md`: "Ask me before every entry." · "No biotech." · "Options only." · "Notify me only
for fills and stop-outs." · "My computer is on Central time." To change a rule for everyone, open a pull request
(`main` is protected; see [CONTRIBUTING.md](../CONTRIBUTING.md)). Weekly reviews propose rule changes;
you decide. Blocking a fund? Block its lookalikes too: see [Wash sales and taxes](safety.md#wash-sales-and-taxes).
