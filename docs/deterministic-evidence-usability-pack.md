# Deterministic evidence usability pack

This unpublished development surface turns already-available, explicitly selected qCoder evidence
into three local views:

- an Evidence Prompt Pack for customer-reviewed assistant handoff;
- a Run Readiness Checklist that projects existing evidence without predicting execution;
- a Blueprint Intent Card that keeps user intent and confirmed choices separate from observations.

Use one explicit output directory:

```bash
qcoder review usability-pack \
  path/to/selected.py \
  path/to/selected.qasm \
  --intent-json path/to/algorithm-intent-card.json \
  --blueprint-json path/to/implementation-blueprint.json \
  --out-dir evidence-usability-output
```

The command writes `evidence-prompt-pack`, `run-readiness-checklist`, and
`blueprint-intent-card` in JSON and Markdown. Omit the Intent Card and Blueprint options when no
explicit or confirmed intent artifact exists; the intent view then says that intent is absent.

Inputs are only the files named on the command line. Directories, globs, hidden-file discovery,
neighboring files, imports, repositories, models, clients, credentials, services, and network
resources are not consulted. Python is parsed statically and OpenQASM 2 is inspected without
executing source or circuits. Output carries content digests and artifact kinds instead of local
absolute paths.

The readiness dispositions are `ready`, `warning`, `missing_evidence`, `unsupported`, and
`not_applicable`. They report only facts supported by current local evidence rules. They do not
predict runtime, fidelity, backend quality, shot count, correctness, execution success, hardware
suitability, or scientific value.

The Blueprint Intent Card accepts current Algorithm Intent Card and Implementation Blueprint v1
inputs. A digest-bearing input must validate. Proposed or clarification-needed intent remains
unconfirmed; source structure never fills an intent gap or confirms a choice.

See [`examples/deterministic_evidence_usability_pack/`](../examples/deterministic_evidence_usability_pack/)
for the checked Bell replay and byte-exact expected outputs.
