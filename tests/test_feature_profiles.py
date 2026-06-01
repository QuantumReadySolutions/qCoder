from __future__ import annotations

import unittest

from qcoder.engines.guidance.resource import build_resource_guidance
from qcoder.engines.profiles.feature_profiles_v0 import build_feature_profiles


class TestFeatureProfiles(unittest.TestCase):
    def _sample_feature_map(self) -> dict[str, float]:
        return {
            "n_qubits": 18.0,
            "n_cbits": 12.0,
            "n_ops": 220.0,
            "n_gate_ops": 180.0,
            "n_measure_ops": 12.0,
            "n_2q_gate_ops": 64.0,
            "n_3p_gate_ops": 2.0,
            "n_param_ops": 4.0,
            "real_depth": 160.0,
            "entangling_depth": 48.0,
            "n_entangling_layers": 20.0,
            "avg_2q_per_entangling_layer": 2.2,
            "max_2q_per_entangling_layer": 5.0,
            "ig_n_edges": 60.0,
            "ig_edge_density": 0.42,
            "ig_is_connected": 1.0,
            "ig_n_components": 1.0,
            "ig_largest_cc_frac": 1.0,
            "ig_max_degree": 7.0,
            "ig_avg_degree": 4.5,
            "span_avg": 2.4,
            "span_max": 7.0,
            "span_std": 1.5,
            "span_nearest_neighbor_ratio": 0.4,
            "span_long_range_ratio": 0.35,
            "span_long_range_ratio_early": 0.30,
            "span_long_range_ratio_late": 0.40,
            "span_avg_early": 2.2,
            "span_avg_late": 2.6,
            "cut_max": 40.0,
            "cut_mean": 8.0,
            "cut_entropy": 2.4,
            "n_active_cuts": 14.0,
        }

    def test_schema_shape_and_profile_keys(self) -> None:
        out = build_feature_profiles(self._sample_feature_map(), feature_schema_version="0.4.0")
        self.assertEqual(out["feature_profiles_schema_version"], "0.1")
        self.assertEqual(out["basis"], "deterministic_formula_from_feature_map")
        self.assertTrue(out["not_guarantees"])
        self.assertEqual(out["inputs"]["feature_schema_version"], "0.4.0")
        profiles = out["profiles"]
        self.assertEqual(
            set(profiles.keys()),
            {
                "size_profile",
                "sampling_profile",
                "entanglement_profile",
                "topology_profile",
                "locality_profile",
                "simulation_pressure_profile",
                "llm_summary_profile",
            },
        )

    def test_deterministic_output(self) -> None:
        feature_map = self._sample_feature_map()
        a = build_feature_profiles(feature_map, feature_schema_version="0.4.0")
        b = build_feature_profiles(feature_map, feature_schema_version="0.4.0")
        self.assertEqual(a, b)

    def test_goldenish_profile_values(self) -> None:
        out = build_feature_profiles(self._sample_feature_map(), feature_schema_version="0.4.0")
        profiles = out["profiles"]
        self.assertEqual(profiles["size_profile"]["tiers"]["statevector_scale"], "small")
        self.assertEqual(profiles["sampling_profile"]["tiers"]["shot_readiness"], "applicable")
        self.assertEqual(profiles["locality_profile"]["tiers"]["long_range"], "long_range_heavy")
        self.assertEqual(profiles["topology_profile"]["tiers"]["connectivity"], "connected_high_density")
        self.assertIn(
            "simulation_pressure_profile:",
            profiles["llm_summary_profile"]["lines"][-1],
        )

    def test_topology_connected_small_graph_for_tiny_dense_circuits(self) -> None:
        fm = {
            "n_qubits": 2.0,
            "ig_is_connected": 1.0,
            "ig_edge_density": 1.0,
            "ig_n_components": 1.0,
        }
        out = build_feature_profiles(fm, feature_schema_version="0.4.0")
        self.assertEqual(
            out["profiles"]["topology_profile"]["tiers"]["connectivity"],
            "connected_small_graph",
        )

    def test_topology_connected_small_graph_boundary_three_qubits(self) -> None:
        fm = {
            "n_qubits": 3.0,
            "ig_is_connected": 1.0,
            "ig_edge_density": 0.5,
            "ig_n_components": 1.0,
        }
        out = build_feature_profiles(fm, feature_schema_version="0.4.0")
        self.assertEqual(
            out["profiles"]["topology_profile"]["tiers"]["connectivity"],
            "connected_small_graph",
        )

    def test_topology_connected_high_density_when_four_plus_qubits(self) -> None:
        fm = {
            "n_qubits": 4.0,
            "ig_is_connected": 1.0,
            "ig_edge_density": 0.5,
            "ig_n_components": 1.0,
        }
        out = build_feature_profiles(fm, feature_schema_version="0.4.0")
        self.assertEqual(
            out["profiles"]["topology_profile"]["tiers"]["connectivity"],
            "connected_high_density",
        )

    def test_simulation_pressure_aligns_with_guidance(self) -> None:
        feature_map = self._sample_feature_map()
        profiles = build_feature_profiles(feature_map, feature_schema_version="0.4.0")
        guidance = build_resource_guidance(feature_map, feature_schema_version="0.4.0")
        self.assertEqual(
            profiles["profiles"]["simulation_pressure_profile"]["tiers"]["mps_pressure"],
            guidance["simulation_guidance"]["mps_bond_dimension"]["pressure"],
        )


if __name__ == "__main__":
    unittest.main()
