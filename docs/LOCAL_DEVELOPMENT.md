# Local Development

Get the NEUQA PR Agent running on your machine.

## 1. Clone and install

```bash
git clone <repo-url>
cd "PR Agent"
pip install -e .
```

## 2. Configuration

Copy the example env file and fill in values (never commit `.env`):

```bash
cp .env.example .env
```

Edit `.env`. Minimum:

- `REPO_URL` — GitHub repo to review (e.g. `https://github.com/org/repo`)
- `REPO_ACCESS_TOKEN` or `MCP_AUTH_TOKEN` — token for GitHub/MCP access
- `MCP_SERVER_URL` (remote MCP) **or** `MCP_TRANSPORT=stdio` + `MCP_STDIO_COMMAND` + `MCP_STDIO_ARGS` (stdio MCP)
- `FOUNDRY_BASE_URL` — must end with `/v1`
- `FOUNDRY_MODEL` — model name

See [CONFIGURATION.md](CONFIGURATION.md) and [.env.example](../.env.example) for all options.

## 3. MCP setup

- **Remote**: set `MCP_SERVER_URL` (e.g. `https://api.githubcopilot.com/mcp/`) and auth token. No subprocess.
- **Stdio (Docker)**: set `MCP_TRANSPORT=stdio`, `MCP_STDIO_COMMAND=docker`, and `MCP_STDIO_ARGS=run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN=... ghcr.io/github/github-mcp-server stdio --toolsets=all`. Ensure `GITHUB_PERSONAL_ACCESS_TOKEN` or `REPO_ACCESS_TOKEN` is in `.env` so the CLI can pass it into the container.

## 4. Verify Foundry

```bash
python scripts/test_foundry_summary.py
```

This checks connectivity and a minimal summary. If it fails, fix `FOUNDRY_BASE_URL` and network access.

## 5. Run CLI

```bash
# Review PR (no comment posted)
python -m pr_agent.main --pr <PR_NUMBER>

# Post comment to PR
python -m pr_agent.main --pr <PR_NUMBER> --post
```

## 6. Run web app

```bash
uvicorn pr_agent.web.app:app --reload --host 0.0.0.0 --port 8080
```

Open `http://localhost:8080`. Use `?pr=123` for PR context.

## 7. Test on a real PR

```bash
python scripts/test_foundry_real_pr.py <PR_NUMBER>
```

Uses MCP to fetch the PR and runs the same pipeline as the CLI.

## Troubleshooting

- **Empty / non-JSON response**: Check `MCP_SERVER_URL` and that the server returns valid JSON.
- **Authorization required**: Set `MCP_AUTH_TOKEN` or `REPO_ACCESS_TOKEN` with a valid token.
- **Connection refused**: Ensure MCP and Foundry endpoints are reachable (no firewall blocking).
- **Missing tools**: MCP server must expose at least `pull_requests` (and related) toolsets.

Documentation in `docs/` is the source of truth; see [README](README.md) for the doc index.
