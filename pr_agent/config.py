import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    repo_url: str
    repo_access_token: str | None
    mcp_access_token: str | None
    mcp_auth_token: str | None
    mcp_server_url: str | None
    mcp_transport: str
    mcp_stdio_command: str | None
    mcp_stdio_args: str | None
    webhook_secret: str | None
    poll_interval_seconds: int
    state_db_path: str
    foundry_base_url: str
    foundry_model: str
    foundry_model_light: str
    foundry_model_heavy: str
    foundry_api_key: str | None
    log_level: str
    mcp_readonly: bool
    prompt_extra: str | None
    review_incremental: bool
    review_skip_simple: bool
    review_simple_max_lines: int
    review_state_path: str
    state_backend: str  # "file" | "postgres"
    database_url: str | None  # required when state_backend == "postgres"
    review_max_concurrency: int
    review_max_files: int | None


class ConfigError(RuntimeError):
    pass


def _get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def _validate_repo_url(repo_url: str) -> None:
    parsed = urlparse(repo_url)
    if not parsed.scheme or not parsed.netloc:
        raise ConfigError("REPO_URL must be a valid URL")


def _validate_foundry_base_url(url: str) -> None:
    if not url.endswith("/v1"):
        raise ConfigError("FOUNDRY_BASE_URL must end with /v1")


def load_config() -> Config:
    load_dotenv(override=False)

    repo_url = _get_env("REPO_URL")
    mcp_server_url = _get_env("MCP_SERVER_URL")
    mcp_transport_raw = (_get_env("MCP_TRANSPORT", "http") or "http").lower()
    mcp_stdio_command = _get_env("MCP_STDIO_COMMAND")
    mcp_stdio_args = _get_env("MCP_STDIO_ARGS")
    foundry_base_url = _get_env("FOUNDRY_BASE_URL")
    foundry_model = _get_env("FOUNDRY_MODEL")
    foundry_model_light = _get_env("FOUNDRY_MODEL_LIGHT")
    foundry_model_heavy = _get_env("FOUNDRY_MODEL_HEAVY")

    if not repo_url:
        raise ConfigError("REPO_URL is required")
    if not foundry_base_url:
        raise ConfigError("FOUNDRY_BASE_URL is required")
    if not foundry_model:
        raise ConfigError("FOUNDRY_MODEL is required")

    _validate_repo_url(repo_url)
    _validate_foundry_base_url(foundry_base_url)

    repo_access_token = _get_env("REPO_ACCESS_TOKEN")
    mcp_access_token = _get_env("MCP_ACCESS_TOKEN")
    mcp_auth_token = _get_env("MCP_AUTH_TOKEN") or repo_access_token
    webhook_secret = _get_env("WEBHOOK_SECRET")
    poll_interval_seconds = int(_get_env("POLL_INTERVAL_SECONDS", "60") or "60")
    state_db_path = (
        _get_env("STATE_DB_PATH")
        or _get_env("REVIEW_STATE_PATH")
        or ".neuqa_state.json"
    ) or ".neuqa_state.json"

    if mcp_server_url:
        mcp_transport = "remote"
    elif mcp_transport_raw == "stdio" and mcp_stdio_command:
        mcp_transport = "stdio"
        mcp_server_url = None
    else:
        raise ConfigError(
            "Set MCP_SERVER_URL for remote MCP (e.g. https://api.githubcopilot.com/mcp/) "
            "or MCP_STDIO_COMMAND for stdio transport."
        )

    if mcp_transport not in {"remote", "stdio"}:
        raise ConfigError("MCP_TRANSPORT must be 'remote' or 'stdio'")

    foundry_api_key = _get_env("FOUNDRY_API_KEY")
    log_level = _get_env("LOG_LEVEL", "info") or "info"
    prompt_extra = _get_env("PROMPT_EXTRA")

    incremental_raw = (_get_env("REVIEW_INCREMENTAL", "false") or "false").lower()
    review_incremental = incremental_raw not in {"false", "f", "no", "n", "0", "off"}

    skip_simple_raw = (_get_env("REVIEW_SKIP_SIMPLE", "false") or "false").lower()
    review_skip_simple = skip_simple_raw not in {"false", "f", "no", "n", "0", "off"}

    review_simple_max_lines = int(_get_env("REVIEW_SIMPLE_MAX_LINES", "40") or "40")
    review_state_path = state_db_path
    state_backend_raw = (_get_env("STATE_BACKEND", "file") or "file").lower()
    state_backend = "postgres" if state_backend_raw == "postgres" else "file"
    database_url = _get_env("DATABASE_URL") or _get_env("POSTGRES_URL")
    if state_backend == "postgres" and not database_url:
        raise ConfigError(
            "STATE_BACKEND=postgres requires DATABASE_URL or POSTGRES_URL"
        )
    review_max_concurrency = int(_get_env("REVIEW_MAX_CONCURRENCY", "6") or "6")
    review_max_files_raw = _get_env("REVIEW_MAX_FILES")
    review_max_files: int | None = (
        int(review_max_files_raw) if review_max_files_raw and review_max_files_raw.isdigit() else None
    )

    mcp_readonly_raw = (_get_env("MCP_READONLY", "false") or "false").lower()
    mcp_readonly = mcp_readonly_raw not in {"false", "f", "no", "n", "0", "off"}

    return Config(
        repo_url=repo_url,
        repo_access_token=repo_access_token,
        mcp_access_token=mcp_access_token,
        mcp_auth_token=mcp_auth_token,
        mcp_server_url=mcp_server_url,
        mcp_transport=mcp_transport,
        mcp_stdio_command=mcp_stdio_command,
        mcp_stdio_args=mcp_stdio_args,
        webhook_secret=webhook_secret,
        poll_interval_seconds=poll_interval_seconds,
        state_db_path=state_db_path,
        foundry_base_url=foundry_base_url,
        foundry_model=foundry_model,
        foundry_model_light=foundry_model_light or foundry_model,
        foundry_model_heavy=foundry_model_heavy or foundry_model,
        foundry_api_key=foundry_api_key,
        log_level=log_level,
        mcp_readonly=mcp_readonly,
        prompt_extra=prompt_extra,
        review_incremental=review_incremental,
        review_skip_simple=review_skip_simple,
        review_simple_max_lines=review_simple_max_lines,
        review_state_path=review_state_path,
        state_backend=state_backend,
        database_url=database_url,
        review_max_concurrency=review_max_concurrency,
        review_max_files=review_max_files,
    )
