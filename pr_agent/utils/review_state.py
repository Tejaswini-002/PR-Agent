from __future__ import annotations

import json
import os
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Union

# Config-like: has state_backend, review_state_path, database_url (optional)
_ConfigLike = Any

STATE_KEY = "default"
_TABLE = "neuqa_review_state"


def _empty_state() -> dict[str, Any]:
    return {"repos": {}}


def _load_file(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return _empty_state()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return _empty_state()


def _save_file(path: str, state: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)


def _load_postgres(database_url: str) -> dict[str, Any]:
    try:
        import psycopg
    except ImportError as e:
        raise RuntimeError(
            "STATE_BACKEND=postgres requires psycopg. Install with: pip install 'neuqa-pr-agent[postgres]' or pip install psycopg[binary]"
        ) from e
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS neuqa_review_state (
                    id TEXT PRIMARY KEY,
                    data JSONB NOT NULL DEFAULT '{}',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.commit()
            cur.execute(
                "SELECT data FROM neuqa_review_state WHERE id = %s",
                (STATE_KEY,),
            )
            row = cur.fetchone()
    if row is None:
        return _empty_state()
    out = row[0]
    return out if isinstance(out, dict) else _empty_state()


def _save_postgres(database_url: str, state: dict[str, Any]) -> None:
    try:
        import psycopg
    except ImportError as e:
        raise RuntimeError(
            "STATE_BACKEND=postgres requires psycopg. Install with: pip install 'neuqa-pr-agent[postgres]' or pip install psycopg[binary]"
        ) from e
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS neuqa_review_state (
                    id TEXT PRIMARY KEY,
                    data JSONB NOT NULL DEFAULT '{}',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                INSERT INTO neuqa_review_state (id, data, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
                """,
                (STATE_KEY, json.dumps(state)),
            )
            conn.commit()


def load_state(path_or_config: Union[str, _ConfigLike]) -> dict[str, Any]:
    """Load state from file (path str) or from config (postgres/file backend)."""
    if isinstance(path_or_config, str):
        return _load_file(path_or_config)
    backend = getattr(path_or_config, "state_backend", "file")
    if backend == "postgres":
        url = getattr(path_or_config, "database_url", None)
        if not url:
            raise RuntimeError("STATE_BACKEND=postgres requires config.database_url")
        return _load_postgres(url)
    path = getattr(path_or_config, "review_state_path", ".neuqa_state.json")
    return _load_file(path)


def save_state(path_or_config: Union[str, _ConfigLike], state: dict[str, Any]) -> None:
    """Save state to file (path str) or to config's backend (postgres/file)."""
    if isinstance(path_or_config, str):
        _save_file(path_or_config, state)
        return
    backend = getattr(path_or_config, "state_backend", "file")
    if backend == "postgres":
        url = getattr(path_or_config, "database_url", None)
        if not url:
            raise RuntimeError("STATE_BACKEND=postgres requires config.database_url")
        _save_postgres(url, state)
        return
    path = getattr(path_or_config, "review_state_path", ".neuqa_state.json")
    _save_file(path, state)


def get_pr_file_hashes(state: dict[str, Any], repo_url: str, pr_number: int) -> dict[str, str]:
    repo_state = state.get("repos", {}).get(repo_url, {})
    pr_state = repo_state.get("prs", {}).get(str(pr_number), {})
    return pr_state.get("files", {})


def update_pr_file_hashes(
    state: dict[str, Any],
    repo_url: str,
    pr_number: int,
    file_hashes: dict[str, str],
) -> dict[str, Any]:
    state.setdefault("repos", {})
    state["repos"].setdefault(repo_url, {})
    state["repos"][repo_url].setdefault("prs", {})
    state["repos"][repo_url]["prs"].setdefault(str(pr_number), {})
    state["repos"][repo_url]["prs"][str(pr_number)]["files"] = file_hashes
    return state


def hash_patch(patch: str | None) -> str:
    payload = patch or ""
    return sha256(payload.encode("utf-8")).hexdigest()


def hash_comment(body: str) -> str:
    """Compute digest of comment body for idempotency tracking."""
    return sha256((body or "").encode("utf-8")).hexdigest()


def should_review(
    state: dict[str, Any], repo_url: str, pr_number: int, head_sha: str
) -> bool:
    """Return True if we have not yet posted a review for this PR at this head SHA."""
    key = f"{repo_url}#{pr_number}"
    reviewed = state.get("reviewed", {})
    entry = reviewed.get(key, {})
    return entry.get("sha") != head_sha


def mark_reviewed(
    state: dict[str, Any],
    repo_url: str,
    pr_number: int,
    head_sha: str,
    comment_hash: str,
) -> None:
    """Record that we posted a review for this PR at this head SHA."""
    state.setdefault("reviewed", {})
    key = f"{repo_url}#{pr_number}"
    state["reviewed"][key] = {"sha": head_sha, "comment_hash": comment_hash}


def filter_changed_files(
    files: list[dict[str, Any]],
    previous_hashes: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    changed: list[dict[str, Any]] = []
    new_hashes: dict[str, str] = {}

    for file_info in files:
        file_path = file_info.get("filename") or file_info.get("path")
        if not file_path:
            continue
        patch = file_info.get("patch") or ""
        digest = hash_patch(patch)
        new_hashes[file_path] = digest
        if previous_hashes.get(file_path) != digest:
            changed.append(file_info)

    return changed, new_hashes
