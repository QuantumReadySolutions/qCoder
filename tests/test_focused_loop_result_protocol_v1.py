"""Stabilizer-predicate result protocol: evaluation, decision semantics, and next action."""

import json
import unittest

from qcoder.focused_loop import fixtures, identities, result_protocol
from qcoder.focused_loop.canonical import FocusedLoopError, canonical_bytes, is_digest

PARAMS = fixtures.PRIMARY_FAMILY_PARAMETERS
ANSWER_KEY = fixtures.build_answer_key(PARAMS)
ALLOWED = fixtures.allowed_outcomes(PARAMS)

#: ``c[0] = 1`` and ``c[1] = 0`` under the recorded ordering: pair zero disagrees.
VIOLATING_OUTCOME = "000000000001"

#: ``c[0] != c[1]`` and ``c[2] != c[3]``: pairs zero and one both disagree.
DOUBLE_VIOLATING_OUTCOME = "000000000101"

ORDERING = fixtures.COUNTS_BITSTRING_ORDERING


def _analysis(counts, **overrides):
    return result_protocol.build_analysis_result(
        analysis_id="analysis-1", counts=counts, answer_key=ANSWER_KEY, **overrides
    )


class TestPredicateEvaluation(unittest.TestCase):
    def test_every_allowed_outcome_satisfies_every_constraint(self):
        counts = {outcome: 1 for outcome in ALLOWED}
        evaluation = result_protocol.evaluate_predicate_satisfaction(
            counts=counts, answer_key=ANSWER_KEY, bitstring_ordering=ORDERING
        )
        self.assertEqual(evaluation["shots_evaluated"], 64)
        self.assertEqual(evaluation["satisfying_shots"], 64)
        self.assertEqual(evaluation["point_estimate"], 1.0)
        self.assertEqual(evaluation["distinct_outcomes_observed"], 64)
        self.assertEqual(evaluation["allowed_support_size"], 64)
        self.assertEqual(evaluation["violations"]["count"], 0)
        self.assertEqual(evaluation["violations"]["constraint_ids"], [])

    def test_violating_outcome_is_attributed_to_the_right_constraint(self):
        evaluation = result_protocol.evaluate_predicate_satisfaction(
            counts={ALLOWED[0]: 597, VIOLATING_OUTCOME: 1},
            answer_key=ANSWER_KEY,
            bitstring_ordering=ORDERING,
        )
        self.assertEqual(evaluation["shots_evaluated"], 598)
        self.assertEqual(evaluation["satisfying_shots"], 597)
        self.assertEqual(evaluation["violations"]["count"], 1)
        self.assertEqual(evaluation["violations"]["constraint_ids"], ["bell_parity_0"])

    def test_multiple_violated_constraints_are_reported(self):
        evaluation = result_protocol.evaluate_predicate_satisfaction(
            counts={DOUBLE_VIOLATING_OUTCOME: 4},
            answer_key=ANSWER_KEY,
            bitstring_ordering=ORDERING,
        )
        self.assertEqual(evaluation["satisfying_shots"], 0)
        self.assertEqual(
            evaluation["violations"]["constraint_ids"], ["bell_parity_0", "bell_parity_1"]
        )
        self.assertEqual(evaluation["violations"]["distinct_constraint_count"], 2)

    def test_zero_count_entries_are_not_accepted_shots(self):
        evaluation = result_protocol.evaluate_predicate_satisfaction(
            counts={ALLOWED[0]: 10, ALLOWED[1]: 0},
            answer_key=ANSWER_KEY,
            bitstring_ordering=ORDERING,
        )
        self.assertEqual(evaluation["shots_evaluated"], 10)
        self.assertEqual(evaluation["distinct_outcomes_observed"], 1)

    def test_unsupported_ordering_fails_closed(self):
        for ordering in ("big_endian", "unknown", "", ORDERING.upper()):
            with self.assertRaises(FocusedLoopError) as caught:
                result_protocol.evaluate_predicate_satisfaction(
                    counts={ALLOWED[0]: 1},
                    answer_key=ANSWER_KEY,
                    bitstring_ordering=ordering,
                )
            self.assertEqual(
                caught.exception.category, "result_protocol_bitstring_ordering_unsupported"
            )

    def test_wrong_width_or_alphabet_outcome_rejected(self):
        for outcome in ("0" * 11, "0" * 13, "00000000000x", "00000000002"):
            with self.assertRaises(FocusedLoopError):
                result_protocol.evaluate_predicate_satisfaction(
                    counts={outcome: 1},
                    answer_key=ANSWER_KEY,
                    bitstring_ordering=ORDERING,
                )

    def test_empty_and_all_zero_count_samples_rejected(self):
        with self.assertRaises(FocusedLoopError) as caught:
            result_protocol.evaluate_predicate_satisfaction(
                counts={}, answer_key=ANSWER_KEY, bitstring_ordering=ORDERING
            )
        self.assertEqual(caught.exception.category, "result_protocol_counts_invalid")
        with self.assertRaises(FocusedLoopError) as caught:
            result_protocol.evaluate_predicate_satisfaction(
                counts={ALLOWED[0]: 0}, answer_key=ANSWER_KEY, bitstring_ordering=ORDERING
            )
        self.assertEqual(caught.exception.category, "result_protocol_sample_size_invalid")

    def test_non_integer_count_rejected(self):
        for count in (1.0, "1", True, -1):
            with self.assertRaises(FocusedLoopError):
                result_protocol.evaluate_predicate_satisfaction(
                    counts={ALLOWED[0]: count},
                    answer_key=ANSWER_KEY,
                    bitstring_ordering=ORDERING,
                )

    def test_foreign_answer_key_rejected(self):
        with self.assertRaises(FocusedLoopError) as caught:
            result_protocol.evaluate_predicate_satisfaction(
                counts={ALLOWED[0]: 1},
                answer_key={"schema_id": "qcoder.other.v1"},
                bitstring_ordering=ORDERING,
            )
        self.assertEqual(caught.exception.category, "result_protocol_answer_key_invalid")


class TestClopperPearsonBoundContract(unittest.TestCase):
    def test_declared_answer_keys(self):
        self.assertEqual(
            result_protocol.clopper_pearson_lower_bound(successes=597, trials=597),
            0.9949945920065333,
        )
        self.assertEqual(
            result_protocol.clopper_pearson_lower_bound(successes=598, trials=598),
            0.9950029413057535,
        )
        self.assertEqual(
            result_protocol.clopper_pearson_lower_bound(successes=599, trials=599),
            0.9950112627972248,
        )

    def test_five_ninety_seven_misses_the_target_and_five_ninety_eight_meets_it(self):
        self.assertLess(
            result_protocol.clopper_pearson_lower_bound(successes=597, trials=597),
            identities.TARGET_LOWER_BOUND,
        )
        self.assertGreaterEqual(
            result_protocol.clopper_pearson_lower_bound(successes=598, trials=598),
            identities.TARGET_LOWER_BOUND,
        )
        self.assertGreater(
            result_protocol.clopper_pearson_lower_bound(successes=599, trials=599),
            result_protocol.clopper_pearson_lower_bound(successes=598, trials=598),
        )

    def test_zero_successes_gives_a_zero_lower_bound(self):
        self.assertEqual(
            result_protocol.clopper_pearson_lower_bound(successes=0, trials=598), 0.0
        )

    def test_bound_is_monotone_in_successes(self):
        values = [
            result_protocol.clopper_pearson_lower_bound(successes=k, trials=598)
            for k in (500, 550, 590, 597, 598)
        ]
        self.assertEqual(values, sorted(values))

    def test_fail_closed_negatives(self):
        cases = {
            "result_protocol_sample_size_invalid": {"successes": 0, "trials": 0},
            "result_protocol_success_count_exceeds_sample": {"successes": 599, "trials": 598},
            "result_protocol_success_count_invalid": {"successes": -1, "trials": 598},
        }
        for category, kwargs in cases.items():
            with self.assertRaises(FocusedLoopError) as caught:
                result_protocol.clopper_pearson_lower_bound(**kwargs)
            self.assertEqual(caught.exception.category, category)

    def test_non_integer_inputs_rejected(self):
        for kwargs in (
            {"successes": 597.0, "trials": 598},
            {"successes": 597, "trials": 598.0},
            {"successes": True, "trials": 598},
            {"successes": "597", "trials": 598},
        ):
            with self.assertRaises(FocusedLoopError):
                result_protocol.clopper_pearson_lower_bound(**kwargs)

    def test_wrong_confidence_level_rejected(self):
        for level in (0.9, 0.99, 0.5, 1.0):
            with self.assertRaises(FocusedLoopError) as caught:
                result_protocol.clopper_pearson_lower_bound(
                    successes=598, trials=598, confidence_level=level
                )
            self.assertEqual(
                caught.exception.category, "result_protocol_confidence_level_unsupported"
            )


class TestTargetMetPath(unittest.TestCase):
    def setUp(self):
        self.analysis = _analysis({ALLOWED[0]: 598})
        self.action = result_protocol.build_next_action(
            action_id="action-1", analysis_result=self.analysis
        )

    def test_conclusion_sampling_state_and_action_are_separate_fields(self):
        self.assertEqual(self.analysis["evidence_conclusion"], "target_met")
        self.assertEqual(self.analysis["sampling_state"], "sampling_sufficient_stop_sampling")
        self.assertNotIn("next_action", self.analysis)
        self.assertNotIn("action", self.analysis)
        self.assertEqual(self.action["action"], "stop_goal_met")
        self.assertTrue(self.action["combination_valid"])

    def test_interval_records_the_exact_bound(self):
        interval = self.analysis["interval"]
        self.assertEqual(interval["kind"], "one_sided_exact_clopper_pearson_lower_bound")
        self.assertEqual(interval["level"], 0.95)
        self.assertEqual(interval["lower"], 0.9950029413057535)
        self.assertGreaterEqual(interval["lower"], 0.995)

    def test_analysis_result_records_every_required_field(self):
        for field in (
            "result_protocol_id",
            "result_protocol_version",
            "quantity",
            "reference_digest",
            "estimator_id",
            "shots_evaluated",
            "satisfying_shots",
            "point_estimate",
            "interval",
            "interval_semantics",
            "violations",
            "distinct_outcomes_observed",
            "allowed_support_size",
            "evidence_conclusion",
            "non_claims",
        ):
            self.assertIn(field, self.analysis, field)
        self.assertEqual(
            self.analysis["result_protocol_id"], identities.RESULT_PROTOCOL_SCHEMA_ID
        )
        self.assertEqual(self.analysis["reference_digest"], ANSWER_KEY["record_digest"])
        self.assertEqual(self.analysis["shots_evaluated"], 598)
        self.assertEqual(self.analysis["satisfying_shots"], 598)
        self.assertEqual(self.analysis["point_estimate"], 1.0)
        self.assertEqual(self.analysis["allowed_support_size"], 64)

    def test_non_claims_are_complete(self):
        for non_claim in (
            "not_a_general_fidelity_estimator",
            "not_a_global_state_equality_proof",
            "not_general_simulator_validation",
            "not_noise_characterization",
            "not_process_fidelity",
            "not_qpu_reliability",
            "not_state_fidelity",
            "not_universal_clifford_correctness",
        ):
            self.assertIn(non_claim, self.analysis["non_claims"])

    def test_records_are_canonical_and_sealed(self):
        for record in (self.analysis, self.action):
            self.assertTrue(is_digest(record["record_digest"]))
            self.assertEqual(json.loads(canonical_bytes(record).decode()), record)

    def test_next_action_binds_to_the_analysis_digest(self):
        self.assertEqual(
            self.action["analysis_result_digest"], self.analysis["record_digest"]
        )

    def test_five_ninety_seven_clean_shots_do_not_reach_the_target(self):
        analysis = _analysis({ALLOWED[0]: 597})
        self.assertLess(analysis["interval"]["lower"], 0.995)
        self.assertEqual(analysis["evidence_conclusion"], "inconclusive")


class TestPredicateViolationPath(unittest.TestCase):
    def setUp(self):
        self.analysis = _analysis({ALLOWED[0]: 597, VIOLATING_OUTCOME: 1})
        self.action = result_protocol.build_next_action(
            action_id="action-1", analysis_result=self.analysis
        )

    def test_conclusion_is_target_not_met(self):
        self.assertEqual(self.analysis["evidence_conclusion"], "target_not_met")
        self.assertEqual(self.analysis["violations"]["count"], 1)
        self.assertEqual(self.analysis["violations"]["constraint_ids"], ["bell_parity_0"])

    def test_sampling_is_finished_for_this_decision(self):
        self.assertEqual(self.analysis["sampling_state"], "sampling_sufficient_stop_sampling")

    def test_next_action_is_unsupported_with_an_investigation_reason(self):
        self.assertEqual(self.action["action"], "unsupported")
        self.assertEqual(
            self.action["rationale"], "exact_predicate_violation_requires_investigation"
        )
        self.assertFalse(self.action["automatic_execution"])

    def test_a_violation_never_requests_more_shots(self):
        serialized = canonical_bytes([self.analysis, self.action]).decode()
        self.assertNotIn("collect_more_shots", serialized)

    def test_a_violation_never_diagnoses_approximation_or_a_method_change(self):
        serialized = canonical_bytes([self.analysis, self.action]).decode()
        for forbidden in (
            "systematic_approximation",
            "approximation_error",
            "switch_method",
            "method_change",
            "mps_approximate",
            "silent_rerun",
            "rerun",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_more_shots_cannot_erase_the_contradiction(self):
        larger = _analysis({ALLOWED[0]: 5_000, VIOLATING_OUTCOME: 1})
        self.assertEqual(larger["evidence_conclusion"], "target_not_met")
        self.assertEqual(larger["sampling_state"], "sampling_sufficient_stop_sampling")
        self.assertEqual(
            result_protocol.build_next_action(action_id="a", analysis_result=larger)["action"],
            "unsupported",
        )


class TestUndersizedCleanEvidencePath(unittest.TestCase):
    def setUp(self):
        self.analysis = _analysis({ALLOWED[0]: 300, ALLOWED[1]: 200})
        self.action = result_protocol.build_next_action(
            action_id="action-1", analysis_result=self.analysis
        )

    def test_conclusion_is_inconclusive_with_collect_more_shots_sampling_state(self):
        self.assertEqual(self.analysis["shots_evaluated"], 500)
        self.assertEqual(self.analysis["satisfying_shots"], 500)
        self.assertEqual(self.analysis["evidence_conclusion"], "inconclusive")
        self.assertEqual(self.analysis["sampling_state"], "collect_more_shots")

    def test_next_action_is_not_an_automatic_execution(self):
        self.assertEqual(self.action["action"], "await_user_decision")
        self.assertFalse(self.action["automatic_execution"])
        self.assertNotEqual(self.action["action"], "collect_more_shots")

    def test_no_adaptive_batch_size_is_emitted_anywhere(self):
        serialized = canonical_bytes([self.analysis, self.action]).decode().casefold()
        for forbidden in ("batch", "batch_size", "additional_shots", "next_shots", "increment"):
            self.assertNotIn(forbidden, serialized)

    def test_no_shot_count_other_than_the_declared_fixed_and_observed_counts(self):
        self.assertEqual(self.analysis["declared_fixed_shots"], 598)
        self.assertEqual(self.analysis["shots_evaluated"], 500)


class TestUnsupportedEvidencePaths(unittest.TestCase):
    def test_stale_invalid_and_unbound_evidence_is_unsupported(self):
        for state in ("invalid", "stale", "ambiguous_ordering", "unbound"):
            analysis = _analysis({ALLOWED[0]: 598}, evidence_state=state)
            self.assertEqual(analysis["evidence_conclusion"], "unsupported", state)
            self.assertIsNone(analysis["interval"])
            self.assertEqual(analysis["sampling_state"], "sampling_state_undetermined")
            self.assertEqual(analysis["unsupported_reason"], f"evidence_{state}")
            action = result_protocol.build_next_action(action_id="a", analysis_result=analysis)
            self.assertEqual(action["action"], "diagnostic_required")

    def test_incomplete_execution_is_unsupported(self):
        for state in ("completed_failure", "not_run", "aborted"):
            analysis = _analysis({ALLOWED[0]: 598}, execution_state=state)
            self.assertEqual(analysis["evidence_conclusion"], "unsupported", state)
            self.assertIsNone(analysis["interval"])

    def test_oversized_sample_is_unsupported_not_target_met(self):
        analysis = _analysis({ALLOWED[0]: 599})
        self.assertEqual(analysis["evidence_conclusion"], "unsupported")
        self.assertEqual(
            analysis["unsupported_reason"], "shot_count_exceeds_declared_fixed_shots"
        )

    def test_unknown_evidence_or_execution_state_rejected(self):
        with self.assertRaises(FocusedLoopError) as caught:
            _analysis({ALLOWED[0]: 598}, evidence_state="probably_fine")
        self.assertEqual(
            caught.exception.category, "result_protocol_evidence_state_invalid"
        )
        with self.assertRaises(FocusedLoopError) as caught:
            _analysis({ALLOWED[0]: 598}, execution_state="mostly_done")
        self.assertEqual(
            caught.exception.category, "result_protocol_execution_state_invalid"
        )


class TestNextActionContract(unittest.TestCase):
    def test_collect_more_shots_is_never_an_action(self):
        for (_, _), (action, _) in result_protocol.ACTION_TABLE.items():
            self.assertNotEqual(action, "collect_more_shots")

    def test_every_table_action_is_a_supported_action(self):
        for action, _ in result_protocol.ACTION_TABLE.values():
            self.assertIn(action, result_protocol.SUPPORTED_ACTIONS)

    def test_combination_validity_is_explicit(self):
        self.assertTrue(
            result_protocol.combination_valid(
                evidence_conclusion="target_met",
                sampling_state="sampling_sufficient_stop_sampling",
                action="stop_goal_met",
            )
        )
        self.assertFalse(
            result_protocol.combination_valid(
                evidence_conclusion="target_not_met",
                sampling_state="collect_more_shots",
                action="stop_goal_met",
            )
        )
        self.assertFalse(
            result_protocol.combination_valid(
                evidence_conclusion="target_not_met",
                sampling_state="sampling_sufficient_stop_sampling",
                action="stop_goal_met",
            )
        )

    def test_user_selection_is_preserved_without_rewriting_the_conclusion(self):
        analysis = _analysis({ALLOWED[0]: 597, VIOLATING_OUTCOME: 1})
        action = result_protocol.build_next_action(
            action_id="a", analysis_result=analysis, user_selected_action="diagnostic_required"
        )
        self.assertEqual(action["evidence_conclusion"], "target_not_met")
        self.assertEqual(action["action"], "unsupported")
        self.assertEqual(action["user_selected_action"], "diagnostic_required")
        self.assertFalse(action["user_selection_rewrites_conclusion"])

    def test_unsupported_user_selection_rejected(self):
        analysis = _analysis({ALLOWED[0]: 598})
        with self.assertRaises(FocusedLoopError) as caught:
            result_protocol.build_next_action(
                action_id="a", analysis_result=analysis, user_selected_action="collect_more_shots"
            )
        self.assertEqual(
            caught.exception.category, "next_action_user_selection_unsupported"
        )

    def test_foreign_analysis_record_rejected(self):
        with self.assertRaises(FocusedLoopError) as caught:
            result_protocol.build_next_action(
                action_id="a", analysis_result={"evidence_conclusion": "target_met"}
            )
        self.assertEqual(
            caught.exception.category, "next_action_analysis_result_invalid"
        )

    def test_unsupported_protocol_identity_rejected(self):
        analysis = dict(_analysis({ALLOWED[0]: 598}))
        analysis["schema_id"] = "qcoder.analysis_result.v2"
        with self.assertRaises(FocusedLoopError):
            result_protocol.build_next_action(action_id="a", analysis_result=analysis)


if __name__ == "__main__":
    unittest.main()
