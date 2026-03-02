# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- **Documentation (structure inspired by AWS FAST template):**
  - `docs/` — CONFIGURATION.md, DEPLOYMENT.md, LOCAL_DEVELOPMENT.md, DEVELOPMENT_INSTRUCTIONS.md, GUARDRAILS.md, SECURITY.md
  - `config/defaults.yaml` — non-secret default values (reference)
  - `vibe-context/AGENTS.md` — rules for AI assistants
- **Configuration and secrets:**
  - Clear split: secrets only in env (or secrets manager); non-secret defaults in `config/`
  - `.env.example` expanded with all variables and comments; `.gitignore` updated so `.env.example` is tracked and only `.env`, `.env.local`, `.env.*.local` are ignored
- CONTRIBUTING.md, CHANGELOG.md

### Changed
- README updated to point to `docs/` for setup, deployment, and configuration.

### Removed
- Root-level duplicate docs: `Gaudrails.md`, `guardrails.md`, `development-instruction.md` (canonical versions in `docs/` only).
- Legacy `neuqa_pr_agent/` package (stub only; real package is `pr_agent`).
- Third-party `github-mcp-server/` clone; use Docker image `ghcr.io/github/github-mcp-server` or remote MCP (see docs).
- Build artifacts: `*.egg-info/` and runtime state `.neuqa_state.json` now in `.gitignore`.

## [0.1.0] — initial release

- Python PR reviewer using GitHub MCP and Foundry (OpenAI-compatible) for summarization.
- CLI, web app, polling, webhook, and CI deployment options.
