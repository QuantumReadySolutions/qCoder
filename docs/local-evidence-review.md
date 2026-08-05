# Review local evidence

`qcoder review local-evidence` is the qCoder OSS development-branch journey for reviewing one
explicitly selected artifact or a bounded explicit list of artifacts in one coherent local report.
It composes existing qCoder evidence contracts; it does not create a second evidence registry,
Run Summary, Help contract, CircuitIR, motif schema, or Current Loop Contract.

No qCoder account, no qCoder token, no Explorer service, and no MCP connection are required. The
command performs no network request or telemetry. It creates only the output files you request.

## Discover and run the journey

```bash
qcoder --help
qcoder review --help
qcoder review local-evidence --help
```

Review one explicitly selected Python/Qiskit file:

```bash
qcoder review local-evidence examples/fixtures/local_evidence_bell.py
```

Review a bounded collection. Every file must be listed; directories and glob patterns are not
accepted:

```bash
qcoder review local-evidence \
  examples/fixtures/local_evidence_bell.py \
  examples/circuits/bell.qasm \
  examples/fixtures/bell_counts_qiskit.json \
  --out-json local-evidence.json \
  --out-md local-evidence.md
```

The collection limit is eight files. qCoder orders selected files deterministically. It does not
recurse, search the repository, discover adjacent or hidden files, follow imports, or watch for
changes.

## Supported inputs

- **Explicit Python/Qiskit source:** bounded static AST inspection, Development Evidence v0, and
  deterministic Python-only motif observations. Source is not imported or executed. The default
  motif lens is `generic_qiskit`; `--python-profile grover_search` and
  `--python-profile qaoa` are explicit bounded structural lenses, not algorithm-identity claims.
- **OpenQASM 2:** bounded parser and CircuitIR/circuit-manifestation facts, including registers,
  operations, measurements, width, depth, and visible custom/unknown-construct qualifications.
  QASM does not produce motif evidence.
- **Supplied counts/run-result JSON:** factual result manifestation and the canonical Run Summary
  v2, including observed shots, bounded dominant outcomes, supplied execution metadata, warnings,
  and missing metadata. qCoder does not execute a simulator, backend, or QPU.
- **Supported qCoder evidence JSON:** canonical Development Evidence v0, Run Summary v2, and
  validated circuit/result manifestation artifacts. The selected artifact's own provenance and
  explicit current/prior bindings are preserved; qCoder does not reproduce or infer prior state.

Malformed JSON, unsupported extensions, and unsupported/newer qCoder evidence versions fail with
a concise customer-facing message or visible unsupported state, not a Python traceback.

### OpenQASM 3 boundary

OpenQASM 3 evidence extraction is not supported in WI-0421. A declared OpenQASM 3 header is
recognized, but the input is not passed through the OpenQASM 2 parser and no partial circuit facts
are presented as complete. The report directs the customer to supply supported OpenQASM 2,
explicitly selected Python/Qiskit source, or supported counts JSON. No OpenQASM 3 parser is added.

## Understand the report

The stable report order is:

1. review scope;
2. provenance;
3. QASM evidence;
4. circuit facts;
5. motif evidence;
6. factual Run Summary;
7. explicit revision evidence;
8. warnings and unsupported state;
9. bounded local planning-guidance boundary;
10. share-safe export choices;
11. supported next actions; and
12. local qCoder Help.

Each selected artifact states what was inspected, what was established, what was not established,
its limitations, and exact supported next actions. Deterministic structural facts remain separate
from bounded planning guidance. The report does not claim correctness, complete algorithm
identity, result causation, optimal shots, backend ranking, fidelity prediction, or quantum
advantage.

Grover- and QAOA-related structural motifs do not establish a complete or correct algorithm,
correct parameterization, result causation, performance, or quantum advantage. The canonical motif
identifiers remain traceable in machine-readable output.

## Local qCoder Help

```bash
qcoder review local-evidence examples/circuits/bell.qasm --local-help
```

Help reports the installed qCoder version, local OSS mode, selected input kinds, available and
unsupported capabilities, report sections, share-safe choices, and copyable next commands. It
states that no qCoder account, no qCoder token, no Explorer service, and no MCP is involved, and
that local evidence does not establish client qualification.

## Create and inspect a share-safe export

Derived evidence only (default):

```bash
qcoder review local-evidence \
  examples/circuits/bell.qasm \
  examples/fixtures/bell_counts_qiskit.json \
  --share-safe-json local-evidence.share-safe.json
python -m json.tool local-evidence.share-safe.json
```

Raw/private categories are excluded by default. Opt in separately to only the category needed:

```bash
qcoder review local-evidence examples/circuits/bell.qasm \
  --share-safe-json qasm-review.share-safe.json \
  --include-original-qasm

qcoder review local-evidence examples/fixtures/local_evidence_bell.py \
  --share-safe-json source-review.share-safe.json \
  --include-source-excerpts

qcoder review local-evidence examples/fixtures/bell_counts_qiskit.json \
  --share-safe-json counts-review.share-safe.json \
  --include-raw-counts
```

Separate flags also cover normalized CircuitIR, raw run-result payloads, Blueprint material when
applicable, customer filenames, and customer paths. There is no broad include-everything switch.
Authentication-like values are redacted where detected, but share-safe output is not a privacy
guarantee: inspect the local file before sharing it. qCoder never uploads the export automatically.

## Ownership and persistence boundary

The journey retains no hidden database, background index, automatic project grouping, cross-loop
history, project motif history, or longitudinal intelligence. Explicit files and output files
remain customer-owned. Current/prior relationships are shown only when they already exist in an
explicitly selected canonical artifact. Active Current Loop registries and snapshots are not
projected into this OSS workflow because their semantics are loop-bound.

This development-branch guide is implementation evidence for later review. It does not activate a
public claim, assign a version, create a release candidate, qualify a client, or publish a package.
