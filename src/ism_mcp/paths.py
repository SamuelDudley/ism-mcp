"""Tokenise repo paths and expand known tokens into BM25-friendly keywords."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from functools import cache
from importlib.resources import files

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


@cache
def _keyword_map() -> dict[str, set[str]]:
    raw = tomllib.loads(files("ism_mcp.data").joinpath("path_keywords.toml").read_text())
    return {token.lower(): set(phrase.split()) for token, phrase in raw.items()}


def _tokens(path: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(path)]


def matched_tokens(path: str) -> set[str]:
    keywords = _keyword_map()
    return {t for t in _tokens(path) if t in keywords}


def expand_paths(paths: list[str]) -> tuple[set[str], set[str]]:
    """Return (expanded_keywords, matched_path_tokens) across all paths."""
    keywords = _keyword_map()
    expanded: set[str] = set()
    matched: set[str] = set()
    for path in paths:
        for token in _tokens(path):
            if token in keywords:
                matched.add(token)
                expanded.update(keywords[token])
    return expanded, matched


def token_keywords(tokens: Iterable[str]) -> dict[str, set[str]]:
    """Map each known token to the keyword set it expands to."""
    keywords = _keyword_map()
    return {t: keywords[t] for t in tokens if t in keywords}
