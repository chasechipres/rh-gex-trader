---
name: setup
description: Set up this repo on this machine (Windows, macOS or Linux) - tools check, dependencies, git hooks, the private folder, your settings - and walk the user through the steps only they can do.
disable-model-invocation: true
---

Set up rh-gex-trader on this machine. The user asked for this, so you may run the commands below. Safe to run
again: check each step first and skip what's already done. Report progress in short lines as you go.

## 1. Detect the platform

Run `uname -s` with the Bash tool: `MINGW*`/`MSYS*`/`CYGWIN*` is **Windows** (the Bash tool is Git Bash there),
`Darwin` is **macOS**, `Linux` is **Linux**. Tell the user which one you found. Use that platform's column below
for every install command and instruction you give.

## 2. Check the tools

Check each with `command -v <tool>` (and `<tool> --version`):

| Tool | Needed for | Windows (PowerShell) | macOS | Linux |
|---|---|---|---|---|
| `git` | everything | `winget install Git.Git` | `brew install git` | distro package |
| `uv` | Python + dependencies | `winget install astral-sh.uv` | `brew install uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `gh` | the GitHub-synced private folder | `winget install GitHub.cli` | `brew install gh` | [cli.github.com](https://cli.github.com) |
| `gitleaks` | secret scan before commits | `winget install Gitleaks.Gitleaks` | `brew install gitleaks` | distro package or GitHub release |
| `pwsh` (Windows only) | the session-start command's `&&` | `winget install Microsoft.PowerShell` | - | - |

On macOS, if `brew` itself is missing, point to [brew.sh](https://brew.sh) first.

If anything is missing, **you can't install it for the user** (installers need their terminal and may ask for an
admin password). Give them one combined install line for their platform, e.g. on Windows
`winget install astral-sh.uv Gitleaks.Gitleaks`. Then tell them to **close and reopen the terminal and restart
`claude`** (the new PATH only reaches new terminals) and run `/setup` again. If `git` or `uv` is missing, stop
here. A missing `gh`, `gitleaks` or `pwsh` doesn't block the next steps: note it, carry on, and repeat it in the
final checklist.

## 3. Dependencies and git hooks

- `uv sync` (creates `.venv`; the guardrail hook needs it, or every Robinhood call is refused).
- `git config core.hooksPath` should print `.githooks`; if not, run `git config core.hooksPath .githooks`.
- macOS/Linux: make sure `.githooks/pre-commit` is executable (`chmod +x` if `test -x` fails).

## 4. GitHub login

Skip if `gh` is missing. Run `gh auth status`. If it isn't logged in, **you can't log in for the user** (it opens a
browser and waits for a code). Ask them to type these in the Claude prompt, one at a time:

```
! gh auth login --web --git-protocol https
! gh auth setup-git
```

Wait until they say it's done, then re-check `gh auth status`.

## 5. The private folder

Run `uv run python -m rhgex init --check`. If `exists`, `git_repo` and `guardrails` are all true, it's set up:
report its `sync` value and run `uv run python -m rhgex init` only if `missing_template_files` is non-empty
(it never overwrites files). Otherwise, find out which machine this is:

- If `gh` is logged in, run `gh repo view "$(gh api user -q .login)/rh-gex-trader-private" --json url`. If it
  exists, this is **another machine**: suggest cloning it.
- Ask the user (AskUserQuestion) to choose one:
  - **First machine, synced to GitHub (recommended)**: `uv run python -m rhgex init --github`. It creates a
    private repo `<their GitHub user>/rh-gex-trader-private`. Say exactly that before running it, since it
    creates something in their GitHub account. Needs `gh` logged in.
  - **First machine, local only**: `uv run python -m rhgex init`. Warn them that it's only on this disk and they
    must back it up themselves; `--github` can be added later.
  - **Another machine**: `uv run python -m rhgex init --clone` (their own private repo via `gh`), or
    `--clone <URL>` if it lives elsewhere. Afterwards skip step 6, since their settings came with the clone,
    unless the time zone differs (step 6, time zone question only).
- If `private/` exists but isn't a git repo or isn't empty when cloning, stop and ask the user. Never delete or
  move anything in `private/` yourself.

## 6. Personalize (first machine only)

The settings still need to be filled in if `private/CLAUDE.md` still contains `**EDIT**`. Read
`private/CLAUDE.md` and `private/guardrails.toml` in full, then ask the user with AskUserQuestion (batch up to 4
questions per call):

1. **Autonomy:** may Claude place orders in the agentic account without asking (keep the grant paragraph), or
   ask before every order (delete it)?
2. **Account size:** about how much is in the agentic account? (Fills the `$X,XXX` line; the limits are
   percentages, so this is context only.)
3. **Time zone:** detect it with `uv run python -c "import time; print(time.strftime('%Z'))"` and offer it
   first. The cron times are 10:13 / 12:33 / 15:03 ET converted to that zone (Central 9:13 / 11:33 / 14:03,
   Mountain 8:13 / 10:33 / 13:03, Pacific 7:13 / 9:33 / 12:03).
4. **S&P 500 funds elsewhere:** do they buy SPY/VOO/IVV/SPLG/SPYM (or similar) in a 401k, IRA or automatic
   plan? If yes, block them (wash-sale risk) and point S&P views to SPX/XSP options.
5. **Stocks held elsewhere** that this account must never touch (free text via "Other", or none).
6. **Limits:** keep the template defaults (aggressive, for a small growth account) or use the "Cautious"
   values written in each comment in `guardrails.toml`.
7. **Anything else** for the "Anything else" section: sectors to avoid, notification preferences (or none).

Then edit the files:

- `private/CLAUDE.md`: write their answers in place of each `**EDIT**` line, remove the `**EDIT**` markers and
  the placeholder instructions ("change each line marked EDIT..."), and delete example lines that don't apply.
  Keep each block's reason, so blocked ideas get redirected rather than just dropped.
- `private/guardrails.toml`: uncomment or add `[[blocked]]` entries matching the blocked symbols in CLAUDE.md,
  and switch to the cautious values if they chose them. Editing this file asks the user for permission: that's
  expected. Change only what they chose.
- Validate the result: `uv run python -m rhgex blocks` must run without errors and list their blocks.
- `uv run python -m rhgex sync -m "my settings"`.

## 7. Steps only the user can do

Check what you can, then give the user a numbered checklist of what's left, worded for their platform. Leave out
anything already done, and keep anything you couldn't verify.

1. **Robinhood (required):** a Robinhood **agentic** sub-account funded only with money they can lose. Then, in
   this Claude session: `/mcp` → `robinhood-trading` → **Authenticate**, and log in in the browser that opens.
   You can't do this for them. When they say it's done, verify with the read-only `get_accounts` tool (the
   guardrail hook allows reads). If `robinhood-trading` isn't listed in `/mcp`, Claude wasn't started from the
   repo folder.
2. **Chrome + X (required for reading posts):** install Chrome and the
   [Claude in Chrome](https://claude.com/chrome) extension, then log in to X in that Chrome profile with an
   account subscribed to [@Han_Akamatsu](https://x.com/Han_Akamatsu) (subscriber posts need it). If the
   claude-in-chrome tools are available in this session, offer to check: open
   `https://x.com/search?q=from%3AHan_Akamatsu&f=live` in a **new** tab, confirm posts load, and close the tab.
   Read only, never interact with X.
3. **Anything from step 2 or 4 still missing** (tools, `gh` login), with the exact commands.
4. **Session-start command:** start every session from the repo folder with
   `git switch main && git pull --ff-only && uv sync && uv run python -m rhgex sync --pull && claude`.
   - Windows: run it in **PowerShell 7** (`pwsh`; Windows PowerShell 5 doesn't support `&&`). To save it,
     offer a function for their `$PROFILE`, e.g. `function rhgex-start { Set-Location "<repo path>"; git switch main && git pull --ff-only && uv sync && uv run python -m rhgex sync --pull && claude }`.
   - macOS/Linux: offer an alias for `~/.zshrc` (macOS default) or `~/.bashrc`, e.g.
     `alias rhgex-start='cd "<repo path>" && git switch main && git pull --ff-only && uv sync && uv run python -m rhgex sync --pull && claude'`.
   Use the real repo path (`pwd`; on Windows convert `/c/Users/...` to `C:\Users\...`). Don't edit their shell
   profile yourself unless they ask.
5. **Keep the computer awake during market hours:** scheduled cycles stop if it sleeps. Windows: Settings →
   System → Power → Sleep "Never" while plugged in. macOS: System Settings → Battery/Energy → prevent automatic
   sleeping, or run `caffeinate -i` in a spare terminal.
6. **Start trading:** type `/trading-day` at about 10:15am ET on a market day.

Finish with `uv run python -m rhgex init --check` and a one-line summary: platform, what was done, and how many
checklist items are left.
