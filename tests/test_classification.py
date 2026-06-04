"""Normalisation of classification and maturity inputs."""

from __future__ import annotations

import pytest

from ism_mcp.classification import normalise_classification, normalise_maturity


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("NC", "NC"),
        ("nc", "NC"),
        ("OFFICIAL", "NC"),
        ("official", "NC"),
        ("non-classified", "NC"),
        ("OS", "OS"),
        ("OFFICIAL:Sensitive", "OS"),
        ("OFFICIAL-Sensitive", "OS"),
        ("official:sensitive", "OS"),
        ("P", "P"),
        ("PROTECTED", "P"),
        ("S", "S"),
        ("SECRET", "S"),
        ("TS", "TS"),
        ("TOP_SECRET", "TS"),
        ("TOP SECRET", "TS"),
        ("top secret", "TS"),
    ],
)
def test_normalise_classification(raw, expected):
    assert normalise_classification(raw) == expected


def test_normalise_classification_rejects_unknown():
    with pytest.raises(ValueError, match="unknown classification"):
        normalise_classification("HUSH-HUSH")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("ML1", "ML1"),
        ("ml1", "ML1"),
        ("1", "ML1"),
        (1, "ML1"),
        ("ML2", "ML2"),
        ("2", "ML2"),
        ("ML3", "ML3"),
        ("3", "ML3"),
    ],
)
def test_normalise_maturity(raw, expected):
    assert normalise_maturity(raw) == expected


def test_normalise_maturity_rejects_unknown():
    with pytest.raises(ValueError, match="unknown maturity"):
        normalise_maturity("ML4")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("top-secret", "TS"),
        ("OFFICIAL Sensitive", "OS"),
        ("non classified", "NC"),
        ("  PROTECTED  ", "P"),
    ],
)
def test_classification_accepts_separator_variants(raw, expected):
    assert normalise_classification(raw) == expected
