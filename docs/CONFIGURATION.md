# Configuration and Secrets

Configuration is split into **non-secret defaults** (in `config/`) and **secrets / environment-specific values** (environment variables only, never committed).

## Principles

1. **Secrets never go in config files or code.** Use environment variables or a secrets manager (e.g. GitHub Secrets in CI).
2. **Default behavior** is defined in `config/defaults.yaml` (optional overrides). Env vars override file defaults.
3. **Local development**: copy `.env.example` to `.env` and fill in values. `.env` is git-ignored.

## Non-secret defaults (config/)

| File | Purpose |
|------|---------|
| `config/defaults.yaml` | Default values for review behavior, logging, and feature flags. Overridden by env vars. |

Example: `REVIEW_SIMPLE_MAX_LINES` can be set in `defaults.yaml` for the team default; individuals override via `.env`.

## Environment variables

### Required

| Variable | Description | Example (no real secrets) |
|----------|-------------|---------------------------|
| `REPO_URL` | Target GitHub repo URL | `https://github.com/org/repo` |
| `FOUNDRY_BASE_URL` | OpenAI-compatible API base (must end with `/v1`) | `http://127.0.0.1:56077/openai/v1` |
| `FOUNDRY_MODEL` | Model identifier for summarization | `phi-4` |

### MCP (one of the following)

- **Remote MCP**: `MCP_SERVER_URL` (e.g. `https://api.githubcopilot.com/mcp/`). Optionally `MCP_AUTH_TOKEN` or `REPO_ACCESS_TOKEN`.
- **Stdio MCP**: `MCP_TRANSPORT=stdio`, `MCP_STDIO_COMMAND`, `MCP_STDIO_ARGS`. Token via `REPO_ACCESS_TOKEN` or `GITHUB_PERSONAL_ACCESS_TOKEN` in env (passed to subprocess).

### Optional (secrets / tuning)

| Variable | Description | Where to set |
|----------|-------------|--------------|
| `REPO_ACCESS_TOKEN` | GitHub PAT for MCP/repo access | `.env` (local), GitHub Secrets (CI) |
| `MCP_AUTH_TOKEN` | Bearer token for remote MCP | `.env` or secrets manager |
| `WEBHOOK_SECRET` | GitHub webhook signature verification | `.env` or secrets manager |
| `FOUNDRY_API_KEY` | API key if required by Foundry endpoint | `.env` or secrets manager |
| `LOG_LEVEL` | `info`, `debug` | `.env` or `config/defaults.yaml` |
| `REVIEW_INCREMENTAL`, `REVIEW_SKIP_SIMPLE`, `REVIEW_SIMPLE_MAX_LINES` | Review behavior | `.env` or defaults.yaml |
| `STATE_DB_PATH` / `REVIEW_STATE_PATH` | State file path | `.env` |
| `STATE_BACKEND`, `DATABASE_URL` | Postgres state backend | `.env` (production) |

See [.env.example](../.env.example) for a full list with placeholders.

## Where to store secrets

- **Local**: `.env` (create from `.env.example`; never commit `.env`).
- **CI (e.g. GitHub Actions)**: Use GitHub Secrets; map to env vars in the workflow.
- **Production / hosted**: Use your platform’s secrets (e.g. Azure Key Vault, AWS Secrets Manager) and inject as environment variables.

## MCP server

This repo does not ship the GitHub MCP server source. Use either:
- **Remote:** `MCP_SERVER_URL` (e.g. `https://api.githubcopilot.com/mcp/`), or  
- **Stdio (Docker):** `docker run -i --rm ghcr.io/github/github-mcp-server stdio --toolsets=all` with token in env (see [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md)).

## Validation

`pr_agent.config.load_config()` validates required variables and URLs at startup. Fix any `ConfigError` before running the agent or web app.
