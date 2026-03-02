from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DiffStats:
    added: int
    deleted: int

    @property
    def total(self) -> int:
        return self.added + self.deleted


def count_changed_lines(patch: str | None) -> DiffStats:
    if not patch:
        return DiffStats(added=0, deleted=0)
    added = 0
    deleted = 0
    for line in patch.splitlines():
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            deleted += 1
    return DiffStats(added=added, deleted=deleted)
