import json
from typing import Any
from urllib.parse import urlparse

from pr_agent.mcp.client import MCPClient, MCPError


class GitHubTools:
    def __init__(self, client: MCPClient, repo_url: str) -> None:
        self._client = client
        self._owner, self._repo = self._parse_repo(repo_url)
        self._tools_cache: list[str] | None = None

    @staticmethod
    def _parse_repo(repo_url: str) -> tuple[str, str]:
        parsed = urlparse(repo_url)
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            raise ValueError("REPO_URL must include owner and repo")
        return parts[0], parts[1]

    def _tools(self) -> list[str]:
        if self._tools_cache is None:
            tools = self._client.list_tools()
            self._tools_cache = [tool.get("name", "") if isinstance(tool, dict) else str(tool) for tool in tools]
        return [t for t in self._tools_cache if t]

    def _has_tool(self, name: str) -> bool:
        return name in self._tools()

    def _best_tool(self, include: list[str], exclude: list[str] | None = None) -> str | None:
        exclude = exclude or []
        candidates = []
        for name in self._tools():
            lname = name.lower()
            if any(term not in lname for term in include):
                continue
            if any(term in lname for term in exclude):
                continue
            score = sum(1 for term in include if term in lname)
            candidates.append((score, name))
        candidates.sort(reverse=True)
        return candidates[0][1] if candidates else None

    def _tool_error(self, op: str) -> str:
        tools = self._tools()
        avail = ", ".join(sorted(tools)[:20]) if tools else "(none)"
        if len(tools) > 20:
            avail += f", ... ({len(tools)} total)"
        return f"No MCP tool available for {op}. Available tools: {avail}"

    def _extract_payload(self, result: Any) -> Any:
        if isinstance(result, dict) and "content" in result:
            content = result.get("content")
            if isinstance(content, list) and content:
                text = content[0].get("text") if isinstance(content[0], dict) else None
                if text is not None and str(text).strip():
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return {"text": text}
                if text is not None:
                    return {} if not str(text).strip() else {"text": text}
        return result

    def get_pull_request(self, pr_number: int) -> dict[str, Any]:
        if self._has_tool("pull_request_read"):
            args_variants = [
                {"owner": self._owner, "repo": self._repo, "pullNumber": pr_number, "method": "get"},
                {"owner": self._owner, "repo": self._repo, "pull_number": pr_number, "method": "get"},
            ]
            for args in args_variants:
                try:
                    result = self._client.call_tool("pull_request_read", args)
                    return self._extract_payload(result) or {}
                except MCPError:
                    continue
        tool = self._best_tool(["pull_request", "get"], exclude=["comments", "reviews", "files"])
        if not tool:
            raise RuntimeError(self._tool_error("pull request get"))
        args_variants = [
            {"owner": self._owner, "repo": self._repo, "pull_number": pr_number},
            {"owner": self._owner, "repo": self._repo, "pullNumber": pr_number},
        ]
        for args in args_variants:
            try:
                result = self._client.call_tool(tool, args)
                return self._extract_payload(result) or {}
            except MCPError:
                continue
        raise RuntimeError("Failed to fetch pull request")

    def list_pull_request_files(self, pr_number: int) -> list[dict[str, Any]]:
        if self._has_tool("pull_request_read"):
            args_variants = [
                {"owner": self._owner, "repo": self._repo, "pullNumber": pr_number, "method": "get_files"},
                {"owner": self._owner, "repo": self._repo, "pull_number": pr_number, "method": "get_files"},
            ]
            for args in args_variants:
                try:
                    result = self._client.call_tool("pull_request_read", args)
                    payload = self._extract_payload(result)
                    if isinstance(payload, dict) and "files" in payload:
                        return payload.get("files") or []
                    if isinstance(payload, list):
                        return payload
                except MCPError:
                    continue
        tool = self._best_tool(["pull_request", "files"], exclude=["comments", "reviews"])
        if not tool:
            raise RuntimeError(self._tool_error("pull request files"))
        args_variants = [
            {"owner": self._owner, "repo": self._repo, "pull_number": pr_number},
            {"owner": self._owner, "repo": self._repo, "pullNumber": pr_number},
        ]
        for args in args_variants:
            try:
                result = self._client.call_tool(tool, args)
                payload = self._extract_payload(result)
                if isinstance(payload, dict) and "files" in payload:
                    return payload.get("files") or []
                if isinstance(payload, list):
                    return payload
            except MCPError:
                continue
        return []

    def get_pull_request_file_diff(self, pr_number: int, file_path: str) -> str | None:
        tool = self._best_tool(["pull_request", "diff"], exclude=["comments", "reviews"])
        if not tool:
            tool = self._best_tool(["pull_request", "patch"], exclude=["comments", "reviews"])
        if not tool:
            tool = self._best_tool(["pull_request", "file"], exclude=["comments", "reviews"])
        if not tool:
            return None
        args_variants = [
            {"owner": self._owner, "repo": self._repo, "pull_number": pr_number, "file_path": file_path},
            {"owner": self._owner, "repo": self._repo, "pullNumber": pr_number, "path": file_path},
        ]
        for args in args_variants:
            try:
                result = self._client.call_tool(tool, args)
                payload = self._extract_payload(result)
                if isinstance(payload, dict):
                    return payload.get("patch") or payload.get("diff")
                if isinstance(payload, str):
                    return payload
            except MCPError:
                continue
        return None

    def create_or_update_pr_comment(self, pr_number: int, body: str) -> None:
        tool = self._best_tool(["pull_request", "comment"], exclude=["review"])
        if not tool:
            raise RuntimeError(self._tool_error("pull request comment"))
        args_variants = [
            {"owner": self._owner, "repo": self._repo, "pull_number": pr_number, "body": body},
            {"owner": self._owner, "repo": self._repo, "pullNumber": pr_number, "body": body},
        ]
        last_error: Exception | None = None
        for args in args_variants:
            try:
                self._client.call_tool(tool, args)
                return
            except MCPError as exc:
                last_error = exc
        raise RuntimeError(f"Failed to post PR comment: {last_error}")

    def list_pull_requests(self, state: str = "open", page: int = 1, per_page: int = 20) -> list[dict[str, Any]]:
        tool = self._best_tool(["list", "pull", "request"], exclude=["search"])
        if not tool:
            raise RuntimeError(self._tool_error("list pull requests"))
        args_variants = [
            {
                "owner": self._owner,
                "repo": self._repo,
                "state": state,
                "page": page,
                "perPage": per_page,
            },
            {
                "owner": self._owner,
                "repo": self._repo,
                "state": state,
                "page": page,
                "per_page": per_page,
            },
        ]
        for args in args_variants:
            try:
                result = self._client.call_tool(tool, args)
                payload = self._extract_payload(result)
                if isinstance(payload, dict) and "pulls" in payload:
                    return payload.get("pulls") or []
                if isinstance(payload, list):
                    return payload
            except MCPError:
                continue
        return []

    def list_issues(self, state: str = "open", page: int = 1, per_page: int = 20) -> list[dict[str, Any]]:
        tool = self._best_tool(["list", "issue"], exclude=["search"])
        if not tool:
            raise RuntimeError(self._tool_error("list issues"))
        args_variants = [
            {
                "owner": self._owner,
                "repo": self._repo,
                "state": state,
                "page": page,
                "perPage": per_page,
            },
            {
                "owner": self._owner,
                "repo": self._repo,
                "state": state,
                "page": page,
                "per_page": per_page,
            },
        ]
        for args in args_variants:
            try:
                result = self._client.call_tool(tool, args)
                payload = self._extract_payload(result)
                if isinstance(payload, dict) and "issues" in payload:
                    return payload.get("issues") or []
                if isinstance(payload, list):
                    return payload
            except MCPError:
                continue
        return []

    def list_commits(self, sha: str | None = None, page: int = 1, per_page: int = 20) -> list[dict[str, Any]]:
        tool = self._best_tool(["list", "commit"], exclude=["search"])
        if not tool:
            raise RuntimeError(self._tool_error("list commits"))
        base_args = {
            "owner": self._owner,
            "repo": self._repo,
            "page": page,
            "perPage": per_page,
        }
        if sha:
            base_args["sha"] = sha
        args_variants = [base_args, {**base_args, "per_page": per_page}]
        for args in args_variants:
            try:
                result = self._client.call_tool(tool, args)
                payload = self._extract_payload(result)
                if isinstance(payload, dict) and "commits" in payload:
                    return payload.get("commits") or []
                if isinstance(payload, list):
                    return payload
            except MCPError:
                continue
        return []

    def list_branches(self, page: int = 1, per_page: int = 50) -> list[dict[str, Any]]:
        tool = (
            "list_branches"
            if self._has_tool("list_branches")
            else "listBranches"
            if self._has_tool("listBranches")
            else self._best_tool(["list", "branch"], exclude=["search"])
        )
        if not tool:
            return []
        args_variants = [
            {"owner": self._owner, "repo": self._repo, "page": page, "perPage": per_page},
            {"owner": self._owner, "repo": self._repo, "page": page, "per_page": per_page},
        ]
        for args in args_variants:
            try:
                result = self._client.call_tool(tool, args)
                payload = self._extract_payload(result)
                if isinstance(payload, dict) and "branches" in payload:
                    return payload.get("branches") or []
                if isinstance(payload, list):
                    return payload
            except MCPError:
                continue
        return []

    def list_pr_comments(self, pr_number: int, page: int = 1, per_page: int = 20) -> list[dict[str, Any]]:
        tool = self._best_tool(["pull_request_read"], exclude=[])
        if not tool:
            raise RuntimeError(self._tool_error("pull request comments"))
        args_variants = [
            {
                "owner": self._owner,
                "repo": self._repo,
                "pullNumber": pr_number,
                "method": "get_comments",
                "page": page,
                "perPage": per_page,
            },
            {
                "owner": self._owner,
                "repo": self._repo,
                "pull_number": pr_number,
                "method": "get_comments",
                "page": page,
                "per_page": per_page,
            },
        ]
        for args in args_variants:
            try:
                result = self._client.call_tool(tool, args)
                payload = self._extract_payload(result)
                if isinstance(payload, dict) and "comments" in payload:
                    return payload.get("comments") or []
                if isinstance(payload, list):
                    return payload
            except MCPError:
                continue
        return []

    def list_issue_comments(self, issue_number: int, page: int = 1, per_page: int = 20) -> list[dict[str, Any]]:
        tool = self._best_tool(["issue_read"], exclude=[])
        if not tool:
            raise RuntimeError(self._tool_error("issue comments"))
        args_variants = [
            {
                "owner": self._owner,
                "repo": self._repo,
                "issue_number": issue_number,
                "method": "get_comments",
                "page": page,
                "perPage": per_page,
            },
            {
                "owner": self._owner,
                "repo": self._repo,
                "issue_number": issue_number,
                "method": "get_comments",
                "page": page,
                "per_page": per_page,
            },
        ]
        for args in args_variants:
            try:
                result = self._client.call_tool(tool, args)
                payload = self._extract_payload(result)
                if isinstance(payload, dict) and "comments" in payload:
                    return payload.get("comments") or []
                if isinstance(payload, list):
                    return payload
            except MCPError:
                continue
        return []

    def list_workflows(self, page: int = 1, per_page: int = 50) -> list[dict[str, Any]]:
        tool = (
            "list_workflows"
            if self._has_tool("list_workflows")
            else self._best_tool(["actions_list"], exclude=[])
            or self._best_tool(["actions", "list"], exclude=[])
        )
        if not tool:
            return []
        # Standalone list_workflows uses owner, repo, page, perPage
        args_variants = [
            {"owner": self._owner, "repo": self._repo, "page": page, "perPage": per_page},
            {"owner": self._owner, "repo": self._repo, "page": page, "per_page": per_page},
            {
                "owner": self._owner,
                "repo": self._repo,
                "method": "list_workflows",
                "page": page,
                "perPage": per_page,
            },
            {
                "owner": self._owner,
                "repo": self._repo,
                "method": "list_workflows",
                "page": page,
                "per_page": per_page,
            },
        ]
        for args in args_variants:
            try:
                result = self._client.call_tool(tool, args)
                payload = self._extract_payload(result)
                if isinstance(payload, dict) and "workflows" in payload:
                    return payload.get("workflows") or []
                if isinstance(payload, list):
                    return payload
            except MCPError:
                continue
        return []
