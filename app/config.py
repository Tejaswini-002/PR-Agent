import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    port: int
    github_app_id: str
    github_private_key_pem: str
    github_webhook_secret: str

    openai_api_key: str
    openai_base_url: str
    openai_model: str

    max_files: int
    max_patch_chars: int

def _get(name: str, default: str | None = None, required: bool = False) -> str:
    v = os.getenv(name, default)
    if required and (v is None or v.strip() == ""):
        raise RuntimeError(f"Missing required env var: {name}")
    return v

def get_settings() -> Settings:
    return Settings(
        port=int(_get("PORT", "8000")),
        github_app_id=_get("GITHUB_APP_ID", required=True),
        github_private_key_pem=_get("GITHUB_APP_PRIVATE_KEY_PEM", required=True).replace("\\n", "\n"),
        github_webhook_secret=_get("GITHUB_WEBHOOK_SECRET", required=True),

        openai_api_key=_get("OPENAI_API_KEY", required=True),
        openai_base_url=_get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_model=_get("OPENAI_MODEL", "gpt-4o-mini"),

        max_files=int(_get("MAX_FILES", "20")),
        max_patch_chars=int(_get("MAX_PATCH_CHARS", "120000")),
    )
