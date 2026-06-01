from __future__ import annotations

import unittest

from qcoder.engines.review.bundle import build_review_bundle
from qcoder.engines.review.markdown import render_review_markdown


class TestReviewBundle(unittest.TestCase):
    def test_review_derived_metrics(self) -> None:
        counts = {
            "schema": "qcoder.counts.v0",
            "counts": {"00": 512, "11": 512},
            "shots_total": 1024,
            "classical_width_expected": 2,
            "notes": [],
        }
        out = build_review_bundle(counts_format="qcoder", counts_v0=counts)
        self.assertEqual(out["derived"]["total_shots"], 1024)
        self.assertEqual(out["derived"]["declared_shots_total"], 1024)
        self.assertEqual(out["derived"]["shots_total_basis"], "sum_counts_observed")
        self.assertEqual(out["derived"]["n_observed_bitstrings"], 2)
        self.assertEqual(len(out["derived"]["top_k"]), 2)
        self.assertAlmostEqual(out["derived"]["top_bitstring_probability"], 0.5)
        self.assertGreater(out["derived"]["entropy"], 0.0)
        self.assertGreater(out["derived"]["effective_support_size"], 1.0)
        shots_check = next(c for c in out["checks"] if c["id"] == "shots_total_match")
        self.assertEqual(shots_check["status"], "pass")

    def test_linkage_and_width_check(self) -> None:
        counts = {
            "schema": "qcoder.counts.v0",
            "counts": {"00": 8, "11": 8},
            "shots_total": 16,
            "classical_width_expected": 2,
            "notes": [],
        }
        preflight = {
            "context_bundle_schema_version": "0.1",
            "circuit": {"n_cbits": 2},
            "hashes": {"qasm_sha256": "abc", "analysis_fingerprint": "def"},
        }
        out = build_review_bundle(
            counts_format="qcoder",
            counts_v0=counts,
            preflight_context=preflight,
            preflight_context_path="preflight.context.json",
        )
        self.assertEqual(out["linkage"]["qasm_sha256"], "abc")
        self.assertEqual(out["linkage"]["analysis_fingerprint"], "def")
        self.assertEqual(out["linkage"]["preflight_context_bundle_schema_version"], "0.1")
        self.assertTrue(any(c["id"] == "classical_width_match" for c in out["checks"]))
        self.assertIn("preflight_excerpt", out)
        excerpt = out["preflight_excerpt"]
        self.assertEqual(excerpt["circuit"]["n_cbits"], 2)
        self.assertIn("selected_feature_map", excerpt)
        self.assertIn("selected_feature_definitions", excerpt)

    def test_review_markdown_sections_order(self) -> None:
        bundle = {
            "inputs": {"counts_format": "qcoder", "preflight_context_path": "preflight.context.json"},
            "linkage": {
                "qasm_sha256": "abc",
                "analysis_fingerprint": "def",
                "preflight_context_bundle_schema_version": "0.1",
            },
            "derived": {
                "total_shots": 10,
                "declared_shots_total": 10,
                "shots_total_basis": "sum_counts_observed",
                "n_observed_bitstrings": 2,
                "top_bitstring_probability": 0.6,
                "concentration": "moderate",
                "entropy": 1.0,
                "effective_support_size": 2.0,
                "top_k": [{"bitstring": "00", "count": 6}],
            },
            "preflight_excerpt": {
                "circuit": {"n_qubits": 2, "n_cbits": 2, "n_ops": 4, "source_format": "qasm2"},
                "selected_feature_map": {"real_depth": 2.0},
                "selected_feature_definitions": {"real_depth": "Computed circuit depth from operation scheduling."},
                "guidance_summary": {"shot_applicability": "applicable", "shot_starting_shots": [1024, 4096]},
            },
            "checks": [],
            "warnings": [],
            "llm_use": {"intended_use": "Attach me."},
        }
        md = render_review_markdown(bundle)
        sections = [
            "## Purpose",
            "## Inputs",
            "## Linkage",
            "## Preflight Context Summary",
            "## Counts Summary",
            "## Distribution Shape",
            "## Checks",
            "## Warnings",
            "## Suggested Use With an LLM",
        ]
        idx = [md.index(s) for s in sections]
        self.assertEqual(idx, sorted(idx))

    def test_mismatched_declared_shots_total_uses_observed_sum(self) -> None:
        counts = {
            "schema": "qcoder.counts.v0",
            "counts": {"00": 5, "11": 3},
            "shots_total": 20,
            "classical_width_expected": 2,
            "notes": [],
        }
        out = build_review_bundle(counts_format="qcoder", counts_v0=counts)
        self.assertEqual(out["derived"]["total_shots"], 8)
        self.assertEqual(out["derived"]["declared_shots_total"], 20)
        self.assertEqual(out["derived"]["shots_total_basis"], "sum_counts_observed")
        self.assertAlmostEqual(out["derived"]["top_bitstring_probability"], 5 / 8)
        shots_check = next(c for c in out["checks"] if c["id"] == "shots_total_match")
        self.assertEqual(shots_check["status"], "fail")
        self.assertIn("using observed total", " ".join(out["warnings"]).lower())

    def test_mismatch_warning_visible_in_markdown(self) -> None:
        bundle = {
            "inputs": {"counts_format": "qcoder", "preflight_context_path": None},
            "linkage": {
                "qasm_sha256": None,
                "analysis_fingerprint": None,
                "preflight_context_bundle_schema_version": None,
            },
            "derived": {
                "total_shots": 8,
                "declared_shots_total": 20,
                "shots_total_basis": "sum_counts_observed",
                "n_observed_bitstrings": 2,
                "top_bitstring_probability": 0.625,
                "concentration": "moderate",
                "entropy": 1.0,
                "effective_support_size": 2.0,
                "top_k": [{"bitstring": "00", "count": 5}],
            },
            "checks": [
                {
                    "id": "shots_total_match",
                    "status": "fail",
                    "detail": "Declared shots_total 20 does not match observed sum(counts) 8.",
                }
            ],
            "warnings": ["Declared shots_total differs from observed sum(counts); using observed total."],
            "llm_use": {"intended_use": "Attach me."},
        }
        md = render_review_markdown(bundle)
        self.assertIn("declared_shots_total", md)
        self.assertIn("shots_total_basis", md)
        self.assertIn("Declared shots_total differs from observed sum(counts)", md)

    def test_mismatched_declared_shots_total_for_qiskit_format(self) -> None:
        counts = {
            "schema": "qcoder.counts.v0",
            "counts": {"00": 2, "11": 2},
            "shots_total": 10,
            "classical_width_expected": 2,
            "notes": [],
        }
        out = build_review_bundle(counts_format="qiskit_counts", counts_v0=counts)
        self.assertEqual(out["derived"]["total_shots"], 4)
        self.assertEqual(out["derived"]["declared_shots_total"], 10)
        shots_check = next(c for c in out["checks"] if c["id"] == "shots_total_match")
        self.assertEqual(shots_check["status"], "fail")

    def test_mixed_width_counts_emit_consistency_warning_for_qcoder(self) -> None:
        counts = {
            "schema": "qcoder.counts.v0",
            "counts": {"0": 3, "11": 5},
            "shots_total": 8,
            "classical_width_expected": None,
            "notes": [],
        }
        out = build_review_bundle(counts_format="qcoder", counts_v0=counts)
        width_check = next(c for c in out["checks"] if c["id"] == "bitstring_width_consistency")
        self.assertEqual(width_check["status"], "fail")
        self.assertIn("[1, 2]", width_check["detail"])
        self.assertIn(
            "Observed bitstring widths are inconsistent across counts keys",
            " ".join(out["warnings"]),
        )
        self.assertEqual(out["derived"]["total_shots"], 8)
        self.assertAlmostEqual(out["derived"]["top_bitstring_probability"], 5 / 8)

    def test_mixed_width_counts_emit_consistency_warning_for_qiskit_counts(self) -> None:
        counts = {
            "schema": "qcoder.counts.v0",
            "counts": {"0": 2, "11": 1},
            "shots_total": 3,
            "classical_width_expected": None,
            "notes": [],
        }
        out = build_review_bundle(counts_format="qiskit_counts", counts_v0=counts)
        width_check = next(c for c in out["checks"] if c["id"] == "bitstring_width_consistency")
        self.assertEqual(width_check["status"], "fail")
        self.assertIn("[1, 2]", width_check["detail"])
        self.assertEqual(out["derived"]["total_shots"], 3)

    def test_review_markdown_states_user_provided_counts_and_no_execution(self) -> None:
        counts = {
            "schema": "qcoder.counts.v0",
            "counts": {"0": 3, "11": 5},
            "shots_total": 8,
            "classical_width_expected": None,
            "notes": [],
        }
        out = build_review_bundle(counts_format="qcoder", counts_v0=counts)
        md = render_review_markdown(out)
        self.assertIn("Counts are user-provided; qCoder did not execute the circuit.", md)
        self.assertIn(
            "Observed bitstring widths are inconsistent across counts keys",
            md,
        )


if __name__ == "__main__":
    unittest.main()

