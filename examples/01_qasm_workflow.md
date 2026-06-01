# 01: QASM workflow (copy-paste)

This is the base no-extra flow with OpenQASM files and the qCoder CLI.

## 1) Install

```bash
pip install qcoder
```

## 2) Analyze a circuit (human-readable)

```bash
qcoder analyze examples/circuits/bell.qasm
```

## 3) Analyze to JSON with deterministic guidance

```bash
qcoder analyze examples/circuits/bell.qasm --json --guidance > bell.features.guidance.json
```

## 4) Analyze to JSON with derived profiles

```bash
qcoder analyze examples/circuits/bell.qasm --json --profiles > bell.features.profiles.json
```

`--profiles` is opt-in and additive. Canonical `features` stays unchanged.

## 5) Build preflight context with guidance + profiles

```bash
qcoder context examples/circuits/bell.qasm \
  --out-json preflight.context.json \
  --out-md preflight.context.md \
  --guidance --profiles
```

Outputs:

- `preflight.context.md` for human review / copy-paste context.
- `preflight.context.json` as deterministic structured source of truth.

## Boundary reminder

In this workflow, qCoder does not execute the circuit, does not run simulator or hardware jobs, and does not call an LLM, upload data, perform retrieval, or generate embeddings.
