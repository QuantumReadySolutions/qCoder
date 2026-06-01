from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TestExamplesSmoke(unittest.TestCase):
    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[1]

    def test_examples_qasm_context_review_smoke(self) -> None:
        root = self._repo_root()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
        qasm = root / "examples" / "circuits" / "bell.qasm"
        counts = root / "examples" / "fixtures" / "bell_counts_qiskit.json"

        self.assertTrue(qasm.exists(), msg=f"missing fixture: {qasm}")
        self.assertTrue(counts.exists(), msg=f"missing fixture: {counts}")

        with tempfile.TemporaryDirectory() as tmp:
            tmpd = Path(tmp)
            out_ctx_json = tmpd / "preflight.context.json"
            out_ctx_md = tmpd / "preflight.context.md"
            out_rev_json = tmpd / "execution.review.json"
            out_rev_md = tmpd / "execution.review.md"

            proc_analyze = subprocess.run(
                [sys.executable, "-m", "qcoder", "analyze", str(qasm), "--json"],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_analyze.returncode, 0, msg=proc_analyze.stderr)
            self.assertIn('"feature_map"', proc_analyze.stdout)

            proc_context = subprocess.run(
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
            self.assertEqual(proc_context.returncode, 0, msg=proc_context.stderr)
            self.assertTrue(out_ctx_json.exists())
            self.assertTrue(out_ctx_md.exists())

            proc_review = subprocess.run(
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
            self.assertEqual(proc_review.returncode, 0, msg=proc_review.stderr)
            self.assertTrue(out_rev_json.exists())
            self.assertTrue(out_rev_md.exists())


if __name__ == "__main__":
    unittest.main()
