from __future__ import annotations

from typing import Any

from . import model_pack as _resource_model_pack
from .structural_scores import (
    mps_pressure_band,
    pressure_score,
    shot_applicability,
    shot_complexity_score,
    statevector_scale_from_nq,
)


def _f(feature_map: dict[str, float], key: str) -> float:
    value = feature_map.get(key, 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _build_guidance_metadata(
    feature_map: dict[str, float],
    *,
    feature_schema_version: str,
) -> dict[str, Any]:
    """Shadow-mode pack metadata; does not alter deterministic pressure or starting_points."""
    pack = _resource_model_pack.load_resource_guidance_pack()
    caveats_common = [
        "shadow_mode_deterministic_guidance_preserved",
        "suggested_values_not_applied_to_pressure_or_starting_points",
        "not_optimality_proof",
        "not_fidelity_proof",
        "not_hardware_correctness_proof",
        "not_runtime_guarantee",
        "not_backend_ranking",
        "not_causal_savings",
    ]
    if pack is None:
        return {
            "guidance_method": "auto",
            "guidance_sources": ["deterministic_heuristics"],
            "model_pack": None,
            "fallback_used": True,
            "model_caveats": caveats_common
            + [
                "local_guidance_pack_missing_or_invalid",
                "deterministic_structural_guidance_only",
            ],
            "calibration_scope": "deterministic_structural_heuristics_only",
            "shadow_guidance": {
                "matched_rule_id": None,
                "suggested_mps_pressure": None,
                "suggested_mps_ladder": None,
                "applied": False,
                "reason": "shadow_mode_pack_missing_or_invalid",
            },
        }

    shadow = _resource_model_pack.evaluate_resource_guidance_pack_shadow(
        feature_map,
        pack,
        feature_schema_version=feature_schema_version,
    )
    td = pack.data.get("training_data", {})
    cal_scope = "deterministic_structural_heuristics_only"
    if isinstance(td, dict) and td.get("curriculum_id"):
        cal_scope = f"synthetic_public_candidate:{td.get('curriculum_id')}"

    meta: dict[str, Any] = {
        "guidance_method": "auto",
        "guidance_sources": ["deterministic_heuristics", "local_guidance_pack_shadow"],
        "model_pack": {
            "id": pack.model_pack_id,
            "version": pack.model_pack_version,
            "sha256": pack.sha256_hex,
            "status": "shadow",
        },
        "fallback_used": True,
        "model_caveats": caveats_common,
        "calibration_scope": cal_scope,
        "shadow_guidance": {
            "matched_rule_id": shadow.get("matched_rule_id"),
            "suggested_mps_pressure": shadow.get("suggested_mps_pressure"),
            "suggested_mps_ladder": shadow.get("suggested_mps_ladder"),
            "applied": False,
            "reason": "shadow_mode_deterministic_guidance_preserved",
        },
    }
    if shadow.get("no_match_reason"):
        meta["shadow_guidance"]["no_match_reason"] = shadow["no_match_reason"]
    if shadow.get("suggested_starting_points") is not None:
        meta["shadow_guidance"]["suggested_starting_points"] = shadow["suggested_starting_points"]
    return meta


def build_resource_guidance(
    feature_map: dict[str, float],
    *,
    feature_schema_version: str,
) -> dict:
    n_qubits = _f(feature_map, "n_qubits")
    n_cbits = _f(feature_map, "n_cbits")
    n_measure_ops = _f(feature_map, "n_measure_ops")
    n_2q_gate_ops = _f(feature_map, "n_2q_gate_ops")
    n_param_ops = _f(feature_map, "n_param_ops")
    real_depth = _f(feature_map, "real_depth")
    entangling_depth = _f(feature_map, "entangling_depth")
    n_entangling_layers = _f(feature_map, "n_entangling_layers")
    cut_max = _f(feature_map, "cut_max")
    cut_mean = _f(feature_map, "cut_mean")
    cut_entropy = _f(feature_map, "cut_entropy")
    n_active_cuts = _f(feature_map, "n_active_cuts")
    span_avg = _f(feature_map, "span_avg")
    span_max = _f(feature_map, "span_max")
    span_long_range_ratio = _f(feature_map, "span_long_range_ratio")
    ig_edge_density = _f(feature_map, "ig_edge_density")
    ig_avg_degree = _f(feature_map, "ig_avg_degree")
    ig_is_connected = _f(feature_map, "ig_is_connected")

    shot_rationale: list[str] = []
    shot_warnings: list[str] = []
    shot_used = {
        "n_measure_ops": n_measure_ops,
        "n_cbits": n_cbits,
        "n_qubits": n_qubits,
        "real_depth": real_depth,
        "n_2q_gate_ops": n_2q_gate_ops,
        "n_param_ops": n_param_ops,
        "entangling_depth": entangling_depth,
    }
    if shot_applicability(feature_map) == "not_applicable":
        shot_guidance = {
            "applicability": "not_applicable",
            "starting_shots": [],
            "confidence": "low",
            "rationale": [
                "No measurement operations or classical bits were detected.",
                "Shot-count guidance is only applicable to sampled measurement workflows.",
            ],
            "warnings": [
                "No backend execution was performed.",
                "Guidance is not a guarantee of confidence or error bounds.",
            ],
        }
    else:
        complexity_score = shot_complexity_score(feature_map)
        if n_cbits >= 8:
            shot_rationale.append("Classical output width is moderate or larger (n_cbits >= 8).")
        if real_depth >= 100:
            shot_rationale.append("Circuit depth is moderate or larger (real_depth >= 100).")
        if entangling_depth >= 20:
            shot_rationale.append("Entangling depth suggests nontrivial correlations may exist.")
        if n_2q_gate_ops >= 50:
            shot_rationale.append("Two-qubit gate volume is moderate or larger (n_2q_gate_ops >= 50).")
        if n_param_ops > 0:
            shot_rationale.append("Parameterized gates detected; exploratory sweeps are common.")

        starting_shots = [1024, 4096]
        if complexity_score >= 2 or n_cbits >= 8:
            if 8192 not in starting_shots:
                starting_shots.append(8192)
        if n_cbits >= 16 or real_depth >= 500 or entangling_depth >= 100:
            starting_shots.append(16384)
            shot_rationale.append("Large exploratory structure detected; include a higher-shot starting point.")

        shot_warnings.extend(
            [
                "No backend execution was performed.",
                "Starting shots depend on structure only, not observable variance.",
                "Use problem-specific confidence and error targets to tune shots.",
            ]
        )

        if not shot_rationale:
            shot_rationale.append("Measured circuit with modest structure; begin with conservative shot counts.")

        shot_guidance = {
            "applicability": "applicable",
            "starting_shots": starting_shots,
            "confidence": "medium",
            "rationale": shot_rationale,
            "warnings": shot_warnings,
        }

    sim_rationale: list[str] = []
    mps_rationale: list[str] = []
    mps_warnings = [
        "No simulator/backend execution was performed.",
        "Bond-dimension starting points depend on simulator implementation and qubit ordering.",
    ]

    statevector_scale = statevector_scale_from_nq(n_qubits)
    sim_rationale.append(f"Statevector scale based primarily on n_qubits={int(n_qubits)}.")

    mps_pressure_score = pressure_score(feature_map)
    if entangling_depth >= 20:
        mps_rationale.append("entangling_depth >= 20")
    if entangling_depth >= 80:
        mps_rationale.append("entangling_depth >= 80")
    if n_entangling_layers >= 10:
        mps_rationale.append("n_entangling_layers >= 10")
    if cut_max >= 8:
        mps_rationale.append("cut_max >= 8")
    if cut_max >= 32:
        mps_rationale.append("cut_max >= 32")
    if cut_mean >= 4:
        mps_rationale.append("cut_mean >= 4")
    if cut_entropy >= 2:
        mps_rationale.append("cut_entropy >= 2")
    if n_active_cuts >= 8:
        mps_rationale.append("n_active_cuts >= 8")
    if span_max >= 4 or span_avg >= 2:
        mps_rationale.append("span stats indicate non-local interactions")
    if span_long_range_ratio >= 0.25:
        mps_rationale.append("span_long_range_ratio >= 0.25")
    if ig_edge_density >= 0.2:
        mps_rationale.append("ig_edge_density >= 0.2")
    if ig_avg_degree >= 4:
        mps_rationale.append("ig_avg_degree >= 4")
    connected_graph_high_density = ig_is_connected >= 1 and ig_edge_density >= 0.4
    pressure = mps_pressure_band(mps_pressure_score)
    if pressure == "low":
        starting_points = [16, 32]
    elif pressure == "medium":
        starting_points = [32, 64, 128]
    else:
        starting_points = [64, 128, 256]

    if connected_graph_high_density:
        if pressure in ("medium", "high") and n_qubits >= 16:
            mps_rationale.append(
                "interaction graph is connected with relatively high edge density among qubits "
                "(structural proxy only)"
            )
        else:
            mps_rationale.append("interaction graph is connected")
    if pressure == "low" and n_qubits <= 8:
        mps_rationale.append("small circuit with limited entangling structure")
        mps_rationale.append("low estimated MPS pressure from structural features")

    if not mps_rationale:
        mps_rationale.append("No strong MPS pressure indicators were detected from structural features.")

    used_features = {
        **shot_used,
        "n_entangling_layers": n_entangling_layers,
        "cut_max": cut_max,
        "cut_mean": cut_mean,
        "cut_entropy": cut_entropy,
        "n_active_cuts": n_active_cuts,
        "span_avg": span_avg,
        "span_max": span_max,
        "span_long_range_ratio": span_long_range_ratio,
        "ig_edge_density": ig_edge_density,
        "ig_avg_degree": ig_avg_degree,
        "ig_is_connected": ig_is_connected,
    }

    return {
        "guidance_schema_version": "0.1",
        "basis": "deterministic_heuristics_from_feature_map",
        "not_guarantees": True,
        "assumptions": [
            "No backend execution was performed.",
            "Guidance is based only on structural circuit features.",
            "Recommendations are starting points, not optimal settings.",
        ],
        "inputs": {
            "feature_schema_version": feature_schema_version,
            "used_features": used_features,
        },
        "shot_guidance": shot_guidance,
        "simulation_guidance": {
            "statevector": {
                "scale": statevector_scale,
                "rationale": sim_rationale,
            },
            "mps_bond_dimension": {
                "pressure": pressure,
                "starting_points": starting_points,
                "rationale": mps_rationale,
                "warnings": mps_warnings,
            },
        },
        "guidance_metadata": _build_guidance_metadata(
            feature_map,
            feature_schema_version=feature_schema_version,
        ),
    }

