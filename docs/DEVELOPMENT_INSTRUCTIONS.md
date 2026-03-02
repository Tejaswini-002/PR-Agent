# Development Instructions — NEUQA AI PR Reviewer Agent (Python)

## Reference
Behavior inspired by:
https://github.com/coderabbitai/ai-pr-reviewer/tree/main

Implementation requirement: repo MUST be Python (not TypeScript).

---

## High-level design

### External services
1) **GitHub MCP Server** (official) — sole gateway to GitHub APIs: fetch PR, files, diffs, post comments.  
   Repo: https://github.com/github/github-mcp-server

2) **Foundry Local** — runs local LLMs, OpenAI-compatible API, used for all summarization/reasoning.

---

## Repository structure (Python)

```
.
├── pr_agent/                 # Main package
│   ├── __init__.py
│   ├── main.py               # CLI entrypoint (local dev)
│   ├── config.py             # Env loader + validation
│   ├── mcp/
│   │   ├── client.py         # MCP transport + auth
│   │   └── github_tools.py   # Wrappers: get PR, list files, get diffs, comment
│   ├── summarizer/
│   │   ├── foundry_client.py  # OpenAI-compatible client (Foundry Local)
│   │   └── prompts.py        # System prompt + output schema
│   ├── review/
│   │   ├── diff_chunker.py   # Chunk diffs per file + size limits
│   │   └── formatter.py     # Markdown PR comment builder
│   ├── utils/
│   │   └── redaction.py     # Secret redaction
│   └── web/
│       └── app.py           # FastAPI web UI
├── config/                   # Non-secret defaults (optional)
│   └── defaults.yaml
├── docs/                     # Authoritative documentation
├── scripts/                  # Test and helper scripts
├── tests/
├── .env.example              # Template; copy to .env (never commit .env)
├── pyproject.toml
└── README.md
```

See [CONFIGURATION.md](CONFIGURATION.md) for env and config.

---

## Runtime modes

### A) Local CLI (developer mode)
```bash
python -m pr_agent.main --pr <number>
```
Flow: load `.env` → MCP fetches PR/files/diffs → chunk diffs → Foundry summarization → print markdown. Use `--post` to post to PR.

### B) GitHub Actions (CI mode)
- Run on `pull_request` events.
- Use GitHub Secrets: `GITHUB_TOKEN` or `REPO_ACCESS_TOKEN`.
- Workflow runs: `python -m pr_agent.main --pr ${{ github.event.pull_request.number }} --post`

---

## Summarization contract (Foundry Local)

**Inputs:** PR title, description (trimmed), diffs per file (chunked).

**Outputs:** summary (5–10 bullets), release_notes, risks (severity), tests (present/missing + suggestions), action_items (checklist).

**Large PRs:** Summarize per-file first, then merge into final summary; avoid huge diffs in one prompt.

---

## GitHub MCP usage policy

**Permitted via MCP:** list PR files, fetch patches/diffs, read comments (optional), create/update PR comment.

**Never:** merge PR, push commits, modify repository contents.
