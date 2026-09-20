# Unpublished D-143 Explorer coordinator

This conference candidate composes the unchanged focused-loop core and bounded local
executor in `qcoder.explorer.focused_loop_coordinator`. It uses the unmodified strict
result-manifest v3 validator, not Current Loop state. This is not the final production
composition placement or a public MCP operation. No model, account or provider is used.

Use Python 3.12 with the prepared Qiskit 2.5.2 / Aer 0.17.2 dependencies installed before
execution. The state implementation currently requires a local POSIX filesystem with
`flock`, atomic rename and `fsync`; shared/network filesystems are not qualified.

Place the exact generated `FX-CLIF-ACCEPT-01` QASM (or `FX-CLIF-HOLDOUT-02`) in a fresh
workspace. The command compares exact bytes against the family generator. Example:

```text
qcoder explorer focused prepare --workspace WORKSPACE --fixture FX-CLIF-ACCEPT-01 --qasm input.qasm
qcoder explorer focused run --workspace WORKSPACE --confirm-plan-digest DISPLAYED_FULL_SHA256
qcoder explorer focused explain result --workspace WORKSPACE
qcoder explorer focused repeat --workspace WORKSPACE
qcoder explorer focused status --workspace WORKSPACE
```

Every operation supports `--json`. Explanation topics are `mps`, `stabilizer`, `shots`,
`plan`, `result`, and `limits`. Explanations, status and repeat do not write state.
The legacy `qcoder student` alias does not expose this command.

Preparation creates one bounded current session under `.qcoder/focused-loop-v1/` and
performs no execution. Only an exact plan-digest confirmation creates authority. A
process lock prevents concurrent dispatch. Before calling the executor, the authority
and unknown-outcome transition are atomically written and fsynced. A crash leaves an
unknown outcome with an unknown dispatch count (zero or one), never permission to retry.
A completed result records the exact observed dispatch count and is reusable without
another authority. A failed/cancelled/timeout attempt is also never retried.

This minimum candidate deliberately has no in-place reset/recovery command. Preserve
unknown/failed evidence and use a separate workspace for a fresh explicitly authorized
attempt. Do not delete state to retry. Canonical self-digests detect corruption; they
are not authentication against a workspace owner who rewrites history. The existing
executor's timeout/cancellation is cooperative/post-dispatch checking, not a new hard
preemptive job terminator. This coordinator does not broaden that executor contract.

The 36 GiB envelope is declared synthetic input, not a measurement of the host. The
natural-order coefficient floor is not a complete peak-memory model. The six Bell-pair
predicate result is not fidelity, global-state proof or general simulator correctness.

Source proof adds `tests/test_explorer_focused_coordinator_v1.py` to the focused matrix
in README.md. Exactly one production module is added to the existing Explorer package,
raising admitted payload membership from 146 to 147. No tests or harness scripts enter
the wheel. Build a new candidate from the committed source; the previous foundation
wheel remains historical evidence.
