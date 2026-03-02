#!/usr/bin/env python3
"""
Test Foundry summary generation on a real PR (by PR number).

Uses REPO_URL and MCP from .env to fetch the PR from GitHub, then runs the same
Foundry pipeline as the main reviewer and prints the raw summary.

Usage:
  python scripts/test_foundry_real_pr.py <PR_NUMBER>

Example:
  python scripts/test_foundry_real_pr.py 42

Prerequisites:
  - Foundry running at FOUNDRY_BASE_URL
  - MCP configured (MCP_SERVER_URL or MCP_STDIO_COMMAND) and able to read the repo
  - REPO_URL in .env points to the repo that contains the PR
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(override=False)

from pr_agent.config import load_config, ConfigError
from pr_agent.mcp.client import MCPClient
from pr_agent.mcp.github_tools import GitHubTools
from pr_agent.main import run_review_pr
from pr_agent.summarizer.foundry_client import FoundryClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Foundry PR review on a real PR")
    parser.add_argument("pr_number", type=int, help="PR number to review")
    parser.add_argument("--max-files", type=int, default=None, help="Limit files to process (for faster testing)")
    args = parser.parse_args()
    pr_number = args.pr_number

    # Ensure progress logs are visible
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        config = load_config()
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"=== Foundry test on real PR #{pr_number} ===\n")
    print(f"REPO_URL: {config.repo_url}")
    print(f"FOUNDRY_BASE_URL: {config.foundry_base_url}\n")

    mcp = MCPClient(config)
    gh = GitHubTools(mcp, config.repo_url)
    foundry = FoundryClient(config)

    try:
        pr = gh.get_pull_request(pr_number)
        if not pr:
            print(f"PR #{pr_number} not found.", file=sys.stderr)
            sys.exit(1)
        title = (pr.get("title") or "").strip() or "(no title)"
        print(f"PR title: {title}\n")
    except Exception as e:
        print(f"Failed to fetch PR: {e}", file=sys.stderr)
        mcp.close()
        sys.exit(1)

    try:
        comment_body = run_review_pr(
            config, gh, foundry, pr_number,
            post=False,
            fast=True,
            incremental=False,
            skip_simple=False,
            max_files=args.max_files,
        )
    except Exception as e:
        print(f"Foundry/review failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        mcp.close()
        sys.exit(1)
    finally:
        mcp.close()

    if comment_body:
        print("--- Formatted review (as would be posted) ---\n")
        print(comment_body)
    else:
        print("(No review output)")
    print("\n=== Done ===")


if __name__ == "__main__":
    main()
