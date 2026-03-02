import json
import os
import shlex
import time
import uuid
from dataclasses import dataclass
from typing import Any

from pr_agent.config import Config
from pr_agent.mcp.stdio_client import RemoteMCPClient, StdioMCPClient


@dataclass
class MCPError(Exception):
    message: str
    data: Any | None = None

    def __str__(self) -> str:
        return self.message


class MCPClient:
    def __init__(self, config: Config) -> None:
        self._transport = config.mcp_transport
        if self._transport == "remote" and config.mcp_server_url:
            self._client = RemoteMCPClient(
                base_url=config.mcp_server_url,
                auth_token=config.mcp_auth_token or config.repo_access_token,
                mcp_readonly=config.mcp_readonly,
            )
        elif self._transport == "stdio" and config.mcp_stdio_command:
            args = shlex.split(config.mcp_stdio_args or "")
            env = os.environ.copy()
            # Ensure GitHub token reaches the Docker MCP server (reads GITHUB_PERSONAL_ACCESS_TOKEN)
            if config.repo_access_token:
                env["GITHUB_PERSONAL_ACCESS_TOKEN"] = config.repo_access_token
            self._client = StdioMCPClient(command=config.mcp_stdio_command, args=args, env=env)
        else:
            raise ValueError(
                "MCP config invalid: set MCP_SERVER_URL for remote or MCP_STDIO_COMMAND for stdio"
            )

    def list_tools(self) -> list[dict[str, Any]]:
        if self._transport == "remote":
            try:
                return self._client.list_tools()
            except RuntimeError as e:
                raise MCPError(str(e)) from e
        try:
            response = self._request("tools/list", {})
        except MCPError as exc:
            if self._transport == "stdio" and "session initialization" in str(exc).lower():
                time.sleep(0.2)
                response = self._request("tools/list", {})
            else:
                raise
        tools = response.get("tools") or (response.get("result") or {}).get("tools")
        if isinstance(tools, list):
            return tools
        return []

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._transport == "remote":
            try:
                return self._client.call_tool(name, arguments)
            except RuntimeError as e:
                raise MCPError(str(e)) from e
        payload = {"name": name, "arguments": arguments}
        response = self._request("tools/call", payload)
        return response.get("result") if "result" in response else response

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        body = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        data = self._client.request(body)
        if "error" in data and data["error"]:
            err = data["error"]
            raise MCPError(err.get("message", "MCP error"), err)
        return data

    def close(self) -> None:
        self._client.close()
