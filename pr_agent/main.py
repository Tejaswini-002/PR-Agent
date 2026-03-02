import argparse
import json
import logging
from typing import Any

from pr_agent.config import ConfigError, load_config
from pr_agent.mcp.client import MCPClient
from pr_agent.mcp.github_tools import GitHubTools
from pr_agent.review.diff_stats import count_changed_lines
from pr_agent.review.formatter import format_review_comment
from pr_agent.summarizer.foundry_client import FoundryClient
from pr_agent.summarizer.file_processor import process_files_parallel
from pr_agent.summarizer.prompts import build_final_prompt
from pr_agent.utils.redaction import redact_text
from pr_agent.utils.review_state import (
    filter_changed_files,
    get_pr_file_hashes,
    hash_comment,
    load_state,
    mark_reviewed,
    save_state,
    should_review,
    update_pr_file_hashes,
)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _safe_get(obj: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in obj:
            return obj[key]
    return None


from pr_agent.utils.file_filters import should_skip_file as _should_skip_file


def _patch_needs_refetch(patch: str | None) -> bool:
    """
    GitHub PR files API patch can be missing or truncated.
    Lightweight heuristic to decide when to refetch full diff.
    """
    if not patch:
        return True
    if len(patch) < 120:
        return True
    # If no hunk markers and no +/- lines, it's not a useful diff chunk.
    if "@@" not in patch and ("\n+" not in patch and "\n-" not in patch):
        return True
    return False


def run_review_pr(
    config: Any,
    gh: GitHubTools,
    foundry: FoundryClient,
    pr_number: int,
    *,
    post: bool = False,
    fast: bool = False,
    incremental: bool = False,
    skip_simple: bool = False,
    max_chars: int = 8000,
    max_chunks: int = 10,
    max_files: int | None = None,
    debug_prompts: bool = False,
    debug_json: bool = False,
) -> str:
    """
    Run PR review and optionally post comment. Returns the formatted comment body.
    Uses idempotency: skips post if already reviewed at this head SHA.
    """
    pr = gh.get_pull_request(pr_number)
    pr_title = redact_text(_safe_get(pr, "title") or "")
    pr_body = redact_text(_safe_get(pr, "body") or "")
    head_sha = ((pr.get("head") or {}).get("sha") or "") if isinstance(pr.get("head"), dict) else ""

    state = load_state(config)
    if post and head_sha and not should_review(state, config.repo_url, pr_number, head_sha):
        logging.info("PR #%s at sha %s already reviewed, skipping", pr_number, head_sha[:7])
        return ""

    files = gh.list_pull_request_files(pr_number)
    file_summaries: list[dict[str, Any]] = []
    prev_hashes = get_pr_file_hashes(state, config.repo_url, pr_number)

    if incremental:
        files, new_hashes = filter_changed_files(files, prev_hashes)
    else:
        _, new_hashes = filter_changed_files(files, prev_hashes)

    total_lines = sum(count_changed_lines(f.get("patch")).total for f in files)
    if skip_simple and (not files or total_lines <= config.review_simple_max_lines):
        final_summary = {
            "summary": ["No substantive changes detected. Review skipped."],
            "intent": "Not enough information in this PR to confirm.",
            "release_notes": [],
            "risks": [],
            "tests": "Not mentioned.",
            "action_items": [],
            "suggestions": [],
            "next_steps": [],
            "inline_suggestions": [],
        }
    else:
        model = config.foundry_model_light if fast else config.foundry_model_heavy
        limit = max_files if max_files is not None else config.review_max_files
        files_to_process = files if limit is None else files[:limit]
        num_files = len([f for f in files_to_process if (f.get("filename") or f.get("path"))])
        logging.info(
            "Reviewing PR #%s model=%s files=%d (max_concurrency=%d) — processing...",
            pr_number, model, num_files, config.review_max_concurrency,
        )

        def get_patch(fi: dict[str, Any]) -> str | None:
            fp = fi.get("filename") or fi.get("path")
            if not fp:
                return None
            patch = fi.get("patch")
            if _patch_needs_refetch(patch):
                return gh.get_pull_request_file_diff(pr_number, fp)
            return patch

        file_summaries = process_files_parallel(
            files_to_process,
            pr_title=pr_title,
            pr_body=pr_body,
            model=model,
            foundry=foundry,
            prompt_extra=config.prompt_extra,
            max_chars=max_chars,
            max_chunks=max_chunks,
            max_concurrency=config.review_max_concurrency,
            chunk_concurrency=3,
            get_patch_fn=get_patch,
            should_skip_fn=_should_skip_file,
        )

        diff_by_file = {}
        for fi in files_to_process:
            fp = fi.get("filename") or fi.get("path")
            if not fp or _should_skip_file(fp):
                continue
            p = get_patch(fi)
            if p:
                diff_by_file[fp] = p

        if not diff_by_file:
            logging.warning("No files with diffs to review (all skipped)")
            final_summary = {
                "summary": ["No reviewable changes (all files skipped or no diff)."],
                "intent": "Not enough information in this PR to confirm.",
                "file_summaries": [],
            }
        else:
            logging.info("Building final summary (%s files)", len(file_summaries))
            # Cap full diff to avoid context overflow for large PRs
            full_diff_raw = "\n\n".join([f"### {fp}\n{diff}" for fp, diff in diff_by_file.items()])
            full_diff = full_diff_raw[:100_000] if len(full_diff_raw) > 100_000 else full_diff_raw
            final_prompt = build_final_prompt(
                pr_title, pr_body, file_summaries,
                extra_instructions=config.prompt_extra, full_diff=full_diff,
            )
            final_summary = foundry.chat_json(final_prompt, model=model)
            final_summary["file_summaries"] = file_summaries

    comment_body = format_review_comment(final_summary)

    if post and head_sha:
        gh.create_or_update_pr_comment(pr_number, comment_body)
        mark_reviewed(state, config.repo_url, pr_number, head_sha, hash_comment(comment_body))
    update_pr_file_hashes(state, config.repo_url, pr_number, new_hashes)
    save_state(config, state)
    return comment_body


def _run_poll(
    config: Any,
    gh: GitHubTools,
    foundry: FoundryClient,
    mcp: MCPClient,
    *,
    fast: bool = False,
    incremental: bool = False,
    skip_simple: bool = False,
) -> None:
    """Poll open PRs and review those that need it."""
    interval = config.poll_interval_seconds
    logging.info("Starting PR poll (interval=%ds)", interval)
    try:
        while True:
            try:
                prs = gh.list_pull_requests(state="open", page=1, per_page=20)
                for item in prs:
                    pr_num = item.get("number") or item.get("pull_number")
                    if not pr_num:
                        continue
                    try:
                        run_review_pr(
                            config, gh, foundry, pr_num,
                            post=True, fast=fast, incremental=incremental, skip_simple=skip_simple,
                        )
                    except Exception as exc:
                        logging.exception("Review failed for PR #%s: %s", pr_num, exc)
            except Exception as exc:
                logging.exception("Poll cycle error: %s", exc)
            logging.info("Sleeping %ds until next poll", interval)
            import time
            time.sleep(interval)
    except KeyboardInterrupt:
        logging.info("Poll stopped")
    finally:
        mcp.close()


def cli() -> None:
    parser = argparse.ArgumentParser(description="NEUQA AI PR Reviewer Agent")
    parser.add_argument("--pr", type=int, help="Pull request number (required unless --poll)")
    parser.add_argument("--post", action="store_true", help="Post review comment")
    parser.add_argument("--max-chars", type=int, default=8000, help="Max chars per diff chunk")
    parser.add_argument("--max-chunks", type=int, default=10, help="Max chunks per file")
    parser.add_argument("--mode", choices=["fast", "full"], default="full", help="Model/context mode")
    parser.add_argument("--incremental", action="store_true", help="Only review changes since last run")
    parser.add_argument("--skip-simple", action="store_true", help="Skip review for trivial changes")

    # Debug flags (these are what you need now)
    parser.add_argument("--debug-prompts", action="store_true", help="Log prompt/diff heads per chunk")
    parser.add_argument("--debug-json", action="store_true", help="Log raw JSON returned by Foundry")
    parser.add_argument("--poll", action="store_true", help="Poll for new/updated PRs and review them")
    args = parser.parse_args()

    if not args.poll and args.pr is None:
        parser.error("--pr is required unless --poll")

    try:
        config = load_config()
    except ConfigError as exc:
        raise SystemExit(str(exc))

    _setup_logging(config.log_level)

    mcp = MCPClient(config)
    gh = GitHubTools(mcp, config.repo_url)
    foundry = FoundryClient(config)

    if args.poll:
        _run_poll(
            config=config,
            gh=gh,
            foundry=foundry,
            mcp=mcp,
            fast=args.mode == "fast",
            incremental=args.incremental or config.review_incremental,
            skip_simple=args.skip_simple or config.review_skip_simple,
        )
        return

    comment_body = run_review_pr(
        config, gh, foundry, args.pr,
        post=args.post,
        fast=args.mode == "fast",
        incremental=args.incremental or config.review_incremental,
        skip_simple=args.skip_simple or config.review_skip_simple,
        max_chars=args.max_chars,
        max_chunks=args.max_chunks,
        debug_prompts=args.debug_prompts,
        debug_json=args.debug_json,
    )
    if comment_body:
        print(comment_body)
    mcp.close()


if __name__ == "__main__":
    cli()