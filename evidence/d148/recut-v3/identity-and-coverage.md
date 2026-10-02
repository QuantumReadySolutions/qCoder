# D-148 v3 bounded correction

This checkpoint implements the authorized human-readable approval/provenance correction.
No new scientific family, LLM integration, provider call, transcript import or Phase E work.

Controlling internal records were read completely through connected GitHub (no internal
worktree accessed):
- human-readable approval/provenance correction: conference commit
  5278339c7af0942975e5fe6a8fc22695b320bd3c;
- multi-assistant clarification: 891355571a09df464e76e49b543f73cc7f8ac0b7;
- coverage mapping: 8ca3e32561ccaffab83a1b011c88b5f7b881ca5b;
- current TACTICAL_CONFERENCE, including receipt 47ea4e34f18a10bbb6f9dc383a19ac0f68f3246e;
- controlling D-148 work order on ops/tactical-conference-1-continuity-20260920.
Strategic authorization 935af4d9fd3d5cf1e30c45a21757ab4ffb7ffd8d remains operative.

## Identity domains

Scientific identity v2 uses normalized top-level Python ASTs for:
- complete ml_research __init__, fixture, models and training modules;
- contracts excluding only locked, now and file_digest;
- runtime excluding only PINS, CODE_FILES, runtime, code_identity and approval_identity;
- the complete byte digest of the canonical JSON/SHA primitive.

Every remaining top-level node, including globals/imports and unknown newly added
symbols, participates. AST normalization discards formatting/comments, not numerical
expressions. Strict fixture/checkpoint/metric validators, model reconstruction, recipes,
seeds, training/selection logic and the scientific identity machinery are covered.
Pure job approval, CLI presentation and tracker delivery modules are excluded.
The explicit exclusion map itself participates. A renamed formerly excluded symbol
fails closed into the scientific identity.

Scientific runtime v2 seals actual Python implementation/version/platform/machine,
CPU/float64/one Torch thread/deterministic algorithms, and the installed non-extra
 dependency closure of NumPy, SciPy, scikit-learn, PennyLane, Torch plus gast and
astunparse (required PennyLane import support that its dependency metadata omitted).
Roots are exactly pinned. The full closure versions are recorded. MLflow and unrelated
delivery/build/test dependencies are not training provenance.

Execution identity v2 independently seals the complete byte digest of all nine bounded
ml_research modules and the canonical primitive. The plan also binds the full exact
installed dependency profile. This covers evaluator, result recomputation, comparison,
durable entry/no-retry/reuse, selected tracker input checks, assessment and read-back,
as well as all routing and approval code. Removing a module from training provenance
does not remove it from execution currentness.

Approval identity v2 separately seals imports and _approval_summary, approve and
valid_approval from job, the component digester and approval_identity from runtime,
and full contracts bytes. The plan binds it; the approval binds that exact plan,
job, attempt, displayed summary, implementation digest and a fresh event nonce.
Full execution currentness additionally covers dependencies outside this slice.

Changing approval wording or CLI/tracker plumbing changes execution identity and
invalidates a pending plan without changing frozen training provenance.
Changing numerical code, recipe, split, preprocessing or scientific dependency
profile invalidates scientific checkpoint provenance as well.

## Approval boundary

The user reads a consequential summary and enters y (or Y) at:
“Approve this exact displayed research job? [y/N]”

The human never transcribes a digest/challenge. Digest display is audit information.
A challenge remains internal in the plan; fresh event nonces identify approvals.
Production opens the existing controlling /dev/tty as a character device, verifies
foreground process-group ownership, bounds read/write, rejects redirected stdin/stdout,
rechecks currentness and foreground ownership after input, then exclusively persists
approval. Approve cannot enter science; run cannot mint approval. Existing single-use,
durable-entry, no-retry and exact-completed-reuse behavior remains unchanged.

Trust boundary: local OS and controlling foreground TTY user origin. This does NOT
claim isolation against malicious same-UID programs able to forge local files or
synthesize terminal input. Automated PTY input occurs only on synthetic test plans,
never on any canonical workspace.

Nineteen real controlling-PTY cases exercise the actual production CLI: y, fragmented y,
default newline, n, arbitrary prose, generic assent, digest-only input, old assistant
token, oversized response, EOF, changed plan during prompt, invalid plan before prompt,
stale checkpoint, redirected input, outside conversational assent, assistant digest
flag, environment/file markers, repeated ceremony and run without approval.
Each establishes character-device/foreground/non-seekable properties and reproduces
the old r+ exception. Successful approval itself leaves scientific entry absent.

## Multi-assistant coverage disposition

No assistant transcript or test-report ingest surface is added.

| Concern | Existing deterministic evidence reused | Honest remaining boundary |
| --- | --- | --- |
| Unsupported split assumption | strict split/checkpoint joins; tampered selected parameter refusal; tracker free text inert | Phase E assistant phrasing |
| Metric/partition relabel | fixed metric/protocol/40 count; train-only selection; checkpoint validation | assistant-facing synthesis in Phase E |
| Invented authority | user TTY origin, no CLI digest flag, invalid origin refusal; 19 replacement PTY cases | no malicious same-UID isolation claim |
| Unknown authorship/test basis | no generic claim ingestion; external_reported vs qcoder_established projection | cannot establish an unobserved assistant test |
| Round-trip repetition | exact completed reuse, delivery-only retry and duplicate read-back tests | repetition never upgrades provenance |
| Conflicting conclusions | qCoder recomputed metrics and deterministic conclusion protected by result/assessment checks | natural-client interaction remains Phase E |

No chat statement is promoted to scientific authority or deterministic evidence.
