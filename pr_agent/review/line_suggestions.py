from __future__ import annotations

import re
from typing import Any

HUNK_RE = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def extract_added_lines(patch: str | None, max_lines: int = 40) -> list[dict[str, Any]]:
    if not patch:
        return []
    added_lines: list[dict[str, Any]] = []
    new_line_no = 0

    for raw in patch.splitlines():
        match = HUNK_RE.match(raw)
        if match:
            new_line_no = int(match.group(1))
            continue

        if raw.startswith("+") and not raw.startswith("+++"):
            added_lines.append({"line": new_line_no, "content": raw[1:]})
            new_line_no += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            continue
        else:
            if raw.startswith("\\"):
                continue
            new_line_no += 1

        if len(added_lines) >= max_lines:
            break

    return added_lines
