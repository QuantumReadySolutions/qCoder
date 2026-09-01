# Review before generation

This unpublished D-136 development candidate provides a deterministic, terminal first value for a
customer who asks qCoder to review substantive implementation choices before source generation or
selected-source modification.

Its private identity is `0.6.0a24.post0.dev9+semantic.only.first.value.v1`. It is synthetic-gate
only, is not a selected public successor, and is not authorized for publication or customer use.

The connected assistant calls `begin_current_loop` once with the exact unchanged customer request
and `review_content`. The semantic content contains one interpretation, an ordered nonempty list of
labeled implementation recommendations, and optional output-artifact text, limitations, one
material blocking question, and one proposed source target. It supplies no route, transaction,
generation, execution, delivery, revision, token, schema, or continuation authority.

qCoder derives request facts, routing, generation and execution state, default inline delivery,
fixed limitations and deferrals, exact group and action labels, semantic revision, projection
digest, confirmation state, and continuation authority. A safe request-grounded proposed target may
be displayed but remains inert. Unsafe, absolute, traversing, unsupported, or ungrounded targets
converge to inline without a repair turn or path processing. Exact confirmation of the displayed
revision is the first source-delivery and workspace-write authority; execution remains separate.

A safe bounded call terminates in one operation with either one complete confirmable review or one
concise customer blocker. Unsafe or malformed content fails closed terminally without schema,
contract, resource, retry, or repair choreography. Repeating the same request and semantically
equivalent content before customer input returns the same effective semantic result.

The successful customer projection contains exactly:

1. Goal and scope
2. Implementation
3. Output and authority

followed by exactly:

* Use recommended choices
* Review or change choices

The MCP text result is the exact qCoder-owned canonical Markdown. `structuredContent` carries the
matching validated machine projection, and both bind to one semantic revision and projection
digest. The candidate does not advertise or package an MCP App; versioned non-UI reference
resources remain optional and are not required to formulate the first call.

Direct generation and genuine selected-source review/modification retain strict exact-target and
native-selection behavior. Before confirmation the review transaction creates no source or QASM,
mutates no customer file, performs no execution, scans no repository, and calls no protected
service.

Generate and verify the D-136 goldens and local environmental timing with:

```text
python scripts/generate-wi0440-d136-goldens.py
python scripts/generate-wi0440-d136-goldens.py --check
python scripts/wi0440-d136-acceptance.py --repetitions 20
```

The timing command measures local qCoder mechanics only. It does not measure native Windows,
Cursor, a model, a client, or customer-visible latency.

The real stdio server records a bounded, sanitized, session-bound ledger containing only
`begin_current_loop` attempts. Initialize, discovery, resources, ping, notifications, and
`complete_current_step` cannot overwrite it. The local operator consumes the ledger exactly once;
it contains no customer request, interpretation, recommendation, target path, source, QASM, token,
credential, raw MCP payload, or private configuration.

D-136 supersedes dev8 proposal-v4 and MCP-App discovery/presentation expectations. It retains
canonical Markdown, structured projection, confirmation-first delivery authority, source/QASM
safety, token privacy, stale-token handling, idempotency, direct generation, selected-source
protection, exact 12+2 inventory, and zero protected-service calls.
