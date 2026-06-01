from __future__ import annotations

from qcoder.engines.guidance.structural_scores import (
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


def _size_profile(feature_map: dict[str, float]) -> dict:
    n_qubits = _f(feature_map, "n_qubits")
    n_cbits = _f(feature_map, "n_cbits")
    n_ops = _f(feature_map, "n_ops")
    n_gate_ops = _f(feature_map, "n_gate_ops")
    real_depth = _f(feature_map, "real_depth")

    gate_volume = "low" if n_gate_ops < 200 else ("moderate" if n_gate_ops < 2000 else "high")
    depth_band = "shallow" if real_depth < 50 else ("moderate" if real_depth < 250 else "deep")
    width_band = statevector_scale_from_nq(n_qubits)

    labels = [
        f"statevector_scale:{width_band}",
        f"gate_volume:{gate_volume}",
        f"depth:{depth_band}",
        "classical:present" if n_cbits > 0 else "classical:none",
    ]
    return {
        "labels": labels,
        "tiers": {
            "statevector_scale": width_band,
            "gate_volume": gate_volume,
            "depth_band": depth_band,
        },
        "signals": {
            "n_qubits": n_qubits,
            "n_cbits": n_cbits,
            "n_ops": n_ops,
            "n_gate_ops": n_gate_ops,
            "real_depth": real_depth,
        },
    }


def _sampling_profile(feature_map: dict[str, float]) -> dict:
    n_measure_ops = _f(feature_map, "n_measure_ops")
    n_cbits = _f(feature_map, "n_cbits")
    n_qubits = _f(feature_map, "n_qubits")
    score = shot_complexity_score(feature_map)
    applicability = shot_applicability(feature_map)
    if score <= 1:
        structure_load = "light"
    elif score <= 3:
        structure_load = "moderate"
    else:
        structure_load = "heavy"

    labels = [
        f"shot_applicability:{applicability}",
        f"structure_load:{structure_load}",
        "measurement:present" if n_measure_ops > 0 else "measurement:none",
    ]
    return {
        "labels": labels,
        "tiers": {
            "shot_readiness": applicability,
            "structure_load": structure_load,
            "shot_complexity_score": score,
        },
        "signals": {
            "n_measure_ops": n_measure_ops,
            "n_cbits": n_cbits,
            "n_qubits": n_qubits,
        },
    }


def _entanglement_profile(feature_map: dict[str, float]) -> dict:
    n_2q_gate_ops = _f(feature_map, "n_2q_gate_ops")
    entangling_depth = _f(feature_map, "entangling_depth")
    n_entangling_layers = _f(feature_map, "n_entangling_layers")
    avg_2q_per_entangling_layer = _f(feature_map, "avg_2q_per_entangling_layer")
    max_2q_per_entangling_layer = _f(feature_map, "max_2q_per_entangling_layer")
    n_3p_gate_ops = _f(feature_map, "n_3p_gate_ops")

    depth_tier = 0 if entangling_depth < 5 else (1 if entangling_depth < 20 else 2)
    volume_tier = 0 if n_2q_gate_ops < 10 else (1 if n_2q_gate_ops < 50 else 2)
    intensity_score = max(depth_tier, volume_tier)
    intensity = ("low", "moderate", "high")[intensity_score]

    labels = [
        f"intensity:{intensity}",
        "multi_qubit:present" if n_3p_gate_ops > 0 else "multi_qubit:none",
    ]
    return {
        "labels": labels,
        "tiers": {"intensity": intensity},
        "signals": {
            "n_2q_gate_ops": n_2q_gate_ops,
            "entangling_depth": entangling_depth,
            "n_entangling_layers": n_entangling_layers,
            "avg_2q_per_entangling_layer": avg_2q_per_entangling_layer,
            "max_2q_per_entangling_layer": max_2q_per_entangling_layer,
            "n_3p_gate_ops": n_3p_gate_ops,
        },
    }


def _topology_profile(feature_map: dict[str, float]) -> dict:
    n_qubits = _f(feature_map, "n_qubits")
    ig_n_edges = _f(feature_map, "ig_n_edges")
    ig_edge_density = _f(feature_map, "ig_edge_density")
    ig_is_connected = _f(feature_map, "ig_is_connected")
    ig_n_components = _f(feature_map, "ig_n_components")
    ig_largest_cc_frac = _f(feature_map, "ig_largest_cc_frac")
    ig_max_degree = _f(feature_map, "ig_max_degree")
    ig_avg_degree = _f(feature_map, "ig_avg_degree")

    connected = ig_is_connected >= 1.0
    high_density = ig_edge_density >= 0.4
    if connected and high_density:
        # Tiny interaction graphs hit high edge density by construction; reserve
        # "high density" wording for larger qubit counts where it is informative.
        if n_qubits <= 3.0:
            connectivity = "connected_small_graph"
        else:
            connectivity = "connected_high_density"
    elif connected:
        connectivity = "connected"
    else:
        connectivity = "disconnected"
    labels = [
        f"connectivity:{connectivity}",
        "components:single" if ig_n_components <= 1 else "components:multi",
    ]
    return {
        "labels": labels,
        "tiers": {"connectivity": connectivity},
        "signals": {
            "ig_n_edges": ig_n_edges,
            "ig_edge_density": ig_edge_density,
            "ig_is_connected": ig_is_connected,
            "ig_n_components": ig_n_components,
            "ig_largest_cc_frac": ig_largest_cc_frac,
            "ig_max_degree": ig_max_degree,
            "ig_avg_degree": ig_avg_degree,
        },
    }


def _locality_profile(feature_map: dict[str, float]) -> dict:
    span_avg = _f(feature_map, "span_avg")
    span_max = _f(feature_map, "span_max")
    span_std = _f(feature_map, "span_std")
    span_nearest_neighbor_ratio = _f(feature_map, "span_nearest_neighbor_ratio")
    span_long_range_ratio = _f(feature_map, "span_long_range_ratio")
    span_long_range_ratio_early = _f(feature_map, "span_long_range_ratio_early")
    span_long_range_ratio_late = _f(feature_map, "span_long_range_ratio_late")
    span_avg_early = _f(feature_map, "span_avg_early")
    span_avg_late = _f(feature_map, "span_avg_late")

    if span_long_range_ratio < 0.1:
        long_range_band = "mostly_local"
    elif span_long_range_ratio < 0.25:
        long_range_band = "mixed"
    else:
        long_range_band = "long_range_heavy"

    labels = [
        f"locality:{long_range_band}",
        "nn_dominant" if span_nearest_neighbor_ratio >= 0.75 else "nn_not_dominant",
    ]
    return {
        "labels": labels,
        "tiers": {"long_range": long_range_band},
        "signals": {
            "span_avg": span_avg,
            "span_max": span_max,
            "span_std": span_std,
            "span_nearest_neighbor_ratio": span_nearest_neighbor_ratio,
            "span_long_range_ratio": span_long_range_ratio,
            "span_long_range_ratio_early": span_long_range_ratio_early,
            "span_long_range_ratio_late": span_long_range_ratio_late,
            "span_avg_early": span_avg_early,
            "span_avg_late": span_avg_late,
        },
    }


def _simulation_pressure_profile(feature_map: dict[str, float]) -> dict:
    n_qubits = _f(feature_map, "n_qubits")
    score = pressure_score(feature_map)
    mps_pressure = mps_pressure_band(score)
    labels = [
        f"mps_pressure:{mps_pressure}",
        f"statevector_scale:{statevector_scale_from_nq(n_qubits)}",
    ]
    return {
        "labels": labels,
        "tiers": {
            "mps_pressure": mps_pressure,
            "pressure_score": score,
        },
        "signals": {
            "n_qubits": n_qubits,
            "entangling_depth": _f(feature_map, "entangling_depth"),
            "n_entangling_layers": _f(feature_map, "n_entangling_layers"),
            "cut_max": _f(feature_map, "cut_max"),
            "cut_mean": _f(feature_map, "cut_mean"),
            "cut_entropy": _f(feature_map, "cut_entropy"),
            "n_active_cuts": _f(feature_map, "n_active_cuts"),
            "span_avg": _f(feature_map, "span_avg"),
            "span_max": _f(feature_map, "span_max"),
            "span_long_range_ratio": _f(feature_map, "span_long_range_ratio"),
            "ig_edge_density": _f(feature_map, "ig_edge_density"),
            "ig_avg_degree": _f(feature_map, "ig_avg_degree"),
            "ig_is_connected": _f(feature_map, "ig_is_connected"),
        },
    }


def _llm_summary_profile(profiles: dict[str, dict]) -> dict:
    order = [
        "size_profile",
        "sampling_profile",
        "entanglement_profile",
        "topology_profile",
        "locality_profile",
        "simulation_pressure_profile",
    ]
    lines: list[str] = []
    labels: list[str] = []
    for key in order:
        tiers = profiles.get(key, {}).get("tiers", {})
        tier_keys = sorted(tiers.keys())
        tier_repr = "; ".join(f"{k}={tiers[k]}" for k in tier_keys)
        lines.append(f"{key}: {tier_repr}")
        labels.extend(profiles.get(key, {}).get("labels", []))
    return {
        "labels": labels,
        "lines": lines,
    }


def build_feature_profiles(feature_map: dict[str, float], *, feature_schema_version: str) -> dict:
    profiles = {
        "size_profile": _size_profile(feature_map),
        "sampling_profile": _sampling_profile(feature_map),
        "entanglement_profile": _entanglement_profile(feature_map),
        "topology_profile": _topology_profile(feature_map),
        "locality_profile": _locality_profile(feature_map),
        "simulation_pressure_profile": _simulation_pressure_profile(feature_map),
    }
    profiles["llm_summary_profile"] = _llm_summary_profile(profiles)
    return {
        "feature_profiles_schema_version": "0.1",
        "basis": "deterministic_formula_from_feature_map",
        "not_guarantees": True,
        "inputs": {
            "feature_schema_version": feature_schema_version,
        },
        "profiles": profiles,
    }
