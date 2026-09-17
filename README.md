# Collar Guardrail

**Deterministic pre-trade risk layer for AI agents on Robinhood Chain.**

Collar Guardrail evaluates proposed trades before execution and returns
`allow` / `warn` / `deny` with reasons, a 0–100 risk score, and a
tamper-evident SHA-256 audit hash.

[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-v1.0.2-brightgreen)](https://registry.modelcontextprotocol.io/servers/io.github.aiguardrail/backend)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)

---

## Overview

Autonomous trading agents can move capital faster than any human can review.
Collar Guardrail sits between an agent and the chain as a deterministic
pre-trade checkpoint: every proposed trade is scored against live oracle
prices, market-hours rules, tier-based policy limits, slippage bounds, and
contract-safety signals before it is allowed to proceed.

The result is a single, auditable verdict — never a probabilistic guess.

---

## Endpoints

| Service | URL |
| :--- | :--- |
| **MCP Server** | `https://backendai-x4m1.onrender.com/mcp-http/mcp` |
| **MCP Server Card** | `https://backendai-x4m1.onrender.com/.well-known/mcp/server-card.json` |
| **Agent Card (A2A)** | `https://backendai-x4m1.onrender.com/.well-known/agent-card.json` |
| **x402 Discovery** | `https://backendai-x4m1.onrender.com/.well-known/x402.json` |
| **llms.txt** | `https://backendai-x4m1.onrender.com/llms.txt` |
| **Live Terminal (UI)** | `https://collar-b46l.onrender.com` |

### MCP Metadata

| Field | Value |
| :--- | :--- |
| **Transport** | `streamable-http` |
| **MCP Protocol** | `2025-06-18` |
| **Authentication** | None required (fixed Tier 1) |

---

## Installation

### MCP Client Configuration

Add the following to your MCP client configuration (Claude Desktop, Cursor,
VS Code, or any MCP-compatible client):

```json
{
  "mcpServers": {
    "collar-guardrail": {
      "url": "https://backendai-x4m1.onrender.com/mcp-http/mcp"
    }
  }
}
