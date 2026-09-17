"""LangChain tools for Collar Guardrail.

Each tool is a thin wrapper around the Collar MCP server at
https://backendai-x4m1.onrender.com/mcp-http/mcp. The MCP server
exposes evaluate_trade, check_token_safety, simulate_balance,
get_supported_assets, and verify_audit_trail.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

_BASE_URL = "https://backendai-x4m1.onrender.com"
_MCP_ENDPOINT = f"{_BASE_URL}/mcp-http/mcp"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
_TIMEOUT = 30.0


def _call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> str:
    """Call an MCP tool and return the text content of the response."""
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
        "id": 1,
    }

    with httpx.Client(timeout=_TIMEOUT) as client:
        response = client.post(_MCP_ENDPOINT, json=payload, headers=_HEADERS)
        response.raise_for_status()
        data = response.json()

    content = data.get("result", {}).get("content", [])
    if content:
        return content[0].get("text", json.dumps(data))
    return json.dumps(data, indent=2)


class EvaluateTradeInput(BaseModel):
    """Input schema for the evaluate_trade tool."""

    wallet: str = Field(
        ...,
        description="EVM wallet address (0x...) the trade would execute from.",
    )
    asset: str = Field(
        ...,
        description="Asset symbol, e.g. NVDA, AAPL, TSLA, USDG.",
    )
    contract_address: str = Field(
        ...,
        description=(
            "Token contract address (0x...). Must match the official "
            "registry address for that symbol, or the trade is denied "
            "as a suspected fake token."
        ),
    )
    side: str = Field(
        ...,
        description="Trade direction: 'buy' or 'sell'.",
    )
    amount: float = Field(
        ...,
        description="Quantity in token units — NOT a pre-computed USD value.",
    )
    max_slippage_bps: int = Field(
        default=100,
        description="Max slippage in basis points (default 100).",
    )
    request_id: Optional[str] = Field(
        default=None,
        description="Optional idempotency key.",
    )


@tool(args_schema=EvaluateTradeInput)
def evaluate_trade(
    wallet: str,
    asset: str,
    contract_address: str,
    side: str,
    amount: float,
    max_slippage_bps: int = 100,
    request_id: Optional[str] = None,
) -> str:
    """Pre-trade risk check for a proposed trade on Robinhood Chain.

    Call this BEFORE executing any trade. Returns allow / warn / deny
    with reasons, a 0-100 risk score, and a tamper-evident audit hash.
    Treat a 'deny' decision as a hard stop.
    """
    return _call_mcp_tool(
        "evaluate_trade",
        {
            "wallet": wallet,
            "asset": asset,
            "contract_address": contract_address,
            "side": side,
            "amount": amount,
            "max_slippage_bps": max_slippage_bps,
            "request_id": request_id,
        },
    )


@tool
def check_token_safety(contract_address: str) -> str:
    """Honeypot / contract safety check for any ERC-20 token.

    Returns severity (safe / warn / danger), specific risk factors,
    and a sell-simulation result. Use before trading unknown memecoins
    or tokens absent from the official registry.
    """
    return _call_mcp_tool(
        "check_token_safety",
        {"contract_address": contract_address},
    )


@tool
def simulate_balance(
    token_address: str,
    holder: str,
    delta: float,
    decimals: int = 18,
) -> str:
    """Simulate a wallet's ERC-20 balance after a hypothetical trade.

    Read-only: no transaction is ever sent. Uses eth_call state override.
    """
    return _call_mcp_tool(
        "simulate_balance",
        {
            "token_address": token_address,
            "holder": holder,
            "delta": delta,
            "decimals": decimals,
        },
    )


@tool
def get_supported_assets() -> str:
    """List every asset in Collar Guardrail's official Robinhood Chain registry.

    Returns symbol, contract_address, and is_native for each asset.
    Resolve a symbol to the correct contract_address BEFORE calling
    evaluate_trade — a mismatched address is treated as a fake-token
    attempt and denied.
    """
    return _call_mcp_tool("get_supported_assets", {})


@tool
def verify_audit_trail(wallet: str, limit: int = 100) -> str:
    """Verify the tamper-evident audit trail for a wallet's past decisions.

    Recomputes every record's SHA-256 hash and checks the hash-chain
    links. Returns healthy=true only if every record's hash matches
    AND the chain is unbroken.
    """
    return _call_mcp_tool(
        "verify_audit_trail",
        {"wallet": wallet, "limit": limit},
    )


def get_tools() -> list:
    """Return all Collar Guardrail tools as a list."""
    return [
        evaluate_trade,
        check_token_safety,
        simulate_balance,
        get_supported_assets,
        verify_audit_trail,
    ]
