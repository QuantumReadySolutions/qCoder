# 06: Free single-run intelligence (copy-paste)

This walkthrough mirrors the **Free Single-Run Intelligence** story on [qcoder.ai](https://qcoder.ai/manual/workflows/single-run-intelligence/): one circuit, one execution **you** run outside qCoder, deterministic qCoder artifacts, then optional **BYO** (bring-your-own) LLM interpretation in **your** tool—no qCoder-hosted LLM and no telemetry upload from qCoder.

## What you get (Free, local)

- **Deterministic circuit analysis** and optional **feature profiles** from `qcoder context`.
- **Resource guidance** (optional `--guidance`) as transparent starting points—not optimality proof. When present, JSON may include **`guidance_metadata`**: a **shadow-mode** read of the packaged local guidance candidate (id, version, hash, optional suggestions). **`shadow_guidance.applied` is false**; deterministic `simulation_guidance.mps_bond_dimension.pressure` / `starting_points` remain the values to plan from until a future evaluated release applies pack output.
- **Preflight** JSON + Markdown for planning.
- **Execution review** JSON + Markdown from **counts you provide** after your run.
- Optional **BYO LLM** step: attach artifacts to your own assistant; see [`07_byo_llm_artifact_pack.md`](./07_byo_llm_artifact_pack.md) and [`prompts/single_run_artifact_to_action.md`](./prompts/single_run_artifact_to_action.md).

**qCoder does not execute the circuit.** It does not run a simulator or hardware, call an LLM, upload data, or perform retrieval.

## Free vs Pro (positioning)

**Free (this repo and CLI):** strong **single-circuit** and **single-run** intelligence—local artifacts from structure plus review from counts you pass in.

**Pro (product direction, not shipped in this open-source package):** adds durable **workflow memory**, adaptation across runs, recommendation and outcome style provenance over time, richer evidence and quality signals over time, project-style workflow memory, integrated BYO or managed LLM workflows with provenance where productized, and optional community-enhanced context when offered under explicit policy.

## 1) Preflight: context + guidance + profiles

From a clone:

```bash
qcoder context examples/circuits/bell.qasm \
  --out-json preflight.context.json \
  --out-md preflight.context.md \
  --guidance --profiles
```

## 2) User-side run

Run the circuit in **your** Qiskit, Cirq, PennyLane, or provider environment. Export counts to JSON compatible with `qcoder review` (see [`05_preflight_review_workflow.md`](./05_preflight_review_workflow.md) and [`fixtures/bell_counts_qiskit.json`](./fixtures/bell_counts_qiskit.json) for a fixture-only example).

If you do not have the example files locally, use the minimal counts-review pattern from the main README.

## 3) Review with qCoder

```bash
qcoder review \
  --counts-json examples/fixtures/bell_counts_qiskit.json \
  --format qiskit_counts \
  --preflight-json preflight.context.json \
  --out-json execution.review.json \
  --out-md execution.review.md
```

## 4) BYO LLM interpretation (optional)

Use [`07_byo_llm_artifact_pack.md`](./07_byo_llm_artifact_pack.md) and the copy-paste prompt in [`prompts/single_run_artifact_to_action.md`](./prompts/single_run_artifact_to_action.md).

## 5) Next local action

Decide locally: adjust shots using guidance, fix a review warning, iterate the circuit, or re-run—still grounded in artifacts; qCoder does not validate hardware for you.

## What this is not

- **Not** a QPU quality score.
- **Not** backend ranking or “best backend” advice from qCoder alone.
- **Not** fidelity proof.
- **Not** hardware correctness proof.
- **Not** a runtime guarantee.
- **Not** a causal savings claim.

## Boundary reminder

qCoder reads local circuit and count files and writes deterministic artifacts. It does not execute circuits, run simulators or hardware, call an LLM, upload telemetry/data, perform retrieval, or create embeddings.
