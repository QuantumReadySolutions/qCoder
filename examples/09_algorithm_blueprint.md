# Algorithm Blueprint walkthrough

This synthetic walkthrough documents the unreleased Algorithm Blueprint feature contract. It uses
no customer evidence, token, private endpoint, repository scan, backend, simulator, or QPU.

## 1. Preserve human intent

Call `create_algorithm_intent_card` with the original request and the
`generic_qiskit` profile. An underspecified request returns `needs_clarification`, preserves the
original text, and asks deterministic questions about goal, problem size, Qiskit constraints,
measurement, execution intent, and desired output.

Profile and assistant proposals keep their origins. They are not rewritten as originally
User-provided information.

## 2. Confirm the reviewed interpretation

Supply a proposed structured interpretation, resolve consequential questions, request
`confirmed`, and include an explicit `confirmation_assertion` with `user_reviewed: true`.
Confirmation means only that the request asserts user review. It is not identity, understanding,
scientific-validity, or correctness verification.

## 3. Create the build contract

Call `create_implementation_blueprint` with the complete confirmed Algorithm Intent Card and its
explicit `represented_by` relationship. The result contains two distinct schema-v1 artifacts:

- Implementation Blueprint: requirements, Qiskit constraints, implementation expectations,
  provenance, alternatives, unresolved user-accepted choices, motifs, and non-claims.
- Output Evidence Contract: expected static-source, constructed-circuit, execution, result, and
  unproven evidence.

The evidence contract is returned with the blueprint; there is no separate tool for it.

## 4. Prepare external generation

Call `create_generation_context_pack` with the explicitly supplied confirmed blueprint and matching
Output Evidence Contract. The pack states fixed requirements, choices an assistant must not invent,
expected evidence, and revision guidance.

Use the pack in Cursor, Claude Code, or Codex, or copy it manually to ChatGPT. ChatGPT is not a
connected Context Bridge integration. Python generation and editing occur outside qCoder under user
control; qCoder does not invoke an assistant or generate code.

## 5. Extract selected static evidence locally

After external generation, select exactly one Python file:

```bash
qcoder blueprint source-evidence --source-file selected_generated.py
```

For a bounded excerpt, pipe it locally:

```bash
qcoder blueprint source-evidence --excerpt-stdin --logical-label "selected builder excerpt"
```

The extractor uses `ast.parse` and records compact imports, aliases, symbols, declarations,
measurements, motifs, safe line references, coverage, ambiguities, and limitations. It does not
import source, follow imports, execute source, scan directories, edit the file, or include raw
source or absolute paths in the artifact.

## 6. Review static alignment

Call `create_source_blueprint_alignment_review` with the explicitly supplied confirmed blueprint,
matching Output Evidence Contract, and compact Selected Python Source Evidence. Do not supply a
file path, repository root, command, or raw excerpt.

The result separates observations, bounded inferences, assumptions, unproven statements, and
optional user-controlled checks using the existing Evidence Confidence Labels: Observed,
User-provided, Inferred, Assumed, Not proven, and Suggested next check.

“Not observed” always means not observed in the explicitly supplied static evidence. It does not
prove absence from the constructed or runtime circuit. Motif presence does not prove Generic,
Grover, or QAOA identity or correctness. Constructed-circuit, execution, and result evidence remain
separate downstream work that can continue through the Explorer Evidence Loop.

## Profile fixtures

- Generic Qiskit Blueprint holds problem-size, measurement, execution, output, and compatibility
  choices until supplied.
- Grover Search holds search-space, marked-state, oracle, iteration, ancilla, and decoding choices;
  oracle or diffusion names are observations, not Grover proof.
- QAOA holds mixer, repetitions, optimizer, backend, shots, initialization, and parameter strategy;
  no profile default silently supplies them.
