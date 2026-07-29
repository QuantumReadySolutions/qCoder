# Current Loop bounded-control input contract

`qcoder.current_loop.bounded_control_input.v1` is the internal client-visible contract for every
WI-0419 local control. It is embedded in `qcoder.current_loop.operation_invocation.v3` and the
`qcoder.connected_assistant.client_binding.v8` descriptor. Customers interact in natural
language; they do not see or edit the machine contract.

The contract derives its domains from the same Python constants used by parser choices and
Current Loop validation. Each dynamic result adds current values, change classification, current
state and contract revisions, qCoder-owned references, and the exact valid-selection graph. The
assistant never inspects help, source, package files, proof records, transcripts, or `.qcoder`.

## Operation and input inventory

| Operation | Customer selection | qCoder-owned/prebound values | Authority and effect |
| --- | --- | --- | --- |
| `contract-status` | none | state, loop, workspace | Read-only local status. |
| `contract-set-preset` | `evidence_only` or `assist` | contract revision | Narrowing applies immediately; broadening creates a proposal. |
| `contract-adjust` | one advertised category/dimension/value combination | contract revision and current values | Narrowing applies immediately; broadening creates a proposal. |
| `contract-confirm-broadening` | approval only | current proposal, proposal digest, contract revision | Applies only the displayed pending proposal. |
| `evidence-exclude` | one eligible qCoder evidence reference and one bounded reason | artifact identity/digest and contract revision | Prevents future use without deleting evidence. |
| `evidence-restore` | one eligible excluded qCoder reference | artifact identity/digest and contract revision | Restores only still-valid evidence. |
| `evidence-delete` | one eligible qCoder-controlled reference plus approval | artifact identity/digest/role and contract revision | Deletes only qCoder-controlled local evidence. |
| stop loop (`abandon`) | approval only | current loop/state/workspace binding | Makes the loop inactive. `Off` is not a preset value. |
| `record-ide-authority` | bounded IDE operation category/output roles plus authority | loop/workspace/revision and receipt construction | Issues a single-use operation receipt; grants no review authority. |
| `register-artifacts` | exact literal output path, truthful provenance, role, and optionally one eligible receipt | receipt/loop/workspace/revision bindings | Registers exact paths only; performs no discovery. |
| bounded recovery (`status`) | none for refresh; customer may naturally choose a displayed alternative | recovery category, state/contract revision, exact next invocation | Preserves prior valid contract and evidence. |
| `open-contract-editor` | none | sidecar schema, loop/workspace/session binding | Opens the optional loopback editor; no hosted access. |
| `evidence-view` | one advertised view and, when ambiguous, one eligible run reference | state, contract, evidence, and run-summary references | Returns only a contract-permitted bounded view. |
| `decline-build-review` | approval only | current loop/state binding | Declines the optional passive review without changing the Blueprint. |

## Presets and Off

`evidence_only` and `assist` are the only selectable named active-loop presets. `custom` is
compiled after a bounded adjustment; it is not selected as an empty policy document. `off` means
there is no active loop, so it is represented by the distinct qCoder-generated stop-loop
invocation and never by an all-false active policy.

## Adjustment selection graph

The graph is category-indexed. Every current evidence category publishes all applicable
dimensions and each dimension publishes only its accepted values:

- `collect`, `derive`, `recommend`, and `request_application_or_execution`:
  `disabled` or `enabled`;
- `prepare`: `disabled` or `bounded_non_material`;
- `assistant_derived_exposure`: `disabled`, `on_request`, or `standing`;
- `assistant_raw_exposure`: `disabled` only under the contract.v1 ceiling.

Each leaf includes its current value, customer meaning, and whether selecting it is unchanged,
narrowing, or broadening. Consumers must not use the cross-product of independent enum lists.

## Rejection and recovery

Unsupported preset, category, dimension, value, reason, or reference input returns
`qcoder.current_loop.bounded_control_rejection.v1`. The result contains safe type/domain metadata,
a hash rather than arbitrary raw input, `hosted_operation_permitted: false`, and a complete local
recovery invocation with refreshed domains. Rejection does not alter prior valid contract state or
evidence.
