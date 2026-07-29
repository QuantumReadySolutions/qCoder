# Changelog

## 0.6.0a2+wi0418.authoritytransport6

- Supply complete local-only bootstrap invocations before the first Current
  Loop coordinator result.
- Bind exact Request Baseline stdin staging to explicit working-directory
  semantics without help-based discovery or coordinator-prefix construction.

## 0.6.0a2+wi0418.authoritytransport5

- Bind every Current Loop action to a qCoder-owned operation-specific invocation.
- Isolate local-only actions from hosted transport and remove assistant-routed transport.

## 0.6.0a2+wi0418.authoritytransport4

- Complete the per-field semantic checkpoint-input contract and reject
  promotion-incompatible field types and bounded values before staging.

## 0.6.0a2+wi0418.authoritytransport3

- Complete the connected-assistant checkpoint-input construction binding while
  retaining the lossless authority transport and exhaustive protocol matrix.

## 0.6.0a2+wi0418.authoritytransport2

- Complete the versioned permitted-input-source taxonomy for every actionable
  Current Loop checkpoint and ready state.
- Make generation posture an explicit bounded enum with a non-null source
  disposition and fail-closed cross-field protocol validation.
- Add exhaustive active, checkpoint, recovery, terminal, and branch-closed
  matrix coverage without changing Protected operations or the twelve-tool
  surface.


## 0.6.0a2+wi0418.authoritytransport1

- Add one bounded versioned UTF-8 checkpoint-input channel for authority-bearing
  free text, with exact display, correction, approval-only promotion, and
  replay/stale-state rejection.
- Complete deterministic protocol coverage for every observable ready Current
  Loop phase, including branch-closed `next_loop_ready` stop/start-next
  semantics.
- Preserve the accepted Request Baseline, Generation Context dual paths,
  exact IDE-to-artifact handoff, and twelve-tool Connected Assistant binding.


## 0.6.0a2+wi0418.workstylerouting1

- Bind supported connected assistants to qCoder's separate hosted-capability and local
  active-build orchestration surfaces without adding an MCP tool.
- Add a versioned, deterministic three-workstyle routing descriptor to MCP initialization
  instructions.
- Make ordinary local command execution the explicit supported route for `qcoder current-loop`
  while preserving bounded single-capability MCP use and all authority boundaries.


## 0.6.0a2+wi0418.artifacthandoff1

- Make the post-IDE-authority handoff deterministic with exact-path retention and
  additive, idempotent artifact registration.
- Distinguish assistant-created, assistant-modified, and user-selected artifact
  provenance while accepting the legacy user-supplied value as an input alias.
- Exclude qCoder local state, discovery expressions, directories, and missing files
  from artifact registration.
- Clarify that authorized ordinary IDE inspection of relevant non-qCoder project
  files never creates or authorizes a qCoder review candidate.


## 0.6.0a2+wi0418.requestbaseline1

- Stage the complete governing customer message locally for exact Request Baseline review before
  activation, then reuse the reviewed bytes without retransmission.
- Add lossless inline, UTF-8 file, and explicit stdin request transports plus attributable,
  additive constraint, choice, interpretation, label, and posture authority.
- Keep activation/baseline approval separate from posture, IDE write/run, exact-artifact review,
  and governing-change confirmation.


## 0.6.0a2+wi0418.dualpath1

- Handle exploratory context, Blueprint-readiness decision checkpoints, and full Generation
  Context Packs as distinct valid outcomes of the existing protected operation.
- Add explicit, attributable decision-disposition and posture-transition authority to the
  existing Current Loop CLI without adding a Context Bridge tool or protected operation.
- Preserve workspace/intent separation, explicit-answer provenance, unresolved decisions, and
  the four independent customer authority boundaries.


## 0.6.0a2+wi0418.checkpoint1

- Mark this private, non-publishable WI-0418 checkpoint-protocol candidate with a distinct PEP 440
  local identity while reserving plain `0.6.0a2` for the eventual frozen publication candidate.
- Make every Current Loop checkpoint deterministically actionable and transmit conversational
  approval through explicit coordinator authority inputs without adding an MCP tool or protected
  operation.


## 0.6.0a2

- Package the accepted Current Loop continuity foundation and deterministic coordinator behind the
  existing `qcoder current-loop` entrypoint.
- Handle exploratory context, Blueprint-readiness decision checkpoints, and full Generation
  Context Packs as distinct valid outcomes of the existing protected operation.
- Add explicit, attributable decision-disposition and posture-transition authority to the
  existing Current Loop CLI without adding a Context Bridge tool or protected operation.
- Preserve workspace/intent separation, explicit-answer provenance, unresolved decisions, and
  the four independent customer authority boundaries.
- Supply explicit, non-silent connected-client activation guidance through the existing local
  Context Bridge initialization response without adding a Context Bridge tool.
- Preserve exactly twelve qCoder Context Bridge domain tools, separate IDE write/run authority,
  exact-artifact review authorization, and fail-closed hosted review behavior.


## 0.6.0a1

- Add the complete Explorer Context Loop contract across Request Baseline, Working Blueprint,
  Generation Context, bounded source/circuit/result evidence, Current Build Context,
  Carry-Forward Proposal, explicit human confirmation, and deterministic Evolved Blueprint
  materialization.
- Expose the twelve public-safe Context Bridge operations required by the complete IDE-first
  workflow while preserving exactly five Prompt Context modes, three profiles, and seven
  carry-forward actions.
- Add the versioned, bounded `qcoder.current_build_context.portable.v1` transport envelope for
  optional passive Current Build Context review without raw-artifact upload, persistence,
  hidden retrieval, browser confirmation, or browser materialization.
- Preserve Qiskit as the only active Context Loop SDK and keep simulator, runtime, and QPU
  execution external to qCoder.


## 0.5.0a9

- Complete the bounded Explorer evidence loop with Context Session Card, Run Readiness Card, Result Review Context Card, Bounded Next Check Planner, and Single-Loop Evidence Diff tools.
- Expose exactly eight Context Bridge tools while preserving the existing guided-evidence, prompt-context, and Evidence Context Pack tools.
- Add `explain`, `review`, `revise`, `troubleshoot`, and `plan_next_checks` prompt-context modes while preserving the default prompt behavior.
- Preserve structured before/after evidence in Single-Loop Evidence Diff calls over Content-Length stdio MCP framing.
- Make the default Context Bridge smoke a concise one-call customer connection check, with optional JSON output and a separate rate-limit-aware `--full` support/release diagnostic.
- Keep Context Bridge current-request-only and process-and-discard, with categorical evidence-provenance labels and no retained artifacts, repository scanning, file editing, history, memory, scoring, or autonomous execution.


## 0.5.0a8

- Add `qcoder context-bridge mcp serve`, a stdio Context Bridge MCP adapter for eligible Explorer users.
- Add `qcoder context-bridge mcp smoke --token-file <path> --json` for sanitized install verification.
- Expose only the approved Context Bridge tools: guided evidence context, prompt context, Evidence Context Pack, Context Session Card, and Run Readiness Card.
- Read Context Bridge tokens from a local token file only; token values are not printed and are not required in IDE config.
- Reject raw QASM, raw counts, paths, unsupported artifact lookup, unknown tools, and non-current-context inputs before forwarding.
- Preserve qCoder OSS local commands, Explorer evidence commands, and archived Pro shell boundaries.


## 0.5.0a6

- Add share-safe / redacted artifact mode for artifacts intended for ChatGPT, Cursor, email, GitHub issues, or support threads.
- Add `--share-safe` / `--redact` to OSS artifact commands and Explorer evidence file output.
- Emit share-safety metadata in JSON artifacts: `share_safe`, `redactions_applied`, `raw_qasm_included`, `local_paths_included`, and `tokens_included`.
- Add a visible share-safe note to Markdown artifacts.
- Fix Windows free-text path redaction, including `C:\Users\...` paths, Windows forward-slash paths, UNC paths, home-relative paths, Linux home paths, and WSL-mounted Windows paths.
- Preserve normal rich local artifacts by default; share-safe mode is opt-in.
- Share-safe mode is designed for safer sharing and users should still review artifacts before sharing. It is not a privacy guarantee.
- Remaining P1 hardening: forward-slash UNC variants, broader Linux root patterns, independent post-scan hardening, and expanded docs wording.


## 0.5.0a5

- Add `qcoder explorer evidence` as the primary Explorer Beta guided-evidence surface.
- Add derived-context Explorer evidence for user-owned OpenQASM 2 artifacts without raw hosted QASM upload.
- Preserve `qcoder student evidence` as a beta compatibility alias.
- Align public package wording with qCoder OSS and Explorer Beta; Pro is not launched or a current public product.
- Preserve the OSS local artifact path (`analyze`, `batch`, `context`, `review`) for no-account, no-token local workflows.

## 0.5.0a4

- Add public Student aliases: `qcoder student status` and `qcoder student demo`.
- Add `qcoder student evidence` for the existing deterministic hosted guided-evidence endpoint.
- Polish Student CLI output so `status` is access-framed, `demo` is the built-in teaching demo, and `evidence` renders learner-friendly summaries by default.
- Hide hosted meta fields in default Student output; add `--json` on Student subcommands for intentional raw payload output.
- Add `QCODER_STUDENT_BASE_URL` / `QCODER_STUDENT_TOKEN` aliases while preserving Preview/Pro env compatibility.
- Student aliases reuse the hosted Preview client configuration: `QCODER_PREVIEW_BASE_URL` / `QCODER_PREVIEW_TOKEN`, with `QCODER_PRO_API_URL` / `QCODER_PRO_TOKEN` compatibility fallbacks.
- No service deployment change is included in this public package slice.
- Existing `qcoder pro preview status` and `qcoder pro preview demo` commands remain compatible.

## 0.5.0a3

- Add public hosted Preview client commands: `qcoder pro preview status` and `qcoder pro preview demo`.
- Support env-based hosted Preview configuration with `QCODER_PREVIEW_BASE_URL` / `QCODER_PREVIEW_TOKEN`, with `QCODER_PRO_API_URL` / `QCODER_PRO_TOKEN` compatibility fallbacks.
- Keep hosted Preview output bounded and token-safe: no token persistence, no Authorization header printing, and safe handling for 200/401/403/network failures.
- Preserve public package boundary: no confidential Pro implementation, account service, protected service, uploads, QPU/provider execution, payment, hosted MCP, or Pro V0.0 launch claim is included in this package.

All notable changes to this project will be documented in this file.

The format is based on common practice for pre-1.0 semantic versioning: **`MAJOR.MINOR.PATCH`** with **`aN`** for alpha prereleases.

## Unreleased

- Add the unreleased Algorithm Blueprint v1 contract: four additive Context Bridge operations,
  explicit intent confirmation, Generic Qiskit/Grover/QAOA profiles, a distinct Output Evidence
  Contract, machine-local Selected Python Source Evidence, and bounded static-source alignment.
- Preserve exactly five Prompt Context modes, all existing Evidence Review requests and aliases,
  process-and-discard behavior, and the no-execution/no-correctness boundaries.

### Evidence Review

- Align the existing eight Context Bridge tools as the bounded Explorer Evidence Review capability for current-session readiness, result interpretation, two-point comparison, user-controlled next checks, and purpose-specific handoff.
- Use the categorical Evidence Confidence Labels Observed, User-provided, Inferred, Assumed, Not proven, and Suggested next check across core review outputs without numerical confidence or correctness scoring.
- Preserve exact tool and Prompt Context mode inventories, existing request compatibility, process-and-discard handling, and current-artifact/current-session boundaries.
- Keep execution external to qCoder, suggested checks user-controlled, and ChatGPT a manual share-safe Prompt Context handoff rather than a connected Context Bridge integration.

## 0.5.0a2 (alpha — public Free + Pro Preview client contract)

Second public alpha for the **Option 3 product line**: unchanged Free local/offline CLI plus an expanded **Pro Preview bootstrap/client contract** (not a generally available hosted Pro product).

### Added

- Public-safe **Pro Preview bootstrap** commands: `qcoder pro signup`, `login`, `install`, `status`, `validate` with local token/config support only.
- **`qcoder pro workflow --dry-run-manifest`** — writes `qcoder.pro_preview.workflow_manifest.v0` locally (QASM hashes/bytes plus local Free analysis); no network.
- **Explicit configured manifest-only service submit** — `qcoder pro workflow --submit --service-url <url>` with optional `--manifest-out`; requires token and a non-default configured service URL; sanitizes manifest before POST.
- Stronger **public package safety** checks, Pro Preview unit tests, and release rehearsal coverage in CI.

### Scope / boundaries

- **No** generally available production hosted Pro service, public account/token issuance from qcoder.ai, or sellable hosted Pro product behavior.
- **No** artifact upload, source upload, or background upload in this submit slice.
- **No** local confidential Pro analysis, cards, or `qcoder.pro_v0` in the wheel.
- **No** telemetry upload or training delivery.
- **No** QPU, simulator, or provider execution in CLI flows.
- Free commands (`analyze`, `batch`, `context`, `review`) remain local/offline and useful without Pro.

## 0.5.0a1 (alpha — public Free + Pro Preview shell)

First public package version for the **Option 3 product line**: local/offline Free CLI plus a service-backed Pro Preview shell. Version **`0.5.0a1`** is distinct from the internal frozen local private-alpha RC **`0.4.0a4`** (not shipped here).

### Changed

- **Package version** — public Free + service-backed Pro Preview shell ships as **`0.5.0a1`**.
- **Public package** — Free local/offline CLI (`analyze`, `batch`, `context`, `review`) with no cards; confidential local Pro implementation is not included.
- **`qcoder pro` shell** — service-backed Pro Preview stub (`signup`, `status`, `login`, `workflow`); no local cards or Pro analysis in the wheel.
- **Release-check** — public Free + Pro shell smoke; wheel/sdist scanned for forbidden Pro artifacts.

### Scope / boundaries

- Free qCoder remains local/offline and useful without Pro.
- Pro Preview service is not implemented in this repository slice.

---

## 0.4.0a2 (alpha)

### Added

- **Local Guidance Pack shadow metadata** — optional **`guidance_metadata`** records the bundled local resource-guidance candidate pack, including pack identity, version/hash metadata, caveats, and **`shadow_guidance`** with **`applied: false`**; deterministic guidance remains authoritative.

### Improved

- **Free Single-Run Intelligence** and **BYO LLM** artifact examples clarify that shadow guidance is metadata only.
- **Release notes** — this alpha has no hosted qCoder compute, no telemetry upload, no qCoder-hosted LLM, no runtime ML dependency, and no optimality, fidelity, runtime, hardware, backend-ranking, or causal-savings claims.

## 0.4.0a1 (alpha)

qCoder **0.4.0a1** adds opt-in derived **feature profiles**, mixed-width **review** checks, and a **5‑minute preflight→review** path.

### Added

- **`--profiles`** on **`qcoder analyze --json`** and **`qcoder context`** — deterministic derived **`feature_profiles`** from **`feature_map`**, emitted with **`feature_profiles_schema_version: "0.1"`** and **`basis: "deterministic_formula_from_feature_map"`**; **`not_guarantees: true`**.
- **`bitstring_width_consistency`** check in **`qcoder review`** — warns when observed bitstring key lengths disagree; derived metrics still use observed counts (also covers **`qcoder`** and **`qiskit_counts`** normalization paths).

### Improved

- **README — First 5 minutes** — quick install → Bell QASM → **`qcoder context --guidance --profiles`** → **`qcoder review`** with sample counts.
- **`examples/`** — Bell OpenQASM, illustrative counts fixture, copy-paste workflow docs, and optional **Qiskit / Cirq / PennyLane** export scripts (structure/export only).
- **Profile label polish** — `connected_small_graph` for tiny circuits instead of misleading `connected_high_density`; **`statevector_scale`** tier key (replacing `circuit_width`); **`llm_summary_profile`** rendered as short sub-bullets in preflight Markdown.
- **Execution review Markdown** — explicit that counts are user-provided and qCoder did not execute the circuit; **Assumptions and Limits** section when present.

### Unchanged / scope

- **Canonical feature schema** — same version, field order, and feature vector layout as **`0.3.0a1`** (`schema_v0`/compute path); profiles are additive only and do not alter canonical **`features`**.

### Local-only boundaries

- No LLM calls, telemetry, uploads, retrieval, or embeddings; no simulator or hardware execution, transpilation, or runtime execution in these CLI flows. Artifacts are local files under your control.

## 0.3.0a1 (alpha)

Optional Cirq and PennyLane intake alongside the existing Qiskit adapter. All adapters follow the same structural rules: framework object → OpenQASM 2 text → qCoder's shared parser pipeline.

### Added

- **`qcoder[cirq]`** — optional **Cirq** `Circuit` intake via OpenQASM 2 export (`cirq.qasm`) into the same canonical extractor used for `.qasm` files.
- **`qcoder[pennylane]`** — optional **PennyLane** intake (`QNode`, and **`QuantumScript`** where the installed version exposes it) via OpenQASM 2 export into the same canonical extractor used for `.qasm` files.

### Changed

- **Adapter error handling** — Qiskit intake wraps **`qiskit.qasm2.dumps`** failures and QASM-parse failures at the adapter boundary in actionable **`RuntimeError`** messages aligned with Cirq and PennyLane adapters.

### Unchanged / scope

- **Canonical feature schema** — same version, field order, and feature vector layout as **`0.2.0a1`** (`schema_v0`/compute path).
- **Intake semantics** — Qiskit, Cirq, and PennyLane adapters are **structure/export intake only**: no transpiler upload, execution, simulator/hardware runs, telemetry, LLM calls, retrieval, or embeddings inside qCoder for these flows.

## 0.2.0a1 (alpha)

Local-only deterministic CLI tooling for quantum circuit analysis and LLM-ready workflow artifacts.

### Added

- **CLI help fixes** — consistent subcommands and help text (`analyze`, `batch`, `context`, `review`).
- **`feature_map`** — derived `name → value` view alongside canonical nested `features` in machine-readable analyze output for readability.
- **`--guidance`** — optional heuristic resource guidance on `qcoder analyze` and `qcoder batch` for shot budgets and simulator / MPS starting points (deterministic from structure only; non-guaranteed).
- **`qcoder context`** — preflight artifacts as **Markdown + JSON** (optional `--guidance`, optional **`--full-features`** glossary appendix).
- **`qcoder review`** — post-execution artifacts as **Markdown + JSON** from user-supplied counts; optional linkage to preflight JSON.
- **`qcoder.counts.v0`** counts schema and **`qiskit_counts`** normalization into the same deterministic review pipeline.
- **Feature glossary** — short deterministic definitions aligned with schema v0 feature names; surfaced in context bundles and **`--full-features`** appendix.
- **Conservative `shots_total` handling** — when declared `shots_total` disagrees with `sum(counts)`, review-derived probabilities use the observed sum, with explicit **`shots_total_match` check**, warning text, and `declared_shots_total` / `shots_total_basis` fields.

### Behaviour

- **Local-only** — no LLM calls, no telemetry, no network, no retrieval or embeddings, no simulator or hardware execution within these CLI flows. Artifacts are files for you to attach or paste into tools of your choice.

### Unchanged

- Canonical circuit feature schema (version, order, and vector layout in `features`) is unchanged for this release.
