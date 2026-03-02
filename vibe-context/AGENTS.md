# Rules for AI Assistants

**If you are an AI assistant working in this repository, follow these rules.**

1. **Read the docs first.** The `docs/` folder is the source of truth. Before changing behavior, config, or deployment, read the relevant doc (e.g. [CONFIGURATION.md](../docs/CONFIGURATION.md), [GUARDRAILS.md](../docs/GUARDRAILS.md), [DEVELOPMENT_INSTRUCTIONS.md](../docs/DEVELOPMENT_INSTRUCTIONS.md)).

2. **Follow existing patterns.** Match the project’s structure and style. The main package is `pr_agent/`; config and secrets are documented in [CONFIGURATION.md](../docs/CONFIGURATION.md). Do not add secrets to config files or code.

3. **Respect guardrails.** [GUARDRAILS.md](../docs/GUARDRAILS.md) defines safety rules (no secret leakage, MCP-only GitHub access, prompt-injection defense). Any new feature or prompt change must comply.

4. **Config and secrets.** Non-secret defaults may go in `config/defaults.yaml`. Secrets (tokens, API keys, webhook secrets) belong only in environment variables or a secrets manager—never in repo or config files. Use `.env.example` as the template; never commit `.env`.

5. **Testing.** Prefer running the CLI or scripts locally to verify changes. Use `python -m pr_agent.main --pr <n>` and `scripts/test_foundry_summary.py` as needed.

6. **Recommend docs to users.** For setup, deployment, or config questions, point to `docs/` (e.g. [LOCAL_DEVELOPMENT.md](../docs/LOCAL_DEVELOPMENT.md), [CONFIGURATION.md](../docs/CONFIGURATION.md), [DEPLOYMENT.md](../docs/DEPLOYMENT.md)).

**Always follow these rules when working in this project.**
