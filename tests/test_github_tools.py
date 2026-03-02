"""Tests for GitHub tools and MCP client (mocked)."""

from unittest.mock import MagicMock

import pytest

from pr_agent.mcp.client import MCPClient, MCPError
from pr_agent.mcp.github_tools import GitHubTools


def test_tool_mapping_list_prs() -> None:
    """When list_tools returns pull_request tools, _best_tool finds a match."""
    mock_client = MagicMock(spec=MCPClient)
    mock_client.list_tools.return_value = [
        {"name": "list_pull_requests"},
        {"name": "get_file_content"},
    ]
    gh = GitHubTools(mock_client, "https://github.com/org/repo")
    tool = gh._best_tool(["list", "pull", "request"], exclude=["search"])
    assert tool == "list_pull_requests"


def test_tool_error_lists_available() -> None:
    """When no matching tool, error message includes available tools."""
    mock_client = MagicMock(spec=MCPClient)
    mock_client.list_tools.return_value = [
        {"name": "get_weather"},
        {"name": "search_code"},
    ]
    gh = GitHubTools(mock_client, "https://github.com/org/repo")
    with pytest.raises(RuntimeError) as exc_info:
        gh.list_pull_requests()
    msg = str(exc_info.value)
    assert "Available tools:" in msg
    assert "get_weather" in msg or "search_code" in msg
