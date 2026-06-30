# Explorer Evidence-Grounded Coding Loop

Explorer Launch uses qCoder evidence to make AI-assisted circuit review more grounded.

Safe framing:

> Explorer helps you make your AI assistant better at quantum circuit work by giving it clean qCoder evidence to reason from.

Also safe:

> Give your AI assistant the quantum context it was missing.

## Manual Artifact Loop

The manual artifact loop is launch-required even when local Cursor MCP is available:

```text
write/edit circuit
-> generate qCoder evidence locally
-> use Explorer to produce plain-English review and next-step guidance
-> share clean Explorer summary with Cursor/ChatGPT
-> revise circuit
-> review again
```

This path is portable, auditable, token-free after artifact generation, and useful for ChatGPT, Cursor, email, issues, forums, and teammates.

Example local artifact commands:

```bash
qcoder context inputs/bell.qasm \
  --out-json artifacts/bell.context.json \
  --out-md artifacts/bell.context.md \
  --guidance \
  --profiles \
  --share-safe

qcoder review \
  --counts-json inputs/bell_counts_qiskit.json \
  --format qiskit_counts \
  --preflight-json artifacts/bell.context.json \
  --out-json artifacts/bell.review.json \
  --out-md artifacts/bell.review.md \
  --share-safe
```

Share only the share-safe JSON or Markdown artifacts unless you intentionally want to share local paths or raw source.

## Local Cursor MCP

The local Cursor MCP complements the artifact loop. It does not replace manual artifacts.

Launch MCP behavior:

- read
- inspect
- explain
- bound
- recommend

It does not:

- execute circuits
- modify user code
- read arbitrary files beyond explicit user-selected inputs
- expose tokens, headers, cookies, local secrets, raw provider payloads, or private artifacts
- call live Explorer/account services

Example Cursor MCP command:

```json
{
  "mcpServers": {
    "qcoder": {
      "command": "qcoder",
      "args": ["mcp", "serve"]
    }
  }
}
```

If testing from a source checkout before installation, point Cursor at the checkout Python environment and module path instead.

## Claim Boundaries

Explorer Launch can describe qCoder structural evidence, share-safe handoff, local Cursor MCP tool calls after implementation/testing, and bounded next checks.

Explorer Launch must not claim runtime prediction, fidelity prediction, backend or QPU ranking, quantum advantage, correctness proof, raw hosted QASM review, persistent Explorer history, autonomous repair, or productized Claude Code/Codex integration.
