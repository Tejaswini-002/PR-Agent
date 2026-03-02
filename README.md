# NEUQA AI PR Reviewer Agent (Python)

Python-based GitHub Pull Request reviewer using **GitHub MCP Server** for GitHub access and **Foundry Local** (or any OpenAI-compatible API) for summarization. Structure and documentation follow patterns inspired by the [Fullstack Solution Template for AgentCore (FAST)](https://github.com/awslabs/fullstack-solution-template-for-agentcore). The solution runs on Azure.

## Features

- MCP-only GitHub access (PR metadata, files, diffs, comments)
- Foundry Local / OpenAI-compatible API for summarization
- Chunked diffs per file with incremental summaries
- Structured PR review (summary, intent, risks, tests, action items)
- Line-by-line suggestions (diff-aware)
- Incremental/continuous reviews; light/heavy model selection; smart skip for trivial changes
- Chat with bot (PR context Q&A in the UI)
- Webhook + polling; idempotent comments (no duplicates per head SHA)

## Project structure

```
├── pr_agent/           # Main package (CLI, MCP, summarizer, review, web)
├── config/             # Non-secret defaults (defaults.yaml)
├── docs/               # Authoritative documentation
├── vibe-context/       # AI assistant rules (AGENTS.md)
├── scripts/            # Test and helper scripts
├── tests/
├── .env.example        # Env template (copy to .env; never commit .env)
├── pyproject.toml
└── README.md
```

**Documentation:** All setup, configuration, and deployment details live in **[docs/](docs/)**. Start with:

- [docs/README.md](docs/README.md) — doc index  
- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — env vars, config, and **secrets**  
- [docs/LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md) — local setup  
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — CLI, web, webhook, CI  

Guardrails and architecture: [docs/GUARDRAILS.md](docs/GUARDRAILS.md), [docs/DEVELOPMENT_INSTRUCTIONS.md](docs/DEVELOPMENT_INSTRUCTIONS.md).

## Quick start

1. **Config and secrets**
   - Copy `cp .env.example .env` and set required values (see [docs/CONFIGURATION.md](docs/CONFIGURATION.md)).
   - **Never commit `.env`.** Use GitHub Secrets (or your platform’s secret store) in CI.

2. **Install**
   ```bash
   pip install -e .
   ```

3. **Run**
   ```bash
   python -m pr_agent.main --pr <number>           # review only
   python -m pr_agent.main --pr <number> --post   # post comment
   ```

4. **Web app**
   ```bash
   uvicorn pr_agent.web.app:app --reload --host 0.0.0.0 --port 8080
   ```

## Configuration and secrets

- **Secrets** (tokens, API keys, webhook secret): only in environment variables or a secrets manager—never in repo or config files.
- **Non-secret defaults:** optional `config/defaults.yaml`; env vars override.
- Full reference: [docs/CONFIGURATION.md](docs/CONFIGURATION.md). Security: [docs/SECURITY.md](docs/SECURITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). AI assistants: [vibe-context/AGENTS.md](vibe-context/AGENTS.md).

## License

MIT.
