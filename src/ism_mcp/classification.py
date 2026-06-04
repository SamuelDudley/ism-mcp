"""Normalise classification and maturity inputs from agent calls."""

from __future__ import annotations

import re

_SEPARATORS = re.compile(r"[\s:_\-]+")

_CLASS_MAP = {
    "nc": "NC",
    "official": "NC",
    "non classified": "NC",
    "os": "OS",
    "official sensitive": "OS",
    "p": "P",
    "protected": "P",
    "s": "S",
    "secret": "S",
    "ts": "TS",
    "top secret": "TS",
}

_MATURITY_MAP = {
    "ml1": "ML1",
    "1": "ML1",
    "ml2": "ML2",
    "2": "ML2",
    "ml3": "ML3",
    "3": "ML3",
}


def _canonical(value: str) -> str:
    return _SEPARATORS.sub(" ", value.strip().lower())


def normalise_classification(value: str) -> str:
    key = _canonical(value)
    if key not in _CLASS_MAP:
        raise ValueError(f"unknown classification: {value!r}")
    return _CLASS_MAP[key]


def normalise_maturity(value: str | int) -> str:
    key = _canonical(str(value))
    if key not in _MATURITY_MAP:
        raise ValueError(f"unknown maturity: {value!r}")
    return _MATURITY_MAP[key]
