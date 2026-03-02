# Deployment

Ways to run the NEUQA PR Agent: local CLI, web app, polling, webhook, and CI.

## Prerequisites

- Python 3.10+
- `.env` created from `.env.example` with required variables (see [CONFIGURATION.md](CONFIGURATION.md))
- MCP: either remote MCP server URL or stdio (e.g. Docker) with GitHub token
- Foundry (or OpenAI-compatible) endpoint for summarization

## Local CLI

```bash
pip install -e .
python -m pr_agent.main --pr <PR_NUMBER>
```

To post the review as a PR comment:

```bash
python -m pr_agent.main --pr <PR_NUMBER> --post
```

Optional: `--mode fast|full`, `--incremental`, `--skip-simple`.

## Web app (FastAPI)

```bash
uvicorn pr_agent.web.app:app --reload --host 0.0.0.0 --port 8080
```

Use `?pr=123` or `?issue=456` for PR/issue context. Requires MCP toolsets: `repos`, `issues`, `pull_requests`, `actions`.

## Polling mode

Review open PRs on an interval (e.g. when webhooks are not available):

```bash
python -m pr_agent.main --poll
```

Set `POLL_INTERVAL_SECONDS` in `.env` (default 60).

## Webhook (GitHub)

1. In GitHub repo: Settings → Webhooks → Add webhook.
2. Payload URL: `https://<your-host>/webhook/github`.
3. Content type: `application/json`.
4. Secret: set `WEBHOOK_SECRET` in your environment (same value as in GitHub).
5. Events: `pull_request` (opened, synchronize).

The app verifies the signature and runs a review + posts a comment on `pull_request` events.

## CI (e.g. GitHub Actions)

1. Add secrets: `REPO_ACCESS_TOKEN` or use `GITHUB_TOKEN`; set `REPO_URL`, `FOUNDRY_BASE_URL`, `FOUNDRY_MODEL` (and optional `FOUNDRY_API_KEY`) as env or secrets.
2. Run on `pull_request` (e.g. opened, synchronize):
   ```yaml
   - run: python -m pr_agent.main --pr ${{ github.event.pull_request.number }} --post
   ```
3. Ensure MCP is reachable from the runner (remote URL or stdio with token in env).

See [CONFIGURATION.md](CONFIGURATION.md) for where to store secrets (GitHub Secrets, env, or platform secrets).
