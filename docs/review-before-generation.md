# Review before generation

This unpublished development candidate adds a deterministic, binding-owned first value for a
customer who explicitly asks qCoder to review a proposed interpretation and material implementation
choices before source generation or source modification.

Its private candidate identity is
`0.6.0a24.post0.dev8+canonical.first.value.v1`; it is not a selected public successor and is not
authorized for publication or handoff.

The connected assistant sends the exact unchanged customer request and a separately attributed
compact proposal v4 in one `begin_current_loop` operation. Accepted proposal v3 inputs normalize to
the same internal form. The assistant—not qCoder—supplies the substantive
recommendations, including exactly one inert source-delivery recommendation: `inline`, or
`workspace_file` with one proposed target. qCoder validates exact-request binding, the six semantic
axes, substantiveness, structural safety, privacy, retention, and revision integrity. It then returns one
display-ready review with exactly:

1. Goal and scope
2. Implementation
3. Output and authority

Only a substantive, unblocked review exposes `Use recommended choices` and `Review or change
choices`. Before confirmation, even a displayed workspace-file recommendation has no write
authority. Confirmation binds to the exact displayed revision and is the first source-delivery and
workspace-write authority. It grants source generation or modification for that revision only;
execution always remains independent.

Review before generation has immediate-interaction precedence over future artifact production only
after qCoder verifies that the proposal's generation-versus-modification kind agrees with the exact
unquoted request and any exact native-client selection. qCoder does not infer review delivery or
write authority from free-form customer prose. A proposed workspace target is displayable only when
it is a structurally safe workspace-relative Python path and its exact text occurs in the unchanged
request, or existing native selected-source provenance grounds it. Request presence is an
anti-invention guard, not semantic interpretation: quotation, examples, comparisons, hypotheticals,
questions, negation, prohibition, correction, and directive wording do not autonomously grant or
deny review write authority. Missing, unsafe, absolute, traversing, unsupported, or ungrounded file
recommendations silently converge to inline without a correction turn. Assistant intended/selected
envelope fields remain irrelevant for generation review. A grounded file recommendation is shown
once and revision-bound, but remains inert until exact displayed confirmation. Only then does qCoder
apply workspace containment and create the exact-target Current Step Contract. Direct generation,
review before modifying selected source, selected-file workflows, and active-loop replacement retain
their strict existing target contracts.

The compact first review shows assistant recommendations once. Its complete editable material-choice
inventory remains behind `Review or change choices`, so the initial three groups do not restate the
same framework, construction, measurement, output, or authority decisions.

The transaction creates no source or QASM, mutates no customer file, performs no execution, calls
no protected service, scans no repository, and adds no model or persistent memory. Its structured
proposal is retained only in the active Current Loop and is discarded through the existing loop
closure semantics.

The exact Bell model pack is
`src/qcoder/model_packs/wi0440_bell_review_before_generation_v1.json`. The non-Bell class matrix is
`src/qcoder/model_packs/wi0440_review_before_generation_class_matrix_v1.json`. Deterministic Bell and
representative GHZ goldens are under `tests/goldens/`.

Verify the goldens and local timing acceptance with:

```text
python scripts/generate-wi0440-d135-goldens.py
python scripts/wi0440-d135-acceptance.py --repetitions 20
```

The timing command measures only fixture-driven deterministic local work. It does not measure an AI
assistant, a protected service, a client, or the historical 188.8-second customer-visible event.
The real stdio binding additionally writes one operation-bound, session-bound, sanitized,
operator-only timing receipt after an accepted private operation. Discovery and resource traffic
cannot overwrite it. A separate local operator process consumes that receipt exactly once; the
receipt never enters the MCP result or customer projection and retains no request, proposal, result
token, target, source, QASM, credential, or client stream.
Targeted native-Windows Cursor end-to-end timing remains a later Roadmap-gated lifecycle step.

## D-135 canonical delivery successor

The preferred proposal is
`qcoder.connected_assistant.review_before_generation_proposal.v4`. It contains each semantic fact
once. Accepted proposal v3 inputs remain strictly validated and normalize into the same internal
representation.

On a successful first review, MCP text content is the exact qCoder-rendered Markdown. The same
validated object remains in `structuredContent`; its semantic revision, Markdown, machine
projection, App render model, delivery recommendation, target, and actions share one deterministic
projection digest. A client presents the text unchanged rather than asking the connected assistant
to reconstruct it.

Extended references are available at `qcoder://current-loop/review-before-generation/v4`,
`qcoder://current-loop/operations/v58`, and
`qcoder://current-loop/authority-continuation/v1`. The progressive App is
`ui://qcoder/current-loop/first-value/v1` with MIME `text/html;profile=mcp-app`. It is packaged
locally, has no remote dependency, verifies the projection digest, renders escaped text, and invokes
only the existing token-only `begin_current_loop` actions. Canonical Markdown remains the complete
fallback.

D-135 intentionally supersedes connected-assistant Markdown reconstruction, full nested schemas
and long examples in every discovery descriptor, duplicate v3 recommendation/material-choice
inputs in the preferred proposal, and a response-global timing receipt. Runtime validation,
accepted v3 inputs, exact target checks, direct generation, selected-source behavior, source/QASM
safety, token privacy, stale-token handling, and idempotency remain enforced.
