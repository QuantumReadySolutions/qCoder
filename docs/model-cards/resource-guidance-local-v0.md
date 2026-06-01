# Model card — `resource_guidance_local_v0` (shadow / metadata only)

**Status:** Packaged as **candidate** JSON (`0.1.0-candidate`) in the public `qcoder` wheel under `qcoder.model_packs`. **Shadow mode only:** qCoder **does not** apply pack suggestions to `simulation_guidance.mps_bond_dimension.pressure` or `starting_points` in this release slice. Deterministic structural heuristics remain the user-visible source of truth.

## Data scope

- **Synthetic / public / qCoder-owned generated variants** only (as declared in the pack `training_data` block).
- **No** real user telemetry, **no** Pro/private workflow exports, **no** unaudited archive dumps.

## Runtime posture

- **Local** package data only (`importlib.resources`); **no** network calls, **no** hosted inference, **no** telemetry upload from this path.
- **No** runtime ML dependency (plain JSON; stdlib load and validate).

## Non-claims (machine-readable keys also appear in the pack JSON)

This pack and any shadow suggestions are **not**:

- an optimality proof (`not_optimality_proof`);
- a fidelity proof (`not_fidelity_proof`);
- hardware correctness proof (`not_hardware_correctness_proof`);
- a runtime guarantee (`not_runtime_guarantee`);
- backend ranking or universal QPU quality scoring (`not_backend_ranking`);
- causal savings or cost optimality (`not_causal_savings`).

## Behavior in qCoder today

- **Deterministic fallback preserved:** `build_resource_guidance` continues to set `pressure` and `starting_points` from structural scores only.
- **`guidance_metadata`:** additive block on the guidance dict documenting pack id/version/hash, `fallback_used`, and `shadow_guidance` with `applied: false` until a future evaluated release explicitly enables application.

## Promotion (future)

Public promotion requires evaluation gates, reproducible labels, and explicit product/API review before any **non-shadow** application of pack outputs.
