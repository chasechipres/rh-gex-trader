"""Set up and sync private/: your own limits, blocked symbols, notes, journal and exit plans.

`rhgex init` is safe to re-run: it creates whatever is missing from templates/private/, never overwrites a file,
and ends with a status report. Three ways in:
    rhgex init                      new private folder, tracked only on this machine (a local git repo)
    rhgex init --github             same, plus a private GitHub repo <you>/rh-gex-trader-private to sync through
    rhgex init --clone              a second machine: clone <you>/rh-gex-trader-private
<you> is whoever `gh` is logged in as; pass a NAME or URL to either flag to use another repo.
--migrate also copies the files from before the split (guardrails.toml, state/, logs/, notes/) into private/,
from disk or, once a pull has deleted them, from git history, and fills private/README.md's track record. The report's `from_history` names the commit each
recovered file came from; check it, and pass --from REV to read them from a commit you choose instead.

`rhgex sync` commits private/ and, when it has a remote, pulls and pushes it. Every cycle uses it.
"""

import functools
import os
import subprocess
import tomllib
from pathlib import Path

from . import paths

# Files kept in the public repo before the split -> where they live in private/ now.
LEGACY = {
    "guardrails.toml": "guardrails.toml",
    "state/plans.json": "state/plans.json",
    "state/ledger.jsonl": "state/ledger.jsonl",
    "state/session.lock": "state/session.lock",
    "logs/journal.jsonl": "logs/journal.jsonl",
    "logs/wash_sales.jsonl": "logs/wash_sales.jsonl",
    "notes/insights.md": "notes/insights.md",
    "notes/heatseeker-guide.md": "notes/heatseeker-guide.md",
    "notes/posts": "notes/posts",
    "notes/reviews": "notes/reviews",
}
LOCAL_ONLY = {"state/account.json": "state/account.json"}  # never in git; carried over on every machine
REPO_NAME = "rh-gex-trader-private"  # every user's private repo, under their own GitHub account
AUTO = "auto"  # --clone with no URL: <gh user>/REPO_NAME


# Variables that point git at a specific repo. Git sets some of them while a hook runs; inherited, they would aim
# every command below at the repo running the hook instead of `cwd`. Git's own list wins; this is the fallback.
REPO_ENV = ("GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
            "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE",
            "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX", "GIT_SHALLOW_FILE",
            "GIT_COMMON_DIR")


@functools.cache
def repo_env() -> frozenset[str]:
    try:
        res = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True)
        listed = res.stdout.split() if res.returncode == 0 else []
    except OSError:
        listed = []
    return frozenset(REPO_ENV) | frozenset(listed)


def clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in repo_env()}


def git(*args: str, cwd: Path = paths.ROOT, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True, env=clean_env())


def gh_user() -> str:
    """The GitHub login `gh` is signed in as."""
    try:
        res = subprocess.run(["gh", "api", "user", "-q", ".login"], capture_output=True, text=True, env=clean_env())
    except FileNotFoundError:
        raise ValueError("the GitHub CLI (gh) isn't installed; pass the private repo's URL to --clone")
    if res.returncode or not res.stdout.strip():
        raise ValueError("gh isn't logged in (run `gh auth login`), or pass the private repo's URL to --clone")
    return res.stdout.strip()


def clone_url(clone: str) -> str:
    return f"https://github.com/{gh_user()}/{REPO_NAME}.git" if clone == AUTO else clone


def _write_new(dest: Path, data: bytes, template: Path | None = None) -> bool:
    """Write dest unless it exists. With template, a dest still identical to its template copy is replaced too."""
    if dest.exists() and not (template and template.is_file() and dest.read_bytes() == template.read_bytes()):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True


def _from_history(rel: str, root: Path, rev: str = "") -> tuple[dict[str, bytes], str]:
    """rel's content (a file, or every file under a folder) at rev, or else just before the commit that deleted it,
    and which commit that was ("<short sha> <subject>")."""
    if not rev:
        # --first-parent: follow this branch's own line (the commit that merged the split), never a side branch.
        sha = git("log", "--first-parent", "--diff-filter=D", "-1", "--format=%H", "--", rel, cwd=root,
                  check=False).stdout.strip()
        if not sha:
            return {}, ""
        rev = f"{sha}^"
    names = git("ls-tree", "-r", "--name-only", rev, "--", rel, cwd=root, check=False).stdout.split()
    if not names:
        return {}, ""
    source = git("log", "-1", "--format=%h %s", rev, cwd=root).stdout.strip()
    return {n: subprocess.run(["git", "show", f"{rev}:{n}"], cwd=root, check=True, capture_output=True,
                              env=clean_env()).stdout for n in names}, source


def copy_legacy(mapping: dict[str, str], root: Path, private: Path, history: bool,
                template: Path | None = None, rev: str = "", sources: dict | None = None) -> list[str]:
    """Copy each old path into private/, from disk or (history=True) from git. With rev, git wins over disk.
    sources, if given, collects old path -> the commit a file came from."""
    copied = []
    for old, new in mapping.items():
        src, source = root / old, ""
        if history and rev:
            files, source = _from_history(old, root, rev)
        elif src.is_file():
            files = {old: src.read_bytes()}
        elif src.is_dir():
            files = {p.relative_to(root).as_posix(): p.read_bytes() for p in src.rglob("*") if p.is_file()}
        else:
            files, source = _from_history(old, root) if history else ({}, "")
        written = [n for n, data in files.items()
                   if _write_new(private / (new + n[len(old):]), data,
                                 template / (new + n[len(old):]) if template else None)]
        copied += written
        if written and source and sources is not None:
            sources[old] = source
    return copied


def copy_templates(template: Path, private: Path) -> list[str]:
    made = []
    for src in sorted(template.rglob("*")):
        rel = src.relative_to(template)
        if src.is_file() and _write_new(private / rel, src.read_bytes()):
            made.append(rel.as_posix())
    return made


def missing_limits(private: Path, template: Path) -> list[str]:
    """[limits] keys the template has and your guardrails.toml doesn't (new settings after an update)."""
    try:
        mine = tomllib.loads((private / "guardrails.toml").read_text(encoding="utf-8")).get("limits", {})
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return []
    theirs = tomllib.loads((template / "guardrails.toml").read_text(encoding="utf-8"))["limits"]
    return sorted(set(theirs) - set(mine))


def remote(private: Path) -> str:
    if not (private / ".git").exists():
        return ""
    return git("remote", "get-url", "origin", cwd=private, check=False).stdout.strip()


def status(private: Path = paths.PRIVATE, template: Path = paths.TEMPLATE) -> dict:
    url = remote(private)
    missing = [p.relative_to(template).as_posix() for p in template.rglob("*")
               if p.is_file() and not (private / p.relative_to(template)).exists()]
    return {
        "private": str(private),
        "exists": private.is_dir(),
        "git_repo": (private / ".git").exists(),
        "guardrails": (private / "guardrails.toml").exists(),
        "sync": url or "local only: commits stay on this machine (add a remote with `rhgex init --github`)",
        "missing_template_files": missing,
        "new_limits_to_add": missing_limits(private, template),
    }


def fill_track_record(private: Path) -> float | None:
    """Rebuild private/README.md's track record from the journal and the latest recorded account value."""
    import json

    from . import exits, record

    accounts = private / "state" / "account.json"
    recs = [r for r in json.loads(accounts.read_text()).values() if r.get("total_value")] if accounts.exists() else []
    value = max(recs, key=lambda r: (r.get("date", ""), r.get("time", "")))["total_value"] if recs else None
    entries = record.load(private / "logs" / "journal.jsonl")
    plans = exits.load(private / "state" / "plans.json")
    record.write_readme(record.render(record.summarize(entries, plans), value), private / "README.md")
    return value


def init(clone: str = "", github: str = "", migrate: bool = False, root: Path = paths.ROOT,
         private: Path = paths.PRIVATE, template: Path = paths.TEMPLATE, rev: str = "") -> dict:
    report: dict = {}
    if rev and git("rev-parse", "--verify", "-q", f"{rev}^{{commit}}", cwd=root, check=False).returncode:
        raise ValueError(f"--from {rev}: no such commit")
    if clone:
        if private.exists() and any(private.iterdir()):
            raise ValueError(f"{private} already exists and isn't empty; move it aside to clone into it")
        clone = clone_url(clone)
        git("clone", clone, str(private), cwd=root)
        report["cloned"] = clone
    private.mkdir(exist_ok=True)
    if migrate:
        sources: dict[str, str] = {}
        report["migrated"] = copy_legacy(LEGACY, root, private, history=True, template=template, rev=rev,
                                         sources=sources)
        if sources:
            report["from_history"] = sources
    report["carried_over"] = copy_legacy(LOCAL_ONLY, root, private, history=False)
    report["created"] = copy_templates(template, private)
    if migrate:
        report["track_record_account_value"] = fill_track_record(private)
    if not (private / ".git").exists():
        git("init", "-q", "-b", "main", cwd=private)
    git("config", "core.hooksPath", "../.githooks", cwd=private)  # the secret scan runs on private commits too
    for key in ("user.name", "user.email"):  # commit as whoever this clone commits as, if git has no global identity
        mine = git("config", key, cwd=private, check=False).stdout.strip()
        theirs = git("config", key, cwd=root, check=False).stdout.strip()
        if not mine and theirs:
            git("config", key, theirs, cwd=private)
    if not git("rev-parse", "--verify", "-q", "HEAD", cwd=private, check=False).stdout.strip():
        git("add", "-A", cwd=private)
        git("commit", "-q", "-m", "private: initial setup from rhgex init", cwd=private)
    if github and not remote(private):
        subprocess.run(["gh", "repo", "create", github, "--private", "--source", str(private),
                        "--remote", "origin", "--push"], check=True, capture_output=True, text=True, env=clean_env())
        report["github"] = remote(private)
    return {**report, "status": status(private, template)}


def sync(message: str, pull_only: bool = False, private: Path = paths.PRIVATE) -> dict:
    """Commit private/, then pull and push it if it has a remote. A conflict stops here for the user."""
    if not (private / ".git").exists():
        raise ValueError("private/ isn't set up; run `uv run python -m rhgex init` (see README)")
    out: dict = {"committed": False, "pulled": False, "pushed": False}
    if not pull_only:
        git("add", "-A", cwd=private)
        if git("diff", "--cached", "--quiet", cwd=private, check=False).returncode:
            res = git("commit", "-q", "-m", message, cwd=private, check=False)
            if res.returncode:
                raise ValueError(f"commit refused: {(res.stdout + res.stderr).strip()}")
            out["committed"] = True
    if not remote(private):
        return {**out, "remote": "none (local only)"}
    res = git("pull", "--no-edit", "-q", cwd=private, check=False)
    if res.returncode:
        raise ValueError(f"pull failed; stop and ask the user, don't hand-merge state: {(res.stdout + res.stderr).strip()}")
    out["pulled"] = True
    if not pull_only:
        res = git("push", "-q", cwd=private, check=False)
        if res.returncode:
            raise ValueError(f"push failed: {(res.stdout + res.stderr).strip()}")
        out["pushed"] = True
    return out
