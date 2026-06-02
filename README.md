# qCoder

`qcoder` is a local, deterministic quantum circuit evidence CLI.

Free `qcoder` commands run offline and do not call hosted services, upload telemetry, or run QPU/simulator jobs.

## Public CLI surface

- `qcoder analyze`
- `qcoder batch`
- `qcoder context`
- `qcoder review`
- `qcoder pro` (service-backed Pro bootstrap shell; non-confidential local plumbing)

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

Pro Preview / V0 bootstrap shell:

```bash
qcoder pro --help
qcoder pro signup
qcoder pro install --token local-preview-token
qcoder pro status
qcoder pro validate
qcoder pro workflow --qasm path/to/circuit.qasm --dry-run-manifest pro.workflow.manifest.json
```

`qcoder pro workflow --dry-run-manifest` prepares a local JSON payload contract for future hosted submission. It does not upload data, execute hosted service workflows, or bundle confidential Pro analysis.

Token-gating is access control only, not a secrecy boundary. Local `qcoder pro` in this public package configures non-confidential bootstrap plumbing only; confidential Pro analysis remains service-side.

Architecture notes: [`docs/architecture.md`](docs/architecture.md).

## Optional extras

```bash
pip install "qcoder[qiskit]"
pip install "qcoder[cirq]"
pip install "qcoder[pennylane]"
```

## License

Apache-2.0 (see `LICENSE` and `NOTICE`).
