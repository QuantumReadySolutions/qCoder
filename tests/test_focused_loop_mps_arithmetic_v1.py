"""Exact MPS bond-rank and coefficient-floor arithmetic, and the five applicability gates."""

import math
import unittest

from qcoder.focused_loop import applicability, contracts, fixtures, identities, mps_floor
from qcoder.focused_loop.canonical import FocusedLoopError, is_digest

PRIMARY_PAIRS = tuple((31 - offset, 32 + offset) for offset in range(15))
HELDOUT_PAIRS = tuple((27 - offset, 28 + offset) for offset in range(15))

CHI_REQUIRED = 32_768
COEFFICIENT_COUNT = 2_863_311_596
PAYLOAD_FLOOR_BYTES = 45_812_985_536
PAYLOAD_FLOOR_GIB = 42.6666676402092
SAFE_ENVELOPE_BYTES = 38_654_705_664
FLOOR_MINUS_ENVELOPE = 7_158_279_872


def _independent_bond_rank(index, pairs):
    """Count spanning pairs directly: bond ``index`` sits between site ``index`` and ``index+1``."""
    spanning = 0
    for left, right in pairs:
        if left <= index < right:
            spanning += 1
    return 2**spanning


def _independent_coefficient_count(qubit_count, pairs):
    total = 0
    for site in range(qubit_count):
        left = 1 if site == 0 else _independent_bond_rank(site - 1, pairs)
        right = 1 if site == qubit_count - 1 else _independent_bond_rank(site, pairs)
        total += 2 * left * right
    return total


class TestBondRankProfile(unittest.TestCase):
    def test_profile_length_and_boundaries(self):
        profile = mps_floor.bond_rank_profile(qubit_count=64, pairs=PRIMARY_PAIRS)
        self.assertEqual(len(profile), 63)
        self.assertEqual(profile[0], 1)
        self.assertEqual(profile[-1], 1)

    def test_central_bond_reaches_two_to_the_fifteenth(self):
        profile = mps_floor.bond_rank_profile(qubit_count=64, pairs=PRIMARY_PAIRS)
        self.assertEqual(profile[31], CHI_REQUIRED)
        self.assertEqual(profile[31], 2**15)
        self.assertEqual(max(profile), CHI_REQUIRED)
        self.assertEqual(profile.index(max(profile)), 31)

    def test_profile_matches_an_independent_count(self):
        profile = mps_floor.bond_rank_profile(qubit_count=64, pairs=PRIMARY_PAIRS)
        for index, value in enumerate(profile):
            self.assertEqual(value, _independent_bond_rank(index, PRIMARY_PAIRS), index)

    def test_profile_grows_by_powers_of_two_toward_the_cut(self):
        profile = mps_floor.bond_rank_profile(qubit_count=64, pairs=PRIMARY_PAIRS)
        for offset in range(16):
            self.assertEqual(profile[16 + offset], 2**offset)

    def test_heldout_cut_also_reaches_the_same_chi(self):
        profile = mps_floor.bond_rank_profile(qubit_count=64, pairs=HELDOUT_PAIRS)
        self.assertEqual(profile[27], CHI_REQUIRED)
        self.assertEqual(max(profile), CHI_REQUIRED)

    def test_chi_required_helper(self):
        self.assertEqual(mps_floor.chi_required(qubit_count=64, pairs=PRIMARY_PAIRS), CHI_REQUIRED)
        self.assertEqual(math.log2(CHI_REQUIRED), 15.0)

    def test_site_bond_dimensions_have_rank_one_boundaries(self):
        dimensions = mps_floor.site_bond_dimensions(qubit_count=64, pairs=PRIMARY_PAIRS)
        self.assertEqual(len(dimensions), 64)
        self.assertEqual(dimensions[0][0], 1)
        self.assertEqual(dimensions[63][1], 1)


class TestCoefficientFloor(unittest.TestCase):
    def setUp(self):
        self.floor = mps_floor.build_coefficient_floor(qubit_count=64, pairs=PRIMARY_PAIRS)

    def test_coefficient_count_is_the_answer_key(self):
        self.assertEqual(
            mps_floor.coefficient_count(qubit_count=64, pairs=PRIMARY_PAIRS), COEFFICIENT_COUNT
        )
        self.assertEqual(
            _independent_coefficient_count(64, PRIMARY_PAIRS), COEFFICIENT_COUNT
        )

    def test_payload_floor_bytes_is_the_answer_key(self):
        self.assertEqual(
            mps_floor.payload_floor_bytes(qubit_count=64, pairs=PRIMARY_PAIRS),
            PAYLOAD_FLOOR_BYTES,
        )
        self.assertEqual(16 * COEFFICIENT_COUNT, PAYLOAD_FLOOR_BYTES)

    def test_floor_gib_is_the_answer_key(self):
        self.assertEqual(self.floor["payload_floor_gib"], PAYLOAD_FLOOR_GIB)
        self.assertAlmostEqual(
            self.floor["payload_floor_gib"], PAYLOAD_FLOOR_BYTES / 1024**3, places=12
        )

    def test_floor_records_procedure_and_units(self):
        self.assertEqual(self.floor["procedure_id"], identities.MPS_FLOOR_PROCEDURE_ID)
        self.assertEqual(self.floor["procedure_id"], "mps_dense_complex128_coefficient_floor_v1")
        self.assertEqual(self.floor["coefficient_bytes"], 16)
        self.assertEqual(self.floor["physical_dimension"], 2)
        self.assertEqual(self.floor["bound_kind"], "lower_bound_payload_only")
        self.assertTrue(is_digest(self.floor["floor_digest"]))

    def test_floor_records_every_mandatory_exclusion(self):
        self.assertEqual(self.floor["exclusions"], sorted(identities.MPS_FLOOR_EXCLUSIONS))
        for exclusion in (
            "aer_python_overhead",
            "allocator_effects",
            "metadata",
            "result_materialization",
            "temporary_decomposition_svd_workspace",
        ):
            self.assertIn(exclusion, self.floor["exclusions"])

    def test_incomplete_exclusions_are_rejected(self):
        with self.assertRaises(FocusedLoopError) as caught:
            mps_floor.build_coefficient_floor(
                qubit_count=64, pairs=PRIMARY_PAIRS, exclusions=("metadata",)
            )
        self.assertEqual(caught.exception.category, "mps_floor_exclusions_incomplete")

    def test_heldout_floor_equals_primary_floor(self):
        heldout = mps_floor.build_coefficient_floor(qubit_count=64, pairs=HELDOUT_PAIRS)
        self.assertEqual(heldout["payload_floor_bytes"], PAYLOAD_FLOOR_BYTES)
        self.assertEqual(heldout["coefficient_count"], COEFFICIENT_COUNT)


class TestChiRequiredClaim(unittest.TestCase):
    def setUp(self):
        self.claim = mps_floor.build_chi_required_claim(
            claim_id="claim-1", qubit_count=64, pairs=PRIMARY_PAIRS
        )

    def test_claim_records_chi_and_derivation(self):
        self.assertEqual(self.claim["schema_id"], identities.CHI_REQUIRED_CLAIM_SCHEMA_ID)
        self.assertEqual(self.claim["chi_required"], CHI_REQUIRED)
        self.assertEqual(self.claim["chi_required_log2"], 15)
        self.assertEqual(self.claim["maximum_bond_index"], 31)
        self.assertEqual(self.claim["boundary_bond_rank"], 1)
        self.assertEqual(self.claim["derivation_id"], identities.CHI_DERIVATION_ID)
        self.assertEqual(self.claim["evidence_class"], "exact_family_specific")
        self.assertEqual(self.claim["ordering_assumption"], "natural_order")

    def test_claim_carries_the_mandatory_limitation(self):
        self.assertEqual(self.claim["limitations"], [identities.AER_MPS_LIMITATION])
        self.assertEqual(
            self.claim["limitations"],
            ["aer_internal_mps_qubit_reordering_not_characterized"],
        )

    def test_claim_never_generalizes(self):
        self.assertEqual(
            self.claim["claim_scope"], "declared_natural_order_nested_bell_construction_only"
        )
        for non_claim in (
            "not_a_claim_about_aer_mps_internal_qubit_reordering",
            "not_a_claim_about_alternative_internal_representations",
            "not_a_claim_about_arbitrary_clifford_circuits",
            "not_a_claim_about_transpiler_or_optimizer_transformations",
        ):
            self.assertIn(non_claim, self.claim["non_claims"])

    def test_claim_embeds_the_coefficient_floor(self):
        self.assertEqual(
            self.claim["coefficient_floor"]["payload_floor_bytes"], PAYLOAD_FLOOR_BYTES
        )

    def test_claim_rejects_a_non_natural_ordering_assumption(self):
        with self.assertRaises(FocusedLoopError) as caught:
            mps_floor.build_chi_required_claim(
                claim_id="claim-1",
                qubit_count=64,
                pairs=PRIMARY_PAIRS,
                ordering_assumption="aer_internal_order",
            )
        self.assertEqual(
            caught.exception.category, "chi_claim_ordering_assumption_invalid"
        )


class TestPairValidation(unittest.TestCase):
    def test_reversed_pair_rejected(self):
        with self.assertRaises(FocusedLoopError) as caught:
            mps_floor.bond_rank_profile(qubit_count=8, pairs=((5, 2),))
        self.assertEqual(caught.exception.category, "mps_pair_order_invalid")

    def test_reused_qubit_rejected(self):
        with self.assertRaises(FocusedLoopError) as caught:
            mps_floor.bond_rank_profile(qubit_count=8, pairs=((1, 3), (3, 5)))
        self.assertEqual(caught.exception.category, "mps_pair_qubit_reused")

    def test_out_of_range_index_rejected(self):
        with self.assertRaises(FocusedLoopError) as caught:
            mps_floor.bond_rank_profile(qubit_count=8, pairs=((1, 9),))
        self.assertEqual(caught.exception.category, "mps_pair_index_invalid")

    def test_empty_and_malformed_pair_lists_rejected(self):
        for pairs in ((), "12", ((1,),), ((1, 2, 3),)):
            with self.assertRaises(FocusedLoopError):
                mps_floor.bond_rank_profile(qubit_count=8, pairs=pairs)

    def test_boolean_index_rejected(self):
        with self.assertRaises(FocusedLoopError):
            mps_floor.bond_rank_profile(qubit_count=8, pairs=((True, 3),))


class TestFloorEnvelopeComparison(unittest.TestCase):
    def setUp(self):
        self.floor = mps_floor.build_coefficient_floor(qubit_count=64, pairs=PRIMARY_PAIRS)

    def test_floor_exceeds_the_synthetic_safe_envelope_by_the_exact_amount(self):
        comparison = mps_floor.compare_floor_to_envelope(
            floor=self.floor, safe_envelope_bytes=SAFE_ENVELOPE_BYTES
        )
        self.assertTrue(comparison["floor_exceeds_envelope"])
        self.assertEqual(comparison["excess_bytes"], FLOOR_MINUS_ENVELOPE)
        self.assertEqual(comparison["excess_bytes"], PAYLOAD_FLOOR_BYTES - SAFE_ENVELOPE_BYTES)
        self.assertEqual(comparison["headroom_bytes"], 0)

    def test_comparison_uses_the_receipt_derived_envelope(self):
        receipt = contracts.build_synthetic_resource_receipt()
        comparison = mps_floor.compare_floor_to_envelope(
            floor=self.floor, safe_envelope_bytes=receipt["safe_envelope_bytes"]
        )
        self.assertEqual(comparison["excess_bytes"], FLOOR_MINUS_ENVELOPE)

    def test_comparison_rejects_a_foreign_floor_record(self):
        with self.assertRaises(FocusedLoopError) as caught:
            mps_floor.compare_floor_to_envelope(
                floor={"payload_floor_bytes": 1}, safe_envelope_bytes=2
            )
        self.assertEqual(caught.exception.category, "mps_floor_record_invalid")


class TestFeasibilityNeverClaimsFeasible(unittest.TestCase):
    def test_feasible_is_not_an_expressible_value(self):
        self.assertNotIn("feasible", applicability.FEASIBILITY_VALUES)
        self.assertEqual(applicability.FORBIDDEN_FEASIBILITY_VALUE, "feasible")

    def test_floor_above_envelope_is_infeasible(self):
        floor = mps_floor.build_coefficient_floor(qubit_count=64, pairs=PRIMARY_PAIRS)
        record = applicability.evaluate_method_applicability(
            applicability_id="a",
            method=identities.METHOD_MPS_EXACT,
            coefficient_floor=floor,
            safe_envelope_bytes=SAFE_ENVELOPE_BYTES,
        )
        self.assertEqual(record["feasibility"], "infeasible_lower_bound_exceeds_envelope")

    def test_floor_below_envelope_is_only_not_established(self):
        small = mps_floor.build_coefficient_floor(qubit_count=8, pairs=((3, 4),))
        record = applicability.evaluate_method_applicability(
            applicability_id="a",
            method=identities.METHOD_MPS_EXACT,
            coefficient_floor=small,
            safe_envelope_bytes=SAFE_ENVELOPE_BYTES,
        )
        self.assertLess(small["payload_floor_bytes"], SAFE_ENVELOPE_BYTES)
        self.assertEqual(record["feasibility"], "not_established")
        self.assertNotEqual(record["feasibility"], "feasible")

    def test_no_evaluation_ever_reports_feasible(self):
        floor = mps_floor.build_coefficient_floor(qubit_count=64, pairs=PRIMARY_PAIRS)
        for method in contracts.METHODS:
            for envelope in (SAFE_ENVELOPE_BYTES, PAYLOAD_FLOOR_BYTES * 4):
                record = applicability.evaluate_method_applicability(
                    applicability_id="a",
                    method=method,
                    coefficient_floor=floor,
                    safe_envelope_bytes=envelope,
                )
                self.assertIn(record["feasibility"], applicability.FEASIBILITY_VALUES)
                self.assertNotEqual(record["feasibility"], "feasible")


class TestFiveIndependentGates(unittest.TestCase):
    def setUp(self):
        self.floor = mps_floor.build_coefficient_floor(qubit_count=64, pairs=PRIMARY_PAIRS)
        self.envelope = contracts.build_synthetic_resource_receipt()["safe_envelope_bytes"]

    def _evaluate(self, method, **overrides):
        return applicability.evaluate_method_applicability(
            applicability_id="a",
            method=method,
            coefficient_floor=self.floor,
            safe_envelope_bytes=self.envelope,
            **overrides,
        )

    def test_gate_set_is_exactly_the_five_declared_gates(self):
        record = self._evaluate(identities.METHOD_STABILIZER)
        self.assertEqual(
            sorted(record["gates"]),
            [
                "available",
                "family_applicable",
                "qualified",
                "result_capable",
                "satisfies_exactness",
            ],
        )
        self.assertEqual(len(applicability.GATE_NAMES), 5)

    def test_mps_exact_is_rejected_by_the_lower_bound_comparison(self):
        record = self._evaluate(identities.METHOD_MPS_EXACT)
        self.assertTrue(record["gates_all_passed"])
        self.assertFalse(record["selected"])
        self.assertEqual(record["rejection_reason"], "resource_lower_bound_exceeded")
        self.assertEqual(record["resource_comparison"]["excess_bytes"], FLOOR_MINUS_ENVELOPE)

    def test_availability_alone_never_selects(self):
        record = self._evaluate(identities.METHOD_MPS_EXACT)
        self.assertTrue(record["gates"]["available"])
        self.assertFalse(record["selected"])

    def test_mps_approximate_conflicts_with_exact_required(self):
        record = self._evaluate(identities.METHOD_MPS_APPROXIMATE)
        self.assertFalse(record["gates"]["satisfies_exactness"])
        self.assertFalse(record["selected"])
        self.assertEqual(record["rejection_reason"], "exactness_policy_conflict")

    def test_mps_approximate_is_never_a_silent_downgrade(self):
        evaluations = applicability.evaluate_regime_methods(
            applicability_prefix="p",
            coefficient_floor=self.floor,
            safe_envelope_bytes=self.envelope,
        )
        self.assertFalse(evaluations[identities.METHOD_MPS_APPROXIMATE]["selected"])
        self.assertEqual(
            applicability.selected_method(evaluations), identities.METHOD_STABILIZER
        )

    def test_stabilizer_selected_only_when_all_five_gates_pass(self):
        record = self._evaluate(identities.METHOD_STABILIZER)
        self.assertTrue(record["selected"])
        for gate in applicability.GATE_NAMES:
            if gate == "satisfies_exactness":
                continue
            degraded = self._evaluate(identities.METHOD_STABILIZER, **{gate: False})
            self.assertFalse(degraded["selected"], gate)
            self.assertIsNotNone(degraded["rejection_reason"])

    def test_non_clifford_circuit_makes_stabilizer_unsupported(self):
        record = self._evaluate(identities.METHOD_STABILIZER, family_applicable=False)
        self.assertFalse(record["gates"]["family_applicable"])
        self.assertFalse(record["selected"])
        self.assertEqual(record["rejection_reason"], "family_not_applicable")
        self.assertEqual(record["feasibility"], "unsupported")

    def test_non_clifford_circuit_selects_nothing(self):
        evaluations = applicability.evaluate_regime_methods(
            applicability_prefix="p",
            coefficient_floor=self.floor,
            safe_envelope_bytes=self.envelope,
            family_applicable=False,
        )
        self.assertIsNone(applicability.selected_method(evaluations))
        for record in evaluations.values():
            self.assertEqual(record["rejection_reason"], "family_not_applicable")

    def test_applicability_carries_the_mandatory_limitation(self):
        record = self._evaluate(identities.METHOD_STABILIZER)
        self.assertEqual(record["limitations"], [identities.AER_MPS_LIMITATION])

    def test_unsupported_method_and_policy_fail_closed(self):
        with self.assertRaises(FocusedLoopError) as caught:
            self._evaluate("statevector")
        self.assertEqual(caught.exception.category, "applicability_method_unsupported")
        with self.assertRaises(FocusedLoopError) as caught:
            self._evaluate(identities.METHOD_MPS_EXACT, exactness_policy="approximate_allowed")
        self.assertEqual(
            caught.exception.category, "applicability_exactness_policy_unsupported"
        )

    def test_mps_requires_resource_evidence(self):
        with self.assertRaises(FocusedLoopError) as caught:
            applicability.evaluate_method_applicability(
                applicability_id="a", method=identities.METHOD_MPS_EXACT
            )
        self.assertEqual(
            caught.exception.category, "applicability_resource_evidence_missing"
        )

    def test_the_primary_fixture_flows_through_the_same_path(self):
        materialized = fixtures.materialize_fixture(fixtures.PRIMARY_FAMILY_PARAMETERS)
        self.assertEqual(
            materialized["coefficient_floor"]["payload_floor_bytes"], PAYLOAD_FLOOR_BYTES
        )


if __name__ == "__main__":
    unittest.main()
