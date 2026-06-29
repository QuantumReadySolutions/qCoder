from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from qcoder.engines.feature_extraction.features.glossary_v0 import (
    STRUCTURAL_SUMMARY_FEATURES,
    selected_feature_definitions,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _top_k(counts: dict[str, int], k: int = 5) -> list[dict[str, Any]]:
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"bitstring": b, "count": c} for b, c in ranked[:k]]


def _entropy_base2(counts: dict[str, int], shots_total: int) -> float:
    if shots_total <= 0:
        return 0.0
    acc = 0.0
    for c in counts.values():
        if c <= 0:
            continue
        p = c / shots_total
        acc -= p * math.log2(p)
    return acc


def _width_from_counts(counts: dict[str, int]) -> int | None:
    if not counts:
        return None
    widths = {len(k) for k in counts}
    if len(widths) == 1:
        return next(iter(widths))
    return None


def _widths_from_counts(counts: dict[str, int]) -> list[int]:
    return sorted({len(k) for k in counts})


def build_review_bundle(
    *,
    counts_format: str,
    counts_v0: dict[str, Any],
    preflight_context: dict[str, Any] | None = None,
    preflight_context_path: str | None = None,
    qcoder_version: str | None = None,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    counts = counts_v0.get("counts", {})
    observed_shots_total = int(sum(int(v) for v in counts.values()))
    declared_shots_total = int(counts_v0.get("shots_total") or 0)
    shots_total = observed_shots_total
    top_k = _top_k(counts, k=5)
    top_prob = (top_k[0]["count"] / shots_total) if top_k and shots_total > 0 else 0.0
    entropy = _entropy_base2(counts, shots_total)
    effective_support_size = (2.0 ** entropy) if entropy > 0 else 1.0
    if top_prob >= 0.8:
        concentration = "high"
    elif top_prob >= 0.4:
        concentration = "moderate"
    else:
        concentration = "low"

    checks: list[dict[str, str]] = []
    warnings: list[str] = []
    linkage: dict[str, Any] = {
        "qasm_sha256": None,
        "analysis_fingerprint": None,
        "preflight_context_bundle_schema_version": None,
    }
    preflight_excerpt: dict[str, Any] | None = None
    observed_widths = _widths_from_counts(counts)
    if len(observed_widths) == 1:
        checks.append(
            {
                "id": "bitstring_width_consistency",
                "status": "pass",
                "detail": f"Observed bitstring width is consistent at {observed_widths[0]}.",
            }
        )
    else:
        checks.append(
            {
                "id": "bitstring_width_consistency",
                "status": "fail",
                "detail": (
                    "Observed bitstring widths are inconsistent across keys: "
                    f"{observed_widths}. Derived metrics still use observed counts."
                ),
            }
        )
        warnings.append(
            "Observed bitstring widths are inconsistent across counts keys; "
            "interpret width-based comparisons with caution."
        )

    if declared_shots_total == observed_shots_total:
        checks.append(
            {
                "id": "shots_total_match",
                "status": "pass",
                "detail": (
                    f"Declared shots_total {declared_shots_total} matches observed sum(counts) "
                    f"{observed_shots_total}."
                ),
            }
        )
    else:
        checks.append(
            {
                "id": "shots_total_match",
                "status": "fail",
                "detail": (
                    f"Declared shots_total {declared_shots_total} does not match observed "
                    f"sum(counts) {observed_shots_total}. Derived probabilities use observed "
                    "sum(counts)."
                ),
            }
        )
        warnings.append("Declared shots_total differs from observed sum(counts); using observed total.")

    if preflight_context is not None:
        hashes = preflight_context.get("hashes", {})
        linkage["qasm_sha256"] = hashes.get("qasm_sha256")
        linkage["analysis_fingerprint"] = hashes.get("analysis_fingerprint")
        linkage["preflight_context_bundle_schema_version"] = preflight_context.get(
            "context_bundle_schema_version"
        )
        expected_width = preflight_context.get("circuit", {}).get("n_cbits")
        feature_map = preflight_context.get("analysis", {}).get("feature_map", {})
        feature_defs = preflight_context.get("analysis", {}).get("feature_definitions", {})
        if not feature_defs:
            feature_defs = selected_feature_definitions(STRUCTURAL_SUMMARY_FEATURES)
        selected_values = {k: feature_map.get(k) for k in STRUCTURAL_SUMMARY_FEATURES if k in feature_map}
        guidance = preflight_context.get("analysis", {}).get("guidance")
        guidance_summary = None
        if isinstance(guidance, dict):
            shot = guidance.get("shot_guidance", {})
            sim = guidance.get("simulation_guidance", {})
            mps = sim.get("mps_bond_dimension", {})
            guidance_summary = {
                "shot_applicability": shot.get("applicability"),
                "shot_starting_shots": shot.get("starting_shots"),
                "statevector_scale": sim.get("statevector", {}).get("scale"),
                "mps_pressure": mps.get("pressure"),
                "mps_starting_points": mps.get("starting_points"),
            }
        preflight_excerpt = {
            "circuit": {
                "n_qubits": preflight_context.get("circuit", {}).get("n_qubits"),
                "n_cbits": preflight_context.get("circuit", {}).get("n_cbits"),
                "n_ops": preflight_context.get("circuit", {}).get("n_ops"),
                "source_format": preflight_context.get("circuit", {}).get("source_format"),
            },
            "selected_feature_map": selected_values,
            "selected_feature_definitions": selected_feature_definitions(tuple(selected_values.keys()))
            if selected_values
            else feature_defs,
            "guidance_summary": guidance_summary,
        }
        observed_width = _width_from_counts(counts)
        if isinstance(expected_width, int) and expected_width >= 0 and observed_width is not None:
            if observed_width == expected_width:
                checks.append(
                    {
                        "id": "classical_width_match",
                        "status": "pass",
                        "detail": f"Observed bitstring width {observed_width} matches preflight n_cbits.",
                    }
                )
            else:
                checks.append(
                    {
                        "id": "classical_width_match",
                        "status": "fail",
                        "detail": (
                            f"Observed bitstring width {observed_width} does not match preflight "
                            f"n_cbits {expected_width}."
                        ),
                    }
                )
                warnings.append("Observed bitstring width differs from preflight n_cbits.")

    if concentration == "high":
        warnings.append("Highly concentrated outcome distribution detected.")

    return {
        "review_bundle_schema_version": "0.1",
        "artifact_type": "qcoder.execution_review",
        "qcoder_product_path": "oss",
        "artifact_role": "local_execution_review",
        "qcoder_version": qcoder_version,
        "basis": "deterministic_counts_review",
        "generated_utc": generated_utc or utc_now_iso(),
        "inputs": {
            "counts_format": counts_format,
            "counts": counts_v0,
            "preflight_context_path": preflight_context_path,
        },
        "linkage": linkage,
        "preflight_excerpt": preflight_excerpt,
        "derived": {
            "total_shots": shots_total,
            "declared_shots_total": declared_shots_total,
            "shots_total_basis": "sum_counts_observed",
            "n_observed_bitstrings": len(counts),
            "top_k": top_k,
            "top_bitstring_probability": top_prob,
            "entropy": entropy,
            "effective_support_size": effective_support_size,
            "concentration": concentration,
        },
        "checks": checks,
        "warnings": warnings,
        "assumptions": [
            "Counts were provided by the user.",
            "qCoder did not execute the circuit.",
            "Review is observational and deterministic.",
        ],
        "llm_use": {
            "intended_use": "Attach or paste this artifact for AI-assisted post-run review.",
            "limits": [
                "Do not interpret this artifact as hardware-verification proof.",
                "No backend execution or telemetry was performed by qCoder.",
            ],
        },
    }
