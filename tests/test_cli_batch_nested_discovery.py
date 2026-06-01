import json
import tempfile
import unittest
from pathlib import Path

from qcoder.cli import main


BELL_QASM = """OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
creg c[2];
h q[0];
cx q[0],q[1];
measure q[0] -> c[0];
measure q[1] -> c[1];
"""


class TestCliBatchNestedDiscovery(unittest.TestCase):
    def test_cli_batch_discovers_nested_generated_tree(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            circuits = root / "circuits"
            (circuits / "synthetic_diagnostics" / "pair_reuse").mkdir(parents=True, exist_ok=True)
            (circuits / "algorithms_generated" / "ghz").mkdir(parents=True, exist_ok=True)
            (circuits / "synthetic_diagnostics" / "pair_reuse" / "a.qasm").write_text(BELL_QASM, encoding="utf-8")
            (circuits / "algorithms_generated" / "ghz" / "b.qasm").write_text(BELL_QASM, encoding="utf-8")
            (circuits / ".gitkeep").write_text("", encoding="utf-8")

            out = root / "generated_features.jsonl"
            rc = main(["batch", str(circuits), "--out", str(out)])
            self.assertEqual(rc, 0)
            lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertEqual(len(lines), 2)
            rows = [json.loads(ln) for ln in lines]
            paths = sorted(r["qasm_path"] for r in rows)
            self.assertTrue(paths[0].endswith("a.qasm") or paths[1].endswith("a.qasm"))
            self.assertTrue(paths[0].endswith("b.qasm") or paths[1].endswith("b.qasm"))


if __name__ == "__main__":
    unittest.main()
