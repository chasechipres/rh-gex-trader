#!/bin/sh
# Move this checkout onto a repo with clean history, keeping the same folder path and your private/ folder.
#
# For when the shared repo's history still holds personal data from before the private-folder split. Run it
# AFTER `rhgex init --migrate --github` has pushed your data to your private repo, with Claude Code (and
# anything else that has this folder open: editors, terminals) CLOSED. Run it from Git Bash on Windows.
#
#   sh scripts/move-to-clean-repo.sh --create OWNER/NAME [--public]   # make the clean repo, then re-clone
#   sh scripts/move-to-clean-repo.sh URL                              # re-clone from a clean repo that exists
#
# --create builds OWNER/NAME from ONE commit holding origin/main's files (no history) and pushes it, private
# unless --public. If NAME is this repo's current name, rename the old one on GitHub first, e.g.
#   gh repo rename rh-gex-trader-archive --repo OWNER/rh-gex-trader
# Then this script renames this folder to <folder>.old-<date>, clones the clean repo into the same path (so
# Claude Code's project memory and settings stay attached), moves private/ across, and runs uv sync, the git
# hooks, `rhgex init --check` and the tests. It deletes nothing: the old folder and the old GitHub repo stay
# until you've checked everything and remove them yourself.
set -eu

# This file lives in the folder being renamed; run from a copy so the rename can't pull it out from under us.
if [ -z "${RHGEX_MOVE_COPY:-}" ]; then
  copy="$(mktemp -d)/move-to-clean-repo.sh"
  cp "$0" "$copy"
  RHGEX_MOVE_COPY=1 RHGEX_MOVE_DIR="$(cd "$(dirname "$0")/.." && pwd)" exec sh "$copy" "$@"
fi

die() { echo "move-to-clean-repo: $*" >&2; exit 1; }
unset $(git rev-parse --local-env-vars 2>/dev/null) 2>/dev/null || true

dir="$RHGEX_MOVE_DIR"
parent="$(dirname "$dir")"
name="$(basename "$dir")"
old="$dir.old-$(date +%Y%m%d-%H%M)"

create="" public="--private" url=""
while [ $# -gt 0 ]; do
  case "$1" in
    --create) create="${2:?--create needs OWNER/NAME}"; shift 2 ;;
    --public) public="--public"; shift ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) url="$1"; shift ;;
  esac
done
[ -n "$create" ] || [ -n "$url" ] || die "pass --create OWNER/NAME or the clean repo's URL (see --help)"

# --- preflight: never move unless the data is safe ---------------------------------------------------------
cd "$dir"
[ -d private/.git ] || die "private/ isn't a git repo; run \`uv run python -m rhgex init --migrate --github\` first"
git -C private remote get-url origin >/dev/null 2>&1 || die "private/ has no remote; run \`uv run python -m rhgex init --github\` so your data is backed up first"
[ -z "$(git -C private status --porcelain)" ] || die "private/ has uncommitted changes; run \`uv run python -m rhgex sync\`"
git -C private fetch -q origin
ahead="$(git -C private rev-list --count '@{u}..HEAD' 2>/dev/null)" || die "private/'s branch doesn't track its remote; run \`git -C private push -u origin main\`"
[ "$ahead" = 0 ] || die "private/ has commits that aren't pushed; run \`uv run python -m rhgex sync\`"
git fetch -q origin
[ "$(git status --porcelain --untracked-files=no)" = "" ] || die "this checkout has uncommitted changes to tracked files; commit or discard them"
[ ! -e "$old" ] || die "$old already exists"
if [ "$(git worktree list | wc -l)" -gt 1 ]; then
  echo "note: other worktrees of this repo exist (git worktree list); they keep pointing at the old repo."
fi

# --- 1. the clean repo: one commit, no history ------------------------------------------------------------
if [ -n "$create" ]; then
  stage="$(mktemp -d)/clean"
  mkdir -p "$stage"
  git archive origin/main | tar -x -C "$stage"
  git -C "$stage" init -q -b main
  git -C "$stage" config user.name "$(git config user.name)"
  git -C "$stage" config user.email "$(git config user.email)"
  git -C "$stage" add -A
  git -C "$stage" -c core.hooksPath=/dev/null commit -q -m "Initial commit"
  for p in guardrails.toml state logs notes private; do
    [ ! -e "$stage/$p" ] || die "origin/main still has $p; merge the private-folder split before cleaning history"
  done
  gh repo create "$create" "$public" --source "$stage" --remote origin --push >/dev/null
  url="$(git -C "$stage" remote get-url origin)"
  echo "created $create ($public): $(git -C "$stage" rev-list --count HEAD) commit, no history"
fi

# --- 2. re-clone into the same path, private/ moved across -------------------------------------------------
cd "$parent"
mv "$dir" "$old" || die "couldn't rename $name; close Claude Code, editors and terminals using it, then re-run"
if ! git clone -q "$url" "$dir"; then
  mv "$old" "$dir"
  die "clone of $url failed; put the old folder back as it was"
fi
mv "$old/private" "$dir/private"
[ ! -f "$old/.claude/settings.local.json" ] || cp "$old/.claude/settings.local.json" "$dir/.claude/"

cd "$dir"
git config core.hooksPath .githooks
{ uv sync -q && uv run python -m rhgex init --check && uv run python -m unittest discover -s tests -t . -q; } ||
  die "moved, but a check failed (output above); the old folder is still at $old, nothing was deleted"

cat <<EOF

Done. $name now tracks $url, with your private/ folder in place.
Check it: start Claude Code here, run \`uv run python -m rhgex plan list\`, and look over $url on GitHub.
When everything's right, remove the leftovers yourself:
  rm -rf "$old"
  gh repo delete <OLD_OWNER/OLD_NAME>      # removes the old history, including GitHub's PR refs
On your other machine (after \`rhgex sync\` there): sh scripts/move-to-clean-repo.sh $url
EOF
