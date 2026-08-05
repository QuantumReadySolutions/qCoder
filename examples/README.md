# qCoder examples

Copy-paste walkthroughs for the qCoder OSS local workflow.

## Quick links

- [`circuits/bell.qasm`](./circuits/bell.qasm) - tiny OpenQASM Bell circuit.
- [`fixtures/bell_counts_qiskit.json`](./fixtures/bell_counts_qiskit.json) - user-provided example counts for `qcoder review` (fixture only, not qCoder execution output).
- [`scripts/export_bell_qiskit.py`](./scripts/export_bell_qiskit.py) - optional Qiskit export helper.
- [`scripts/export_bell_cirq.py`](./scripts/export_bell_cirq.py) - optional Cirq export helper.
- [`scripts/export_bell_pennylane.py`](./scripts/export_bell_pennylane.py) - optional PennyLane export helper.
- [`06_single_run_intelligence.md`](./06_single_run_intelligence.md) - OSS single-run intelligence workflow.
- [`07_byo_llm_artifact_pack.md`](./07_byo_llm_artifact_pack.md) - BYO LLM artifact pack.
- [`08_evidence_review.md`](./08_evidence_review.md) - synthetic Explorer Evidence Review walkthrough using existing Context Bridge operations.
- [`09_algorithm_blueprint.md`](./09_algorithm_blueprint.md) - synthetic intent-to-static-source Algorithm Blueprint walkthrough for the unreleased feature branch.
- [`10_local_evidence_review.md`](./10_local_evidence_review.md) - coherent OSS review of explicitly selected local evidence.
- [`fixtures/local_evidence_bell.py`](./fixtures/local_evidence_bell.py) - fixed public Python/Qiskit source fixture for bounded static evidence.
- [`prompts/single_run_artifact_to_action.md`](./prompts/single_run_artifact_to_action.md) - copy-paste BYO prompt.

## Walkthroughs

1. [`01_qasm_workflow.md`](./01_qasm_workflow.md) - base OpenQASM flow: `analyze`, `context`, guidance, and profiles.
2. [`02_qiskit_workflow.md`](./02_qiskit_workflow.md) - optional Qiskit adapter intake + OpenQASM export.
3. [`03_cirq_workflow.md`](./03_cirq_workflow.md) - optional Cirq adapter intake + OpenQASM export.
4. [`04_pennylane_workflow.md`](./04_pennylane_workflow.md) - optional PennyLane adapter intake + OpenQASM export.
5. [`05_preflight_review_workflow.md`](./05_preflight_review_workflow.md) - end-to-end preflight and post-run review with fixture counts.
6. [`06_single_run_intelligence.md`](./06_single_run_intelligence.md) - OSS single-run intelligence: preflight → your run → review → optional BYO LLM → next local action.
7. [`07_byo_llm_artifact_pack.md`](./07_byo_llm_artifact_pack.md) - which artifacts to attach to a user-managed LLM; JSON vs Markdown roles.
8. [`08_evidence_review.md`](./08_evidence_review.md) - bounded current-session Evidence Review, next checks, and handoff with synthetic evidence.
9. [`09_algorithm_blueprint.md`](./09_algorithm_blueprint.md) - explicit confirmation, Qiskit-first blueprint, external generation, local static extraction, and bounded alignment.
10. [`10_local_evidence_review.md`](./10_local_evidence_review.md) - one local review across explicitly selected Python, QASM2, counts, or canonical evidence JSON.
11. [`prompts/single_run_artifact_to_action.md`](./prompts/single_run_artifact_to_action.md) - copy-paste BYO prompt for artifact-to-action follow-up.

## Boundary reminder

qCoder creates deterministic local artifacts from circuit structure and user-provided counts. In these examples, qCoder does not execute circuits, run simulators or hardware backends, call an LLM, upload telemetry/data, perform retrieval, or create embeddings.
