import unittest

from qcoder.engines.feature_extraction.reps.interaction_graph import InteractionGraph
from qcoder.engines.feature_extraction.reps.cut_profile import compute_cut_profile_stats


class TestCutProfile(unittest.TestCase):
    def test_bell_2q(self):
        # 2 qubits => 1 cut; edge (0,1) crosses cut 0
        ig = InteractionGraph(n_qubits=2, edges={(0, 1): 1})
        s = compute_cut_profile_stats(ig)
        self.assertEqual(s.cut_profile, (1.0,))
        self.assertAlmostEqual(s.cut_max, 1.0)
        self.assertAlmostEqual(s.cut_mean, 1.0)
        self.assertAlmostEqual(s.cut_std, 0.0)
        self.assertAlmostEqual(s.cut_entropy, 0.0)
        self.assertEqual(s.n_active_cuts, 1)
        self.assertEqual(s.max_span_in_order, 1)

    def test_three_qubit_long_edge_uniform(self):
        # 3 qubits => cuts [0,1]; edge (0,2) crosses both cuts => [1,1]
        ig = InteractionGraph(n_qubits=3, edges={(0, 2): 1})
        s = compute_cut_profile_stats(ig)
        self.assertEqual(s.cut_profile, (1.0, 1.0))
        # uniform distribution over 2 bins => normalized entropy = 1
        self.assertAlmostEqual(s.cut_entropy, 1.0)

    def test_four_qubit_weighted_mix(self):
        # 4 qubits => cuts [0,1,2]
        # edge (0,3) weight 1 => adds 1 to cuts 0,1,2
        # edge (1,2) weight 2 => adds 2 to cut 1
        # expected [1,3,1]
        ig = InteractionGraph(n_qubits=4, edges={(0, 3): 1, (1, 2): 2})
        s = compute_cut_profile_stats(ig)
        self.assertEqual(s.cut_profile, (1.0, 3.0, 1.0))
        self.assertAlmostEqual(s.cut_max, 3.0)
        self.assertAlmostEqual(s.cut_mean, (1.0 + 3.0 + 1.0) / 3.0)
        self.assertEqual(s.n_active_cuts, 3)
        self.assertEqual(s.max_span_in_order, 3)


if __name__ == "__main__":
    unittest.main()
