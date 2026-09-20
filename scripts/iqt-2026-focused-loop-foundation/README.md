# IQT 2026 focused-mode conference foundation proof

This directory is an internal engineering harness for the D-143 conference track. It is
not a release packet, public-demo authorization, customer enablement, or post-WI-0441
production integration.

## Immutable source basis

- Phase A source: `7937f4a3e6075182d53881640761ca53087148ae`
- Conference branch: `conference/iqt-2026-focused-mode-foundation-v1`
- Frozen fixture: `FX-CLIF-ACCEPT-01 / NESTED_BELL_64Q_SMALL_SUPPORT_PREDICATE_V1`

## Exact Aer environment

The real-Aer proof uses the same exact simulator pins already used by qCoder's prepared
natural-client rehearsal:

- `qiskit==2.5.2`
- `qiskit-aer==0.17.2`

Use a compatible isolated Python 3.13, 3.12, or 3.11 interpreter. The repository-level
`.python-version` is not itself evidence that a binary Aer wheel exists for that
interpreter.

Example source-level setup (dependency acquisition happens before the bounded proof):

```bash
python3.13 -m venv .venv-iqt-focused
.venv-iqt-focused/bin/python -m pip install -r scripts/iqt-2026-focused-loop-foundation/requirements.txt
.venv-iqt-focused/bin/python -m pip install -e .
```

The executor itself never installs dependencies.

## Real-Aer proof

```bash
.venv-iqt-focused/bin/python -m pytest -q \
  tests/test_focused_loop_conference_real_aer_v1.py
```

This performs four finite actual local Aer executions with fresh authority attempt
identities: three primary-fixture seeds and one held-out fixture. The canonical primary
case additionally proves sibling receipt / strict-manifest-v3 compatibility, exact
598-shot predicate analysis, exact-result reuse with zero second execution, source and
workspace immutability, process-environment immutability, and a Python-socket network
sentinel. It also compares the scientific conclusion from actual Aer with the old
explicitly injected fake-backend proof path without requiring identical random
histograms.

## Focused deterministic/adversarial/package regression set

```bash
.venv-iqt-focused/bin/python -m pytest -q \
  tests/test_focused_loop_contracts_v1.py \
  tests/test_focused_loop_cp_oracle_v1.py \
  tests/test_focused_loop_executor_v1.py \
  tests/test_focused_loop_fixture_v1.py \
  tests/test_focused_loop_manifest_join_v1.py \
  tests/test_focused_loop_mps_arithmetic_v1.py \
  tests/test_focused_loop_package_isolation_v1.py \
  tests/test_focused_loop_phase_a_integrated_v1.py \
  tests/test_focused_loop_plan_authority_v1.py \
  tests/test_focused_loop_privacy_v1.py \
  tests/test_focused_loop_receipt_v1.py \
  tests/test_focused_loop_result_protocol_v1.py \
  tests/test_focused_loop_reuse_v1.py \
  tests/test_wi0441_public_build_allowlist_v1.py \
  tests/test_focused_loop_conference_real_aer_v1.py
```

The existing executor suite supplies the controlled timeout, cancel, unavailable-backend,
wrong-shot-total, runtime-deviation, and duplicate-attempt negatives. The integrated
Phase A suite remains explicitly fake-backed compatibility evidence; it is not relabeled
as real execution.

## Provisional package closure

The conference branch adds exactly two packages to the explicit source-package boundary:

- `qcoder.focused_loop`
- `qcoder.executors`

and adds exactly their 16 Python source files to both `MANIFEST.in` and
`packaging/public-package-allowlist-v1.json`.

That is a source-level package-closure prototype only. Do not treat it as installed-wheel
acceptance, merge/freeze/release authority, or permission for an external IQT
demonstration. Those dispositions remain separate.
