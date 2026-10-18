# Contributing

Thanks for helping. This repo places real orders, so changes go through review, and anything that touches the
guardrails needs a test. Changes made with Claude follow the same rules (CLAUDE.md's "Changing this repo").

## Get set up

Follow [Setup](docs/setup.md#install), then type `/setup` in `claude`. You need your own private folder
(`rhgex init`) only to run cycles; the tests don't use it.

## What goes where

| Change | Where | Branch prefix |
|---|---|---|
| Code, the hook, tools | `rhgex/`, with tests in `tests/` | `feat/…` or `fix/…` |
| How Claude trades (the playbook) | `CLAUDE.md`, `.claude/` | `rules/…` |
| Docs | `README.md`, `docs/`, this file | `docs/…` |
| Defaults for new users | `templates/private/` | `feat/…` |
| **Your own** limits, notes, preferences | `private/` (your private repo, never a PR here) | - |

Nothing personal goes in this repo: no account values, positions, journal entries, private-repo links or
credentials. The pre-commit hook scans for secrets; don't skip it with `--no-verify`.

## Repo layout

```
rh-gex-trader/              shared (this repo)
├── CLAUDE.md               the playbook Claude follows; imports private/CLAUDE.md
├── CONTRIBUTING.md         how to change this repo
├── .mcp.json               Robinhood MCP server (URL only, no credentials)
├── .claude/                guardrail hooks, permission lists, the /setup and /trading-day skills
├── .githooks/pre-commit    secret scan (both repos) + tests (this repo)
├── docs/                   strategy, setup, running it, guardrails and exits, the 24/7 cloud server
├── rhgex/
│   ├── __init__.py         the command line
│   ├── paths.py            where everything lives
│   ├── init.py             set up and sync private/
│   ├── hook.py             pre/post hooks on every Robinhood call
│   ├── guardrails.py       order checks
│   ├── exits.py            exit plans and the exit check
│   ├── watches.py          watch triggers, checked every exit check
│   ├── monitor.py          the watcher: wakes the session when a level is crossed
│   ├── dailyloss.py        daily loss stop and drawdown pause
│   ├── sizing.py           position size for a fixed % risk
│   ├── leveraged.py        single-stock leveraged funds and their stocks
│   ├── preflight.py        pre-trade checklist
│   ├── lock.py             one machine at a time
│   ├── record.py           track record
│   ├── calls.py            the source's calls, scored
│   ├── washlog.py          wash-sale log (logging only)
│   ├── market.py           technicals + fundamentals (Yahoo Finance)
│   ├── indicators.py       EMA, RSI, ATR
│   ├── gex.py              gamma profile (Cboe delayed chains)
│   └── fit.py              option structures that fit the risk budget
├── templates/private/      what `rhgex init` copies into private/
├── scripts/                owner tools
├── tests/                  unit tests, plus doc facts vs the code
└── private/                YOUR private repo, ignored here
```

## Make the change

1. **Fork first** unless you've been added as a collaborator: only collaborators can push branches here.
   `gh repo fork chasechipres/rh-gex-trader --clone` makes your fork and clones it (or run `gh repo fork` in an
   existing clone; it adds your fork as `origin` and this repo as `upstream`). Keep `main` in sync with
   `gh repo sync <you>/rh-gex-trader` or `git pull upstream main`.
2. Branch off an up-to-date `main` (`git switch main && git pull --ff-only && git switch -c fix/…`). One topic
   per branch, pushed to your fork (collaborators can push to this repo). `main` is protected: no direct or
   force pushes, even for the owner.
3. Commit with a short imperative subject (≤ 72 chars, e.g. "Add stale-rules check to exit step 1") and a body
   only when the why isn't obvious.
4. Test: `uv run python -m unittest discover -s tests -t .` (or `uv run pytest`). The pre-commit hook runs the
   tests when code, templates, the docs (`README.md`, `docs/`, this file), `CLAUDE.md` or
   `.claude/settings.json` is staged, and `tests/test_readme.py` checks facts in the docs against the code, so a
   change that leaves them stale is refused. Fix the docs in the same commit.
   - **Hook or guardrails changes** (`rhgex/hook.py`, `guardrails.py`, `dailyloss.py`, `exits.py`, `paths.py`)
     need a test that covers them. Changes should fail closed: what the hook can't verify, it refuses.
   - **New limits** go in `templates/private/guardrails.toml` with a comment and a cautious value; `rhgex init`
     tells existing users to copy them in.

## Open the pull request

Title like a commit subject. Body, in this order:

- **Summary:** what changes and why, in 1-3 sentences.
- **Changes:** a bullet per file or behavior, naming the file.
- **Trading impact:** what this changes about orders, limits, exits or the cycle, or "none". A `CLAUDE.md` or
  `.claude/` change makes running sessions ask for a restart; say so.
- **Testing:** the commands run and their result (e.g. "unittest: 149 passed"), plus anything checked by hand.

## Merging

Only the maintainer (and collaborators with write access) can merge. A PR is merged when:

- CI passes: GitHub Actions runs the tests on Linux, Windows and macOS for every PR, and `main` won't accept
  a merge until all three pass,
- the branch is up to date with `main` (if `main` moved, click **Update branch** on the PR; CI runs again),
- the maintainer has reviewed it, and
- it's one topic with nothing personal in it.

It's merged with **squash**, so the PR title becomes the commit on `main`, and the branch is deleted afterward.
Expect changes to `CLAUDE.md`, the hook or the default limits to get the closest look: they change how real
money is traded for everyone who pulls.
