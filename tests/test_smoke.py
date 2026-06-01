import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from qcoder.pipelines.analyze import analyze_qasm


class TestSmoke(unittest.TestCase):
    def test_analyze_qasm2(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "qcoder_test.qasm"
            p.write_text(
                'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\ncreg c[1];\nh q[0];\nmeasure q[0] -> c[0];\n',
                encoding="utf-8",
            )
            report = analyze_qasm(str(p))
            self.assertEqual(report.example.ir.source_format, "qasm2")
            self.assertEqual(report.example.ir.n_qubits, 1)
            self.assertGreaterEqual(report.example.ir.n_ops, 1)


if __name__ == "__main__":
    unittest.main()
