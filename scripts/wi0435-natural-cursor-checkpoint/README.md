# WI-0435 natural Cursor checkpoint v6

Private, unfrozen, unpublished rehearsal. Preserve v1-v5 as diagnostic-only. Use only the new v6 workspace and one fresh Agent conversation.

## Setup

From this packet directory, run once:

```bash
./setup.sh /absolute/path/to/existing/context-bridge-token-file
```

Setup selects Python 3.11 or newer, installs the exact rehearsal wheel, installs and prevalidates pinned `qiskit==2.5.2` and `qiskit-aer==0.17.2`, and creates a deterministic source/circuit/coherent-result Current Loop precondition. That precondition is automated setup evidence, not natural Cursor evidence. It has one bootstrap, one Request Baseline, and one current coherent Run Summary.

Setup fails before Cursor opens if the wheel, runtime, public 12-tool inventory, private two-operation inventory, User-scope MCP isolation, or instrumentation isolation is wrong. It never reads or retains the credential.

Open exactly `/home/rob/projects/qcoder-wi0435-natural-cursor-workspace-v6`, enable only its two project servers, visibly confirm the workspace, and start one fresh Agent conversation. All event records, timing, captures, and safe-return files remain outside this workspace.

After each response run `./helpers/capture.sh LABEL SECONDS`. Add `yes` as the fourth argument only if procedural narration was visibly present. Internal counts are collected automatically; unprovable observations become `not_observed` rather than questions for the operator. For a timeout use `./helpers/capture.sh LABEL timeout timeout`.

## Four prompts

1. `Change the Python source to prepare a Ψ+ Bell state. Stop after the source; then tell me whether the earlier circuit and result remain current and preserve their history.`

   Required: the existing exact source target is reused without search or clarification; the new source becomes current; prior circuit/result become non-current but remain historical; no execution.

   Capture: `./helpers/capture.sh 01-source-replaced SECONDS`

2. `Export the updated circuit as QASM. Do not run it; then tell me whether the earlier result is current for this new circuit.`

   Required: the existing exact QASM target is reused; updated QASM becomes current; prior result stays historical and non-current; no execution.

   Capture: `./helpers/capture.sh 02-circuit-replaced SECONDS`

3. `Use qCoder to evaluate the exact selected files fixtures/bare-counts.json and fixtures/unknown-result-manifest.json as result evidence controls. Do not execute anything, infer lineage, or claim either belongs to the registered circuit.`

   Required: no execution; bare counts and unknown lineage cannot become current for the registered circuit.

   Capture: `./helpers/capture.sh 03-lineage-controls SECONDS`

4. `Use qCoder for a source-only Bell step. The exact selected file fixtures/preexisting_bell.py already exists; if it satisfies the source role, accept it without rewriting it or claiming the assistant created it.`

   Required: exact selected source satisfies the bounded role without byte, timestamp, mode, or provenance mutation.

   Capture: `./helpers/capture.sh 04-preexisting-no-mutation SECONDS`

## Seal

Close Cursor, then run:

```bash
./helpers/seal.sh
```

Return only the printed ZIP path, size, SHA-256, and unexpected visible behavior. Restore any preserved User-scope MCP configuration. Do not return credentials, raw artifacts, Cursor logs, MCP configuration, or raw qCoder state.
