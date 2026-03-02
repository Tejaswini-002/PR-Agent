from __future__ import annotations

from typing import Any


def _section(title: str, body: str) -> str:
    return f"## {title}\n\n{body}\n\n"


def _sanitize_diff_line(line: str, max_len: int = 120) -> str:
    """Strip diff prefix and truncate so raw diff lines are readable."""
    s = str(line).strip()
    if s.startswith("+") and not s.startswith("+++"):
        s = s[1:].strip()
    elif s.startswith("-") and not s.startswith("---"):
        s = s[1:].strip()
    if len(s) > max_len:
        s = s[: max_len - 3].rstrip() + "..."
    return s or "(empty)"


def _is_likely_raw_diff(s: str) -> bool:
    """True if this looks like raw diff output rather than a human summary."""
    s = str(s).strip()
    if not s or s in ("+", "-", "(empty)"):
        return True
    if s.startswith("@@") or "\n" in s:
        return True
    if s.startswith("+") or s.startswith("-"):
        return len(s) > 60  # long diff line
    return False


def _format_added_removed_modified(
    added: list[Any], removed: list[Any], modified: list[Any], max_items: int = 3
) -> tuple[list[str], list[str], list[str]]:
    """Normalize and sanitize; keep only short, human-readable items (skip raw diff dump)."""
    def take(items: list[Any]) -> list[str]:
        out: list[str] = []
        for i, x in enumerate(items):
            if i >= max_items:
                break
            s = _sanitize_diff_line(x) if isinstance(x, str) else str(x).strip()
            if s and s != "(empty)" and not _is_likely_raw_diff(s):
                out.append(s)
        return out

    return take(added), take(removed), take(modified)


def _format_file_technical(file_path: str, fs: dict[str, Any]) -> str:
    """Format one file as a compact, readable card (no raw diff dump)."""
    what_changed = (fs.get("what_changed") or "").strip() or "—"
    ftype = fs.get("technical_type") or fs.get("type") or "—"
    added = fs.get("technical_added") or fs.get("added") or []
    removed = fs.get("technical_removed") or fs.get("removed") or []
    modified = fs.get("technical_modified") or fs.get("modified") or []
    impact = fs.get("technical_impact") or fs.get("impact") or []
    if not isinstance(added, list):
        added = [added] if added else []
    if not isinstance(removed, list):
        removed = [removed] if removed else []
    if not isinstance(modified, list):
        modified = [modified] if modified else []
    if not isinstance(impact, list):
        impact = [impact] if impact else []

    added_fmt, removed_fmt, modified_fmt = _format_added_removed_modified(added, removed, modified)
    has_details = added_fmt or removed_fmt or modified_fmt

    diff_stats = fs.get("diff_stats")
    stats_str = ""
    if isinstance(diff_stats, dict):
        a = diff_stats.get("added", 0)
        d = diff_stats.get("removed", 0)
        if a is not None and d is not None:
            stats_str = f" · +{a} −{d} lines"
        elif a is not None:
            stats_str = f" · +{a} lines"

    impact_fmt = [str(i).strip() for i in impact if str(i).strip()] if impact else []
    impact_line = " ".join(impact_fmt) if impact_fmt else "—"

    lines = [
        f"**`{file_path}`**{stats_str}  \n*{ftype}*",
        "",
        f"{what_changed}",
        "",
        f"*Impact:* {impact_line}",
    ]
    if has_details:
        lines.append("")
        if added_fmt:
            lines.append("Added: " + " · ".join(added_fmt[:3]))
        if removed_fmt:
            lines.append("Removed: " + " · ".join(removed_fmt[:3]))
        if modified_fmt:
            lines.append("Modified: " + " · ".join(modified_fmt[:3]))
    return "\n".join(lines)


def _high_level_summary_paragraph(
    intent: str, summary_bullets: list[str]
) -> str:
    """One paragraph describing the overall PR impact (example-style)."""
    intent = (intent or "").strip() or "Not enough information in this PR to confirm."
    if not summary_bullets:
        return intent
    bullets = " ".join(b.strip() for b in summary_bullets if b and str(b).strip())
    if not bullets:
        return intent
    return f"The changes in this pull request {intent.lower().rstrip('.')}. {bullets}"


def _file_summary_table(file_summaries: list[dict[str, Any]]) -> str:
    """Markdown table: File | Summary (one paragraph per file)."""
    if not file_summaries:
        return ""
    rows = []
    for fs in file_summaries:
        path = fs.get("file_path") or fs.get("path") or "unknown"
        what = (fs.get("what_changed") or "").strip() or "—"
        impact_list = fs.get("technical_impact") or fs.get("impact") or []
        if not isinstance(impact_list, list):
            impact_list = [impact_list] if impact_list else []
        impact_str = " ".join(str(i).strip() for i in impact_list if str(i).strip())
        if impact_str and impact_str not in what:
            summary = f"{what} {impact_str}".strip()
        else:
            summary = what
        rows.append(f"| `{path}` | {summary} |")
    header = "| File | Summary |\n| --- | --- |"
    return header + "\n" + "\n".join(rows)


def _changed_files_section(file_summaries: list[dict[str, Any]]) -> str:
    """List changed files with name and one-line summary."""
    if not file_summaries:
        return ""
    lines = []
    for fs in file_summaries:
        path = fs.get("file_path") or fs.get("path") or "unknown"
        what = (fs.get("what_changed") or "").strip() or "—"
        diff_stats = fs.get("diff_stats")
        stats_str = ""
        if isinstance(diff_stats, dict):
            a = diff_stats.get("added")
            d = diff_stats.get("removed")
            if a is not None and d is not None:
                stats_str = f" ({a:+d} / {d} lines)"
            elif a is not None:
                stats_str = f" ({a:+d} lines)"
        lines.append(f"- **{path}**{stats_str}: {what}")
    return "\n".join(lines)


def _risks(items: list[dict[str, Any]]) -> str:
    if not items:
        return "—"
    lines = []
    for risk in items:
        severity = risk.get("severity", "Low")
        desc = risk.get("description", "")
        lines.append(f"**{severity}** — {desc}")
    return "\n\n".join(lines)


def _technical_summary_section(file_summaries: list[dict[str, Any]]) -> str:
    """Build PR Technical Summary: compact cards per file."""
    if not file_summaries:
        return ""
    parts: list[str] = []
    for i, fs in enumerate(file_summaries):
        if i > 0:
            parts.append("---")
            parts.append("")
        path = fs.get("file_path") or fs.get("path") or "unknown"
        parts.append(_format_file_technical(path, fs))
        parts.append("")
    return "\n".join(parts).strip()


def format_review_comment(summary: dict[str, Any]) -> str:
    summary_bullets = summary.get("summary", [])
    intent = summary.get("intent", "Not enough information in this PR to confirm.")
    file_summaries = summary.get("file_summaries", [])
    risks = summary.get("risks", [])
    tests = (summary.get("tests") or "").strip() or "—"

    high_level = _high_level_summary_paragraph(intent, summary_bullets)
    file_table = _file_summary_table(file_summaries)

    sections = [
        _section("High-Level Summary", high_level),
    ]
    if file_table:
        sections.append(_section("Summary by file", file_table))
    tech = _technical_summary_section(file_summaries)
    if tech:
        sections.append(_section("Details by file", tech))
    sections.extend([
        _section("Risks", _risks(risks)),
        _section("Tests", tests),
    ])
    return "\n".join(sections).strip() + "\n"
