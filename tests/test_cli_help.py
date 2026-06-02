from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from qcoder import __version__
from qcoder.cli import main
from qcoder.pipelines.analyze import analyze_qasm


class TestCliHelp(unittest.TestCase):
    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[1]

    def _run_module_help(self, subcmd: str) -> str:
        root = self._repo_root()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
        proc = subprocess.run(
            [sys.executable, "-m", "qcoder", subcmd, "--help"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        return proc.stdout

    def test_root_help(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--help"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("usage: qcoder", out)
        self.assertIn("analyze", out)
        self.assertIn("batch", out)
        self.assertIn("context", out)
        self.assertIn("review", out)
        self.assertIn("pro", out)

    def test_root_version_prints_package_version(self) -> None:
        for flag in ("--version", "-V"):
            with self.subTest(flag=flag):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = main([flag])
                self.assertEqual(rc, 0)
                self.assertEqual(buf.getvalue().strip(), __version__)

    def test_analyze_help_includes_qasm_and_json(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                main(["analyze", "--help"])
        self.assertEqual(ctx.exception.code, 0)
        out = buf.getvalue()
        self.assertIn("qasm", out)
        self.assertIn("--json", out)
        self.assertIn("--guidance", out)
        self.assertIn("--profiles", out)
        self.assertIn("requires --json", out.lower())

    def test_batch_help_includes_circuits_dir_and_out(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as ctx:
                main(["batch", "--help"])
        self.assertEqual(ctx.exception.code, 0)
        out = buf.getvalue()
        self.assertIn("circuits_dir", out)
        self.assertIn("--out", out)
        self.assertIn("--guidance", out)

    def test_python_m_qcoder_analyze_help(self) -> None:
        out = self._run_module_help("analyze")
        self.assertIn("qasm", out)
        self.assertIn("--json", out)
        self.assertIn("--guidance", out)
        self.assertIn("--profiles", out)

    def test_python_m_qcoder_batch_help(self) -> None:
        out = self._run_module_help("batch")
        self.assertIn("circuits_dir", out)
        self.assertIn("--out", out)
        self.assertIn("--guidance", out)

    def test_python_m_qcoder_context_help(self) -> None:
        out = self._run_module_help("context")
        self.assertIn("--out-json", out)
        self.assertIn("--out-md", out)
        self.assertIn("--full-features", out)
        self.assertIn("--profiles", out)

    def test_python_m_qcoder_review_help(self) -> None:
        out = self._run_module_help("review")
        self.assertIn("--counts-json", out)
        self.assertIn("--format", out)

    def test_python_m_qcoder_pro_help(self) -> None:
        out = self._run_module_help("pro")
        self.assertIn("signup", out)
        self.assertIn("login", out)
        self.assertIn("install", out)
        self.assertIn("status", out)
        self.assertIn("validate", out)
        self.assertIn("workflow", out)
        self.assertIn("service-backed", out.lower())

    def test_analyze_profiles_without_json_warns_stderr_and_exit_2(self) -> None:
        root = self._repo_root()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
        with tempfile.TemporaryDirectory() as tmp:
            qasm = Path(tmp) / "bell.qasm"
            qasm.write_text(
                "OPENQASM 2.0;\nqreg q[1];\ncreg c[1];\nmeasure q[0] -> c[0];\n",
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "qcoder",
                    "analyze",
                    str(qasm),
                    "--profiles",
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("qcoder:", proc.stderr.lower())
        self.assertIn("--json", proc.stderr)

    def test_analyze_guidance_human_output_uses_simulator_starting_points_label(self) -> None:
        root = self._repo_root()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
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
            proc = subprocess.run(
                [sys.executable, "-m", "qcoder", "analyze", str(qasm), "--guidance"],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertIn("simulator starting points:", proc.stdout)
            self.assertNotIn("simulation:", proc.stdout)


class TestAnalyzeJsonFeatureMap(unittest.TestCase):
    def test_to_json_dict_has_feature_map_with_expected_keys(self) -> None:
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
            report = analyze_qasm(str(qasm))
            d = report.to_json_dict()
        self.assertIn("feature_map", d)
        self.assertIn("features", d)
        self.assertEqual(d["features"]["schema_version"], "0.4.0")
        fm = d["feature_map"]
        self.assertIsInstance(fm, dict)
        for key in ("n_qubits", "n_ops", "estimated_depth"):
            self.assertIn(key, fm)
        self.assertEqual(fm["n_qubits"], 2.0)
        names = d["features"]["feature_names"]
        vals = d["features"]["features"]
        self.assertEqual(fm["n_qubits"], dict(zip(names, vals))["n_qubits"])


if __name__ == "__main__":
    unittest.main()
