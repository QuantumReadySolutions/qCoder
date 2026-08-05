# Local selected-evidence review

This fixed public journey reviews only the files named explicitly:

```bash
qcoder review local-evidence \
  examples/fixtures/local_evidence_bell.py \
  examples/circuits/bell.qasm \
  examples/fixtures/bell_counts_qiskit.json \
  --out-json local-evidence.json \
  --out-md local-evidence.md
```

Show local qCoder Help for one input:

```bash
qcoder review local-evidence examples/circuits/bell.qasm --local-help
```

Create a derived-only share-safe export and inspect it locally:

```bash
qcoder review local-evidence examples/circuits/bell.qasm \
  --share-safe-json local-evidence.share-safe.json
python -m json.tool local-evidence.share-safe.json
```

The journey needs no qCoder account, no qCoder token, no Explorer service, and no MCP. OpenQASM 3
is recognized but evidence extraction is not supported. No backend or simulator is run.
