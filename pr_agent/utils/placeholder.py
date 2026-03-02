"""Detect and fix LLM placeholder responses like 'See Foundry Model Summary below'."""

from __future__ import annotations

# Phrases that indicate a generic placeholder instead of real analysis
_PLACEHOLDER_PHRASES = frozenset({
    "see foundry model summary below",
    "see foundry model summary",
    "see summary below",
    "see summary",
    "refer to summary below",
    "see above",
    "see below",
    "see the summary",
    "see the model summary",
})


def is_placeholder_summary(text: str | None) -> bool:
    """Return True if text looks like a generic placeholder, not a real file summary."""
    if not text or not isinstance(text, str):
        return True
    t = text.strip().lower()
    if len(t) < 20:  # Very short responses are often placeholders
        return True
    for phrase in _PLACEHOLDER_PHRASES:
        if phrase in t:
            return True
    return False


def sanitize_file_summary(
    summary: dict[str, object],
    file_path: str,
) -> dict[str, object]:
    """
    Replace placeholder what_changed/summary with a fallback.
    Modifies summary in place and returns it.
    """
    fixed = dict(summary)
    fallback = f"Changes in {file_path}."

    # Fix what_changed
    what = fixed.get("what_changed")
    if is_placeholder_summary(str(what) if what else None):
        fixed["what_changed"] = fallback

    # Fix summary (can be list or str)
    raw_summary = fixed.get("summary")
    if isinstance(raw_summary, str) and is_placeholder_summary(raw_summary):
        fixed["summary"] = [fallback]
    elif isinstance(raw_summary, list):
        cleaned = []
        for item in raw_summary:
            s = str(item).strip() if item else ""
            if is_placeholder_summary(s):
                cleaned.append(fallback)
            else:
                cleaned.append(item)
        if cleaned != raw_summary:
            fixed["summary"] = cleaned

    return fixed
