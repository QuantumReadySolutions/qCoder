import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qcoder.pipelines.batch import analyze_directory

BELL_QASM = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0],q[1];
measure q[0] -> c[0];
measure q[1] -> c[1];
"""

ONEQ_QASM = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[1];
creg c[1];
rx(0.5) q[0];
measure q[0] -> c[0];
"""

INVALID_QASM = "this is not valid qasm {"


class TestBatchPipeline(unittest.TestCase):
    def test_deterministic_two_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "bell.qasm").write_text(BELL_QASM, encoding="utf-8")
            (root / "oneq.qasm").write_text(ONEQ_QASM, encoding="utf-8")

            results = analyze_directory(
                d,
                backend="Amber",
                precision="fp64",
                threshold=1e-4,
            )
            self.assertEqual(len(results), 2)
            paths = [r["qasm_path"] for r in results if "error" not in r]
            self.assertEqual(sorted(paths), paths, "results should be in sorted order by path")
            for r in results:
                if "error" in r:
                    continue
                self.assertIn("features", r)
                self.assertEqual(r["features"]["schema_version"], "0.4.0")
                self.assertEqual(
                    len(r["features"]["feature_names"]),
                    len(r["features"]["features"]),
                )

    def test_skip_errors(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "bell.qasm").write_text(BELL_QASM, encoding="utf-8")
            (root / "oneq.qasm").write_text(ONEQ_QASM, encoding="utf-8")
            (root / "bad.qasm").write_text(INVALID_QASM, encoding="utf-8")

            def analyze_qasm_raise_for_bad(path, **kwargs):
                from qcoder.pipelines.analyze import analyze_qasm
                if path.endswith("bad.qasm"):
                    raise ValueError("Invalid QASM")
                return analyze_qasm(path, **kwargs)

            with patch("qcoder.pipelines.batch.analyze_qasm", side_effect=analyze_qasm_raise_for_bad):
                results = analyze_directory(
                    d,
                    fail_fast=False,
                )
            self.assertEqual(len(results), 3)
            errors = [r for r in results if "error" in r]
            self.assertEqual(len(errors), 1)
            self.assertIn("qasm_path", errors[0])
            self.assertIn("error", errors[0])
            successes = [r for r in results if "error" not in r]
            self.assertEqual(len(successes), 2)
            for r in successes:
                self.assertEqual(r["features"]["schema_version"], "0.4.0")

    def test_nested_qasm_discovered_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "top.qasm").write_text(ONEQ_QASM, encoding="utf-8")
            nested = root / "synthetic_diagnostics" / "span_sweep"
            nested.mkdir(parents=True, exist_ok=True)
            (nested / "nested.qasm").write_text(BELL_QASM, encoding="utf-8")
            # non-QASM files should be ignored
            (root / ".gitkeep").write_text("", encoding="utf-8")
            (nested / "readme.txt").write_text("ignore me", encoding="utf-8")

            results = analyze_directory(d)
            self.assertEqual(len(results), 2)
            paths = sorted(r["qasm_path"] for r in results)
            self.assertTrue(paths[0].endswith("nested.qasm") or paths[1].endswith("nested.qasm"))
            self.assertTrue(paths[0].endswith("top.qasm") or paths[1].endswith("top.qasm"))

    def test_non_recursive_mode_still_available(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "top.qasm").write_text(ONEQ_QASM, encoding="utf-8")
            nested = root / "algorithms_generated" / "ghz"
            nested.mkdir(parents=True, exist_ok=True)
            (nested / "nested.qasm").write_text(BELL_QASM, encoding="utf-8")

            results = analyze_directory(d, recursive=False)
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]["qasm_path"].endswith("top.qasm"))

    def test_batch_default_no_guidance(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "top.qasm").write_text(ONEQ_QASM, encoding="utf-8")
            results = analyze_directory(d)
            self.assertEqual(len(results), 1)
            self.assertNotIn("guidance", results[0])

    def test_batch_with_guidance(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "top.qasm").write_text(ONEQ_QASM, encoding="utf-8")
            results = analyze_directory(d, include_guidance=True)
            self.assertEqual(len(results), 1)
            self.assertIn("guidance", results[0])
            self.assertEqual(results[0]["guidance"]["guidance_schema_version"], "0.1")
