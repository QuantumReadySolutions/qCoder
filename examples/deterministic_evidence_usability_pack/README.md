# Deterministic evidence usability replay

This replay uses two explicitly selected Bell artifacts plus already-confirmed intent and
Blueprint inputs. qCoder parses the selected files statically and writes three deterministic
views in JSON and Markdown. It does not execute the Python source or circuit, discover neighboring
files, call a model or service, use a credential, or retain project memory.

Run from the repository root (or replace the paths with the same installed example files):

```bash
qcoder review usability-pack \
  examples/deterministic_evidence_usability_pack/bell.py \
  examples/deterministic_evidence_usability_pack/bell.qasm \
  --intent-json examples/deterministic_evidence_usability_pack/algorithm-intent-card.json \
  --blueprint-json examples/deterministic_evidence_usability_pack/implementation-blueprint.json \
  --out-dir evidence-usability-output
```

The checked files under `expected/` are the byte-for-byte expected outputs. The Evidence Prompt
Pack can be supplied to an assistant after customer review; it does not guarantee assistant
quality. The Run Readiness Checklist summarizes existing evidence and does not predict execution
success. The Blueprint Intent Card keeps confirmed intent and choices separate from observed
source or circuit structure.
