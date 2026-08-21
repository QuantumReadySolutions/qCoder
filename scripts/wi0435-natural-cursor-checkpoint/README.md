# WI-0435 natural Cursor checkpoint v5

Private, unfrozen, unpublished rehearsal. Preserve v1-v4 as diagnostic-only. Use only the new v5 workspace and a fresh Agent conversation.

## Setup

From this packet directory, run once:

```bash
./setup.sh /absolute/path/to/existing/context-bridge-token-file
```

Setup selects Python 3.11 or newer, installs the exact rehearsal wheel in the workspace venv, separately installs pinned `qiskit==2.5.2` and `qiskit-aer==0.17.2`, and runs a non-campaign sampler preflight. It fails before Cursor opens if the runtime, wheel, public 12-tool inventory, private two-operation inventory, User-scope MCP isolation, or instrumentation isolation is wrong. It never reads or retains the credential.

Open exactly `/home/rob/projects/qcoder-wi0435-natural-cursor-workspace-v5`, enable only its two project servers, visibly confirm the workspace, and start one fresh Agent conversation. No capture, timing, or safe-return file is inside this workspace.

After each response, run `./helpers/capture.sh LABEL SECONDS`. The helper asks only bounded observations. Use `unknown` or `not_observed` rather than guessing. For a timeout use `./helpers/capture.sh LABEL timeout timeout`.

## Nine prompts

1. `Use qCoder to write a Qiskit program that prepares a Φ+ Bell state. Stop after generating the code.`

   Capture: `./helpers/capture.sh 00-source SECONDS`

2. `Now export the circuit as QASM. Do not run it.`

   Capture: `./helpers/capture.sh 00-circuit SECONDS`

3. `Run the registered Bell circuit locally with 1,024 shots under the native client's controls. Save exact result evidence for this attempt, let qCoder validate it, and show the current Run Summary.`

   Capture: `./helpers/capture.sh 01-coherent-current SECONDS`

4. `Run the same registered circuit locally with 2,000 shots and save the exact result evidence, but stop before handing that saved result back to qCoder. Do not rerun it.`

   Confirm the saved result exists, then immediately capture so its pending checkpoint and exact byte digest are sealed outside the workspace: `./helpers/capture.sh 02-before-recovery SECONDS`

5. `Resume the pending qCoder step from the exact saved result artifact. Do not run the circuit again.`

   Normal recovery calls private `complete_current_step` directly with no begin, rerun, CLI/help, state inspection, or workspace discovery. The final response must show the canonical current Run Summary.

   Capture: `./helpers/capture.sh 03-after-recovery SECONDS`

6. `Change the Python source to prepare a Ψ+ Bell state. Stop after the source; then tell me whether the earlier circuit and result remain current and preserve their history.`

   Capture: `./helpers/capture.sh 04-source-replaced SECONDS`

7. `Export the updated circuit as QASM. Do not run it; then tell me whether the earlier result is current for this new circuit.`

   Capture: `./helpers/capture.sh 05-circuit-replaced SECONDS`

8. `Use qCoder to evaluate the exact selected files fixtures/bare-counts.json and fixtures/unknown-result-manifest.json as result evidence controls. Do not execute anything, infer lineage, or claim either belongs to the registered circuit.`

   Capture: `./helpers/capture.sh 06-lineage-controls SECONDS`

9. `Use qCoder for a source-only Bell step. The exact selected file fixtures/preexisting_bell.py already exists; if it satisfies the source role, accept it without rewriting it or claiming the assistant created it.`

   Capture: `./helpers/capture.sh 07-preexisting-no-mutation SECONDS`

## Seal

Close Cursor, then run:

```bash
./helpers/seal.sh
```

Return only the printed ZIP path, size, SHA-256, and unexpected visible behavior. Restore any preserved User-scope MCP configuration. Do not return credentials, raw artifacts, Cursor logs, MCP configuration, or raw qCoder state.
