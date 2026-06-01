import unittest

from qcoder.engines.feature_extraction.reps.interaction_graph import InteractionGraph
from qcoder.engines.feature_extraction.reps.interaction_graph_metrics import (
    compute_interaction_graph_metrics,
)


class TestInteractionGraphMetrics(unittest.TestCase):
    def test_one_qubit_no_edges(self):
        # A) 1 qubit, no edges
        ig = InteractionGraph(n_qubits=1, edges={})
        m = compute_interaction_graph_metrics(ig)
        self.assertEqual(m.ig_n_components, 1)
        self.assertEqual(m.ig_is_connected, 1)
        self.assertAlmostEqual(m.ig_largest_cc_frac, 1.0)
        self.assertEqual(m.ig_max_degree, 0)
        self.assertAlmostEqual(m.ig_pair_reuse_hhi, 0.0)
        self.assertAlmostEqual(m.ig_pair_reuse_top1_frac, 0.0)

    def test_chain_plus_isolate(self):
        # B) 4 qubits, edges (0,1), (1,2) => 0-1-2 connected, 3 isolated
        ig = InteractionGraph(n_qubits=4, edges={(0, 1): 1, (1, 2): 1})
        m = compute_interaction_graph_metrics(ig)
        self.assertEqual(m.ig_n_components, 2)
        self.assertAlmostEqual(m.ig_largest_cc_frac, 3 / 4)
        # degrees: 0->1, 1->2, 2->1, 3->0 => [1,2,1,0]
        self.assertEqual(m.ig_max_degree, 2)
        self.assertAlmostEqual(m.ig_avg_degree, (1 + 2 + 1 + 0) / 4, places=10)

    def test_star(self):
        # C) 4 qubits, star at 0: edges (0,1), (0,2), (0,3)
        ig = InteractionGraph(n_qubits=4, edges={(0, 1): 1, (0, 2): 1, (0, 3): 1})
        m = compute_interaction_graph_metrics(ig)
        self.assertEqual(m.ig_n_components, 1)
        self.assertEqual(m.ig_is_connected, 1)
        self.assertEqual(m.ig_max_degree, 3)
        # degrees [3,1,1,1]
        self.assertAlmostEqual(m.ig_avg_degree, (3 + 1 + 1 + 1) / 4, places=10)

    def test_pair_reuse_metrics_weighted(self):
        # weighted pair counts: 3,1,2 => total 6
        # hhi = (3/6)^2 + (1/6)^2 + (2/6)^2 = 14/36
        # top1 = 3/6
        ig = InteractionGraph(n_qubits=4, edges={(0, 1): 3, (1, 2): 1, (2, 3): 2})
        m = compute_interaction_graph_metrics(ig)
        self.assertAlmostEqual(m.ig_pair_reuse_hhi, 14.0 / 36.0, places=10)
        self.assertAlmostEqual(m.ig_pair_reuse_top1_frac, 0.5, places=10)


if __name__ == "__main__":
    unittest.main()
