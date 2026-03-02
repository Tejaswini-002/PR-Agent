"""MCP client implementations: StdioMCPClient (subprocess) and RemoteMCPClient (HTTP/SSE)."""

import json
import logging
import os
import selectors
import subprocess
import time
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class RemoteMCPClient:
    """MCP client for remote servers (JSON-RPC over HTTP, with optional SSE fallback)."""

    def __init__(
        self,
        base_url: str,
        auth_token: str | None = None,
        timeout: float = 60.0,
        mcp_readonly: bool = False,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        headers: dict[str, str] = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2024-11-05",
        }
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        if mcp_readonly:
            headers["X-MCP-Readonly"] = "true"
        self._client = httpx.Client(base_url=self._base_url, headers=headers, timeout=timeout)
        self._session_id: str | None = None

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        body = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        return self._post_jsonrpc(body)

    def _post_jsonrpc(self, body: dict[str, Any]) -> dict[str, Any]:
        resp = self._client.post("/", json=body)
        if resp.status_code in (404, 405):
            logger.debug("JSON-RPC POST returned %s, trying SSE transport", resp.status_code)
            return self._try_sse_transport(body)
        if resp.status_code == 400 and resp.text and "authorization" in resp.text.lower():
            raise RuntimeError(
                "MCP server requires an Authorization header. "
                "Set MCP_AUTH_TOKEN or REPO_ACCESS_TOKEN in .env."
            )
        resp.raise_for_status()
        raw = resp.text
        if not raw or not raw.strip():
            raise RuntimeError("MCP server returned empty response")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # api.githubcopilot.com returns SSE (event: message \n data: {...}) even for POST
            data = self._parse_sse_like_response(raw)
            if data is None:
                preview = (raw[:200] + "...") if len(raw) > 200 else raw
                raise RuntimeError(
                    f"MCP server returned non-JSON (status={resp.status_code}). "
                    f"api.githubcopilot.com often returns HTML/empty to direct HTTP clients. "
                    f"Use local Docker MCP server (MCP_TRANSPORT=stdio) instead. "
                    f"Response preview: {preview!r}"
                )
        if "error" in data and data["error"]:
            raise RuntimeError(data["error"].get("message", "MCP error"))
        if "MCP-Session-Id" in resp.headers:
            self._session_id = resp.headers["MCP-Session-Id"]
        return data

    def _parse_sse_like_response(self, raw: str) -> dict[str, Any] | None:
        """Parse SSE-style body (event: ... \n data: {...}) and return the first JSON object."""
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    msg = json.loads(payload)
                    if isinstance(msg, dict) and ("result" in msg or "error" in msg):
                        return msg
                except json.JSONDecodeError:
                    continue
        return None

    def _try_sse_transport(self, body: dict[str, Any]) -> dict[str, Any]:
        """Fallback: when server returns 404/405, try SSE transport (old HTTP+SSE)."""
        with self._client.stream("POST", "/", json=body) as resp:
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "text/event-stream" in ct:
                return self._read_sse_response(resp)
        raise RuntimeError("MCP server did not support JSON-RPC or SSE transport")

    def _read_sse_response(self, resp: httpx.Response) -> dict[str, Any]:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    msg = json.loads(data)
                    if "error" in msg and msg["error"]:
                        raise RuntimeError(msg["error"].get("message", "MCP error"))
                    return msg
                except json.JSONDecodeError:
                    continue
        raise RuntimeError("No JSON-RPC response in SSE stream")

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        tools = result.get("result", {}).get("tools") if isinstance(result.get("result"), dict) else result.get("tools")
        if isinstance(tools, list):
            return tools
        return []

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        resp = self._request("tools/call", {"name": name, "arguments": arguments})
        return resp.get("result") if "result" in resp else resp

    def close(self) -> None:
        self._client.close()


class StdioMCPClient:
    def __init__(self, command: str, args: list[str], env: dict[str, str] | None = None) -> None:
        if not command:
            raise ValueError("stdio command is required")
        # Pass env so GITHUB_PERSONAL_ACCESS_TOKEN from .env reaches the Docker container
        popen_env = env if env is not None else os.environ.copy()
        self._proc = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=popen_env,
        )
        if not self._proc.stdin or not self._proc.stdout:
            raise RuntimeError("Failed to start stdio MCP process")
        self._selector = selectors.DefaultSelector()
        self._selector.register(self._proc.stdout, selectors.EVENT_READ)
        self._initialize()

    def _initialize(self) -> None:
        init_payload = {
            "jsonrpc": "2.0",
            "id": "init-1",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "neuqa-pr-agent", "version": "0.1.0"},
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
            },
        }
        self.request(init_payload, timeout=60.0, expect_id="init-1")
        self._send_notification("initialized", {})

    def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        if not self._proc.stdin:
            raise RuntimeError("stdio MCP process not available")
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def request(
        self,
        payload: dict[str, Any],
        timeout: float = 60.0,
        expect_id: str | None = None,
    ) -> dict[str, Any]:
        if not self._proc.stdin or not self._proc.stdout:
            raise RuntimeError("stdio MCP process not available")
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

        end_time = time.time() + timeout
        target_id = expect_id if expect_id is not None else payload.get("id")
        while time.time() < end_time:
            events = self._selector.select(timeout=0.5)
            for key, _ in events:
                line = key.fileobj.readline()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if message.get("id") == target_id:
                    return message
        raise TimeoutError("Timed out waiting for MCP stdio response")

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
