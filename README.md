# langchain-collar

**LangChain tools for Collar Guardrail** — deterministic pre-trade risk
checks for AI trading agents on Robinhood Chain.

[![PyPI version](https://img.shields.io/pypi/v/langchain-collar.svg)](https://pypi.org/project/langchain-collar/)
[![Python versions](https://img.shields.io/pypi/pyversions/langchain-collar.svg)](https://pypi.org/project/langchain-collar/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)

---

## What is this?

This package wraps the [Collar Guardrail](https://collar-b46l.onrender.com)
MCP server as native LangChain tools. Any LangChain agent can now evaluate
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
```

Requires Python 3.10+ and `langchain-core>=0.3.0`.

---

## Quick Start

### 1. Add the tools to any LangChain agent

```python
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
```

### 2. Or call a tool directly

```python
from langchain_collar import evaluate_trade

verdict = evaluate_trade.invoke({
    "wallet": "0x1234567890abcdef1234567890abcdef12345678",
    "asset": "NVDA",
    "contract_address": "0x<official_registry_address>",
    "side": "buy",
    "amount": 10.0,
})
print(verdict)
```

---

## Available Tools

| Tool | Description |
| :--- | :--- |
| `evaluate_trade` | **Call before every trade.** Returns `allow` / `warn` / `deny`, reasons, risk score, and audit hash. Treat `deny` as a hard stop. |
| `check_token_safety` | Honeypot / contract safety check for any ERC-20 token. Returns severity (`safe` / `warn` / `danger`) plus a sell-simulation result. |
| `simulate_balance` | Read-only simulation of a wallet's ERC-20 balance after a hypothetical trade. No transaction is sent. |
| `get_supported_assets` | The official Robinhood Chain asset registry. Resolve a symbol to its canonical contract address **before** calling `evaluate_trade`. |
| `verify_audit_trail` | Recomputes every past decision's SHA-256 hash and verifies the hash-chain links. Returns `healthy=true` only if nothing was tampered with. |

---

## How It Works

Each tool is a thin wrapper around the Collar Guardrail MCP server at:

```
https://backendai-x4m1.onrender.com/mcp-http/mcp
```

The MCP transport is **Streamable HTTP** (protocol version `2025-06-18`).
No API key is required for the MCP endpoint — every call is evaluated at a
fixed **Tier 1 ceiling ($5,000 notional)**. For higher limits, use the
REST API with wallet-signature authentication (see the [Collar docs](https://backendai-x4m1.onrender.com/docs.html)).

---

## Decision Semantics

| Decision | Meaning | Action |
| :--- | :--- | :--- |
| `allow` | Policy passed. | Safe to execute. |
| `warn` | Policy soft-violated. | Trade may proceed but is flagged. Reasons prefixed with `ADVISORY:` are non-blocking. |
| `deny` | Policy hard-violated. | **Do not execute.** Reasons are blocking. |

> **Safety rule:** If a verdict contains an `error` key, no verdict was
> produced. Treat it as a hard stop. If `decision == "deny"`, do not
> execute the trade.

---

## Example: Full Pre-Trade Flow

```python
from langchain_collar import (
    evaluate_trade,
    get_supported_assets,
    check_token_safety,
)

# 1. Resolve the symbol to its canonical contract address
assets = get_supported_assets.invoke({})
print(assets)  # → list of {symbol, contract_address, is_native}

# 2. Optionally check the token for honeypot risk
safety = check_token_safety.invoke({
    "contract_address": "0x<token_address>",
})
print(safety)  # → {"severity": "safe", ...}

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
```

---

## Configuration

The package talks to the public Collar MCP endpoint by default. If you are
self-hosting Collar, override the base URL:

```python
import langchain_collar.tools as tools

tools._BASE_URL = "https://your-colar-instance.example.com"
tools._MCP_ENDPOINT = f"{tools._BASE_URL}/mcp-http/mcp"
```

---

## Related Resources

| Resource | URL |
| :--- | :--- |
| **Collar Guardrail** | https://collar-b46l.onrender.com |
| **MCP Server Card** | https://backendai-x4m1.onrender.com/.well-known/mcp/server-card.json |
| **Agent Integration Guide** | https://backendai-x4m1.onrender.com/agent-docs.html |
| **API Reference** | https://backendai-x4m1.onrender.com/docs.html |
| **MCP Registry** | `io.github.aiguardrail/backend` |

---

## Contributing

Issues and pull requests are welcome. Please open an issue first to discuss
larger changes.

---

## Disclosure

Collar is independent third-party infrastructure. Not built, operated, or
endorsed by Robinhood. COLR is a separate token, not affiliated with
Robinhood Markets, Inc.

---

## License

MIT — see [LICENSE](./LICENSE).
