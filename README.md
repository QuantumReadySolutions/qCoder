# qCoder

`qcoder` is a local, deterministic quantum circuit evidence CLI.

The current public local path is **qCoder OSS**. OSS commands run locally and do not call hosted services, upload telemetry, or run QPU/simulator jobs.

## Public CLI surface

- `qcoder analyze`
- `qcoder batch`
- `qcoder context`
- `qcoder review`
- `qcoder student` (temporary Explorer Beta compatibility namespace for account-backed status/demo/evidence checks)
- `qcoder pro` (archived pilot/bootstrap client contract; non-confidential local plumbing only, not a current public product path)

## Current product boundaries

Public `qcoder` ships **OSS local commands** plus Explorer Beta compatibility commands. Pro is not launched and is not a current public product path.

- **OSS commands** (`analyze`, `batch`, `context`, `review`) are Apache-2.0, local-first/offline, and useful without an account or token. They do not upload data, call a qCoder hosted service, or run QPU/simulator jobs.
- **Explorer Beta compatibility commands** (`qcoder student status`, `qcoder student demo`, `qcoder student evidence`) use the temporary `qcoder student` namespace during beta. They are account-backed checks for Explorer Beta status and built-in guided evidence samples.
- Current Explorer Beta built-in evidence is **not** custom hosted analysis of user-owned circuits. Use OSS for user-owned QASM/artifact analysis today.
- Future Explorer custom evidence should use derived qCoder context/features rather than raw hosted QASM upload unless a separate privacy/retention design is approved.
- **`qcoder pro` bootstrap/workflow commands** are archived pilot/client-contract surfaces. They are not a Pro purchase path, not a current public signup path, and not generally available hosted Pro.
- There is **no generally available production hosted Pro service**, Pro account/token issuance, artifact/source upload, telemetry/training ingest, confidential local analyzer/cards, QPU/provider execution, or launched Pro V0.0 behavior in this public-main surface.
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

Explorer Beta compatibility checks and archived Pro bootstrap:

```bash
qcoder student status
qcoder student demo
qcoder student evidence
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
