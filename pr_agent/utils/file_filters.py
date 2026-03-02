"""File filtering for PR review."""

_SKIP_FILE_NAMES = frozenset({
    ".DS_Store",
    "Thumbs.db",
    ".gitignore",
})

_SKIP_EXTENSIONS = frozenset({
    ".md",
    ".yml",
    ".yaml",
    ".sh",
})


def should_skip_file(file_path: str) -> bool:
    """Return True if file should be skipped (not reviewable/summarized)."""
    if not file_path or not file_path.strip():
        return True

    base = file_path.split("/")[-1].split("\\")[-1]
    if base in _SKIP_FILE_NAMES:
        return True

    lower = base.lower()
    for ext in _SKIP_EXTENSIONS:
        if lower.endswith(ext):
            return True

    return False
