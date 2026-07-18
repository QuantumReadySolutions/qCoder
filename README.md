# qCoder

`qcoder` is a local, deterministic quantum circuit evidence CLI.

The current public local path is **qCoder OSS**. OSS commands run locally and do not call hosted services, upload telemetry, or run QPU/simulator jobs.

## Public CLI surface

- `qcoder analyze`
- `qcoder batch`
- `qcoder context`
- `qcoder review`
- `qcoder explorer` (Explorer Beta account-backed status/demo/evidence checks)
- `qcoder context-bridge` (token-backed Context Bridge MCP adapter for eligible Explorer users)
- `qcoder student` (temporary compatibility alias for Explorer Beta)
- `qcoder pro` (archived pilot/bootstrap client contract; non-confidential local plumbing only, not a current public product path)

## Current product boundaries

Public `qcoder` ships **OSS local commands**, Explorer Beta compatibility commands, and the Context Bridge adapter command for eligible Explorer users. Pro is not launched and is not a current public product path.

- **OSS commands** (`analyze`, `batch`, `context`, `review`) are Apache-2.0, local-first/offline, and useful without an account or token. They do not upload data, call a qCoder hosted service, or run QPU/simulator jobs.
- **Explorer Beta commands** (`qcoder explorer status`, `qcoder explorer demo`, `qcoder explorer evidence`) are account-backed checks for Explorer Beta status, built-in guided evidence samples, and derived-context guided evidence for user-owned OpenQASM 2 artifacts. The older `qcoder student ...` commands remain available as beta compatibility aliases.
- **Context Bridge adapter commands** (`qcoder context-bridge mcp serve`, `qcoder context-bridge mcp smoke`) are for eligible Explorer users with support-managed Context Bridge token access. They expose bounded current-evidence context tools to configured MCP clients and read tokens from a local token file.
- Explorer Beta custom evidence uses locally derived qCoder context/features. The CLI may read QASM locally, but the hosted request must not include raw QASM, raw source text, local paths, operation lists, raw counts, notebooks, prompts, tokens, auth headers, or cookies.
- Explorer Beta custom evidence is stateless in this v0 slice; it does not create persistent Explorer history.
- **`qcoder pro` bootstrap/workflow commands** are archived pilot/client-contract surfaces. They are not a Pro purchase path, not a current public signup path, and not generally available hosted Pro.
- There is **no generally available production hosted Pro service**, Pro account/token issuance, artifact/source upload, telemetry/training ingest, confidential local analyzer/cards, QPU/provider execution, or launched Pro V0.0 behavior in this public-main surface.
- **No confidential Pro analysis or cards** are bundled in this package. Token-gating is **access control only**, not a secrecy boundary.

## Context Bridge inventory

Eligible Explorer users can discover exactly these eight Context Bridge tools:

- `get_guided_evidence_context`
- `create_prompt_context`
- `create_evidence_context_pack`
- `create_context_session_card`
- `create_run_readiness_card`
- `create_result_review_context_card`
- `create_next_check_plan`
- `create_single_loop_evidence_diff`

`create_prompt_context` supports `explain`, `review`, `revise`, `troubleshoot`, and `plan_next_checks` modes; omitting the mode preserves the default behavior. Context Bridge uses only evidence explicitly supplied for the current request, processes it without retaining artifacts, and does not scan repositories, edit files, execute circuits or next checks, keep history or memory, score correctness, or perform autonomous work.

## Quick start

Install:

```bash
pip install qcoder
```

Analyze a circuit:

```bash
qcoder analyze path/to/circuit.qasm --json
```

Create local context and review artifacts:

```bash
qcoder context path/to/circuit.qasm --out-json preflight.context.json --out-md preflight.context.md
qcoder review --counts-json counts.json --format qiskit_counts --preflight-json preflight.context.json --out-json execution.review.json --out-md execution.review.md
```

For artifacts you intend to paste into ChatGPT, Cursor, email, GitHub issues, or support threads, add `--share-safe`:

```bash
qcoder analyze path/to/circuit.qasm --json --share-safe
qcoder context path/to/circuit.qasm --out-json preflight.context.json --out-md preflight.context.md --share-safe
qcoder review --counts-json counts.json --format qiskit_counts --preflight-json preflight.context.json --out-json execution.review.json --out-md execution.review.md --share-safe
```

Share-safe mode is designed for safer sharing: it redacts local paths and token/header-like strings, adds `share_safe=true`, and marks raw QASM/local paths/tokens as not included. Review artifacts before sharing; this is not a guarantee that all sensitive project content has been removed.

Explorer Beta compatibility checks and archived Pro bootstrap:

```bash
qcoder explorer status
qcoder explorer demo
qcoder explorer evidence
qcoder explorer evidence --qasm path/to/circuit.qasm
qcoder explorer evidence --context-json preflight.context.json
qcoder explorer evidence --qasm path/to/circuit.qasm --out-json explorer.json --out-md explorer.md --share-safe
qcoder context-bridge mcp serve --help
qcoder context-bridge mcp smoke --token-file ~/.qcoder/context-bridge/token.txt --json
qcoder pro --help
```

**Support-safe checklist**

Safe to share with QRS support:

- `qcoder --version`
- command name
- HTTP status or CLI error code
- `job_id`, if produced
- redacted output
- manifest schema/version

Do not share:

- bearer tokens
- secrets
- source code
- repository archives
- notebooks
- private prompts or chat transcripts
- raw QASM/source artifacts through unsupported paths

Architecture notes: [`docs/architecture.md`](docs/architecture.md).

## Optional extras

```bash
pip install "qcoder[qiskit]"
pip install "qcoder[cirq]"
pip install "qcoder[pennylane]"
```

## License

Apache-2.0 (see `LICENSE` and `NOTICE`).
