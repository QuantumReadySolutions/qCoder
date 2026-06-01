from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestCliContextReview(unittest.TestCase):
    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[1]

    def test_context_and_review_write_files(self) -> None:
        root = self._repo_root()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
        with tempfile.TemporaryDirectory() as tmp:
            tmpd = Path(tmp)
            qasm = tmpd / "bell.qasm"
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
            out_ctx_json = tmpd / "preflight.context.json"
            out_ctx_md = tmpd / "preflight.context.md"
            proc_ctx = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "qcoder",
                    "context",
                    str(qasm),
                    "--out-json",
                    str(out_ctx_json),
                    "--out-md",
                    str(out_ctx_md),
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_ctx.returncode, 0, msg=proc_ctx.stderr)
            self.assertTrue(out_ctx_json.exists())
            self.assertTrue(out_ctx_md.exists())

            counts = tmpd / "counts.json"
            counts.write_text(json.dumps({"00": 5, "11": 3}), encoding="utf-8")
            out_rev_json = tmpd / "execution.review.json"
            out_rev_md = tmpd / "execution.review.md"
            proc_rev = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "qcoder",
                    "review",
                    "--counts-json",
                    str(counts),
                    "--format",
                    "qiskit_counts",
                    "--preflight-json",
                    str(out_ctx_json),
                    "--out-json",
                    str(out_rev_json),
                    "--out-md",
                    str(out_rev_md),
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_rev.returncode, 0, msg=proc_rev.stderr)
            self.assertTrue(out_rev_json.exists())
            self.assertTrue(out_rev_md.exists())

    def test_review_warns_on_mismatched_declared_shots_total(self) -> None:
        root = self._repo_root()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
        with tempfile.TemporaryDirectory() as tmp:
            tmpd = Path(tmp)
            counts = tmpd / "counts_mismatch.json"
            counts.write_text(
                json.dumps(
                    {
                        "schema": "qcoder.counts.v0",
                        "counts": {"00": 5, "11": 3},
                        "shots_total": 20,
                    }
                ),
                encoding="utf-8",
            )
            out_rev_json = tmpd / "execution.review.json"
            out_rev_md = tmpd / "execution.review.md"
            proc_rev = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "qcoder",
                    "review",
                    "--counts-json",
                    str(counts),
                    "--format",
                    "qcoder",
                    "--out-json",
                    str(out_rev_json),
                    "--out-md",
                    str(out_rev_md),
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_rev.returncode, 0, msg=proc_rev.stderr)
            review_json = json.loads(out_rev_json.read_text(encoding="utf-8"))
            self.assertEqual(review_json["derived"]["total_shots"], 8)
            self.assertEqual(review_json["derived"]["declared_shots_total"], 20)
            self.assertEqual(review_json["derived"]["shots_total_basis"], "sum_counts_observed")
            shots_check = next(c for c in review_json["checks"] if c["id"] == "shots_total_match")
            self.assertEqual(shots_check["status"], "fail")
            self.assertTrue(
                any("Declared shots_total differs from observed sum(counts)" in w for w in review_json["warnings"])
            )
            md = out_rev_md.read_text(encoding="utf-8")
            self.assertIn("Declared shots_total differs from observed sum(counts)", md)

    def test_context_with_profiles_writes_profiles_json_and_markdown_section(self) -> None:
        root = self._repo_root()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
        with tempfile.TemporaryDirectory() as tmp:
            tmpd = Path(tmp)
            qasm = tmpd / "bell.qasm"
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
            out_ctx_json = tmpd / "preflight.context.json"
            out_ctx_md = tmpd / "preflight.context.md"
            proc_ctx = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "qcoder",
                    "context",
                    str(qasm),
                    "--out-json",
                    str(out_ctx_json),
                    "--out-md",
                    str(out_ctx_md),
                    "--profiles",
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_ctx.returncode, 0, msg=proc_ctx.stderr)
            context_json = json.loads(out_ctx_json.read_text(encoding="utf-8"))
            self.assertIn("feature_profiles", context_json["analysis"])
            context_md = out_ctx_md.read_text(encoding="utf-8")
            self.assertIn("## Derived feature profiles", context_md)


if __name__ == "__main__":
    unittest.main()

