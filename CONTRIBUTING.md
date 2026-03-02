# Contributing to NEUQA PR Agent

## Documentation first

The **docs/** folder is the source of truth. Before changing behavior or adding features:

- Read [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for config and secrets.
- Read [docs/GUARDRAILS.md](docs/GUARDRAILS.md) for safety rules.
- Follow [docs/DEVELOPMENT_INSTRUCTIONS.md](docs/DEVELOPMENT_INSTRUCTIONS.md) for architecture and patterns.

AI assistants should follow [vibe-context/AGENTS.md](vibe-context/AGENTS.md).

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env   # fill in values; never commit .env
```

See [docs/LOCAL_DEVELOPMENT.md](docs/LOCAL_DEVELOPMENT.md) for full setup.

## Config and secrets

- Do **not** add secrets to config files or code. Use environment variables or a secrets manager.
- Non-secret defaults may go in `config/defaults.yaml`. Document new env vars in `.env.example` and `docs/CONFIGURATION.md`.

## Code and tests

- Main package: `pr_agent/`. Keep structure aligned with `docs/DEVELOPMENT_INSTRUCTIONS.md`.
- Run tests: `pytest`.
- Run CLI: `python -m pr_agent.main --pr <number>` (optionally `--post`).

## Submitting changes

- Open a PR with a clear description. Link to docs if you change behavior or config.
- Ensure the PR does not introduce secrets or violate [docs/GUARDRAILS.md](docs/GUARDRAILS.md).
