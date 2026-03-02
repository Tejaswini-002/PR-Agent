from __future__ import annotations

import hashlib
import hmac
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Ensure summary debug logs are visible when running uvicorn
_log_handler = logging.StreamHandler(sys.stdout)
_log_handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
_pr_agent_logger = logging.getLogger("pr_agent.web.app")
if not _pr_agent_logger.handlers:
    _pr_agent_logger.addHandler(_log_handler)
_pr_agent_logger.setLevel(logging.INFO)

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pr_agent.config import load_config
from pr_agent.mcp.client import MCPClient
from pr_agent.mcp.github_tools import GitHubTools
from pr_agent.summarizer.file_processor import process_files_parallel
from pr_agent.review.diff_stats import count_changed_lines
from pr_agent.summarizer.foundry_client import FoundryClient
from pr_agent.summarizer.parser import parse_high_level_summary
from pr_agent.summarizer.prompts import (
    build_high_level_summary_prompt,
    build_chat_prompt,
)
from pr_agent.utils.file_filters import should_skip_file
from pr_agent.utils.redaction import redact_text
from pr_agent.main import run_review_pr
from pr_agent.utils.review_state import (
    filter_changed_files,
    get_pr_file_hashes,
    load_state,
    save_state,
    update_pr_file_hashes,
)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="NEUQA Repo Explorer")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Favicon and Apple touch icons (serve from static to avoid 404s)
_FAVICON_PATH = STATIC_DIR / "favicon.png"


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(_FAVICON_PATH, media_type="image/png")


@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
def apple_touch_icon():
    return FileResponse(_FAVICON_PATH, media_type="image/png")


def _redact_item(obj: Any) -> Any:
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, list):
        return [_redact_item(item) for item in obj]
    if isinstance(obj, dict):
        return {key: _redact_item(val) for key, val in obj.items()}
    return obj


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
        return stripped.strip("`")
    return stripped


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _try_parse_json(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        snippet = _extract_json_object(text)
        if not snippet:
            return None
        try:
            parsed = json.loads(snippet)
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        cleaned = _strip_code_fences(value)
        parsed = _try_parse_json(cleaned)
        if parsed and "summary" in parsed:
            return _as_list(parsed.get("summary"))
        return [value]
    return [str(value)]


def _normalize_branches(branches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize branch items for the template. MCP returns { name, sha, protected }; template expects commit.sha."""
    out: list[dict[str, Any]] = []
    for b in branches or []:
        if not isinstance(b, dict):
            continue
        name = b.get("name") or b.get("branch") or ""
        sha = b.get("sha") or (b.get("commit") or {}).get("sha") if isinstance(b.get("commit"), dict) else ""
        protected = b.get("protected", False)
        out.append({
            "name": name,
            "sha": sha,
            "protected": protected,
            "commit": {"sha": sha},
        })
    return out


def _normalize_summary_list(value: Any) -> list[str]:
    """Return a list of plain summary bullet strings; never return raw JSON for display."""
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = _strip_code_fences(value).strip()
        if cleaned.startswith("{"):
            parsed = _try_parse_json(cleaned)
            if parsed and isinstance(parsed.get("summary"), list):
                return [str(s).strip() for s in parsed["summary"] if str(s).strip()]
        elif cleaned:
            return [cleaned]
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, dict) and "summary" in item:
                out.extend(_normalize_summary_list(item.get("summary")))
                continue
            s = str(item).strip()
            if not s:
                continue
            # Strip markdown code fences so "```json\n{...}\n```" is parsed, not shown raw
            s = _strip_code_fences(s)
            if not s:
                continue
            if s.startswith("{"):
                parsed = _try_parse_json(s)
                if parsed and isinstance(parsed.get("summary"), list):
                    out.extend(str(x).strip() for x in parsed["summary"] if str(x).strip())
                continue
            out.append(s)
        return out
    return []


def _format_lines_changed(added: int, deleted: int) -> str:
    if added == 0 and deleted == 0:
        return ""
    if added and deleted:
        return f"+{added} / -{deleted}"
    if added:
        return f"+{added}"
    return f"-{deleted}"


def _one_line_from_value(val: Any) -> str:
    """Turn a value (possibly JSON string) into one display line; never return raw JSON."""
    if val is None:
        return ""
    if isinstance(val, list) and val:
        parts = []
        for i, item in enumerate(val):
            if i >= 5:
                break
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                t = item.get("text") or item.get("description") or item.get("summary")
                if t and str(t).strip():
                    parts.append(str(t).strip())
        if parts:
            return " • ".join(parts)
        return ""
    if isinstance(val, str) and val.strip():
        cleaned = _strip_code_fences(val).strip()
        if cleaned.startswith("{"):
            parsed = _try_parse_json(cleaned)
            if parsed and isinstance(parsed.get("summary"), list):
                return _one_line_from_value(parsed["summary"])
            if parsed and isinstance(parsed.get("what_changed"), str) and parsed["what_changed"].strip():
                return parsed["what_changed"].strip()
        return cleaned
    return ""


def _file_summary_to_text(fs: dict[str, Any]) -> str:
    """Extract a single 'what changed' string from a file summary dict (LLM may use different keys)."""
    if not fs:
        return ""
    for key in ("what_changed", "change_summary", "file_summary", "description", "summary", "intent", "content"):
        val = fs.get(key)
        if val is None:
            continue
        one = _one_line_from_value(val)
        if one:
            return one
        if isinstance(val, list) and val:
            parts = []
            for i, item in enumerate(val):
                if i >= 5:
                    break
                if isinstance(item, str) and item.strip():
                    parts.append(item.strip())
                elif isinstance(item, dict):
                    t = item.get("text") or item.get("description") or item.get("summary")
                    if t and str(t).strip():
                        parts.append(str(t).strip())
            if parts:
                return " • ".join(parts)
    # Last resort: use any string or list value in the dict (skip file_path, etc.)
    skip_keys = {"file_path", "path", "inline_suggestions", "risks"}
    for key, val in fs.items():
        if key in skip_keys or val is None:
            continue
        one = _one_line_from_value(val)
        if one and len(one) < 2000:
            return one
        if isinstance(val, list) and val:
            parts = []
            for x in val[:5]:
                if isinstance(x, str) and x.strip():
                    parts.append(x.strip())
                elif isinstance(x, dict):
                    t = x.get("text") or x.get("content") or x.get("description")
                    if t and str(t).strip():
                        parts.append(str(t).strip())
            if parts:
                return " • ".join(parts)
    return ""


def _build_file_changes(
    file_summaries: list[dict[str, Any]],
    pr_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build file_changes for UI from LLM file_summaries and PR file list (for line counts)."""
    path_to_stats: dict[str, tuple[int, int]] = {}
    for f in pr_files:
        path = f.get("filename") or f.get("path")
        if not path:
            continue
        stats = count_changed_lines(f.get("patch"))
        path_to_stats[path] = (stats.added, stats.deleted)

    # Index file_summaries by path so we can merge with full file list
    summary_by_path: dict[str, dict[str, Any]] = {}
    for fs in file_summaries:
        path = fs.get("file_path") or fs.get("path")
        if path:
            summary_by_path[path] = fs

    # Build one row per pr_file so every changed file appears; merge in summary when present
    result: list[dict[str, Any]] = []
    for f in pr_files:
        path = f.get("filename") or f.get("path")
        if not path:
            continue
        fs = summary_by_path.get(path)
        what = _file_summary_to_text(fs) if fs else ""
        if not what:
            what = "—"
        a, d = path_to_stats.get(path, (0, 0))
        lines_str = _format_lines_changed(a, d)
        result.append({
            "file_path": path,
            "what_changed": what,
            "lines_changed": lines_str,
        })
    return result


def _normalize_summary(summary: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(summary)
    candidate = normalized.get("summary")
    # If summary is a string, try to parse as JSON
    if isinstance(candidate, str):
        cleaned = _strip_code_fences(candidate)
        parsed = _try_parse_json(cleaned)
        if parsed is not None:
            # Merge parsed keys into normalized
            for k, v in parsed.items():
                normalized[k] = v
            # If parsed has file_summaries, attach
            if "file_summaries" in parsed:
                normalized["file_summaries"] = parsed["file_summaries"]
            return normalized
    # If summary is a list and first item is a string, try to parse as JSON
    if isinstance(candidate, list) and candidate and isinstance(candidate[0], str):
        cleaned = _strip_code_fences(candidate[0])
        parsed = _try_parse_json(cleaned)
        if parsed is not None:
            for k, v in parsed.items():
                normalized[k] = v
            if "file_summaries" in parsed:
                normalized["file_summaries"] = parsed["file_summaries"]
            return normalized
    return normalized


def _client() -> tuple[MCPClient, GitHubTools]:
    config = load_config()
    mcp = MCPClient(config)
    return mcp, GitHubTools(mcp, config.repo_url)


def _run_review_background(pr_number: int) -> None:
    """Run PR review in background (for webhook)."""
    try:
        config = load_config()
        mcp = MCPClient(config)
        gh = GitHubTools(mcp, config.repo_url)
        foundry = FoundryClient(config)
        run_review_pr(
            config, gh, foundry, pr_number,
            post=True,
            fast=True,
            incremental=config.review_incremental,
            skip_simple=config.review_skip_simple,
        )
    except Exception as exc:
        logging.getLogger("pr_agent.web.app").exception("Webhook review failed: %s", exc)
    finally:
        mcp.close()


def _summarize_pr(
    pr_number: int,
    pr_title: str,
    pr_body: str,
    files: list[dict[str, Any]],
    fast: bool,
    incremental: bool,
    skip_simple: bool,
    max_chars: int = 8000,
    max_files: int | None = None,
    max_chunks: int = 6,
) -> dict[str, Any]:
    config = load_config()
    foundry = FoundryClient(config)
    file_summaries: list[dict[str, Any]] = []

    state = load_state(config)
    prev_hashes = get_pr_file_hashes(state, config.repo_url, pr_number)
    if incremental:
        files, new_hashes = filter_changed_files(files, prev_hashes)
    else:
        _, new_hashes = filter_changed_files(files, prev_hashes)

    total_lines = 0
    for file_info in files:
        total_lines += count_changed_lines(file_info.get("patch")).total

    if skip_simple and (not files or total_lines <= config.review_simple_max_lines):
        skip_files = [
            f.get("filename") or f.get("path")
            for f in files
            if (f.get("filename") or f.get("path"))
            and not should_skip_file(f.get("filename") or f.get("path"))
        ]
        summary: dict[str, Any] = {
            "high_level_summary": "No substantive changes detected. Review skipped.",
            "changed_files": skip_files,
            "file_summaries": [
                {"file": fp, "type": "Docs", "summary": "Minor or trivial change."}
                for fp in skip_files
            ],
            "impact": "",
        }
        update_pr_file_hashes(state, config.repo_url, pr_number, new_hashes)
        save_state(config, state)
        return summary

    model = config.foundry_model_light if fast else config.foundry_model_heavy

    files_to_process = files[:max_files] if max_files is not None else files
    max_concurrency = getattr(config, "review_max_concurrency", 6)

    file_summaries = process_files_parallel(
        files_to_process,
        pr_title=pr_title,
        pr_body=pr_body,
        model=model,
        foundry=foundry,
        prompt_extra=config.prompt_extra,
        max_chars=max_chars,
        max_chunks=max_chunks,
        max_concurrency=max_concurrency,
        chunk_concurrency=3,
        get_patch_fn=None,
        should_skip_fn=should_skip_file,
    )

    changed_files = [
        fp
        for fp in (
            f.get("filename") or f.get("path")
            for f in files_to_process
            if f.get("filename") or f.get("path")
        )
        if not should_skip_file(fp)
    ]
    diff_parts: list[str] = []
    for file_info in files_to_process:
        file_path = file_info.get("filename") or file_info.get("path")
        patch = file_info.get("patch")
        if not file_path or not patch or should_skip_file(file_path):
            continue
        diff_parts.append(f"--- File: {file_path} ---\n{redact_text(patch)}")

    full_diff_raw = "\n\n".join(diff_parts)
    full_diff = full_diff_raw[:50_000] if len(full_diff_raw) > 50_000 else full_diff_raw
    high_level_prompt = build_high_level_summary_prompt(
        pr_title,
        pr_body,
        changed_files,
        file_summaries,
        extra_instructions=config.prompt_extra,
        full_diff=full_diff,
    )
    _log_summary_debug(
        final_prompt=high_level_prompt,
        num_files=len(file_summaries),
        total_diff_chars=len(full_diff),
        diff_preview=full_diff[:500] if full_diff else "",
    )
    raw = foundry.chat_json(high_level_prompt, model=model)
    summary = parse_high_level_summary(raw, changed_files)
    summary["changed_files"] = changed_files

    update_pr_file_hashes(state, config.repo_url, pr_number, new_hashes)
    save_state(config, state)
    return summary


def _chat_pr(
    pr_title: str,
    pr_body: str,
    file_summaries: list[dict[str, Any]],
    question: str,
    fast: bool,
) -> str:
    config = load_config()
    foundry = FoundryClient(config)
    model = config.foundry_model_light if fast else config.foundry_model_heavy
    prompt = build_chat_prompt(
        pr_title,
        pr_body,
        file_summaries,
        question,
        extra_instructions=config.prompt_extra,
    )
    return foundry.chat_text(prompt, model=model)


def _log_summary_debug(
    *,
    final_prompt: dict[str, Any],
    num_files: int,
    total_diff_chars: int,
    diff_preview: str,
) -> None:
    """Log final prompt and diff stats for debugging (prompt changes, diff inclusion)."""
    logger = logging.getLogger("pr_agent.web.app")
    messages = final_prompt.get("messages") or []
    prompt_str = ""
    for m in messages:
        if isinstance(m, dict) and m.get("content"):
            prompt_str += str(m["content"])
    logger.info(
        "PR summary final prompt: num_files=%s total_diff_chars=%s",
        num_files,
        total_diff_chars,
    )
    logger.info("PR summary final prompt (first 2000 chars): %s", prompt_str[:2000])
    logger.info("PR diff preview (first 500 chars): %s", diff_preview or "(none)")


def _user_friendly_connection_error(exc: BaseException) -> str:
    """Return a clearer message when the failure is due to MCP/server connection or invalid response."""
    cause = getattr(exc, "last_attempt", None) or exc
    if hasattr(cause, "__cause__") and cause.__cause__:
        cause = cause.__cause__
    msg = str(cause).strip().lower()
    if not msg:
        msg = str(exc).strip().lower()
    if "retryerror" in str(type(exc).__name__).lower() or "retry" in str(exc).lower():
        if "jsondecodeerror" in str(exc).lower() or "non-json" in msg:
            return (
                "MCP server (api.githubcopilot.com) returns non-JSON to direct HTTP clients. "
                "Use local Docker MCP server instead: unset MCP_SERVER_URL, set MCP_TRANSPORT=stdio, "
                "MCP_STDIO_COMMAND=docker, MCP_STDIO_ARGS=run -i --rm ghcr.io/github/github-mcp-server stdio --toolsets=all"
            )
    if "expecting value" in msg or "non-json" in msg:
        return (
            "MCP server returned empty or non-JSON. "
            "api.githubcopilot.com often does not work with direct HTTP. "
            "Use local Docker MCP (MCP_TRANSPORT=stdio, MCP_STDIO_COMMAND=docker) instead."
        )
    if "authorization" in msg and ("missing" in msg or "required" in msg):
        return (
            "MCP server requires an Authorization header. "
            "Set REPO_ACCESS_TOKEN or MCP_ACCESS_TOKEN in .env (e.g. your GitHub or Copilot token)."
        )
    if "connection" in msg or "connect" in msg or "refused" in msg or "timeout" in msg or "unreachable" in msg:
        try:
            config = load_config()
            if config.mcp_transport == "stdio":
                hint = (
                    "Cannot start the GitHub MCP server. "
                    "1) Run: docker pull ghcr.io/github/github-mcp-server "
                    "2) Ensure GITHUB_PERSONAL_ACCESS_TOKEN is in .env and has repo scope. "
                    "3) Test manually: docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN=$GITHUB_PERSONAL_ACCESS_TOKEN "
                    "ghcr.io/github/github-mcp-server stdio --toolsets=all"
                )
                orig = str(exc).strip()
                if orig and len(orig) < 200:
                    return f"{hint} — Original error: {orig}"
                return hint
        except Exception:
            pass
        return (
            "Cannot reach the GitHub MCP server. "
            "For stdio: ensure Docker is running. For remote: set MCP_SERVER_URL (e.g. http://localhost:3000)."
        )
    if "invalid json" in msg or "mcp server returned" in msg:
        return str(exc)
    if "docker" in msg or "subprocess" in msg or "no such file" in msg or "spawn" in msg or "command not found" in msg:
        return (
            "Failed to start MCP server. Ensure Docker is installed and running. "
            "Test with: docker run -i --rm ghcr.io/github/github-mcp-server stdio --toolsets=all"
        )
    return str(exc)


def _first_summary_bullet(pr_summary: dict[str, Any]) -> str:
    """Get the first summary bullet for display; works whether summary is list or JSON string."""
    summary_list = _as_list(pr_summary.get("summary"))
    if not summary_list:
        return ""
    s = str(summary_list[0]).strip()
    if s.startswith("{"):
        parsed = _try_parse_json(s)
        if parsed and isinstance(parsed.get("summary"), list) and parsed["summary"]:
            s = str(parsed["summary"][0]).strip()
    return (s[:200] + "…") if len(s) > 200 else s


def _file_changes_from_pr_files_only(pr_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build file_changes list from PR files only (no LLM summary)."""
    out: list[dict[str, Any]] = []
    for f in pr_files:
        path = f.get("filename") or f.get("path")
        if not path:
            continue
        stats = count_changed_lines(f.get("patch"))
        out.append({
            "file_path": path,
            "what_changed": "—",
            "lines_changed": _format_lines_changed(stats.added, stats.deleted),
        })
    return out


@app.get("/health")
def health() -> dict[str, str]:
    """Simple health check - no MCP required."""
    return {"status": "ok", "message": "Server is running"}


class SummariesRequest(BaseModel):
    """Request body for POST /summaries (microservice API)."""
    prNumber: int
    repoUrl: str | None = None  # optional; uses config REPO_URL if not set
    mode: str = "full"  # "fast" | "full"
    postToGithub: bool = False


@app.post("/summaries")
def post_summaries(payload: SummariesRequest) -> dict[str, Any]:
    """
    Generate a PR summary (for NestJS/other callers).
    Accepts POST from any origin; returns summary or error.
    """
    mcp = None
    try:
        mcp, gh = _client()
        pr_number = payload.prNumber
        config = load_config()
        use_fast = (payload.mode or "full").lower() == "fast"
        post_comment = payload.postToGithub or False

        pr_item = gh.get_pull_request(pr_number)
        pr_files = gh.list_pull_request_files(pr_number)
        for file_info in pr_files:
            if not file_info.get("patch"):
                file_path = file_info.get("filename") or file_info.get("path")
                if file_path:
                    file_info["patch"] = gh.get_pull_request_file_diff(pr_number, file_path)
        pr_title = redact_text(pr_item.get("title", "")) if pr_item else ""
        pr_body = redact_text(pr_item.get("body", "")) if pr_item else ""

        use_incremental = config.review_incremental
        use_skip_simple = config.review_skip_simple

        pr_summary = _summarize_pr(
            pr_number,
            pr_title,
            pr_body,
            pr_files,
            fast=use_fast,
            incremental=use_incremental,
            skip_simple=use_skip_simple,
        )
        high_level = pr_summary.get("high_level_summary", "") or ""
        file_summaries = pr_summary.get("file_summaries") or []

        if post_comment and high_level:
            foundry = FoundryClient(config)
            run_review_pr(
                config, gh, foundry, pr_number,
                post=True,
                fast=use_fast,
                incremental=use_incremental,
                skip_simple=use_skip_simple,
            )

        return {
            "status": "completed",
            "prNumber": pr_number,
            "repoUrl": payload.repoUrl or config.repo_url,
            "summaryMarkdown": high_level,
            "file_summaries": file_summaries,
            "errorMessage": None,
        }
    except Exception as exc:
        _pr_agent_logger.exception("POST /summaries failed: %s", exc)
        return {
            "status": "failed",
            "prNumber": payload.prNumber,
            "repoUrl": payload.repoUrl or "",
            "summaryMarkdown": None,
            "file_summaries": [],
            "errorMessage": str(exc),
        }
    finally:
        if mcp is not None:
            mcp.close()


@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle GitHub webhook for PR events. Triggers review on opened/synchronize."""
    body = await request.body()
    config = load_config()
    if config.webhook_secret:
        sig = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            config.webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    action = payload.get("action")
    if action not in ("opened", "synchronize"):
        return {"ok": True, "skipped": f"action={action}"}
    pr_data = payload.get("pull_request")
    if not pr_data:
        return {"ok": True, "skipped": "no pull_request"}
    pr_number = pr_data.get("number")
    if not pr_number:
        return {"ok": True, "skipped": "no pr number"}
    background_tasks.add_task(_run_review_background, pr_number)
    return {"ok": True, "pr": pr_number}


@app.get("/api/pr-summary/{pr_number}")
def get_pr_summary(
    pr_number: int,
    fast: int = Query(1),
    incremental: int | None = Query(None),
    skip_simple: int | None = Query(None),
    force_refresh: int = Query(0),
):
    mcp, gh = _client()
    try:
        pr_item = gh.get_pull_request(pr_number)
        pr_files = gh.list_pull_request_files(pr_number)
        for file_info in pr_files:
            if not file_info.get("patch"):
                file_path = file_info.get("filename") or file_info.get("path")
                if file_path:
                    file_info["patch"] = gh.get_pull_request_file_diff(pr_number, file_path)
        pr_title = redact_text(pr_item.get("title", "")) if pr_item else ""
        pr_body = redact_text(pr_item.get("body", "")) if pr_item else ""
        config = load_config()
        use_incremental = bool(incremental) if incremental is not None else config.review_incremental
        if force_refresh:
            use_incremental = False
        use_skip_simple = bool(skip_simple) if skip_simple is not None else config.review_skip_simple

        summarization_error: str | None = None
        pr_summary: dict[str, Any] = {}
        try:
            if fast:
                pr_summary = _summarize_pr(
                    pr_number,
                    pr_title,
                    pr_body,
                    pr_files,
                    fast=True,
                    incremental=use_incremental,
                    skip_simple=use_skip_simple,
                    max_chars=6000,
                    max_files=getattr(config, "review_max_files", None),
                    max_chunks=3,
                )
            else:
                pr_summary = _summarize_pr(
                    pr_number,
                    pr_title,
                    pr_body,
                    pr_files,
                    fast=False,
                    incremental=use_incremental,
                    skip_simple=use_skip_simple,
                )
        except Exception as e:
            summarization_error = str(e)
            pr_summary = {}

        file_summaries = pr_summary.get("file_summaries") or []
        changed_files = pr_summary.get("changed_files") or [
            fp
            for fp in (
                f.get("filename") or f.get("path")
                for f in pr_files
                if f.get("filename") or f.get("path")
            )
            if not should_skip_file(fp)
        ]
        pr_obj = {
            "number": pr_number,
            "title": pr_item.get("title", ""),
            "author": (pr_item.get("user") or {}).get("login", ""),
            "updated_at": pr_item.get("updated_at", ""),
            "html_url": pr_item.get("html_url", ""),
        }

        try:
            state_data = load_state(config)
            repo_url = config.repo_url
            pr_key = str(pr_number)
            state_data.setdefault("repos", {})
            state_data["repos"].setdefault(repo_url, {})
            state_data["repos"][repo_url].setdefault("prs", {})
            state_data["repos"][repo_url]["prs"].setdefault(pr_key, {})
            state_data["repos"][repo_url]["prs"][pr_key]["high_level_summary"] = pr_summary.get("high_level_summary", "")
            state_data["repos"][repo_url]["prs"][pr_key]["file_summaries"] = file_summaries
            save_state(config, state_data)
        except Exception:
            pass

        out: dict[str, Any] = {
            "pr": pr_obj,
            "changed_files": changed_files,
            "high_level_summary": pr_summary.get("high_level_summary", ""),
            "file_summaries": file_summaries,
            "impact": pr_summary.get("impact", ""),
        }
        if summarization_error:
            out["error"] = summarization_error
            if "connection" in summarization_error.lower() or "connect" in summarization_error.lower():
                out["error"] += " Ensure Foundry is running (see scripts/test_foundry_summary.py)."
        return out
    except Exception as exc:
        return {
            "error": _user_friendly_connection_error(exc),
            "pr": {},
            "changed_files": [],
            "high_level_summary": "",
            "file_summaries": [],
            "impact": "",
        }
    finally:
        mcp.close()


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    state: str = Query("open"),
    page: int = 1,
    per_page: int = 20,
    pr: int | None = None,
    issue: int | None = None,
    pr_detail: int | None = None,
    summarize: int = 1,
    fast: int = 1,
    incremental: int | None = None,
    skip_simple: int | None = None,
    force_refresh: int = Query(0),
    chat: str | None = None,
) -> HTMLResponse:
    try:
        mcp, gh = _client()
    except Exception as exc:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "state": state,
                "page": page,
                "per_page": per_page,
                "prs": [],
                "all_prs": [],
                "issues": [],
                "commits": [],
                "branches": [],
                "merges": [],
                "workflows": [],
                "comments": [],
                "comments_kind": "",
                "pr_detail": {},
                "pr_files": [],
                "pr_summary": {},
                "summary_list": [],
                "release_notes_list": [],
                "action_items_list": [],
                "suggestions_list": [],
                "next_steps_list": [],
                "inline_suggestions": [],
                "chat_question": "",
                "chat_answer": "",
                "incremental": incremental,
                "skip_simple": skip_simple,
                "force_refresh": force_refresh,
                "summarize": summarize,
                "fast": fast,
                "show_summary": False,
                "errors": [_user_friendly_connection_error(exc)],
            },
        )
    errors: list[str] = []

    prs: list[dict[str, Any]] = []
    all_prs: list[dict[str, Any]] = []
    issues_list: list[dict[str, Any]] = []
    commits_list: list[dict[str, Any]] = []
    branches_list: list[dict[str, Any]] = []
    merges_list: list[dict[str, Any]] = []
    workflows_list: list[dict[str, Any]] = []
    comments_list: list[dict[str, Any]] = []
    comments_kind = ""
    pr_item: dict[str, Any] | None = None
    pr_files: list[dict[str, Any]] = []
    pr_summary: dict[str, Any] | None = None
    pr_chat_answer: str | None = None
    show_summary = False

    try:
        prs = gh.list_pull_requests(state=state, page=page, per_page=per_page)
        open_prs = gh.list_pull_requests(state="open", page=page, per_page=per_page)
        closed_prs = gh.list_pull_requests(state="closed", page=page, per_page=per_page)
        seen: set[int] = set()
        for item in open_prs + closed_prs:
            number = item.get("number") or item.get("pull_number")
            if not number or number in seen:
                continue
            seen.add(number)
            # Fetch high_level_summary and file_summaries from state (or legacy file_changes)
            high_level_summary = ""
            file_summaries: list[dict[str, Any]] = []
            try:
                config = load_config()
                state_data = load_state(config)
                repo_url = config.repo_url
                pr_key = str(number)
                pr_state = state_data.get("repos", {}).get(repo_url, {}).get("prs", {}).get(pr_key, {})
                high_level_summary = pr_state.get("high_level_summary", "")
                file_summaries = pr_state.get("file_summaries", [])
                # Legacy: migrate from old file_changes if no file_summaries
                if not file_summaries and pr_state.get("file_changes"):
                    for fc in pr_state["file_changes"]:
                        path = fc.get("file_path") or fc.get("path")
                        w = fc.get("what_changed") or fc.get("summary") or "—"
                        if isinstance(w, str) and (w.strip().startswith("{") or "```" in w):
                            w = _one_line_from_value(w) or "—"
                        file_summaries.append({
                            "file": path,
                            "type": "—",
                            "summary": w if isinstance(w, str) else str(w),
                        })
                # Fallback: If hashes exist but no summary, show hint
                pr_hashes = get_pr_file_hashes(state_data, repo_url, number)
                if pr_hashes and not file_summaries:
                    file_summaries = [
                        {"file": k, "type": "—", "summary": "Analysis not yet run. Click Summary."}
                        for k in pr_hashes.keys()
                    ]
            except Exception:
                high_level_summary = ""
                file_summaries = []
            item["high_level_summary"] = high_level_summary
            item["file_summaries"] = file_summaries
            all_prs.append(item)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"PRs: {_user_friendly_connection_error(exc)}")

    try:
        issues_list = gh.list_issues(state=state, page=page, per_page=per_page)
        issues_list = [item for item in issues_list if not item.get("pull_request")]
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Issues: {_user_friendly_connection_error(exc)}")

    try:
        commits_list = gh.list_commits(page=page, per_page=per_page)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Commits: {_user_friendly_connection_error(exc)}")

    try:
        branches_list = gh.list_branches(page=page, per_page=per_page)
    except Exception:  # noqa: BLE001
        pass  # optional: show empty branches; no service warning

    try:
        merged = gh.list_pull_requests(state="closed", page=page, per_page=per_page)
        merges_list = [item for item in merged if item.get("merged_at")]
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Merges: {_user_friendly_connection_error(exc)}")

    try:
        workflows_list = gh.list_workflows(page=page, per_page=per_page)
    except Exception:  # noqa: BLE001
        pass  # optional: show empty workflows; no service warning

    try:
        if pr is not None:
            comments_kind = f"PR #{pr}"
            comments_list = gh.list_pr_comments(pr, page=page, per_page=per_page)
        if issue is not None:
            comments_kind = f"Issue #{issue}"
            comments_list = gh.list_issue_comments(issue, page=page, per_page=per_page)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Comments: {_user_friendly_connection_error(exc)}")

    try:
        if pr_detail is not None:
            pr_item = gh.get_pull_request(pr_detail)
            pr_files = gh.list_pull_request_files(pr_detail)
            for file_info in pr_files:
                if not file_info.get("patch"):
                    file_path = file_info.get("filename") or file_info.get("path")
                    if file_path:
                        file_info["patch"] = gh.get_pull_request_file_diff(pr_detail, file_path)
            if summarize:
                pr_title = redact_text(pr_item.get("title", "")) if pr_item else ""
                pr_body = redact_text(pr_item.get("body", "")) if pr_item else ""
                config = load_config()
                use_incremental = bool(incremental) if incremental is not None else config.review_incremental
                if force_refresh:
                    use_incremental = False
                use_skip_simple = bool(skip_simple) if skip_simple is not None else config.review_skip_simple
                if fast:
                    pr_summary = _summarize_pr(
                        pr_detail,
                        pr_title,
                        pr_body,
                        pr_files,
                        fast=True,
                        incremental=use_incremental,
                        skip_simple=use_skip_simple,
                        max_chars=6000,
                        max_files=getattr(config, "review_max_files", None),
                        max_chunks=3,
                    )
                else:
                    pr_summary = _summarize_pr(
                        pr_detail,
                        pr_title,
                        pr_body,
                        pr_files,
                        fast=False,
                        incremental=use_incremental,
                        skip_simple=use_skip_simple,
                        max_files=getattr(config, "review_max_files", None),
                    )
                file_summaries = pr_summary.get("file_summaries") or []
                changed_files = pr_summary.get("changed_files") or [
                    fp
                    for fp in (
                        f.get("filename") or f.get("path")
                        for f in pr_files
                        if f.get("filename") or f.get("path")
                    )
                    if not should_skip_file(fp)
                ]
                # Ensure file_summaries match changed_files order; fill gaps with placeholders
                by_path = {fs.get("file"): fs for fs in file_summaries if fs.get("file")}
                ordered: list[dict[str, Any]] = []
                for path in changed_files:
                    if path in by_path:
                        ordered.append(by_path[path])
                    else:
                        ordered.append({"file": path, "type": "—", "summary": "Changes in this file."})
                for path, fs in by_path.items():
                    if path not in changed_files:
                        ordered.append(fs)
                pr_summary["file_summaries"] = ordered
                # Save to state
                try:
                    state_data = load_state(config)
                    repo_url = config.repo_url
                    pr_key = str(pr_detail)
                    state_data.setdefault("repos", {})
                    state_data["repos"].setdefault(repo_url, {})
                    state_data["repos"][repo_url].setdefault("prs", {})
                    state_data["repos"][repo_url]["prs"].setdefault(pr_key, {})
                    state_data["repos"][repo_url]["prs"][pr_key]["high_level_summary"] = pr_summary.get("high_level_summary", "")
                    state_data["repos"][repo_url]["prs"][pr_key]["file_summaries"] = ordered
                    save_state(config, state_data)
                except Exception:
                    pass
                show_summary = True
            if chat:
                if not pr_summary:
                    pr_title = redact_text(pr_item.get("title", "")) if pr_item else ""
                    pr_body = redact_text(pr_item.get("body", "")) if pr_item else ""
                    config = load_config()
                    use_incremental = bool(incremental) if incremental is not None else config.review_incremental
                    use_skip_simple = bool(skip_simple) if skip_simple is not None else config.review_skip_simple
                    pr_summary = _summarize_pr(
                        pr_detail,
                        pr_title,
                        pr_body,
                        pr_files,
                        fast=True,
                        incremental=use_incremental,
                        skip_simple=use_skip_simple,
                        max_chars=6000,
                        max_files=getattr(config, "review_max_files", None),
                        max_chunks=3,
                    )
                    pr_summary = _normalize_summary(pr_summary or {})
                pr_chat_answer = _chat_pr(
                    redact_text(pr_item.get("title", "")) if pr_item else "",
                    redact_text(pr_item.get("body", "")) if pr_item else "",
                    [pr_summary],
                    chat,
                    fast=bool(fast),
                )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"PR Detail: {_user_friendly_connection_error(exc)}")

    mcp.close()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "state": state,
            "page": page,
            "per_page": per_page,
            "prs": _redact_item(prs),
            "all_prs": _redact_item(all_prs),
            "issues": _redact_item(issues_list),
            "commits": _redact_item(commits_list),
            "branches": _redact_item(_normalize_branches(branches_list)),
            "merges": _redact_item(merges_list),
            "workflows": _redact_item(workflows_list),
            "comments": _redact_item(comments_list),
            "comments_kind": comments_kind,
            "pr_detail": _redact_item(pr_item or {}),
            "pr_files": _redact_item(pr_files),
            "pr_summary": _redact_item(pr_summary or {}),
            "high_level_summary": (pr_summary or {}).get("high_level_summary", ""),
            "file_summaries": (pr_summary or {}).get("file_summaries", []),
            "summary_list": _normalize_summary_list((pr_summary or {}).get("summary")),
            "release_notes_list": _as_list((pr_summary or {}).get("release_notes")),
            "action_items_list": _as_list((pr_summary or {}).get("action_items")),
            "suggestions_list": _as_list((pr_summary or {}).get("suggestions")),
            "next_steps_list": _as_list((pr_summary or {}).get("next_steps")),
            "inline_suggestions": _redact_item(
                (pr_summary or {}).get("inline_suggestions") or []
            ),
            "chat_question": chat or "",
            "chat_answer": pr_chat_answer or "",
            "incremental": incremental,
            "skip_simple": skip_simple,
            "force_refresh": force_refresh,
            "summarize": summarize,
            "fast": fast,
            "show_summary": show_summary,
            "errors": errors,
        },
    )
