#!/usr/bin/env bash
# Build a clean public-release tree from the tracked files at HEAD.
#
# The public repository carries only README, CLAUDE.md, and the code. This script
# snapshots HEAD into an output directory, drops the internal artifacts that stay
# private (HANDOVER.md and docs/), scrubs any local-only reference, strips the
# now-dangling references to those files from README.md and CLAUDE.md, and fails
# if any private marker survives. Your working tree and history are untouched.
#
# Usage:
#   ./scripts/prepare-public-release.sh [OUTPUT_DIR]
#     OUTPUT_DIR defaults to dist/public (gitignored).
set -euo pipefail

REPO_URL="https://github.com/samueldudley/ism-mcp"
TAG="v1.1"

cd "$(git rev-parse --show-toplevel)"
OUT="${1:-dist/public}"

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "note: working tree has uncommitted changes; snapshotting committed HEAD only." >&2
fi

rm -rf "$OUT"
mkdir -p "$OUT"
git archive HEAD | tar -x -C "$OUT"

# Internal-only artifacts: kept in this repo, excluded from the public tree.
# This script holds the private reference strings it scrubs for, so it stays private.
rm -f "$OUT/HANDOVER.md"
rm -rf "$OUT/docs"
rm -f "$OUT/scripts/prepare-public-release.sh"

python3 - "$OUT" "$REPO_URL" <<'PY'
import pathlib
import sys

out = pathlib.Path(sys.argv[1])
repo_url = sys.argv[2]

# Insurance scrub. The public-shipping files are already clean; this catches any
# local-only reference that slips in later. Longest paths first.
subs = [
    ("file:///home/dudley/code/ism-mcp.git", repo_url + ".git"),
    ("/home/dudley/code/ism-mcp", "<repo>"),
    ("/home/dudley/code/wayland-remote", "/path/to/your-project"),
    ("wayland-remote-admin", "demo-admin"),
    ("wayland-remote", "your-project"),
    ("/home/dudley", "~"),
    ("sam.dudley", "reviewer"),
]
for path in out.rglob("*"):
    if not path.is_file():
        continue
    try:
        text = path.read_text()
    except (UnicodeDecodeError, ValueError):
        continue
    new = text
    for old, repl in subs:
        new = new.replace(old, repl)
    if new != text:
        path.write_text(new)


def keep_lines(path, predicate):
    if not path.is_file():
        return
    lines = path.read_text().splitlines(keepends=True)
    path.write_text("".join(line for line in lines if predicate(line)))


def drop_section(path, heading, stop_prefix):
    if not path.is_file():
        return
    out_lines = []
    skipping = False
    for line in path.read_text().splitlines(keepends=True):
        if line.startswith(heading):
            skipping = True
            continue
        if skipping and line.startswith(stop_prefix):
            skipping = False
        if not skipping:
            out_lines.append(line)
    path.write_text("".join(out_lines))


claude = out / "CLAUDE.md"
readme = out / "README.md"

# Repository-layout entries and the workflow line that point at the excluded files.
keep_lines(
    claude,
    lambda line: not (
        line.lstrip().startswith(("docs/plans/", "docs/superpowers/", "HANDOVER.md"))
        or "docs/plans/` are executable" in line
    ),
)
if claude.is_file():
    text = claude.read_text()
    text = text.replace(
        ", and `HANDOVER.md` for current state and next planned work", ""
    )
    claude.write_text(text)

# The closeout checklist is internal process referencing HANDOVER.md.
drop_section(claude, "### Closing a development branch", "## ")

# The lone design-doc pointer in the README.
keep_lines(readme, lambda line: "docs/superpowers/" not in line and "docs/plans/" not in line)
PY

# Guard: nothing private may survive into the public tree.
if grep -rIlE '/home/|wayland-remote|file:///|sam\.dudley' "$OUT"; then
    echo "ERROR: private markers remain in $OUT (files listed above)." >&2
    exit 1
fi

echo "Public tree ready in $OUT (HANDOVER.md and docs/ excluded, references scrubbed)."
echo
echo "Publish it with:"
echo "  cd $OUT"
echo "  git init -b main && git add -A && git commit -m 'ism-mcp $TAG'"
echo "  git remote add origin $REPO_URL.git"
echo "  git push -u origin main"
echo "  git tag -a $TAG -m 'ism-mcp $TAG' && git push origin $TAG"
