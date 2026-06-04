"""Clone or update the OSCAL ISM mirror and read files at tags. Shells out to git."""

from __future__ import annotations

import subprocess
from pathlib import Path

DEFAULT_REPO = "https://github.com/AustralianCyberSecurityCentre/ism-oscal.git"
DEFAULT_CACHE = Path.home() / ".local/share/ism-mcp/oscal"


class GitError(RuntimeError):
    pass


def _git(repo_dir: Path | None, *args: str) -> str:
    cmd = ["git"]
    if repo_dir is not None:
        cmd += ["-C", str(repo_dir)]
    cmd += list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def ensure_clone(repo: str = DEFAULT_REPO, cache: Path = DEFAULT_CACHE) -> Path:
    """Clone `repo` into `cache` if absent, otherwise fetch tags. Return the repo dir."""
    cache = Path(cache)
    if (cache / ".git").is_dir():
        _git(cache, "fetch", "--tags", "--force", "origin")
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    _git(None, "clone", "--quiet", repo, str(cache))
    return cache


def list_tags(repo_dir: Path) -> list[str]:
    out = _git(Path(repo_dir), "tag", "--sort=v:refname")
    return [line.strip() for line in out.splitlines() if line.strip()]


def read_file_at_tag(repo_dir: Path, tag: str, relpath: str) -> str:
    return _git(Path(repo_dir), "show", f"{tag}:{relpath}")


def current_commit(repo_dir: Path, ref: str = "HEAD") -> str:
    return _git(Path(repo_dir), "rev-parse", ref).strip()
