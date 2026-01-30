def parse_command(text: str) -> str | None:
    t = (text or "").strip().lower()
    if t.startswith("/review"):
        return "review"
    if t.startswith("/describe"):
        return "describe"
    return None
