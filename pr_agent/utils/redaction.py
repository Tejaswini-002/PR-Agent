import re

SECRET_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xoxb-[A-Za-z0-9-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)apikey\s*[:=]\s*[^\s\"']+"),
    re.compile(r"(?i)token\s*[:=]\s*[^\s\"']+"),
    re.compile(r"(?i)password\s*[:=]\s*[^\s\"']+"),
    re.compile(r"(?i)secret\s*[:=]\s*[^\s\"']+"),
    re.compile(r"(?i)REPO_ACCESS_TOKEN\s*=\s*[^\s\"']+"),
    re.compile(r"(?i)GITHUB_TOKEN\s*=\s*[^\s\"']+"),
]


def redact_text(text: str) -> str:
    if not text:
        return text
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("***REDACTED***", redacted)
    return redacted
