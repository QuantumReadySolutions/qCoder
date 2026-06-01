# 05: Preflight + review workflow (copy-paste)

This walkthrough uses repository fixtures only. Counts in this example are user-provided fixture data, not qCoder execution output.

## 1) Generate preflight context (guidance + profiles)

```bash
qcoder context examples/circuits/bell.qasm \
  --out-json preflight.context.json \
  --out-md preflight.context.md \
  --guidance --profiles
```

## 2) Review with fixture counts

```bash
qcoder review \
  --counts-json examples/fixtures/bell_counts_qiskit.json \
  --format qiskit_counts \
  --preflight-json preflight.context.json \
  --out-json execution.review.json \
  --out-md execution.review.md
```

## 3) What each artifact is for

- `preflight.context.md`: concise planning context for humans.
- `preflight.context.json`: deterministic machine-readable preflight source.
- `execution.review.md`: concise post-run summary from provided counts.
- `execution.review.json`: deterministic machine-readable review source.

## 4) Optional: use guidance in your own simulator (user-side code)

qCoder only wrote **`preflight.context.json`**. The snippets below are **your** framework code: they load that artifact and run a simulator **outside** qCoder. Guidance is a deterministic starting point, not a guarantee of optimal shots or bond dimension.

### Index convention for `starting_shots` and `starting_points`

When qCoder emits ordered lists:

- index **`0`** — lighter / faster pilot
- index **`1`** — balanced default (use this when at least two entries exist)
- index **`2`** — more conservative / heavier (present only when the list has three entries)

If a list has **exactly two** values, **`[1]`** is the higher of the pair; there is no third slot. If shot applicability is **`not_applicable`**, `starting_shots` may be empty—do not index it.

### Read balanced defaults from preflight JSON

```python
import json
from pathlib import Path

ctx = json.loads(Path("preflight.context.json").read_text(encoding="utf-8"))
guidance = ctx["analysis"]["guidance"]
shots_list = guidance["shot_guidance"]["starting_shots"]
pts = guidance["simulation_guidance"]["mps_bond_dimension"]["starting_points"]

if len(shots_list) < 2 or len(pts) < 2:
    raise ValueError("Expected at least two guidance entries for index-1 convention")

shots = shots_list[1]
bond_dim = pts[1]
```

Wire `shots` / `bond_dim` into Qiskit, Cirq, or PennyLane as in the [resource guidance](https://qcoder.ai/manual/workflows/resource-guidance/) and [adapter](https://qcoder.ai/manual/adapters/qiskit/) pages (same index convention).

## Boundary reminder

qCoder reads local circuit/count files and computes deterministic artifacts. It does not execute/simulate circuits, run hardware, call an LLM, upload telemetry/data, perform retrieval, or create embeddings.
