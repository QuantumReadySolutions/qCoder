import tempfile
import unittest
from pathlib import Path

from qcoder.pipelines.analyze import analyze_qasm


class TestAnalyzePipeline(unittest.TestCase):
    def test_bell_no_mirror_dir(self):
        p = Path("/tmp/qcoder_bell.qasm")
        p.write_text(
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
        r = analyze_qasm(
            str(p),
            circuit_id="t1",
            circuit_name="bell",
            processor="Amber",
            precision="fp64",
            threshold=1e-4,
        )
        self.assertEqual(r.example.ir.source_format, "qasm2")
        self.assertEqual(r.run_config.backend, "GPU")
        self.assertEqual(r.run_config.precision, "double")
        self.assertEqual(r.example.global_features.schema_version, "0.4.0")
        self.assertEqual(len(r.example.global_features.feature_names), len(r.example.global_features.features))
        # No mirror_metadata when mirror_artifacts_dir not set
        self.assertIsNone(r.mirror_metadata)

    def test_bell(self):
        """Alias for test_bell_no_mirror_dir for backward compatibility."""
        self.test_bell_no_mirror_dir()

    def test_analyze_with_mirror_artifacts_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            qasm_dir = Path(tmp) / "qasm"
            qasm_dir.mkdir()
            art_dir = Path(tmp) / "artifacts" / "mirror"
            # Unitary circuit (no measure)
            qasm_path = qasm_dir / "u.qasm"
            qasm_path.write_text(
                "OPENQASM 2.0;\nqreg q[2];\ncx q[0], q[1];\nu1(0.5) q[0];\n",
                encoding="utf-8",
            )
            r = analyze_qasm(
                str(qasm_path),
                circuit_id="u1",
                circuit_name="u",
                mirror_artifacts_dir=str(art_dir),
            )
            self.assertIsNotNone(r.mirror_metadata)
            self.assertTrue(r.mirror_metadata["adjoint_supported"])
            mirror_ref = r.mirror_metadata.get("mirror_qasm_ref")
            self.assertIsNotNone(mirror_ref)
            self.assertTrue(mirror_ref.endswith("__mirror.qasm"))
            written = art_dir / mirror_ref
            self.assertTrue(written.exists())
            self.assertIn("u1(-0.5)", written.read_text())

    def test_analyze_json_default_no_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "m.qasm"
            p.write_text(
                "OPENQASM 2.0;\nqreg q[1];\ncreg c[1];\nmeasure q[0] -> c[0];\n",
                encoding="utf-8",
            )
            r = analyze_qasm(str(p))
            out = r.to_json_dict()
            self.assertNotIn("guidance", out)
            self.assertNotIn("feature_profiles", out)

    def test_analyze_json_with_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "m.qasm"
            p.write_text(
                "OPENQASM 2.0;\nqreg q[1];\ncreg c[1];\nmeasure q[0] -> c[0];\n",
                encoding="utf-8",
            )
            r = analyze_qasm(str(p))
            out = r.to_json_dict(include_guidance=True)
            self.assertIn("guidance", out)
            self.assertEqual(out["guidance"]["guidance_schema_version"], "0.1")

    def test_analyze_json_with_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "m.qasm"
            p.write_text(
                "OPENQASM 2.0;\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];\n",
                encoding="utf-8",
            )
            r = analyze_qasm(str(p))
            out = r.to_json_dict(include_profiles=True)
            self.assertIn("feature_profiles", out)
            self.assertEqual(out["feature_profiles"]["feature_profiles_schema_version"], "0.1")


if __name__ == "__main__":
    unittest.main()
