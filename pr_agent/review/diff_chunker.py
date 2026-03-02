from __future__ import annotations


def chunk_diff(diff_text: str, max_chars: int = 8000, max_chunks: int = 10) -> list[str]:
    if not diff_text:
        return []
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in diff_text.splitlines():
        line_len = len(line) + 1
        if current_len + line_len > max_chars and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
            if len(chunks) >= max_chunks:
                break
        current.append(line)
        current_len += line_len

    if current and len(chunks) < max_chunks:
        chunks.append("\n".join(current))

    return chunks
