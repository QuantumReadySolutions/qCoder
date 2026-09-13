"""Contract records: objective, execution profile, resource receipt, candidate proposal."""

import json
import unittest

from qcoder.focused_loop import contracts, identities
from qcoder.focused_loop.canonical import (
    FocusedLoopError,
    canonical_bytes,
    digest_excluding,
    is_digest,
)


def _category(assertion):
    return assertion.exception.category


class TestObjectiveRecord(unittest.TestCase):
    def test_objective_is_sealed_and_canonical(self):
        record = contracts.build_evidence_objective(objective_id="obj-1")
        self.assertEqual(record["schema_id"], identities.OBJECTIVE_SCHEMA_ID)
        self.assertEqual(record["regime_id"], identities.REGIME_ID)
        self.assertEqual(
            record["exactness_policy"], identities.EXACTNESS_POLICY_EXACT_REQUIRED
        )
        self.assertEqual(record["shots"], identities.FIXED_SHOTS)
        self.assertEqual(record["confidence_level"], identities.CONFIDENCE_LEVEL)
        self.assertEqual(record["target_lower_bound"], identities.TARGET_LOWER_BOUND)
        self.assertEqual(record["evidence_class"], "exact_family_specific")
        self.assertTrue(is_digest(record[contracts.RECORD_DIGEST_FIELD]))
        self.assertEqual(
            record[contracts.RECORD_DIGEST_FIELD],
            digest_excluding(record, field=contracts.RECORD_DIGEST_FIELD),
        )
        self.assertEqual(json.loads(canonical_bytes(record).decode()), record)

    def test_objective_records_non_goals(self):
        record = contracts.build_evidence_objective(objective_id="obj-1")
        for non_goal in (
            "no_adaptive_shot_policy",
            "no_general_fidelity_estimate",
            "no_general_simulator_ranking",
            "no_remote_or_qpu_execution",
            "no_runtime_reconciliation",
            "no_state_fidelity_estimate",
        ):
            self.assertIn(non_goal, record["non_goals"])

    def test_objective_rejects_approximate_policy(self):
        with self.assertRaises(FocusedLoopError) as caught:
            contracts.build_evidence_objective(
                objective_id="obj-1", exactness_policy="approximate_allowed"
            )
        self.assertEqual(_category(caught), "objective_exactness_policy_unsupported")

    def test_objective_rejects_unsupported_confidence_level(self):
        with self.assertRaises(FocusedLoopError) as caught:
            contracts.build_evidence_objective(objective_id="obj-1", confidence_level=0.99)
        self.assertEqual(_category(caught), "confidence_level_unsupported")

    def test_objective_rejects_blank_id(self):
        with self.assertRaises(FocusedLoopError) as caught:
            contracts.build_evidence_objective(objective_id="  ")
        self.assertEqual(_category(caught), "objective_id_invalid")


class TestAlphaIsExact(unittest.TestCase):
    def test_alpha_is_not_computed_by_float_subtraction(self):
        self.assertEqual(contracts.confidence_alpha(0.95), 0.05)
        self.assertNotEqual(1 - 0.95, 0.05)

    def test_unsupported_level_fails_closed(self):
        for level in (0.9, 0.99, 1.0, 0.0, -0.95):
            with self.assertRaises(FocusedLoopError):
                contracts.confidence_alpha(level)

    def test_non_numeric_level_rejected(self):
        with self.assertRaises(FocusedLoopError):
            contracts.confidence_alpha("0.95")


class TestExecutionProfile(unittest.TestCase):
    def test_profile_is_sealed(self):
        record = contracts.build_execution_profile(
            profile_id="prof-1",
            method=identities.METHOD_STABILIZER,
            circuit_family_class="clifford_only",
        )
        self.assertEqual(record["schema_id"], identities.EXECUTION_PROFILE_SCHEMA_ID)
        self.assertEqual(record["method"], identities.METHOD_STABILIZER)
        self.assertEqual(record["noise_model"], "noiseless")
        self.assertEqual(record["ordering_assumption"], "natural_order")
        self.assertFalse(record["mid_circuit_measurement"])
        self.assertFalse(record["reset_used"])
        self.assertFalse(record["dynamic_operations"])
        self.assertEqual(
            record[contracts.RECORD_DIGEST_FIELD],
            digest_excluding(record, field=contracts.RECORD_DIGEST_FIELD),
        )

    def test_profile_rejects_unknown_method(self):
        with self.assertRaises(FocusedLoopError) as caught:
            contracts.build_execution_profile(
                profile_id="prof-1",
                method="statevector",
                circuit_family_class="clifford_only",
            )
        self.assertEqual(_category(caught), "execution_profile_method_invalid")

    def test_profile_rejects_remote_locality(self):
        with self.assertRaises(FocusedLoopError) as caught:
            contracts.build_execution_profile(
                profile_id="prof-1",
                method=identities.METHOD_STABILIZER,
                circuit_family_class="clifford_only",
                execution_locality="remote_qpu",
            )
        self.assertEqual(_category(caught), "execution_profile_locality_invalid")

    def test_profile_rejects_non_bool_gate_input(self):
        with self.assertRaises(FocusedLoopError) as caught:
            contracts.build_execution_profile(
                profile_id="prof-1",
                method=identities.METHOD_STABILIZER,
                circuit_family_class="clifford_only",
                simulator_available=1,
            )
        self.assertEqual(_category(caught), "execution_profile_availability_invalid")


class TestResourceReceipt(unittest.TestCase):
    def test_synthetic_receipt_matches_answer_key(self):
        record = contracts.build_synthetic_resource_receipt()
        self.assertEqual(record["schema_id"], identities.RESOURCE_RECEIPT_SCHEMA_ID)
        self.assertEqual(record["total_memory_bytes"], 68_719_476_736)
        self.assertEqual(record["available_floor_bytes"], 42_949_672_960)
        self.assertEqual(record["reserve_bytes"], 4_294_967_296)
        self.assertEqual(record["safe_envelope_bytes"], 38_654_705_664)
        self.assertEqual(record["limit_scope"], "host")
        self.assertEqual(record["total_memory_bytes"], 64 * contracts.GIB)
        self.assertEqual(record["safe_envelope_bytes"], 36 * contracts.GIB)

    def test_synthetic_receipt_is_marked_synthetic_and_not_a_probe(self):
        record = contracts.build_synthetic_resource_receipt()
        self.assertEqual(
            record["observation_method"], contracts.SYNTHETIC_RESOURCE_OBSERVATION_METHOD
        )
        self.assertTrue(record["observation_is_synthetic"])
        self.assertFalse(record["real_machine_probe_performed"])

    def test_safe_envelope_is_derived_not_supplied(self):
        record = contracts.build_resource_receipt(
            receipt_id="r",
            total_memory_bytes=32 * contracts.GIB,
            available_floor_bytes=20 * contracts.GIB,
            reserve_bytes=2 * contracts.GIB,
        )
        self.assertEqual(record["safe_envelope_bytes"], 18 * contracts.GIB)
        self.assertEqual(record["safe_envelope_band"], "ge_8gib_lt_32gib")

    def test_memory_band_thresholds(self):
        self.assertEqual(contracts.memory_band(4 * contracts.GIB), "lt_8gib")
        self.assertEqual(contracts.memory_band(8 * contracts.GIB), "ge_8gib_lt_32gib")
        self.assertEqual(contracts.memory_band(36 * contracts.GIB), "ge_32gib_lt_128gib")
        self.assertEqual(contracts.memory_band(256 * contracts.GIB), "ge_128gib")

    def test_receipt_rejects_inconsistent_inputs(self):
        with self.assertRaises(FocusedLoopError) as caught:
            contracts.build_resource_receipt(
                receipt_id="r",
                total_memory_bytes=8,
                available_floor_bytes=16,
                reserve_bytes=1,
            )
        self.assertEqual(_category(caught), "resource_available_exceeds_total")
        with self.assertRaises(FocusedLoopError) as caught:
            contracts.build_resource_receipt(
                receipt_id="r",
                total_memory_bytes=16,
                available_floor_bytes=8,
                reserve_bytes=8,
            )
        self.assertEqual(_category(caught), "resource_reserve_exceeds_available")

    def test_receipt_rejects_unsupported_observation_method(self):
        with self.assertRaises(FocusedLoopError) as caught:
            contracts.build_resource_receipt(
                receipt_id="r",
                total_memory_bytes=16,
                available_floor_bytes=8,
                reserve_bytes=1,
                observation_method="guessed_from_hostname",
            )
        self.assertEqual(_category(caught), "resource_observation_method_unsupported")


class TestCandidateRecommendation(unittest.TestCase):
    def _payload(self, action="await_user_decision"):
        return json.dumps(
            {
                "candidate_id": "cand-1",
                "proposed_action": action,
                "rationale": "undersized clean evidence",
            }
        )

    def test_typed_candidate_is_proposal_only(self):
        record = contracts.ingest_candidate_recommendation(
            self._payload(), provider_class="ide_llm"
        )
        self.assertEqual(
            record["schema_id"], identities.CANDIDATE_RECOMMENDATION_SCHEMA_ID
        )
        self.assertEqual(record["authority_class"], "proposal_only")
        self.assertIs(record["is_evidence"], False)
        self.assertIs(record["confers_authority"], False)
        self.assertEqual(
            contracts.validate_candidate_action(record), "await_user_decision"
        )

    def test_every_provider_class_is_accepted_as_proposal_only(self):
        for provider in contracts.PROVIDER_CLASSES:
            record = contracts.ingest_candidate_recommendation(
                self._payload(), provider_class=provider
            )
            self.assertEqual(record["provider_class"], provider)
            self.assertIs(record["confers_authority"], False)

    def test_prose_wrapped_json_is_rejected(self):
        wrapped = f"Here is my recommendation:\n{self._payload()}\nHope that helps!"
        with self.assertRaises(FocusedLoopError) as caught:
            contracts.ingest_candidate_recommendation(wrapped, provider_class="ide_llm")
        self.assertEqual(_category(caught), "candidate_payload_invalid")

    def test_fenced_json_is_rejected_without_extraction(self):
        fenced = "```json\n" + self._payload() + "\n```"
        with self.assertRaises(FocusedLoopError):
            contracts.ingest_candidate_recommendation(fenced, provider_class="ide_llm")

    def test_duplicate_keys_are_rejected(self):
        duplicated = (
            '{"candidate_id":"a","candidate_id":"b","proposed_action":"stop_goal_met",'
            '"rationale":"r"}'
        )
        with self.assertRaises(FocusedLoopError) as caught:
            contracts.ingest_candidate_recommendation(duplicated, provider_class="ide_llm")
        self.assertEqual(_category(caught), "typed_payload_duplicate_key")

    def test_missing_required_field_is_rejected(self):
        partial = json.dumps({"candidate_id": "a", "proposed_action": "stop_goal_met"})
        with self.assertRaises(FocusedLoopError) as caught:
            contracts.ingest_candidate_recommendation(partial, provider_class="ide_llm")
        self.assertEqual(_category(caught), "candidate_payload_invalid")

    def test_unknown_extra_field_is_rejected(self):
        extra = json.dumps(
            {
                "candidate_id": "a",
                "proposed_action": "stop_goal_met",
                "rationale": "r",
                "shots": 1024,
            }
        )
        with self.assertRaises(FocusedLoopError):
            contracts.ingest_candidate_recommendation(extra, provider_class="ide_llm")

    def test_non_object_payloads_are_rejected(self):
        for payload in ("[1,2,3]", '"stop_goal_met"', "null", "42", ""):
            with self.assertRaises(FocusedLoopError):
                contracts.ingest_candidate_recommendation(payload, provider_class="ide_llm")

    def test_unsupported_provider_class_is_rejected(self):
        with self.assertRaises(FocusedLoopError) as caught:
            contracts.ingest_candidate_recommendation(
                self._payload(), provider_class="anonymous_scraper"
            )
        self.assertEqual(_category(caught), "candidate_provider_class_unsupported")

    def test_well_formed_candidate_with_unsupported_action_is_rejected(self):
        record = contracts.ingest_candidate_recommendation(
            self._payload(action="switch_to_mps_approximate"), provider_class="public_api_model"
        )
        self.assertEqual(record["proposed_action"], "switch_to_mps_approximate")
        with self.assertRaises(FocusedLoopError) as caught:
            contracts.validate_candidate_action(record)
        self.assertEqual(_category(caught), "candidate_action_unsupported")

    def test_collect_more_shots_is_not_an_action(self):
        self.assertNotIn("collect_more_shots", contracts.SUPPORTED_ACTIONS)
        record = contracts.ingest_candidate_recommendation(
            self._payload(action="collect_more_shots"), provider_class="ide_llm"
        )
        with self.assertRaises(FocusedLoopError):
            contracts.validate_candidate_action(record)

    def test_validation_rejects_foreign_record(self):
        with self.assertRaises(FocusedLoopError) as caught:
            contracts.validate_candidate_action({"proposed_action": "stop_goal_met"})
        self.assertEqual(_category(caught), "candidate_record_invalid")


if __name__ == "__main__":
    unittest.main()
