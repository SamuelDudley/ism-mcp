"""Path tokenisation and keyword expansion."""

from __future__ import annotations

from ism_mcp.paths import expand_paths, matched_tokens


def test_expand_known_tokens():
    expanded, matched = expand_paths(["src/auth/jwt.py"])
    assert "authentication" in expanded
    assert "session" in expanded
    assert "token" in expanded
    assert "credential" in expanded
    assert "jwt" in matched
    assert "auth" in matched


def test_expand_is_case_insensitive():
    expanded, _ = expand_paths(["src/Auth/JWT.py"])
    assert "authentication" in expanded


def test_unknown_tokens_drop_silently():
    expanded, matched = expand_paths(["src/foo/bar.py"])
    assert expanded == set()
    assert matched == set()


def test_multiple_paths_merge():
    expanded, matched = expand_paths(["src/auth/jwt.py", "src/log/audit.py"])
    assert "authentication" in expanded
    assert "logging" in expanded
    assert {"jwt", "auth", "log", "audit"}.issubset(matched)


def test_empty_input_returns_empty():
    expanded, matched = expand_paths([])
    assert expanded == set()
    assert matched == set()


def test_matched_tokens_returns_known_tokens_only():
    assert matched_tokens("src/auth/jwt.py") == {"auth", "jwt"}
    assert matched_tokens("src/foo/bar.py") == set()
