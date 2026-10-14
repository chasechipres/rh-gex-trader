# Contributing

Thanks for helping. This repo places real orders, so changes go through review, and anything that touches the
guardrails needs a test. Changes made with Claude follow the same rules (CLAUDE.md's "Changing this repo").

## Get set up

Follow the README's [Setup](README.md#setup), then type `/setup` in `claude`. You need your own private folder
(`rhgex init`) only to run cycles; the tests don't use it.

## What goes where

| Change | Where | Branch prefix |
|---|---|---|
| Code, the hook, tools | `rhgex/`, with tests in `tests/` | `feat/…` or `fix/…` |
| How Claude trades (the playbook) | `CLAUDE.md`, `.claude/` | `rules/…` |
| Docs | `README.md`, this file | `docs/…` |
| Defaults for new users | `templates/private/` | `feat/…` |
| **Your own** limits, notes, preferences | `private/` (your private repo, never a PR here) | - |

Nothing personal goes in this repo: no account values, positions, journal entries, private-repo links or
credentials. The pre-commit hook scans for secrets; don't skip it with `--no-verify`.

## Make the change

1. Branch off an up-to-date `main` (`git switch main && git pull --ff-only && git switch -c fix/…`). One topic
   per branch. `main` is protected: no direct or force pushes. Without write access, push to your fork.
2. Commit with a short imperative subject (≤ 72 chars, e.g. "Add stale-rules check to exit step 1") and a body
   only when the why isn't obvious.
3. Test: `uv run python -m unittest discover -s tests -t .` (or `uv run pytest`). The pre-commit hook runs the
   tests when code, templates, `README.md`, `CLAUDE.md` or `.claude/settings.json` is staged, and
   `tests/test_readme.py` checks README facts against the code, so a change that leaves the README stale is
   refused. Fix the README in the same commit.
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

It's merged with **squash** once it's green and reviewed, and the branch is deleted.
