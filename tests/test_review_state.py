"""Tests for review state and idempotency."""

import tempfile

import pytest

from pr_agent.utils.review_state import (
    hash_comment,
    load_state,
    mark_reviewed,
    save_state,
    should_review,
)


def test_should_review_empty_state() -> None:
    state: dict = {"repos": {}}
    assert should_review(state, "https://github.com/org/repo", 1, "abc123") is True


def test_should_review_different_sha() -> None:
    state = {
        "reviewed": {
            "https://github.com/org/repo#1": {"sha": "old123", "comment_hash": "h1"},
        },
    }
    assert should_review(state, "https://github.com/org/repo", 1, "new456") is True


def test_should_review_same_sha() -> None:
    state = {
        "reviewed": {
            "https://github.com/org/repo#1": {"sha": "abc123", "comment_hash": "h1"},
        },
    }
    assert should_review(state, "https://github.com/org/repo", 1, "abc123") is False


def test_mark_reviewed() -> None:
    state: dict = {}
    mark_reviewed(state, "https://github.com/org/repo", 42, "sha999", "chash")
    assert state["reviewed"]["https://github.com/org/repo#42"] == {
        "sha": "sha999",
        "comment_hash": "chash",
    }


def test_hash_comment() -> None:
    h1 = hash_comment("hello")
    h2 = hash_comment("hello")
    assert h1 == h2
    assert hash_comment("world") != h1
    assert len(h1) == 64  # sha256 hex


def test_load_save_state_file_backend() -> None:
    """Passing a path string uses file backend (backward compatible)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = f.name
    try:
        state = load_state(path)
        assert state == {"repos": {}}
        mark_reviewed(state, "https://github.com/o/r", 1, "sha1", "ch1")
        save_state(path, state)
        loaded = load_state(path)
        assert loaded.get("reviewed", {}).get("https://github.com/o/r#1") == {
            "sha": "sha1",
            "comment_hash": "ch1",
        }
    finally:
        import os

        os.unlink(path)
