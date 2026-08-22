# WI-0435 natural Cursor checkpoint v7

Private, unfrozen, unpublished rehearsal. Preserve v1-v6 as diagnostic evidence. Use only the new v7 workspace and one fresh Agent conversation.

## Setup

From this packet directory, run once:

```bash
./setup.sh /absolute/path/to/existing/context-bridge-token-file
```

Setup selects Python 3.11 or newer, installs the exact rehearsal wheel, installs and prevalidates pinned `qiskit==2.5.2` and `qiskit-aer==0.17.2`, and creates a deterministic source/circuit/coherent-result Current Loop precondition. The precondition is automated setup evidence, not natural Cursor evidence. It has one bootstrap, one Request Baseline, and one current coherent Run Summary.

Setup fails before Cursor opens if the wheel, runtime, public 12-tool inventory, private two-operation inventory, User-scope MCP isolation, or instrumentation isolation is wrong. It never reads or retains the credential.

Open exactly `/home/rob/projects/qcoder-wi0435-natural-cursor-workspace-v7`, enable only its two project servers, visibly confirm the workspace, and start one fresh Agent conversation. All instrumentation remains outside the workspace.

After each response run `./helpers/capture.sh LABEL SECONDS`. Internal counts and state facts are automatic; unprovable observations become `not_observed`. For a timeout use `./helpers/capture.sh LABEL timeout timeout`.

## Two prompts

1. `Use qCoder to evaluate the exact selected files fixtures/bare-counts.json and fixtures/unknown-result-manifest.json as result evidence controls. Do not execute anything, infer lineage, or claim either belongs to the registered circuit.`

   Required: one private `begin_current_loop` call carries exactly the two named paths; no execution, search, CLI/help/state/package archaeology, or registration. The response states that bare counts are not current evidence, unknown lineage is historical/non-current only, and the current result is unchanged.

   Capture: `./helpers/capture.sh 01-lineage-controls SECONDS`

2. `Use qCoder for a source-only Bell step. The exact selected file fixtures/preexisting_bell.py already exists; if it satisfies the source role, accept it without rewriting it or claiming the assistant created it.`

   Required: the one exact selected source satisfies the bounded role without a write or byte, timestamp, mode, or provenance mutation.

   Capture: `./helpers/capture.sh 02-preexisting-no-mutation SECONDS`

## Seal

Close Cursor, then run:

```bash
./helpers/seal.sh
```

Return only the printed ZIP path, size, SHA-256, and unexpected visible behavior. Restore any preserved User-scope MCP configuration. Do not return credentials, raw artifacts, Cursor logs, MCP configuration, or raw qCoder state.
