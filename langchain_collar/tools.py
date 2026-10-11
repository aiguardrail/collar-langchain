"""LangChain tools for Collar Guardrail — pre-trade risk checks on Robinhood Chain."""

from __future__ import annotations

import asyncio
import functools
import itertools
import json
import logging
import os
import threading
import time
import uuid
from typing import Annotated, Any, Callable, Literal, Optional

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

__version__ = "1.1.0"

log = logging.getLogger("langchain_collar")

_BASE_URL = os.environ.get("COLLAR_BASE_URL", "https://api.collarguardrail.com")
_TIMEOUT = float(os.environ.get("COLLAR_TIMEOUT", "30"))
_MAX_RETRIES = int(os.environ.get("COLLAR_MAX_RETRIES", "2"))
_ASSETS_TTL = 300  # seconds

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


# ---------------------------------------------------------------------------
# MCP client (streamable HTTP)
# ---------------------------------------------------------------------------

class CollarError(Exception):
    """Any failure talking to the Collar Guardrail API."""


class _SessionExpired(CollarError):
    pass


class _MCPClient:
    def __init__(self, base_url: str, timeout: float, max_retries: int) -> None:
        self._endpoint = f"{base_url.rstrip('/')}/mcp-http/mcp"
        self._http = httpx.Client(timeout=timeout)
        self._max_retries = max_retries
        self._sid: Optional[str] = None
        self._lock = threading.Lock()
        self._ids = itertools.count(1)

    # -- session ----------------------------------------------------------

    def _ensure_session(self) -> str:
        with self._lock:
            if self._sid:
                return self._sid
            payload = {
                "jsonrpc": "2.0",
                "id": next(self._ids),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "langchain-collar", "version": __version__},
                },
            }
            r = self._http.post(self._endpoint, json=payload, headers=_HEADERS)
            r.raise_for_status()
            sid = r.headers.get("mcp-session-id")
            if not sid:
                raise CollarError("MCP server did not return mcp-session-id")
            # MCP spec: confirm initialization (best effort).
            try:
                self._http.post(
                    self._endpoint,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                    headers={**_HEADERS, "mcp-session-id": sid},
                )
            except httpx.HTTPError:
                pass
            self._sid = sid
            return sid

    def reset_session(self) -> None:
        with self._lock:
            self._sid = None

    # -- response parsing -------------------------------------------------

    @staticmethod
    def _parse(resp: httpx.Response, rpc_id: int) -> Any:
        ctype = resp.headers.get("content-type", "")
        messages: list[dict] = []
        if "text/event-stream" in ctype:
            for line in resp.text.splitlines():
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if chunk:
                        try:
                            messages.append(json.loads(chunk))
                        except ValueError:
                            continue
        else:
            try:
                body = resp.json()
            except ValueError as e:
                raise CollarError(f"Invalid response from server: {resp.text[:200]}") from e
            messages = body if isinstance(body, list) else [body]

        msg = next((m for m in messages if m.get("id") == rpc_id), None)
        if msg is None:
            raise CollarError("No matching JSON-RPC response in server reply")
        if "error" in msg:
            err = msg["error"]
            text = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            if "session" in text.lower():
                raise _SessionExpired(text)
            raise CollarError(text)
        return msg.get("result")

    @staticmethod
    def _unwrap(result: Any) -> Any:
        if not isinstance(result, dict):
            return result
        if result.get("isError"):
            content = result.get("content") or [{}]
            raise CollarError(str(content[0].get("text", "tool error")))
        if "structuredContent" in result:
            return result["structuredContent"]
        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and first.get("type") == "text":
                try:
                    return json.loads(first["text"])
                except (ValueError, TypeError):
                    return first["text"]
        return result

    # -- calls ------------------------------------------------------------

    def _call_once(self, tool: str, arguments: dict) -> Any:
        sid = self._ensure_session()
        rpc_id = next(self._ids)
        payload = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        r = self._http.post(
            self._endpoint, json=payload, headers={**_HEADERS, "mcp-session-id": sid}
        )
        if r.status_code in (400, 404) and "session" in r.text.lower():
            raise _SessionExpired(r.text[:200])
        r.raise_for_status()
        return self._unwrap(self._parse(r, rpc_id))

    def call(self, tool: str, arguments: dict) -> Any:
        last: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                return self._call_once(tool, arguments)
            except _SessionExpired as e:
                self.reset_session()
                last = e
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500:
                    raise CollarError(
                        f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                    ) from e
                last = e
            except httpx.TransportError as e:
                last = e
            if attempt < self._max_retries:
                time.sleep(0.5 * (2**attempt))
        raise CollarError(f"{tool} failed after retries: {last}") from last


_client = _MCPClient(_BASE_URL, _TIMEOUT, _MAX_RETRIES)


# ---------------------------------------------------------------------------
# Fail-closed wrapper
# ---------------------------------------------------------------------------

def _fail_closed(fn: Callable[..., Any]) -> Callable[..., Any]:
    """On any error, return an explicit non-allow result instead of raising."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (CollarError, httpx.HTTPError) as e:
            log.warning("%s failed: %s", fn.__name__, e)
            return {
                "decision": "error",
                "allowed": False,
                "error": str(e),
                "note": "Guardrail unavailable. Treat as DENY: do not execute the trade.",
            }

    return wrapper


def _clean(**kwargs: Any) -> dict:
    return {k: v for k, v in kwargs.items() if v is not None}


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------

Address = Annotated[str, Field(pattern=r"^0x[a-fA-F0-9]{40}$")]


class EvaluateTradeInput(BaseModel):
    """Input schema for the evaluate_trade tool."""

    wallet: Address = Field(..., description="EVM wallet address (0x...) the trade would execute from.")
    asset: str = Field(..., description="Asset symbol, e.g. NVDA, AAPL, TSLA, USDG.")
    contract_address: Address = Field(
        ...,
        description=(
            "Token contract address (0x...). Must match the official registry "
            "address for that symbol, or the trade is denied as a suspected fake token."
        ),
    )
    side: Literal["buy", "sell"] = Field(..., description="Trade direction: 'buy' or 'sell'.")
    amount: float = Field(..., gt=0, description="Quantity in token units, NOT a pre-computed USD value.")
    max_slippage_bps: int = Field(default=100, ge=0, le=10000, description="Max slippage in basis points (default 100).")
    request_id: Optional[str] = Field(
        default=None,
        description="Optional idempotency key. Auto-generated if omitted.",
    )


class EvaluateTradePaidInput(EvaluateTradeInput):
    """Input schema for the evaluate_trade_paid tool."""

    payment_proof: Optional[str] = Field(
        default=None,
        description=(
            "x402 payment proof from the facilitator. Omit on the first call "
            "to receive the payment challenge."
        ),
    )


class CheckTokenSafetyInput(BaseModel):
    contract_address: Address = Field(..., description="Token contract address (0x...).")


class SimulateBalanceInput(BaseModel):
    token_address: Address = Field(..., description="ERC-20 contract address (0x...).")
    holder: Address = Field(..., description="Wallet address whose balance is simulated (0x...).")
    delta: float = Field(..., description="Signed amount (negative = spend).")
    decimals: int = Field(default=18, ge=0, le=36, description="Token decimals (default 18).")


class GetSupportedAssetsInput(BaseModel):
    """No arguments."""


class VerifyAuditTrailInput(BaseModel):
    wallet: Address = Field(..., description="EVM wallet address (0x...).")
    limit: int = Field(default=100, ge=1, le=1000, description="How many recent records to verify (1-1000, default 100).")


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

@_fail_closed
def _evaluate_trade(
    wallet: str,
    asset: str,
    contract_address: str,
    side: str,
    amount: float,
    max_slippage_bps: int = 100,
    request_id: Optional[str] = None,
) -> Any:
    return _client.call(
        "evaluate_trade",
        _clean(
            wallet=wallet,
            asset=asset,
            contract_address=contract_address,
            side=side,
            amount=amount,
            max_slippage_bps=max_slippage_bps,
            request_id=request_id or str(uuid.uuid4()),  # stable across retries
        ),
    )


@_fail_closed
def _evaluate_trade_paid(
    wallet: str,
    asset: str,
    contract_address: str,
    side: str,
    amount: float,
    max_slippage_bps: int = 100,
    request_id: Optional[str] = None,
    payment_proof: Optional[str] = None,
) -> Any:
    return _client.call(
        "evaluate_trade_paid",
        _clean(
            wallet=wallet,
            asset=asset,
            contract_address=contract_address,
            side=side,
            amount=amount,
            max_slippage_bps=max_slippage_bps,
            request_id=request_id or str(uuid.uuid4()),
            payment_proof=payment_proof,
        ),
    )


@_fail_closed
def _check_token_safety(contract_address: str) -> Any:
    return _client.call("check_token_safety", {"contract_address": contract_address})


@_fail_closed
def _simulate_balance(token_address: str, holder: str, delta: float, decimals: int = 18) -> Any:
    return _client.call(
        "simulate_balance",
        {"token_address": token_address, "holder": holder, "delta": delta, "decimals": decimals},
    )


_assets_cache: dict[str, Any] = {"ts": 0.0, "data": None}


@_fail_closed
def _get_supported_assets() -> Any:
    now = time.monotonic()
    if _assets_cache["data"] is not None and now - _assets_cache["ts"] < _ASSETS_TTL:
        return _assets_cache["data"]
    data = _client.call("get_supported_assets", {})
    _assets_cache.update(ts=now, data=data)
    return data


@_fail_closed
def _verify_audit_trail(wallet: str, limit: int = 100) -> Any:
    return _client.call("verify_audit_trail", {"wallet": wallet, "limit": limit})


def _aio(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Async twin of a sync tool function (runs in a worker thread)."""

    async def run(**kwargs: Any) -> Any:
        return await asyncio.to_thread(fn, **kwargs)

    run.__name__ = f"a{fn.__name__}"
    return run


# ---------------------------------------------------------------------------
# StructuredTool wrappers
# ---------------------------------------------------------------------------

evaluate_trade = StructuredTool.from_function(
    func=_evaluate_trade,
    coroutine=_aio(_evaluate_trade),
    name="evaluate_trade",
    description=(
        "Pre-trade risk check for a proposed trade on Robinhood Chain.\n\n"
        "Call this BEFORE executing any trade. Returns allow / warn / deny "
        "with reasons, a 0-100 risk score, and a tamper-evident audit hash. "
        "Evaluated at a fixed Tier 1 ceiling ($5,000 notional). Treat a "
        "'deny' or 'error' decision as a hard stop."
    ),
    args_schema=EvaluateTradeInput,
)

evaluate_trade_paid = StructuredTool.from_function(
    func=_evaluate_trade_paid,
    coroutine=_aio(_evaluate_trade_paid),
    name="evaluate_trade_paid",
    description=(
        "Pre-trade risk check gated by an x402 payment. Evaluated as COLR "
        "Tier 2: $25,000 notional ceiling, 10/25 per-minute rate limits. "
        "No COLR holdings are required; the on-chain payment is the "
        "credential. Call without payment_proof first to receive the "
        "payment challenge, settle on-chain, then retry with the proof. "
        "Treat a 'deny' or 'error' decision as a hard stop."
    ),
    args_schema=EvaluateTradePaidInput,
)

check_token_safety = StructuredTool.from_function(
    func=_check_token_safety,
    coroutine=_aio(_check_token_safety),
    name="check_token_safety",
    description=(
        "Honeypot / contract safety check for any ERC-20 token. Returns "
        "severity (safe / warn / danger), risk factors, and a sell-simulation "
        "result. When severity=danger, evaluate_trade auto-DENIES the trade."
    ),
    args_schema=CheckTokenSafetyInput,
)

simulate_balance = StructuredTool.from_function(
    func=_simulate_balance,
    coroutine=_aio(_simulate_balance),
    name="simulate_balance",
    description=(
        "Simulate a wallet's ERC-20 balance after a hypothetical trade using "
        "eth_call state override. Read-only: no transaction is ever sent."
    ),
    args_schema=SimulateBalanceInput,
)

get_supported_assets = StructuredTool.from_function(
    func=_get_supported_assets,
    coroutine=_aio(_get_supported_assets),
    name="get_supported_assets",
    description=(
        "List every asset in the guardrail's official Robinhood Chain registry, "
        "with its canonical contract address. Call this to resolve a symbol to "
        "the correct contract_address before evaluate_trade."
    ),
    args_schema=GetSupportedAssetsInput,
)

verify_audit_trail = StructuredTool.from_function(
    func=_verify_audit_trail,
    coroutine=_aio(_verify_audit_trail),
    name="verify_audit_trail",
    description=(
        "Verify the tamper-evident audit trail for a wallet's past guardrail "
        "decisions. Returns healthy=true only if every record's SHA-256 hash "
        "matches and the chain is unbroken."
    ),
    args_schema=VerifyAuditTrailInput,
)

ALL_TOOLS = [
    evaluate_trade,
    evaluate_trade_paid,
    check_token_safety,
    simulate_balance,
    get_supported_assets,
    verify_audit_trail,
]

__all__ = [t.name for t in ALL_TOOLS] + ["ALL_TOOLS", "CollarError"]
