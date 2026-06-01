from __future__ import annotations

import unittest
from unittest import mock

from qcoder.engines.guidance.resource import build_resource_guidance


class TestResourceGuidance(unittest.TestCase):
    def test_no_measurement_not_applicable_for_shots(self) -> None:
        fm = {
            "n_qubits": 8.0,
            "n_cbits": 0.0,
            "n_measure_ops": 0.0,
            "real_depth": 40.0,
            "n_2q_gate_ops": 20.0,
        }
        g = build_resource_guidance(fm, feature_schema_version="0.4.0")
        self.assertEqual(g["shot_guidance"]["applicability"], "not_applicable")
        self.assertEqual(g["shot_guidance"]["starting_shots"], [])

    def test_small_measured_circuit_shots(self) -> None:
        fm = {
            "n_qubits": 4.0,
            "n_cbits": 4.0,
            "n_measure_ops": 4.0,
            "real_depth": 10.0,
            "entangling_depth": 2.0,
            "n_2q_gate_ops": 2.0,
            "n_param_ops": 0.0,
        }
        g = build_resource_guidance(fm, feature_schema_version="0.4.0")
        self.assertEqual(g["shot_guidance"]["applicability"], "applicable")
        self.assertEqual(g["shot_guidance"]["starting_shots"], [1024, 4096])

    def test_ghz8_style_n_cbits_includes_8192(self) -> None:
        """n_cbits >= 8 triggers moderate classical width rationale; include 8192 in starting shots."""
        fm = {
            "n_qubits": 8.0,
            "n_cbits": 8.0,
            "n_measure_ops": 8.0,
            "real_depth": 24.0,
            "entangling_depth": 7.0,
            "n_2q_gate_ops": 7.0,
            "n_param_ops": 0.0,
        }
        g = build_resource_guidance(fm, feature_schema_version="0.4.0")
        self.assertEqual(g["shot_guidance"]["applicability"], "applicable")
        shots = g["shot_guidance"]["starting_shots"]
        self.assertIn(8192, shots)
        self.assertEqual(shots[:2], [1024, 4096])
        rationale = "\n".join(g["shot_guidance"]["rationale"])
        self.assertIn("n_cbits >= 8", rationale)

    def test_small_low_pressure_no_dense_graph_wording(self) -> None:
        """Tiny measured circuit: avoid alarming 'dense' graph phrasing under low pressure."""
        fm = {
            "n_qubits": 2.0,
            "n_cbits": 2.0,
            "n_measure_ops": 2.0,
            "real_depth": 2.0,
            "entangling_depth": 1.0,
            "n_entangling_layers": 1.0,
            "cut_max": 1.0,
            "cut_mean": 1.0,
            "cut_entropy": 0.0,
            "n_active_cuts": 1.0,
            "span_avg": 1.0,
            "span_max": 1.0,
            "span_long_range_ratio": 0.0,
            "ig_edge_density": 1.0,
            "ig_avg_degree": 1.0,
            "ig_is_connected": 1.0,
        }
        g = build_resource_guidance(fm, feature_schema_version="0.4.0")
        mps = g["simulation_guidance"]["mps_bond_dimension"]
        self.assertEqual(mps["pressure"], "low")
        joined = "\n".join(mps["rationale"])
        self.assertNotIn("dense", joined.lower())
        self.assertIn("interaction graph is connected", joined)

    def test_higher_complexity_measured_circuit_shots(self) -> None:
        fm = {
            "n_qubits": 20.0,
            "n_cbits": 20.0,
            "n_measure_ops": 20.0,
            "real_depth": 200.0,
            "entangling_depth": 40.0,
            "n_2q_gate_ops": 120.0,
            "n_param_ops": 10.0,
        }
        g = build_resource_guidance(fm, feature_schema_version="0.4.0")
        shots = g["shot_guidance"]["starting_shots"]
        self.assertIn(8192, shots)
        self.assertIn(16384, shots)
        shot_r = "\n".join(g["shot_guidance"]["rationale"])
        self.assertIn("nontrivial correlations may exist", shot_r)

    def test_high_mps_pressure(self) -> None:
        fm = {
            "n_qubits": 36.0,
            "n_cbits": 10.0,
            "n_measure_ops": 10.0,
            "real_depth": 350.0,
            "entangling_depth": 120.0,
            "n_entangling_layers": 40.0,
            "cut_max": 48.0,
            "cut_mean": 9.0,
            "cut_entropy": 2.5,
            "n_active_cuts": 20.0,
            "span_avg": 3.2,
            "span_max": 9.0,
            "span_long_range_ratio": 0.6,
            "ig_edge_density": 0.45,
            "ig_avg_degree": 6.0,
            "ig_is_connected": 1.0,
        }
        g = build_resource_guidance(fm, feature_schema_version="0.4.0")
        self.assertEqual(g["simulation_guidance"]["statevector"]["scale"], "large")
        mps = g["simulation_guidance"]["mps_bond_dimension"]
        self.assertEqual(mps["pressure"], "high")
        self.assertEqual(mps["starting_points"], [64, 128, 256])


class TestResourceGuidanceMetadata(unittest.TestCase):
    """Bundled shadow pack adds guidance_metadata without changing deterministic MPS fields."""

    _low_fm = {
        "n_qubits": 2.0,
        "n_cbits": 2.0,
        "n_measure_ops": 2.0,
        "real_depth": 2.0,
        "entangling_depth": 1.0,
        "n_entangling_layers": 1.0,
        "cut_max": 1.0,
        "cut_mean": 1.0,
        "cut_entropy": 0.0,
        "n_active_cuts": 1.0,
        "span_avg": 1.0,
        "span_max": 1.0,
        "span_long_range_ratio": 0.0,
        "ig_edge_density": 1.0,
        "ig_avg_degree": 1.0,
        "ig_is_connected": 1.0,
    }

    def test_deterministic_mps_unchanged_with_metadata(self) -> None:
        g = build_resource_guidance(self._low_fm, feature_schema_version="0.4.0")
        mps = g["simulation_guidance"]["mps_bond_dimension"]
        self.assertEqual(mps["pressure"], "low")
        self.assertEqual(mps["starting_points"], [16, 32])
        self.assertIn("guidance_metadata", g)
        meta = g["guidance_metadata"]
        self.assertEqual(meta["guidance_method"], "auto")
        self.assertIn("deterministic_heuristics", meta["guidance_sources"])
        self.assertIn("local_guidance_pack_shadow", meta["guidance_sources"])
        self.assertEqual(meta["model_pack"]["status"], "shadow")
        self.assertTrue(meta["fallback_used"])
        self.assertFalse(meta["shadow_guidance"]["applied"])
        self.assertEqual(
            meta["shadow_guidance"]["reason"],
            "shadow_mode_deterministic_guidance_preserved",
        )

    def test_shadow_guidance_not_applied(self) -> None:
        g = build_resource_guidance(self._low_fm, feature_schema_version="0.4.0")
        sg = g["guidance_metadata"]["shadow_guidance"]
        self.assertFalse(sg["applied"])

    @mock.patch("qcoder.engines.guidance.model_pack.load_resource_guidance_pack", return_value=None)
    def test_missing_pack_no_crash(self, _m: mock.MagicMock) -> None:
        g = build_resource_guidance(self._low_fm, feature_schema_version="0.4.0")
        self.assertEqual(g["simulation_guidance"]["mps_bond_dimension"]["pressure"], "low")
        meta = g["guidance_metadata"]
        self.assertEqual(meta["guidance_sources"], ["deterministic_heuristics"])
        self.assertIsNone(meta["model_pack"])
        self.assertTrue(meta["fallback_used"])


if __name__ == "__main__":
    unittest.main()

