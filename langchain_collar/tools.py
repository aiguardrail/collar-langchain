import httpx
import json
from typing import Any

_MCP_ENDPOINT = "https://api.collarguardrail.com/mcp-http/mcp"

# Session cache — bir kez initialize et, tekrar kullan
_session_cache: dict[str, str] = {}


def _get_mcp_session() -> str:
    """Initialize MCP session and return session ID (cached)."""
    if "sid" in _session_cache:
        return _session_cache["sid"]

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "langchain-collar", "version": "1.0.6"},
        },
    }
    r = httpx.post(_MCP_ENDPOINT, json=payload, headers=headers, timeout=15)
    r.raise_for_status()
    sid = r.headers.get("mcp-session-id")
    if not sid:
        raise RuntimeError("MCP server did not return mcp-session-id")
    _session_cache["sid"] = sid
    return sid


def _call_mcp_tool(tool_name: str, arguments: dict) -> Any:
    sid = _get_mcp_session()

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "mcp-session-id": sid,
    }
    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    r = httpx.post(_MCP_ENDPOINT, json=payload, headers=headers, timeout=30)
    r.raise_for_status()

    # SSE response: satırlardan birinde `data: {...}` var
    for line in r.text.splitlines():
        if line.startswith("data: "):
            data = json.loads(line[6:])
            return data.get("result")
    return json.loads(r.text)
