from __future__ import annotations


def _f(feature_map: dict[str, float], key: str) -> float:
    value = feature_map.get(key, 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def pressure_score(feature_map: dict[str, float]) -> int:
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

    score = 0
    if entangling_depth >= 20:
        score += 1
    if entangling_depth >= 80:
        score += 1
    if n_entangling_layers >= 10:
        score += 1
    if cut_max >= 8:
        score += 1
    if cut_max >= 32:
        score += 1
    if cut_mean >= 4:
        score += 1
    if cut_entropy >= 2:
        score += 1
    if n_active_cuts >= 8:
        score += 1
    if span_max >= 4 or span_avg >= 2:
        score += 1
    if span_long_range_ratio >= 0.25:
        score += 1
    if ig_edge_density >= 0.2:
        score += 1
    if ig_avg_degree >= 4:
        score += 1
    if ig_is_connected >= 1 and ig_edge_density >= 0.4:
        score += 1
    return score


def mps_pressure_band(score: int) -> str:
    if score <= 2:
        return "low"
    if score <= 5:
        return "medium"
    return "high"


def shot_complexity_score(feature_map: dict[str, float]) -> int:
    n_cbits = _f(feature_map, "n_cbits")
    real_depth = _f(feature_map, "real_depth")
    entangling_depth = _f(feature_map, "entangling_depth")
    n_2q_gate_ops = _f(feature_map, "n_2q_gate_ops")
    n_param_ops = _f(feature_map, "n_param_ops")

    score = 0
    if n_cbits >= 8:
        score += 1
    if real_depth >= 100:
        score += 1
    if entangling_depth >= 20:
        score += 1
    if n_2q_gate_ops >= 50:
        score += 1
    if n_param_ops > 0:
        score += 1
    return score


def statevector_scale_from_nq(n_qubits: float) -> str:
    if n_qubits <= 20:
        return "small"
    if n_qubits <= 30:
        return "moderate"
    return "large"


def shot_applicability(feature_map: dict[str, float]) -> str:
    n_measure_ops = _f(feature_map, "n_measure_ops")
    n_cbits = _f(feature_map, "n_cbits")
    if n_measure_ops <= 0 and n_cbits <= 0:
        return "not_applicable"
    return "applicable"
