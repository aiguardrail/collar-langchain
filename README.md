markdown
# langchain-collar

**LangChain tools for Collar Guardrail** — deterministic pre-trade risk
checks for AI trading agents on Robinhood Chain.

[![PyPI version](https://img.shields.io/pypi/v/langchain-collar.svg)](https://pypi.org/project/langchain-collar/)
[![PyPI downloads](https://img.shields.io/pypi/dm/langchain-collar.svg)](https://pypi.org/project/langchain-collar/)
[![Python versions](https://img.shields.io/pypi/pyversions/langchain-collar.svg)](https://pypi.org/project/langchain-collar/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)

---

## What is this?

This package wraps the [Collar Guardrail](https://collarguardrail.com)
MCP server as native LangChain tools. Any LangChain agent can evaluate
proposed trades against a deterministic risk policy **before** executing
them — with `allow` / `warn` / `deny` verdicts, a 0–100 risk score, and a
tamper-evident SHA-256 audit hash.

If you're building a trading agent that needs to respect rate limits, tier
ceilings, honeypot checks, or market-hours rules, these tools enforce those
constraints outside your agent's own runtime.

---

## Installation

```bash
pip install langchain-collar
Requires Python 3.10+ and langchain-core>=0.3.0.

Quick Start
Add tools to a LangChain agent
python
from langchain_collar import get_tools
from langchain.agents import create_agent

tools = get_tools()
agent = create_agent("gpt-4o", tools)

result = agent.invoke({
    "messages": [{
        "role": "user",
        "content": (
            "Before executing a 10 NVDA buy from wallet "
            "0x1234567890abcdef1234567890abcdef12345678, "
            "run a pre-trade risk check."
        ),
    }]
})
print(result)
Or call a tool directly
python
from langchain_collar import evaluate_trade

verdict = evaluate_trade.invoke({
    "wallet": "0x1234567890abcdef1234567890abcdef12345678",
    "asset": "NVDA",
    "contract_address": "0x<official_registry_address>",
    "side": "buy",
    "amount": 10.0,
})
print(verdict)
Available Tools
Tool	Description
evaluate_trade	Call before every trade. Returns allow / warn / deny, reasons, risk score, and audit hash. Evaluated at a fixed Tier 1 ceiling ($5,000 notional). Treat deny as a hard stop. Honeypot findings (severity=danger) from check_token_safety automatically force a deny regardless of other checks.
evaluate_trade_paid	Same as evaluate_trade, gated by an x402 payment. Evaluated as Tier 2 ($25,000 ceiling). Call without payment_proof first to receive the on-chain payment challenge; settle it with an x402-capable client; retry with the proof to receive a full verdict at tier=2. No COLR holdings are required — the on-chain payment is the credential.
check_token_safety	Honeypot / contract safety check for any ERC-20 token. Returns severity (safe / warn / danger) plus a sell-simulation result. When severity=danger, the next evaluate_trade for the same contract is auto-denied.
simulate_balance	Read-only simulation of a wallet's ERC-20 balance after a hypothetical trade. No transaction is sent.
get_supported_assets	The official Robinhood Chain asset registry. Resolve a symbol to its canonical contract address before calling evaluate_trade.
verify_audit_trail	Recomputes every past decision's SHA-256 hash and verifies the hash-chain links. Returns healthy=true only if nothing was tampered with.
How It Works
Each tool is a thin wrapper around the Collar Guardrail MCP server at:

text
https://api.collarguardrail.com/mcp-http/mcp
The MCP transport is Streamable HTTP (protocol version 2025-06-18).
No API key is required for the MCP endpoint — every call is evaluated at a
fixed Tier 1 ceiling ($5,000 notional).

For higher limits, use one of:

evaluate_trade_paid — the MCP tool in this package. Evaluated as
Tier 2 ($25,000 ceiling) for a per-call x402 fee, no COLR required.

REST API with wallet-signature authentication — full Tier 1/2/3
access. See the Collar agent docs.

Decision Semantics
Decision	Meaning	Action
allow	Policy passed.	Safe to execute.
warn	Policy soft-violated.	Trade may proceed but is flagged. Reasons prefixed with ADVISORY: are non-blocking.
deny	Policy hard-violated.	Do not execute. Reasons are blocking. Honeypot findings (severity=danger) always produce a deny.
Safety rule: If a verdict contains an error key, no verdict was
produced. Treat it as a hard stop. If decision == "deny", do not
execute the trade.

Example: Full Pre-Trade Flow
python
import json

from langchain_collar import (
    evaluate_trade,
    get_supported_assets,
    check_token_safety,
)

# 1. Resolve the symbol to its canonical contract address
assets = get_supported_assets.invoke({})
print(assets)  # → list of {symbol, contract_address, is_native}

# 2. Check the token for honeypot risk BEFORE evaluating the trade
safety = json.loads(check_token_safety.invoke({
    "contract_address": "0x<token_address>",
}))
if safety.get("severity") == "danger":
    raise RuntimeError(
        f"Token is flagged as dangerous: {safety.get('risk_factors')}"
    )

# 3. Run the pre-trade risk check
verdict = evaluate_trade.invoke({
    "wallet": "0x1234567890abcdef1234567890abcdef12345678",
    "asset": "NVDA",
    "contract_address": "0x<official_registry_address>",
    "side": "buy",
    "amount": 10.0,
    "max_slippage_bps": 100,
})

if '"decision": "deny"' in verdict:
    raise RuntimeError("Trade denied by Collar Guardrail")

# Proceed with the trade only if the verdict is allow or warn
Paid Tier (x402)
For trades above the Tier 1 ceiling ($5,000), use `evaluate_trade_paid`.
It grants Tier 2 ($25,000 ceiling) in exchange for an on-chain x402
payment — no COLR holdings, no signup, no API key.

Price: $0.10 USDG per call on Robinhood Chain (eip155:4663).
Discovery: https://api.collarguardrail.com/.well-known/x402.json.
Facilitator: Ultravioleta DAO.

python
from langchain_collar import evaluate_trade_paid

# First call: no payment_proof → returns the payment challenge
challenge = evaluate_trade_paid.invoke({
    "wallet": "0x...",
    "asset": "NVDA",
    "contract_address": "0x...",
    "side": "buy",
    "amount": 50.0,
})
print(challenge)  # → {status: "payment_required", network, asset, amount, pay_to, ...}

# Settle the payment on-chain with an x402-capable client, then retry:
verdict = evaluate_trade_paid.invoke({
    "wallet": "0x...",
    "asset": "NVDA",
    "contract_address": "0x...",
    "side": "buy",
    "amount": 50.0,
    "payment_proof": "<proof from the facilitator>",
})
# verdict now carries tier=2 with a $25,000 ceiling
Configuration
The package talks to the public Collar MCP endpoint
(https://api.collarguardrail.com/mcp-http/mcp) by default. To self-host
Collar, override the base URL before the first tool call:

python
import langchain_collar.tools as tools

tools._BASE_URL = "https://your-collar-instance.example.com"
tools._MCP_ENDPOINT = f"{tools._BASE_URL}/mcp-http/mcp"
Related Resources
Resource	URL
Collar Guardrail (UI)	https://collarguardrail.com
Agent Integration Guide	https://collarguardrail.com/agent-docs.html
MCP Server Card	https://api.collarguardrail.com/.well-known/mcp-server-card.json
MCP Registry	io.github.aiguardrail/backend
Live Status	https://api.collarguardrail.com/status
Live Latency	https://api.collarguardrail.com/latency.html
Risk Score Methodology	https://api.collarguardrail.com/methodology.html
PyPI	https://pypi.org/project/langchain-collar/
Contributing
Issues and pull requests are welcome. Please open an issue first to discuss
larger changes.

Disclosure
Collar is the risk layer for autonomous finance on Robinhood Chain.
Deterministic, auditable, and independent.

COLR is our own utility token, issued and operated by the Collar team.
It is not affiliated with, endorsed by, or issued by Robinhood Markets,
Inc. or any Robinhood entity. Robinhood Chain is a public blockchain we
build on — using it does not imply any relationship with Robinhood.
