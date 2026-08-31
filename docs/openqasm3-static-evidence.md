# Bounded OpenQASM 3 static evidence

This document describes the private unpublished
`0.6.0a24.post0.dev2+openqasm3.local.evidence.v1` candidate. Public qCoder 0.6.0a24 is unchanged.

qCoder extracts bounded static evidence from the explicitly supported OpenQASM 3.0 subset of one
explicitly selected UTF-8 file. It reports unsupported constructs and qualifies or withholds every
fact they may affect. qCoder does not execute the source or circuit.

## Use the existing local surfaces

```bash
qcoder review local-evidence examples/openqasm3_static_evidence/bell.qasm3
qcoder review local-evidence \
  examples/openqasm3_static_evidence/partial-control-flow.qasm3 \
  --out-json local-evidence.json \
  --out-md local-evidence.md
qcoder review usability-pack \
  examples/openqasm3_static_evidence/bell.qasm3 \
  --out-dir openqasm3-evidence-output
```

Inputs are explicit files only. Directories, globs, imports, neighboring files, hidden files,
repositories, models, clients, protected services, and network resources are not inspected. The
maximum selected source size is 100000 bytes. Raw source is excluded from evidence by default and
can appear only through the existing separate original-QASM share-safe opt-in.

## Identities

- sidecar: `qcoder.openqasm3_static_evidence.v1`;
- parser: `qcoder.openqasm3.bounded_parser.v1`;
- package-owned standard vocabulary: `qcoder.openqasm3.stdgates_3_0.v1`.

The raw selected source bytes are identified by SHA-256. The customer-visible artifact label is a
basename, not an absolute local path.

## Headers and include

The operative declaration must be exactly `OPENQASM 3;` or `OPENQASM 3.0;`. A missing, malformed,
duplicate, misplaced, ambiguous, or later-version declaration fails with a bounded category. The
only supported include is the exact global `include "stdgates.inc";`. qCoder supplies that
vocabulary from the package and never opens a filesystem include. Every other include is visible
as recognized but unsupported and is never followed.

`U` (three parameters, one qubit) and `gphase` (one parameter, zero qubits) are language built-ins.
The exact case-sensitive package vocabulary activated by `stdgates.inc` is:

`p`, `x`, `y`, `z`, `h`, `s`, `sdg`, `t`, `tdg`, `sx`, `rx`, `ry`, `rz`, `cx`, `cy`, `cz`, `ch`,
`swap`, `cp`, `crx`, `cry`, `crz`, `cu`, `ccx`, `cswap`, `CX`, `phase`, `cphase`, `id`, `u1`, `u2`,
and `u3`.

Parameter count, target arity, and case are exact.

## Supported static subset

The v1 subset supports scalar and positive statically sized `qubit` and `bit` declarations;
deterministic scalar indexing; whole-register references; equal-width bounded broadcasting;
supported gate calls; supported measurement assignment, declaration, arrow, and unassigned forms;
whole-register measurement with equal source/destination widths; reset; barrier; declaration-before-
use custom gates; and ordered `inv`, `ctrl`, `negctrl`, and `pow` modifier chains.

Custom-gate bodies may contain only supported built-in or prior valid custom-gate calls. Formal
parameter identifiers are bounded symbolic variables. Bodies are preserved but not recursively
expanded. A call establishes its identity, explicit parameters and targets, and declaration link;
it does not establish internal primitive counts, expanded depth, internal interactions, execution,
or semantic equivalence. Forward references, recursion, and cycles are unsupported.

Supported expressions are decimal, hexadecimal, octal, and binary integers; numeric separators;
decimal and scientific floating literals; `pi`, `tau`, `euler`, `π`, `τ`, and `ℇ`; custom-gate
formal parameters; unary `+` and `-`; parentheses; and binary `+`, `-`, `*`, `/`, and `**`. Arbitrary
identifiers, functions, casts, runtime values, Python, division by zero, and excessive depth are not
evaluated.

## Classification and exactness

Every structurally bounded occurrence is exactly one of `supported`, `partially_supported`,
`recognized_but_unsupported`, or `unrecognized`. `malformed` is separate. A partial occurrence
states what was established, what was unavailable, and which facts are affected. Unsupported
dynamic bodies are not descended into and their contents are not counted as complete operations.

A file is `supported` only when every occurrence is supported. Any partial, recognized-unsupported,
unrecognized, or recovered-malformed occurrence makes the file `partial`. A malformed string,
comment, statement, or brace boundary that prevents reliable recovery makes the file `fatal` and
produces no complete circuit projection. Parsed prefixes are never represented as complete files.

Derived facts use only `exact`, `lower_bound`, `partial`, `not_established`, and `not_applicable`.
Width, operation and measurement counts, depth, interaction edges, and gate statistics carry their
own exactness. Partial files never enter a complete-CircuitIR consumer. Custom-gate calls remain
call-level observations and make expanded primitive depth unavailable.

## Recognized but unsupported

The parser ledgers compatibility `qreg`/`creg`; classical computation beyond `bit`; arrays;
aliases; slices, sets, and concatenation; input/output; physical qubits; assignments; functions;
casts; control flow; loops; switch; break/continue/end; subroutines and return; extern; timing,
duration, stretch, and boxes; calibration and OpenPulse families; pragmas; annotations; arbitrary
includes; vendor extensions; unsupported modifiers; and later-version constructs such as `nop`.
Their semantics are withheld.

## Bounded diagnostics and limits

Customer-safe diagnostic categories include `missing_header`, `invalid_header`,
`unsupported_openqasm_version`, `malformed_syntax`, `input_size_exceeded`,
`parser_limit_exceeded`, `unsupported_include`, `unsupported_construct`,
`unrecognized_construct`, `duplicate_declaration`, `invalid_register_reference`,
`index_out_of_range`, `unsupported_expression`, `unsupported_modifier`, `unsafe_path`, and
`invalid_encoding`. Package-owned limits cover tokens, statements, declarations, operations,
nesting, expressions, custom gates, modifiers, broadcasting, recovery, diagnostics, and ledger
entries. A limit never truncates evidence and then claims completeness.

## Claim and privacy boundary

The sidecar does not establish full OpenQASM 3 compliance, dynamic-circuit support, conversion,
semantic equivalence, algorithm identity or correctness, expected output, hardware compatibility,
backend suitability, execution success, runtime, resources, fidelity, optimal shots, or statistical
sufficiency. It adds no motif evidence and cannot establish intent or confirmation.

No credential, token, authentication state, private configuration, environment state, repository
information, include contents, or unrelated file is retained. JSON and Markdown ordering is
deterministic. See [`../examples/openqasm3_static_evidence/`](../examples/openqasm3_static_evidence/)
for original qCoder fixtures and byte-checked outputs.
