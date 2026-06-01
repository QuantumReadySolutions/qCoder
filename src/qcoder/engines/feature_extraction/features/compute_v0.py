from __future__ import annotations

from dataclasses import dataclass

from ..ir import CircuitIR
from ..reps.cut_profile import compute_cut_profile_stats
from ..reps.depth import compute_depth_stats
from ..reps.entangling_layers import compute_entangling_layer_stats
from ..reps.gate_set_stats import compute_gate_set_stats
from ..reps.interaction_graph import build_interaction_graph
from ..reps.interaction_graph_metrics import compute_interaction_graph_metrics
from ..reps.spans import compute_span_stats
from .schema_v0 import SCHEMA_V0


@dataclass(frozen=True)
class FeatureVector:
    schema_version: str
    feature_names: tuple[str, ...]
    features: tuple[float, ...]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "feature_names": list(self.feature_names),
            "features": list(self.features),
        }


def compute_features_v0(ir: CircuitIR) -> FeatureVector:
    n_measure = 0
    n_barrier = 0
    n_reset = 0
    n_gate = 0
    n_1q = 0
    n_2q = 0
    n_3p = 0
    n_param = 0
    n_custom = 0

    for op in ir.operations:
        if op.is_measure:
            n_measure += 1
            continue
        if op.is_barrier:
            n_barrier += 1
            continue
        if op.is_reset:
            n_reset += 1
            continue

        if not op.qubits:
            continue

        n_gate += 1
        if op.is_custom:
            n_custom += 1
        if op.params:
            n_param += 1

        ar = len(op.qubits)
        if ar == 1:
            n_1q += 1
        elif ar == 2:
            n_2q += 1
        else:
            n_3p += 1

    depth = compute_depth_stats(ir)
    ig = build_interaction_graph(ir)
    spans = compute_span_stats(ir)
    cuts = compute_cut_profile_stats(ig)
    gate_stats = compute_gate_set_stats(ir)
    ig_metrics = compute_interaction_graph_metrics(ig)
    ent_layers = compute_entangling_layer_stats(ir)

    n_edges = float(len(ig.edges))
    denom = (ir.n_qubits * (ir.n_qubits - 1) / 2.0) if ir.n_qubits >= 2 else 1.0
    edge_density = float(n_edges / denom) if denom > 0 else 0.0

    values = {
        "n_qubits": float(ir.n_qubits),
        "n_cbits": float(ir.n_cbits),
        "n_ops": float(ir.n_ops),

        "n_gate_ops": float(n_gate),
        "n_1q_gate_ops": float(n_1q),
        "n_2q_gate_ops": float(n_2q),
        "n_3p_gate_ops": float(n_3p),
        "n_param_ops": float(n_param),
        "n_custom_ops": float(n_custom),

        "n_measure_ops": float(n_measure),
        "n_barrier_ops": float(n_barrier),
        "n_reset_ops": float(n_reset),

        "estimated_depth": float(depth.estimated_depth),
        "real_depth": float(depth.real_depth),
        "avg_parallel_gates": float(depth.avg_parallel_gates),
        "parallelism_factor": float(depth.parallelism_factor),

        "ig_n_edges": float(n_edges),
        "ig_edge_density": float(edge_density),

        "span_avg": float(spans.avg_span),
        "span_max": float(spans.max_span),
        "span_std": float(spans.span_std),
        "span_nearest_neighbor_ratio": float(spans.nearest_neighbor_ratio),
        "span_long_range_ratio": float(spans.long_range_ratio),
        "span_long_range_ratio_early": float(spans.long_range_ratio_early),
        "span_long_range_ratio_late": float(spans.long_range_ratio_late),
        "span_avg_early": float(spans.avg_span_early),
        "span_avg_late": float(spans.avg_span_late),

        # Phase 2: cut profile (natural qubit order only)
        "cut_max": float(cuts.cut_max),
        "cut_mean": float(cuts.cut_mean),
        "cut_std": float(cuts.cut_std),
        "cut_entropy": float(cuts.cut_entropy),
        "n_active_cuts": float(cuts.n_active_cuts),
        "max_span_in_order": float(cuts.max_span_in_order),

        # Quantumness v1: gate set + angles + basis/diagonal
        "n_basis_change_ops": float(gate_stats.n_basis_change_ops),
        "basis_change_qubit_coverage": float(gate_stats.basis_change_qubit_coverage),
        "n_diagonal_gate_ops": float(gate_stats.n_diagonal_gate_ops),
        "diagonal_gate_fraction": float(gate_stats.diagonal_gate_fraction),
        "n_t_like_ops": float(gate_stats.n_t_like_ops),
        "n_distinct_angles": float(gate_stats.n_distinct_angles),
        "angle_genericity_ratio": float(gate_stats.angle_genericity_ratio),
        "is_certified_diagonal_only": float(gate_stats.is_certified_diagonal_only),

        # Quantumness v1: IG degree/connectivity metrics (unweighted)
        "ig_max_degree": float(ig_metrics.ig_max_degree),
        "ig_avg_degree": float(ig_metrics.ig_avg_degree),
        "ig_degree_std": float(ig_metrics.ig_degree_std),
        "ig_degree_entropy": float(ig_metrics.ig_degree_entropy),
        "ig_n_components": float(ig_metrics.ig_n_components),
        "ig_largest_cc_frac": float(ig_metrics.ig_largest_cc_frac),
        "ig_is_connected": float(ig_metrics.ig_is_connected),
        "ig_pair_reuse_hhi": float(ig_metrics.ig_pair_reuse_hhi),
        "ig_pair_reuse_top1_frac": float(ig_metrics.ig_pair_reuse_top1_frac),

        # Quantumness v1: entangling depth/layers
        "entangling_depth": float(ent_layers.entangling_depth),
        "n_entangling_layers": float(ent_layers.n_entangling_layers),
        "avg_2q_per_entangling_layer": float(ent_layers.avg_2q_per_entangling_layer),
        "max_2q_per_entangling_layer": float(ent_layers.max_2q_per_entangling_layer),
    }

    feats = tuple(float(values.get(name, 0.0)) for name in SCHEMA_V0.feature_names)

    return FeatureVector(
        schema_version=SCHEMA_V0.version,
        feature_names=SCHEMA_V0.feature_names,
        features=feats,
    )
