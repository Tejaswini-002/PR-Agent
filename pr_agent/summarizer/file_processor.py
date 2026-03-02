"""Parallel file processing for PR review and summarization."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from pr_agent.review.diff_chunker import chunk_diff
from pr_agent.review.diff_stats import count_changed_lines
from pr_agent.review.line_suggestions import extract_added_lines
from pr_agent.summarizer.foundry_client import FoundryClient
from pr_agent.summarizer.prompts import (
    build_batch_file_prompt,
    build_chunk_prompt,
    build_file_merge_prompt,
)
from pr_agent.utils.placeholder import sanitize_file_summary
from pr_agent.utils.redaction import redact_text


def process_single_file(
    *,
    file_path: str,
    patch: str,
    pr_title: str,
    pr_body: str,
    model: str,
    foundry: FoundryClient,
    prompt_extra: str | None,
    max_chars: int,
    max_chunks: int,
    chunk_concurrency: int = 3,
) -> dict[str, Any]:
    """
    Process one file: chunk diff, analyze chunks (in parallel), merge.
    Returns file summary dict with file_path and diff_stats.
    """
    redacted_patch = redact_text(patch)
    chunks = chunk_diff(redacted_patch, max_chars=max_chars, max_chunks=max_chunks)
    stats = count_changed_lines(patch)
    added_lines = extract_added_lines(patch)

    # Process chunks in parallel
    chunk_summaries: list[dict[str, Any]] = []
    if len(chunks) <= 1 or chunk_concurrency <= 1:
        for chunk in chunks:
            prompt = build_chunk_prompt(
                pr_title, pr_body, file_path, chunk,
                added_lines=added_lines, extra_instructions=prompt_extra,
            )
            chunk_summaries.append(foundry.chat_json(prompt, model=model))
    else:
        with ThreadPoolExecutor(max_workers=min(chunk_concurrency, len(chunks))) as ex:
            futures = {
                ex.submit(
                    _process_chunk,
                    pr_title=pr_title,
                    pr_body=pr_body,
                    file_path=file_path,
                    chunk=chunk,
                    added_lines=added_lines,
                    prompt_extra=prompt_extra,
                    model=model,
                    foundry=foundry,
                ): i
                for i, chunk in enumerate(chunks)
            }
            results: list[tuple[int, dict[str, Any]]] = []
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results.append((idx, future.result()))
                except Exception as exc:
                    logging.getLogger(__name__).warning(
                        "Chunk %s/%s for %s failed: %s", idx + 1, len(chunks), file_path, exc
                    )
                    results.append((idx, {"what_changed": f"Chunk analysis failed: {exc}", "summary": []}))
            chunk_summaries = [r[1] for r in sorted(results, key=lambda x: x[0])]

    # When only 1 chunk, use it directly—skip merge call (saves 1 API call per small file)
    if len(chunk_summaries) == 1:
        file_summary = dict(chunk_summaries[0])
    else:
        file_prompt = build_file_merge_prompt(
            pr_title, pr_body, file_path, chunk_summaries,
            extra_instructions=prompt_extra,
        )
        file_summary = foundry.chat_json(file_prompt, model=model)

    file_summary["file_path"] = file_path
    file_summary["diff_stats"] = {"added": stats.added, "removed": stats.deleted, "total": stats.total}

    # Sanitize placeholder responses
    file_summary = sanitize_file_summary(file_summary, file_path)
    return file_summary


def _process_chunk(
    pr_title: str,
    pr_body: str,
    file_path: str,
    chunk: str,
    added_lines: list[dict[str, Any]],
    prompt_extra: str | None,
    model: str,
    foundry: FoundryClient,
) -> dict[str, Any]:
    prompt = build_chunk_prompt(
        pr_title, pr_body, file_path, chunk,
        added_lines=added_lines, extra_instructions=prompt_extra,
    )
    return foundry.chat_json(prompt, model=model)


def process_files_parallel(
    files: list[dict[str, Any]],
    *,
    pr_title: str,
    pr_body: str,
    model: str,
    foundry: FoundryClient,
    prompt_extra: str | None,
    max_chars: int,
    max_chunks: int,
    max_concurrency: int,
    chunk_concurrency: int = 3,
    get_patch_fn: Any = None,
    should_skip_fn: Any = None,
) -> list[dict[str, Any]]:
    """
    Process multiple files in parallel. Each file is processed by process_single_file.
    get_patch_fn(file_info) -> str | None: optional, to refetch patch if needed.
    should_skip_fn(file_path) -> bool: optional, to skip certain files.
    """
    file_summaries: list[dict[str, Any]] = []
    tasks: list[tuple[int, str, str]] = []  # (original_index, file_path, patch)

    for i, file_info in enumerate(files):
        file_path = file_info.get("filename") or file_info.get("path")
        if not file_path:
            continue
        if should_skip_fn and should_skip_fn(file_path):
            continue
        patch = file_info.get("patch")
        if get_patch_fn and (not patch or _patch_needs_refetch(patch)):
            patch = get_patch_fn(file_info)
        if not patch:
            continue
        tasks.append((i, file_path, patch))

    if not tasks:
        return []

    # Group small files into batches to reduce API calls
    batchable: list[tuple[int, str, str]] = []
    individual: list[tuple[int, str, str]] = []
    for idx, fp, pt in tasks:
        if len(pt) <= _BATCH_MAX_CHARS_PER_FILE:
            batchable.append((idx, fp, pt))
        else:
            individual.append((idx, fp, pt))

    all_results: list[tuple[int, dict[str, Any]]] = []

    # Process batchable in groups of _BATCH_MAX_FILES
    log = logging.getLogger(__name__)
    num_batches = (len(batchable) + _BATCH_MAX_FILES - 1) // _BATCH_MAX_FILES
    for i in range(0, len(batchable), _BATCH_MAX_FILES):
        batch = batchable[i : i + _BATCH_MAX_FILES]
        batch_idx = i // _BATCH_MAX_FILES + 1
        if num_batches > 0:
            log.info("Processing batch %s/%s (%s small files)", batch_idx, num_batches, len(batch))
        all_results.extend(
            _process_batch(batch, pr_title, pr_body, model, foundry, prompt_extra)
        )

    def process_one(args: tuple[int, str, str]) -> tuple[int, dict[str, Any]]:
        idx, fp, pt = args
        try:
            summary = process_single_file(
                file_path=fp,
                patch=pt,
                pr_title=pr_title,
                pr_body=pr_body,
                model=model,
                foundry=foundry,
                prompt_extra=prompt_extra,
                max_chars=max_chars,
                max_chunks=max_chunks,
                chunk_concurrency=chunk_concurrency,
            )
            log.info("Processed: %s", fp)
            return (idx, summary)
        except Exception as exc:
            logging.getLogger(__name__).warning("File %s failed: %s", fp, exc)
            stats = count_changed_lines(pt)
            return (
                idx,
                {
                    "file_path": fp,
                    "what_changed": f"Analysis failed: {exc}",
                    "summary": [],
                    "diff_stats": {"added": stats.added, "removed": stats.deleted, "total": stats.total},
                },
            )

    # Process larger files individually (in parallel)
    with ThreadPoolExecutor(max_workers=min(max_concurrency, len(individual) or 1)) as ex:
        futures = {ex.submit(process_one, t): t[0] for t in individual}
        results: list[tuple[int, dict[str, Any]]] = []
        for future in as_completed(futures):
            idx, summary = future.result()
            all_results.append((idx, summary))

    file_summaries = [r[1] for r in sorted(all_results, key=lambda x: x[0])]
    return file_summaries


# Batch small files: diff < this chars, max this many per batch
_BATCH_MAX_CHARS_PER_FILE = 4500
_BATCH_MAX_FILES = 3


def _process_batch(
    batch: list[tuple[int, str, str]],
    pr_title: str,
    pr_body: str,
    model: str,
    foundry: FoundryClient,
    prompt_extra: str | None,
) -> list[tuple[int, dict[str, Any]]]:
    """Process a batch of small files in one API call. Returns [(idx, summary), ...]."""
    file_diffs = [(fp, pt) for _, fp, pt in batch]
    prompt = build_batch_file_prompt(pr_title, pr_body, file_diffs, prompt_extra)
    try:
        raw = foundry.chat_json(prompt, model=model)
        summaries = raw.get("file_summaries") or []
        results: list[tuple[int, dict[str, Any]]] = []
        for i, (idx, fp, pt) in enumerate(batch):
            stats = count_changed_lines(pt)
            if i < len(summaries):
                fs = dict(summaries[i])
                fs["file_path"] = fs.get("file_path") or fp
                fs["diff_stats"] = {"added": stats.added, "removed": stats.deleted, "total": stats.total}
                fs = sanitize_file_summary(fs, fp)
            else:
                fs = {
                    "file_path": fp,
                    "what_changed": f"Changes in {fp}.",
                    "diff_stats": {"added": stats.added, "removed": stats.deleted, "total": stats.total},
                }
            results.append((idx, fs))
        return results
    except Exception as exc:
        logging.getLogger(__name__).warning("Batch failed: %s", exc)
        return [
            (idx, {
                "file_path": fp,
                "what_changed": f"Analysis failed: {exc}",
                "diff_stats": {"added": count_changed_lines(pt).added, "removed": count_changed_lines(pt).deleted, "total": count_changed_lines(pt).total},
            })
            for idx, fp, pt in batch
        ]


def _patch_needs_refetch(patch: str | None) -> bool:
    if not patch:
        return True
    if len(patch) < 120:
        return True
    if "@@" not in patch and ("\n+" not in patch and "\n-" not in patch):
        return True
    return False
