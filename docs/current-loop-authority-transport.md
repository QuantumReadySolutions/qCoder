# Current Loop free-text authority transport

This inventory is normative for the connected-assistant runtime in
`0.6.0a2+wi0418.authoritytransport2`.

Classification:

- A — enumerated or canonical-reference input; ordinary argv is bounded.
- B — already staged, displayed, and promoted using authority only.
- C — arbitrary free text carried by
  `qcoder.current_loop.checkpoint_input.v1`.
- D — compatibility/manual inline transport that generated connected-assistant
  protocols never emit.

| Current Loop surface | Classification | Connected-assistant disposition |
|---|---:|---|
| `activate --request`, `--request-file`, `--request-stdin` | B | Exact Request Baseline capture; approval reuses qCoder-held bytes. |
| `activate --constraint`, `--choice`, `--assistant-interpretation`, `--label` | B | Additive fields are retained inside the pending activation capture and never replace `original_request`. |
| posture and provenance selectors | A | Enumerated authority/provenance values remain separate from arbitrary text. |
| `prepare-generation --interpretation-summary` | C, D | Stage `proposed_interpretation`; inline flag is compatibility/manual only. |
| `prepare-generation --profile-answer` | C, D | Stage `reviewed_profile_answers`; hosted-presented values are staged automatically. |
| `prepare-generation --constraint`, `--non-goal` | C, D | Stage exact lists; inline flags are compatibility/manual only. |
| `prepare-generation --confirmation` | C, D | Stage exact confirmation when one is needed; approval never repeats it in argv. |
| `prepare-generation --decision-disposition` selected value | C, D | Stage the full exact disposition set; decision IDs, actions, and provenance remain bounded fields. |
| `prepare-generation --posture-reason` | C, D | Stage the exact reason at the posture checkpoint. |
| `authorize-artifacts --action`, provenance, role | A | Exact-set action and canonical provenance are bounded; paths remain exact retained paths. |
| `authorize-artifacts --artifact-type` | D | Optional compatibility metadata; generated protocols do not emit a literal. |
| `continue-unchanged --statement` | C, D | Stage the complete statement and promote it with authority only. |
| `propose-change --proposed-value`, `--control-treatment` | C, D | Stage the complete proposal selection before requesting the hosted proposal. |
| `confirm-change --confirmation` | C, D | Stage the proposal-specific confirmation; approval sends no repeated text. |
| artifact, seed, parent, workspace, and canonical reference paths | A | Exact path/reference values only; no discovery or reconstruction. |

The connected-assistant protocol uses:

1. `stage-checkpoint-input` with explicit UTF-8 stdin or a bounded UTF-8 file;
2. qCoder's complete exact display;
3. `approve-checkpoint-input --approve` with no free-text values; or
4. a replacement staged input for correction.

Supplying content never grants authority or calls Protected. Replay, stale
revision, phase/operation/workspace mismatch, invalid UTF-8, NUL, unsafe
terminal controls, and oversize input fail closed.

## Permitted-input-source taxonomy

Every coordinator result uses
`qcoder.current_loop.permitted_input_source_disposition.v1`. An actionable
result has a non-empty `permitted_input_source`, one or more of the following
categories, bounded input semantics, protocol binding, and prohibited
derivations:

| Category | Meaning |
|---|---|
| `bounded_enumerated_customer_choice` | The user chooses from qCoder's displayed supported values. The assistant transmits only that enum; it does not infer a default. |
| `checkpoint_input_transport` | Arbitrary UTF-8 is staged through explicit stdin or a bounded file, then displayed before any authority is accepted. |
| `qcoder_held_staged_value` | qCoder already holds the exact displayed value. The assistant never sends it back. |
| `exact_artifact_lineage` | A path comes only from an exact IDE create/modify result or exact user selection, with truthful role and provenance. |
| `authority_only_approval` | The invocation carries explicit authority and no repeated content. Silence and omission are not approval. |
| `qcoder_managed_canonical_reference` | qCoder supplies the exact saved artifact, seed, or parent reference. The assistant does not rediscover it. |
| `exact_customer_selected_workspace` | The next loop uses the exact workspace selected for that future loop; it is not found by discovery. |
| `exact_request_capture_transport` | The complete Request Baseline enters through its existing exact inline, file, or explicit stdin capture. |
| `no_input_permitted_or_required` | No invocation is actionable. A separate machine-readable no-action disposition explains why. |

These categories are composable when a checkpoint genuinely has more than one
bounded source. For example, artifact review combines qCoder-held exact
candidates, an enumerated exact-set action, and authority-only approval.
Combining categories never permits arbitrary free text in argv.

## Checkpoint categories

- Request Baseline review uses qCoder-held staged bytes and authority-only
  activation/baseline approval.
- Generation posture is a bounded enumerated authority decision:
  `blueprint_guided` or `exploratory_first_pass`. The assistant may present
  both choices naturally and may transmit a user-accepted recommendation, but
  it may not infer a posture or silently select a default. This checkpoint does
  not use arbitrary checkpoint-input transport.
- Intent, decision-resolution, posture-reason, continuation, and governing
  proposal text use checkpoint-input staging whenever qCoder does not already
  hold the exact values.
- Hosted-presented clarification values are staged automatically. Unchanged
  approval is authority-only; correction replaces the staged set and requires
  another exact display and approval.
- IDE write/run and activation approvals are authority-only.
- Artifact registration uses exact path lineage. Artifact review then uses a
  separate bounded exact-set action and authority.
- Saved evidence and next-loop parent/seed data use qCoder-managed canonical
  references.

## Protocol completeness

Every active actionable result contains:

- `supported_next_action`;
- `next_invocation` or a bounded invocation template;
- `required_authority_input` and
  `required_authority_disposition`;
- non-null `permitted_input_source`;
- `input_source_disposition`;
- `bounded_input_semantics`;
- `protocol_binding`; and
- `prohibited_derivations`.

The coordinator validates the cross-field contract before serializing a
result. Checkpoint input cannot claim that input is disallowed; authority-only
approval cannot permit content retransmission; a pure enumerated checkpoint
cannot advertise arbitrary checkpoint transport; required authority must agree
with the invocation; and a closed continuation branch cannot expose a
governing-change action.

An active state with no current action emits `no_action_reason` and
`no_action_disposition`, including whether the assistant must stop, whether the
build is complete, whether a new loop may be started, and whether the prior
branch is closed. It emits no actionable invocation. Completed and abandoned
states are terminal. `next_loop_ready` is actionable only as stop or start-next
using qCoder-supplied canonical references; the completed build's governing
proposal branch remains closed.

Missing source dispositions, unsupported posture values, ambiguous authority,
stale bindings, content-plus-approval bypass, replay, and contradictory
cross-field combinations fail closed. No actionable checkpoint may serialize
`permitted_input_source: null`.
