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
- [`08_explorer_evidence_grounded_coding_loop.md`](./08_explorer_evidence_grounded_coding_loop.md) - Explorer artifact loop and local Cursor MCP setup.
- [`prompts/single_run_artifact_to_action.md`](./prompts/single_run_artifact_to_action.md) - copy-paste BYO prompt.

## Walkthroughs

1. [`01_qasm_workflow.md`](./01_qasm_workflow.md) - base OpenQASM flow: `analyze`, `context`, guidance, and profiles.
2. [`02_qiskit_workflow.md`](./02_qiskit_workflow.md) - optional Qiskit adapter intake + OpenQASM export.
3. [`03_cirq_workflow.md`](./03_cirq_workflow.md) - optional Cirq adapter intake + OpenQASM export.
4. [`04_pennylane_workflow.md`](./04_pennylane_workflow.md) - optional PennyLane adapter intake + OpenQASM export.
5. [`05_preflight_review_workflow.md`](./05_preflight_review_workflow.md) - end-to-end preflight and post-run review with fixture counts.
6. [`06_single_run_intelligence.md`](./06_single_run_intelligence.md) - OSS single-run intelligence: preflight → your run → review → optional BYO LLM → next local action.
7. [`07_byo_llm_artifact_pack.md`](./07_byo_llm_artifact_pack.md) - which artifacts to attach to a user-managed LLM; JSON vs Markdown roles.
8. [`08_explorer_evidence_grounded_coding_loop.md`](./08_explorer_evidence_grounded_coding_loop.md) - launch-required manual artifact loop plus local Cursor MCP setup.
9. [`prompts/single_run_artifact_to_action.md`](./prompts/single_run_artifact_to_action.md) - copy-paste BYO prompt for artifact-to-action follow-up.

## Boundary reminder

qCoder creates deterministic local artifacts from circuit structure and user-provided counts. In these examples, qCoder does not execute circuits, run simulators or hardware backends, call an LLM, upload telemetry/data, perform retrieval, or create embeddings.
