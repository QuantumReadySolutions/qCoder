# Current Loop free-text authority transport

This inventory is normative for the connected-assistant runtime in
`0.6.0a2+wi0418.authoritytransport1`.

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
