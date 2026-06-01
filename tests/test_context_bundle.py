from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from qcoder.pipelines.context import build_preflight_context
from qcoder.engines.context.markdown import render_context_markdown


class TestContextBundle(unittest.TestCase):
    def test_context_bundle_shape_no_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qasm = Path(tmp) / "bell.qasm"
            qasm.write_text(
                "OPENQASM 2.0;\n"
                'include "qelib1.inc";\n'
                "qreg q[2];\n"
                "creg c[2];\n"
                "h q[0];\n"
                "cx q[0],q[1];\n"
                "measure q[0] -> c[0];\n"
                "measure q[1] -> c[1];\n",
                encoding="utf-8",
            )
            b = build_preflight_context(str(qasm), include_guidance=False)
        self.assertEqual(b["context_bundle_schema_version"], "0.1")
        self.assertEqual(b["artifact_type"], "qcoder.preflight_context")
        self.assertIn("analysis", b)
        self.assertIn("features", b["analysis"])
        self.assertIn("feature_map", b["analysis"])
        self.assertIn("feature_definitions", b["analysis"])
        self.assertEqual(b["analysis"]["feature_definitions_scope"], "selected")
        self.assertIn("real_depth", b["analysis"]["feature_definitions"])
        self.assertNotIn("guidance", b["analysis"])
        self.assertNotIn("feature_profiles", b["analysis"])
        self.assertEqual(b["basis"], "deterministic_analysis")
        limits = b["llm_use"]["limits"]
        self.assertEqual(len(limits), 2)
        self.assertNotIn(
            "Feature profiles are deterministic structural taxonomy",
            " ".join(limits),
        )
        self.assertIn("qasm_sha256", b["hashes"])
        self.assertIn("analysis_fingerprint", b["hashes"])

    def test_context_bundle_basis_guidance_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qasm = Path(tmp) / "m.qasm"
            qasm.write_text(
                "OPENQASM 2.0;\nqreg q[1];\ncreg c[1];\nmeasure q[0] -> c[0];\n",
                encoding="utf-8",
            )
            b = build_preflight_context(str(qasm), include_guidance=True)
        self.assertEqual(b["basis"], "deterministic_analysis_plus_guidance")

    def test_context_bundle_basis_profiles_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qasm = Path(tmp) / "m.qasm"
            qasm.write_text(
                "OPENQASM 2.0;\nqreg q[1];\ncreg c[1];\nmeasure q[0] -> c[0];\n",
                encoding="utf-8",
            )
            b = build_preflight_context(str(qasm), include_profiles=True)
        self.assertEqual(b["basis"], "deterministic_analysis_plus_profiles")
        limits = b["llm_use"]["limits"]
        self.assertIn(
            "Feature profiles are deterministic structural taxonomy, not execution evidence.",
            limits,
        )
        self.assertEqual(len(limits), 3)

    def test_context_bundle_basis_guidance_and_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qasm = Path(tmp) / "m.qasm"
            qasm.write_text(
                "OPENQASM 2.0;\nqreg q[1];\ncreg c[1];\nmeasure q[0] -> c[0];\n",
                encoding="utf-8",
            )
            b = build_preflight_context(
                str(qasm), include_guidance=True, include_profiles=True
            )
        self.assertEqual(
            b["basis"], "deterministic_analysis_plus_guidance_and_profiles"
        )
        self.assertIn(
            "Feature profiles are deterministic structural taxonomy, not execution evidence.",
            b["llm_use"]["limits"],
        )

    def test_context_markdown_sections_order(self) -> None:
        bundle = {
            "circuit": {
                "qasm_path": "a.qasm",
                "source_format": "qasm2",
                "circuit_id": None,
                "circuit_name": None,
                "n_qubits": 2,
                "n_cbits": 2,
                "n_ops": 4,
            },
            "analysis": {"feature_map": {"real_depth": 2.0}},
            "assumptions": ["No backend execution was performed."],
            "llm_use": {"intended_use": "Attach me.", "limits": ["No execution evidence."]},
        }
        md = render_context_markdown(bundle)
        sections = [
            "## Purpose",
            "## Circuit",
            "## Structural Summary",
            "## Assumptions and Limits",
            "## Suggested Use With an LLM",
        ]
        idx = [md.index(s) for s in sections]
        self.assertEqual(idx, sorted(idx))

    def test_context_markdown_profiles_section_order(self) -> None:
        bundle = {
            "circuit": {
                "qasm_path": "a.qasm",
                "source_format": "qasm2",
                "circuit_id": None,
                "circuit_name": None,
                "n_qubits": 2,
                "n_cbits": 2,
                "n_ops": 4,
            },
            "analysis": {
                "feature_map": {"real_depth": 2.0},
                "feature_profiles": {
                    "profiles": {
                        "size_profile": {
                            "tiers": {"statevector_scale": "small"},
                            "labels": ["statevector_scale:small"],
                        },
                        "sampling_profile": {"tiers": {"shot_readiness": "applicable"}, "labels": []},
                        "entanglement_profile": {"tiers": {"intensity": "low"}, "labels": []},
                        "topology_profile": {"tiers": {"connectivity": "connected"}, "labels": []},
                        "locality_profile": {"tiers": {"long_range": "mostly_local"}, "labels": []},
                        "simulation_pressure_profile": {"tiers": {"mps_pressure": "low"}, "labels": []},
                        "llm_summary_profile": {
                            "lines": ["size_profile: statevector_scale=small"],
                            "labels": [],
                        },
                    }
                },
                "guidance": {
                    "shot_guidance": {"applicability": "applicable", "starting_shots": [1024, 4096]},
                    "simulation_guidance": {
                        "statevector": {"scale": "small"},
                        "mps_bond_dimension": {"pressure": "low", "starting_points": [16, 32]},
                    },
                },
            },
            "assumptions": ["No backend execution was performed."],
            "llm_use": {"intended_use": "Attach me.", "limits": ["No execution evidence."]},
        }
        md = render_context_markdown(bundle)
        sections = [
            "## Structural Summary",
            "## Derived feature profiles",
            "## Resource Guidance",
        ]
        idx = [md.index(s) for s in sections]
        self.assertEqual(idx, sorted(idx))
        self.assertIn("- llm_summary_profile:", md)
        self.assertIn("  - size_profile: statevector_scale=small", md)

    def test_context_markdown_structural_summary_has_meanings(self) -> None:
        bundle = {
            "circuit": {"qasm_path": "a.qasm", "source_format": "qasm2", "n_qubits": 2, "n_cbits": 2, "n_ops": 4},
            "analysis": {
                "feature_map": {"real_depth": 2.0, "cut_max": 1.0},
                "feature_definitions": {
                    "real_depth": "Computed circuit depth from operation scheduling.",
                    "cut_max": "Maximum cut value across natural qubit-order cuts.",
                },
            },
            "assumptions": [],
            "llm_use": {"intended_use": "", "limits": []},
        }
        md = render_context_markdown(bundle)
        self.assertIn("real_depth: `2` — Computed circuit depth from operation scheduling.", md)
        self.assertIn("cut_max: `1` — Maximum cut value across natural qubit-order cuts.", md)

    def test_default_markdown_no_full_feature_appendix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qasm = Path(tmp) / "bell.qasm"
            qasm.write_text(
                "OPENQASM 2.0;\n"
                "qreg q[2];\n"
                "creg c[2];\n"
                "h q[0];\n"
                "cx q[0],q[1];\n"
                "measure q[0] -> c[0];\n"
                "measure q[1] -> c[1];\n",
                encoding="utf-8",
            )
            b = build_preflight_context(str(qasm))
        md = render_context_markdown(b)
        self.assertNotIn("## Full Feature Reference", md)

    def test_full_features_markdown_has_appendix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qasm = Path(tmp) / "bell.qasm"
            qasm.write_text(
                "OPENQASM 2.0;\n"
                "qreg q[2];\n"
                "creg c[2];\n"
                "h q[0];\n"
                "cx q[0],q[1];\n"
                "measure q[0] -> c[0];\n"
                "measure q[1] -> c[1];\n",
                encoding="utf-8",
            )
            b = build_preflight_context(str(qasm), include_full_features=True)
        self.assertEqual(b["analysis"]["feature_definitions_scope"], "full")
        md = render_context_markdown(b)
        self.assertIn("## Full Feature Reference", md)
        self.assertIn("n_qubits:", md)
        self.assertIn("real_depth:", md)
        self.assertIn("entangling_depth:", md)

    def test_context_bundle_includes_profiles_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qasm = Path(tmp) / "bell.qasm"
            qasm.write_text(
                "OPENQASM 2.0;\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];\n",
                encoding="utf-8",
            )
            b = build_preflight_context(str(qasm), include_profiles=True)
        self.assertIn("feature_profiles", b["analysis"])
        self.assertEqual(
            b["analysis"]["feature_profiles"]["feature_profiles_schema_version"],
            "0.1",
        )
        md = render_context_markdown(b)
        self.assertIn("connectivity=connected_small_graph", md)
        self.assertIn("- llm_summary_profile:", md)
        self.assertIn("  - topology_profile: connectivity=connected_small_graph", md)
        self.assertNotIn("connected_high_density", md)

    def test_analysis_fingerprint_changes_when_profiles_included(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            qasm = Path(tmp) / "bell.qasm"
            qasm.write_text(
                "OPENQASM 2.0;\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];\n",
                encoding="utf-8",
            )
            no_profiles = build_preflight_context(str(qasm), include_profiles=False)
            with_profiles = build_preflight_context(str(qasm), include_profiles=True)
        self.assertNotEqual(
            no_profiles["hashes"]["analysis_fingerprint"],
            with_profiles["hashes"]["analysis_fingerprint"],
        )


if __name__ == "__main__":
    unittest.main()

