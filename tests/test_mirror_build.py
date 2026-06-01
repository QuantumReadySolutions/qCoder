import unittest
from qcoder.core.qasm2.mirror_build import build_mirror_qasm, UnsupportedQasm


class TestMirrorBuild(unittest.TestCase):
    def test_build_mirror_cx_u1(self):
        qasm = "OPENQASM 2.0;\nqreg q[2];\ncx q[0], q[1];\nu1(0.5) q[0];\n"
        out, n = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertEqual(n, 2)
        self.assertIn("u1(-0.5)", out)
        self.assertIn("cx ", out)

    def test_build_mirror_drop_barriers(self):
        qasm = "OPENQASM 2.0;\nqreg q[1];\nh q[0];\nbarrier q[0];\n"
        out, n = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertEqual(n, 1)
        self.assertIn("h q[0];", out)
        self.assertNotIn("barrier", out)
        self.assertIn("creg c[1];", out)
        self.assertIn("measure q[0] -> c[0];", out)

    def test_standard_include_qelib1_supported(self):
        qasm = 'OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\nh q[0];\n'
        out, n = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertEqual(n, 1)
        self.assertIn('include "qelib1.inc";', out)
        self.assertIn("h q[0];", out)

    def test_nonstandard_include_still_unsupported(self):
        qasm = 'OPENQASM 2.0;\ninclude "stdgates.inc";\nqreg q[1];\nh q[0];\n'
        with self.assertRaises(UnsupportedQasm):
            build_mirror_qasm(qasm, drop_barriers=True)

    def test_cp_adjoint_negates_angle(self):
        qasm = "OPENQASM 2.0;\nqreg q[2];\ncp(0.25) q[0], q[1];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertIn("cp(-0.25) q[0], q[1];", out)

    def test_ry_adjoint_negates_angle(self):
        qasm = "OPENQASM 2.0;\nqreg q[1];\nry(1.5) q[0];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertIn("ry(-1.5) q[0];", out)

    def test_rx_rz_rzz_adjoint_negates_angle(self):
        qasm = "OPENQASM 2.0;\nqreg q[2];\nrx(0.3) q[0];\nrz(0.4) q[0];\nrzz(0.5) q[0], q[1];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertIn("rx(-0.3) q[0];", out)
        self.assertIn("rz(-0.4) q[0];", out)
        self.assertIn("rzz(-0.5) q[0], q[1];", out)

    def test_crx_cry_crz_adjoint_negates_angle(self):
        qasm = "OPENQASM 2.0;\nqreg q[2];\ncrx(0.6) q[0], q[1];\ncry(0.7) q[0], q[1];\ncrz(0.8) q[0], q[1];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertIn("crx(-0.6) q[0], q[1];", out)
        self.assertIn("cry(-0.7) q[0], q[1];", out)
        self.assertIn("crz(-0.8) q[0], q[1];", out)

    def test_cu3_adjoint_parameter_transform(self):
        qasm = "OPENQASM 2.0;\nqreg q[2];\ncu3(0.1, 0.2, 0.3) q[0], q[1];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertIn("cu3(-0.1, -0.3, -0.2) q[0], q[1];", out)

    def test_rxx_adjoint_negates_angle(self):
        qasm = "OPENQASM 2.0;\nqreg q[2];\nrxx(0.9) q[0], q[1];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertIn("rxx(-0.9) q[0], q[1];", out)

    def test_p_and_cu1_adjoint_negate_angle(self):
        qasm = "OPENQASM 2.0;\nqreg q[2];\np(0.7) q[0];\ncu1(0.2) q[0], q[1];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertIn("p(-0.7) q[0];", out)
        self.assertIn("cu1(-0.2) q[0], q[1];", out)

    def test_cswap_is_self_adjoint(self):
        qasm = "OPENQASM 2.0;\nqreg q[3];\ncswap q[0], q[1], q[2];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertEqual(out.count("cswap q[0], q[1], q[2];"), 2)

    def test_ccx_is_self_adjoint(self):
        qasm = "OPENQASM 2.0;\nqreg q[3];\nccx q[0], q[1], q[2];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertEqual(out.count("ccx q[0], q[1], q[2];"), 2)

    def test_ch_is_self_adjoint(self):
        qasm = "OPENQASM 2.0;\nqreg q[2];\nch q[0], q[1];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertEqual(out.count("ch q[0], q[1];"), 2)

    def test_cy_is_self_adjoint(self):
        qasm = "OPENQASM 2.0;\nqreg q[2];\ncy q[0], q[1];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertEqual(out.count("cy q[0], q[1];"), 2)

    def test_rccx_is_self_adjoint(self):
        qasm = "OPENQASM 2.0;\nqreg q[3];\nrccx q[0], q[1], q[2];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertEqual(out.count("rccx q[0], q[1], q[2];"), 2)

    def test_sx_sxdg_are_adjoint_partners(self):
        qasm = "OPENQASM 2.0;\nqreg q[1];\nsx q[0];\nsxdg q[0];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertIn("sx q[0];", out)
        self.assertIn("sxdg q[0];", out)

    def test_symbolic_cp_cu1_params_preserved(self):
        qasm = "OPENQASM 2.0;\nqreg q[2];\ncp(pi/32) q[0], q[1];\ncu1(theta) q[0], q[1];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertIn("cp(-(pi/32)) q[0], q[1];", out)
        self.assertIn("cu1(-(theta)) q[0], q[1];", out)
        self.assertNotIn("-0.0", out)

    def test_double_negation_is_simplified(self):
        qasm = "OPENQASM 2.0;\nqreg q[2];\ncu1(-pi/16) q[0], q[1];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertIn("cu1(pi/16) q[0], q[1];", out)
        self.assertNotIn("cu1(-(-pi/16))", out)

    def test_zero_negation_simplified_to_zero(self):
        qasm = "OPENQASM 2.0;\nqreg q[1];\nu2(0,0) q[0];\n"
        out, _ = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertIn("u2(0, 0) q[0];", out)
        self.assertNotIn("-0.0", out)

    def test_multi_qreg_width_and_measure_flattening(self):
        qasm = "OPENQASM 2.0;\nqreg q[6];\nqreg flag[1];\nh q[0];\nx flag[0];\n"
        out, n = build_mirror_qasm(qasm, drop_barriers=True)
        self.assertEqual(n, 7)
        self.assertIn("qreg q[6];", out)
        self.assertIn("qreg flag[1];", out)
        self.assertIn("creg c[7];", out)
        self.assertEqual(out.count("measure "), 7)
        self.assertIn("measure q[0] -> c[0];", out)
        self.assertIn("measure q[5] -> c[5];", out)
        self.assertIn("measure flag[0] -> c[6];", out)


if __name__ == "__main__":
    unittest.main()
