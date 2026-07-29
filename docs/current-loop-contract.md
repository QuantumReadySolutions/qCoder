# Explorer Current Loop Contract v1

The Current Loop Contract is qCoder's canonical, one-loop participation policy. It governs what
qCoder may collect, derive, expose, recommend, prepare, and request to apply or execute. It does
not contain the Working Blueprint or evidence payloads, grant IDE authority, or authorize raw
exposure, application, execution, external services, or hardware.

The contract is the `qcoder.current_loop.contract.v1` section of
`qcoder.current_loop.local_state.v3`. Canonical state is JSON. YAML is neither parsed nor
authoritative. The section inherits the Current Loop store's atomic write, lock, private
permissions, workspace binding, compare-and-swap revision, size bounds, and symlink rejection.

## Presets and compiled policy

- **Off** means there is no active loop and therefore no active contract.
- **Evidence only** permits exact authorized collection, local organization and integrity
  derivation, local views, and explicitly requested share-safe derived exposure. Standing
  recommendation, preparation, raw exposure, and execution requests are disabled.
- **Assist** is the default after exact-message activation. It adds selected standing share-safe
  derived context, bounded recommendations, and non-material preparation. Raw exposure,
  application, execution, paid/external activity, and Blueprint evolution remain disabled.
- **Custom** is a complete policy compiled from bounded customer-selected settings.

Each evidence category has separate `collect`, `derive`, `expose`, `recommend`, `prepare`, and
`request_application_or_execution` dispositions. Exposure distinguishes local qCoder use, local
presentation, and connected-assistant destinations; raw and derived forms; and standing versus
on-request modes.

The first-release categories are Request Baseline, Working Blueprint, Generation Context, Python
Manifestation, Circuit Manifestation, Result Manifestation, lineage, and derived metrics.

## Activation and posture

For one exact, unambiguous, explicitly qCoder-directed exploratory message, bootstrap capture mode
`exact_current_customer_message` preserves the bytes, activates the loop, applies Assist, and
returns an activation receipt in one invocation. The receipt binds the baseline digest, capture
provenance, contract identity and revision, effective-policy digest, activation revision, and a
plain-language summary. It grants no posture, IDE, raw-exposure, artifact-review,
governing-change, external-service, or execution authority.

Combined, changed, ambiguous, Blueprint-guided, or explicitly strict input uses `review_required`
and the existing exact-display plus authority-only approval path. Generation posture remains
unset until generation becomes relevant. Contract inspection, contract changes, exact event
receipts, permitted evidence registration, and non-generation review remain available.

## Natural controls

Connected assistants use qCoder-generated local invocations for contract status, preset
selection, one bounded category/dimension adjustment, broadening confirmation, evidence
exclusion, restoration, and deletion. Customers speak naturally; they never edit JSON or YAML.

Every such invocation carries `qcoder.current_loop.bounded_control_input.v1`. The contract
publishes exact preset, category, dimension, value, reason, and eligible-reference domains;
customer-language meanings; current values; and the complete valid-selection graph. It is derived
from the same constants used by parser choices and contract validation. The assistant selects only
advertised values, never constructs a policy document, never invents proposal, receipt, evidence,
revision, loop, or workspace references, and never consults help, source, package files, proof
records, transcripts, or `.qcoder` to discover a domain.

`Off` is not a `contract-set-preset` value. It is the distinct qCoder-generated stop-loop action,
because an inactive loop cannot contain an ordinary all-false active contract. Unsupported values
or invalid combinations return safe bounded recovery with refreshed domains and a complete local
next invocation; they do not alter the prior valid contract or evidence.

Narrowing applies immediately, cancels now-disallowed future use, and marks dependent views stale
or incomplete. It cannot recall information already exposed. Broadening produces an exact pending
proposal and requires a separate authority-only confirmation. Stale contract or state revisions
fail closed.

Evidence controls use qCoder-owned artifact references. Exclusion preserves the local record but
prevents future use. Restoration requires the same valid digest and available evidence. Deletion
is limited to qCoder-controlled local evidence and leaves an integrity tombstone without raw
content; arbitrary project files are never deleted.

## Exact IDE operation receipts

After separate IDE authority, qCoder may issue a single-use
`qcoder.current_loop.operation_receipt.v1`. It binds loop, workspace, issue revision, operation
category, and authorized output-role ceiling. Registration accepts only exact literal paths
actually created, modified, or produced by that action. qCoder verifies and hashes only those
paths. It never lists directories, reads Git status, builds repository maps, globs, watches, or
discovers neighboring files.

Unknown, unsupported, secret-bearing, or potentially sensitive outputs require explicit exact
selection, exclusion, or rejection. Without a trustworthy operation receipt, the existing visible
exact-artifact authorization flow remains the only fallback.

## Deterministic recovery and lifetime

Recoverable failures carry `qcoder.current_loop.recovery.v1`, preserve prior valid authority and
evidence, and identify one complete qCoder-generated next invocation. Strategies include
qCoder-owned correction, restaging, revision refresh, bounded alternatives, operation-receipt
rebinding, skip, abandon-step, and stop-loop. Internal profile classification such as
`generic_qiskit` is qCoder-owned when attributable context permits it.

Contract state is active only for one loop. Closing or abandoning the loop makes it inactive.
Start-next and later explicit activation compile fresh Assist defaults: revisions, exclusions,
deletions, recommendations, and settings do not carry forward. There is no Account Center
synchronization, automatic reopening, project history, hosted contract storage, or cross-loop
intelligence.
