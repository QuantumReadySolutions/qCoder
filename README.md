# qCoder

`qcoder` is a local, deterministic quantum circuit evidence CLI.

Free `qcoder` commands run offline and do not call hosted services, upload telemetry, or run QPU/simulator jobs.

## Public CLI surface

- `qcoder analyze`
- `qcoder batch`
- `qcoder context`
- `qcoder review`
- `qcoder pro` (Pro bootstrap and client contract; non-confidential local plumbing only)

## Pro Preview boundaries

Public `qcoder` ships **Free local commands** plus a **Pro bootstrap/client contract**. It is **not** the sellable hosted Pro product.

- **Free commands** (`analyze`, `batch`, `context`, `review`) run offline. They do not upload data, call a qCoder hosted service, or run QPU/simulator jobs.
- **`qcoder pro` bootstrap** (`signup`, `login`, `install`, `status`, `validate`) stores local token/config only. It does not upload circuits, run confidential analysis, or generate Pro cards locally.
- **`qcoder pro workflow --dry-run-manifest`** writes a local JSON contract (`qcoder.pro_preview.workflow_manifest.v0`) and performs **no network calls**. This is the default path for most users.
- **`qcoder pro workflow --submit`** posts a **sanitized manifest only** to an **explicitly configured** `--service-url` (or `QCODER_PRO_API_URL`). Use it only when QRS has given you a service URL and token. The default `https://qcoder.ai/preview` URL is **not** accepted for submit.
- There is **no generally available production hosted Pro service**, account/token issuance, or artifact upload in this public-main surface. Production hosted service, Cloud Run/GCS, and confidential analysis are separate/future.
- **No confidential Pro analysis or cards** are bundled in this package. Token-gating is **access control only**, not a secrecy boundary.

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

Pro Preview bootstrap (local contract rehearsal):

```bash
qcoder pro --help
qcoder pro signup
qcoder pro install --token <token-if-provided>
qcoder pro status
qcoder pro validate
qcoder pro workflow --qasm path/to/circuit.qasm --dry-run-manifest pro.workflow.manifest.json
```

Use **`--dry-run-manifest`** unless QRS has given you a non-default service URL and token for contract rehearsal. Manifest-only submit (no artifact upload) is opt-in:

```bash
qcoder pro workflow --qasm path/to/circuit.qasm --submit --service-url <url-qrs-provided>
```

Architecture notes: [`docs/architecture.md`](docs/architecture.md).

## Optional extras

```bash
pip install "qcoder[qiskit]"
pip install "qcoder[cirq]"
pip install "qcoder[pennylane]"
```

## License

Apache-2.0 (see `LICENSE` and `NOTICE`).
