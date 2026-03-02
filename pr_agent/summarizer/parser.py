"""Safe parsing of LLM summary output with fallback heuristics."""

from __future__ import annotations

import json
import re
from typing import Any

from pr_agent.utils.placeholder import is_placeholder_summary


def _strip_diff_markers(text: str) -> str:
    """Remove raw diff markers from text for display."""
    if not text or not isinstance(text, str):
        return str(text) if text else ""
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("+++", "---", "@@")):
            continue
        if re.match(r"^[+-](?![-\d.])\s", stripped) or re.match(r"^[+-]$", stripped):
            continue
        cleaned.append(line)
    result = "\n".join(cleaned).strip()
    return result if result else text


def _extract_json_block(text: str) -> str | None:
    """Extract first complete {...} block from text."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, c in enumerate(text[start:], start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_high_level_summary(
    raw: str | dict[str, Any],
    changed_files: list[str],
) -> dict[str, Any]:
    """
    Parse LLM output into high_level_summary schema.
    Tries strict JSON, then repair, then heuristic fallback.
    """
    if isinstance(raw, dict):
        return _validate_and_normalize(raw, changed_files)

    text = str(raw).strip()
    # Strip code fences
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()

    # 1. Strict json.loads
    try:
        data = json.loads(text)
        return _validate_and_normalize(data, changed_files)
    except json.JSONDecodeError:
        pass

    # 2. Extract {...} block and re-parse
    snippet = _extract_json_block(text)
    if snippet:
        try:
            data = json.loads(snippet)
            return _validate_and_normalize(data, changed_files)
        except json.JSONDecodeError:
            pass

    # 3. Heuristic fallback
    return _heuristic_fallback(text, changed_files)


def _validate_and_normalize(data: dict[str, Any], changed_files: list[str]) -> dict[str, Any]:
    """Ensure required fields exist and strip diff markers from summaries."""
    high = (data.get("high_level_summary") or "").strip()
    high = _strip_diff_markers(high) or "Summary could not be generated."
    impact = _strip_diff_markers((data.get("impact") or "").strip())

    raw_files = data.get("file_summaries") or []
    raw_by_path: dict[str, dict[str, Any]] = {}
    for f in raw_files:
        fp = f.get("file") or f.get("file_path") or ""
        if fp:
            raw_by_path[fp] = f
            raw_by_path[fp.split("/")[-1]] = f  # also by basename

    file_summaries: list[dict[str, Any]] = []
    valid_types = {"Docs", "Logic Change", "Refactor", "Config", "Dependency", "Test"}
    used_raw = set()

    for path in changed_files:
        match = raw_by_path.get(path)
        if not match:
            match = raw_by_path.get(path.split("/")[-1])
        if match and id(match) not in used_raw:
            used_raw.add(id(match))
            raw = match.get("summary") or match.get("what_changed") or ""
            if isinstance(raw, list) and raw:
                summary = str(raw[0]).strip()
            else:
                summary = str(raw).strip()
            summary = _strip_diff_markers(summary)
            if is_placeholder_summary(summary):
                summary = f"Changes in {path}."
            summary = summary or f"Changes in {path}."
            ftype = (match.get("type") or match.get("technical_type") or "Logic Change").strip()
            if ftype not in valid_types:
                ftype = "Logic Change"
            file_summaries.append({"file": path, "type": ftype, "summary": summary})
        else:
            file_summaries.append({"file": path, "type": "Logic Change", "summary": f"Changes in {path}."})

    return {
        "high_level_summary": high,
        "file_summaries": file_summaries,
        "impact": impact,
    }


def _heuristic_fallback(text: str, changed_files: list[str]) -> dict[str, Any]:
    """Fallback when JSON parsing fails: extract first 2-3 sentences, placeholder file rows."""
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    high = ". ".join(sentences[:3]) + "." if sentences else "Summary could not be generated."
    high = _strip_diff_markers(high)
    file_summaries = [
        {"file": fp, "type": "Logic Change", "summary": f"Changes in {fp}."}
        for fp in changed_files
    ]
    return {
        "high_level_summary": high,
        "file_summaries": file_summaries,
        "impact": "",
    }
