"""Where everything lives. The public repo holds the code and the playbook; everything personal lives in
private/, a separate git repo cloned inside this one (and ignored by it). `rhgex init` creates it.

private/
    CLAUDE.md          your account notes, timezone and schedule, why each symbol is blocked
    guardrails.toml    your limits and blocked symbols (the hook reads these)
    README.md          your track record (`rhgex record --readme`)
    notes/             saved posts, insights, weekly reviews
    logs/              journal.jsonl, wash_sales.jsonl
    state/             plans.json, ledger.jsonl, session.lock (synced); account.json (local only)
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "private"
PRIVATE = ROOT / "private"

GUARDRAILS = PRIVATE / "guardrails.toml"
README = PRIVATE / "README.md"
NOTES = PRIVATE / "notes"
POSTS = NOTES / "posts"
LOGS = PRIVATE / "logs"
STATE = PRIVATE / "state"


def ready(path: Path) -> bool:
    """Whether path can be written: anywhere outside private/, and inside it once `rhgex init` has made it."""
    return not path.is_relative_to(PRIVATE) or PRIVATE.is_dir()


def ensure(folder: Path) -> Path:
    """Create folder to write into. Inside private/, only once `rhgex init` has made private/ itself."""
    if not ready(folder):
        raise FileNotFoundError("private/ isn't set up; run `uv run python -m rhgex init` (see README)")
    folder.mkdir(parents=True, exist_ok=True)
    return folder
