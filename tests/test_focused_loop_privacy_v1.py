"""Purpose-limited privacy projections for every focused-loop destination."""

import unittest

from qcoder.focused_loop import contracts, fixtures, privacy, result_protocol
from qcoder.focused_loop.canonical import FocusedLoopError, canonical_bytes, is_digest

PARAMS = fixtures.PRIMARY_FAMILY_PARAMETERS

#: A record deliberately carrying one field from every prohibited class.
LEAKY_RECORD = {
    "schema_id": "qcoder.test_record.v1",
    "record_digest": "0" * 64,
    "safe_envelope_bytes": 38_654_705_664,
    "safe_envelope_band": "ge_32gib_lt_128gib",
    "total_memory_bytes": 68_719_476_736,
    "available_floor_bytes": 42_949_672_960,
    "reserve_bytes": 4_294_967_296,
    "qasm": 'OPENQASM 2.0;\ninclude "qelib1.inc";\n',
    "source_text": "def build_circuit(): ...",
    "counts": {"000000000000": 598},
    "path": "/home/someone/projects/secret/circuit.qasm",
    "hostname": "someones-laptop",
    "username": "someone",
    "token": "sk-live-not-a-real-token",
    "nested": {
        "credential": "hunter2",
        "qasm_text": "h q[0];",
        "safe_envelope_bytes": 38_654_705_664,
    },
}


class TestProhibitedKeyRule(unittest.TestCase):
    def test_the_rule_is_a_single_explicit_data_structure(self):
        self.assertIsInstance(privacy.PROHIBITED_FIELD_CLASSES, dict)
        self.assertEqual(
            sorted(privacy.PROHIBITED_FIELD_CLASSES),
            [
                "credential",
                "filesystem_path",
                "machine_identity",
                "raw_counts",
                "raw_customer_source",
                "raw_qasm",
                "raw_resource_detail",
            ],
        )

    def test_every_required_class_is_withheld_from_model_and_protected(self):
        for destination in privacy.RESTRICTED_DESTINATIONS:
            classes = privacy.PROHIBITED_CLASSES_BY_DESTINATION[destination]
            self.assertEqual(sorted(classes), sorted(privacy.PROHIBITED_FIELD_CLASSES))

    def test_specific_keys_are_withheld_from_the_model_surface(self):
        withheld = privacy.prohibited_keys_for("model_decision_context")
        for key in (
            "available_floor_bytes",
            "counts",
            "credential",
            "hostname",
            "password",
            "path",
            "qasm",
            "qasm_text",
            "reserve_bytes",
            "secret",
            "source_text",
            "token",
            "total_memory_bytes",
            "username",
            "working_directory",
        ):
            self.assertIn(key, withheld, key)

    def test_derived_resource_fields_are_never_prohibited(self):
        for destination in privacy.DESTINATIONS:
            withheld = privacy.prohibited_keys_for(destination)
            for permitted in privacy.PERMITTED_RESOURCE_FIELDS:
                self.assertNotIn(permitted, withheld)

    def test_credentials_are_prohibited_at_every_destination(self):
        for destination in privacy.DESTINATIONS:
            withheld = privacy.prohibited_keys_for(destination)
            for key in privacy.PROHIBITED_FIELD_CLASSES["credential"]:
                self.assertIn(key, withheld, f"{destination}:{key}")

    def test_unsupported_destination_fails_closed(self):
        for destination in ("cloud", "public_api", "", None, "MODEL_DECISION_CONTEXT"):
            with self.assertRaises(FocusedLoopError) as caught:
                privacy.prohibited_keys_for(destination)
            self.assertEqual(
                caught.exception.category, "privacy_destination_unsupported"
            )


class TestRestrictedProjections(unittest.TestCase):
    def test_model_and_protected_projections_withhold_every_class(self):
        for destination in privacy.RESTRICTED_DESTINATIONS:
            projected = privacy.project_record(LEAKY_RECORD, destination=destination)
            keys = privacy.collect_keys(projected)
            for forbidden in (
                "available_floor_bytes",
                "counts",
                "credential",
                "hostname",
                "path",
                "qasm",
                "qasm_text",
                "reserve_bytes",
                "source_text",
                "token",
                "total_memory_bytes",
                "username",
            ):
                self.assertNotIn(forbidden, keys, f"{destination}:{forbidden}")

    def test_no_prohibited_value_survives_serialization(self):
        for destination in privacy.RESTRICTED_DESTINATIONS:
            projected = privacy.project_record(LEAKY_RECORD, destination=destination)
            serialized = canonical_bytes(projected).decode()
            for secret in (
                "OPENQASM",
                "def build_circuit",
                "/home/someone",
                "someones-laptop",
                "sk-live-not-a-real-token",
                "hunter2",
                "68719476736",
                "42949672960",
                "4294967296",
            ):
                self.assertNotIn(secret, serialized, f"{destination}:{secret}")

    def test_derived_safe_envelope_survives(self):
        for destination in privacy.RESTRICTED_DESTINATIONS:
            projected = privacy.project_record(LEAKY_RECORD, destination=destination)
            self.assertEqual(projected["safe_envelope_bytes"], 38_654_705_664)
            self.assertEqual(projected["safe_envelope_band"], "ge_32gib_lt_128gib")

    def test_withheld_fields_are_named_not_valued(self):
        projected = privacy.project_record(
            LEAKY_RECORD, destination="model_decision_context"
        )
        self.assertIn("qasm", projected["fields_withheld"])
        self.assertIn("token", projected["fields_withheld"])
        self.assertIn("total_memory_bytes", projected["fields_withheld"])
        self.assertEqual(
            sorted(projected["field_classes_withheld"]),
            sorted(privacy.PROHIBITED_FIELD_CLASSES),
        )

    def test_projection_is_traceable_and_sealed(self):
        projected = privacy.project_record(
            LEAKY_RECORD, destination="protected_service"
        )
        self.assertEqual(projected["privacy_projection_id"], privacy.PROJECTION_ID)
        self.assertEqual(projected["privacy_destination"], "protected_service")
        self.assertEqual(projected["source_record_digest"], "0" * 64)
        self.assertEqual(projected["source_schema_id"], "qcoder.test_record.v1")
        self.assertTrue(is_digest(projected[privacy.PROJECTION_DIGEST_FIELD]))
        self.assertNotIn("record_digest", projected)

    def test_nested_prohibited_keys_are_removed_at_depth(self):
        projected = privacy.project_record(
            LEAKY_RECORD, destination="model_decision_context"
        )
        self.assertEqual(projected["nested"], {"safe_envelope_bytes": 38_654_705_664})


class TestLocalAndDeveloperProjections(unittest.TestCase):
    def test_local_deterministic_retains_exact_local_evidence(self):
        projected = privacy.project_record(
            LEAKY_RECORD, destination="local_deterministic"
        )
        self.assertIn("qasm", projected)
        self.assertIn("counts", projected)
        self.assertEqual(projected["total_memory_bytes"], 68_719_476_736)

    def test_local_deterministic_still_withholds_credentials(self):
        projected = privacy.project_record(
            LEAKY_RECORD, destination="local_deterministic"
        )
        keys = privacy.collect_keys(projected)
        self.assertNotIn("token", keys)
        self.assertNotIn("credential", keys)
        self.assertNotIn("hunter2", canonical_bytes(projected).decode())

    def test_developer_projection_withholds_machine_identity(self):
        projected = privacy.project_record(LEAKY_RECORD, destination="developer")
        keys = privacy.collect_keys(projected)
        self.assertNotIn("hostname", keys)
        self.assertNotIn("username", keys)
        self.assertNotIn("token", keys)
        self.assertIn("qasm", keys)


class TestProjectionsOfRealRecords(unittest.TestCase):
    def test_resource_receipt_projection_carries_only_derived_detail(self):
        receipt = contracts.build_synthetic_resource_receipt()
        projected = privacy.project_record(
            receipt, destination="model_decision_context"
        )
        self.assertEqual(projected["safe_envelope_bytes"], 38_654_705_664)
        self.assertEqual(projected["safe_envelope_band"], "ge_32gib_lt_128gib")
        for forbidden in ("total_memory_bytes", "available_floor_bytes", "reserve_bytes"):
            self.assertNotIn(forbidden, projected, forbidden)
        self.assertEqual(
            sorted(projected["fields_withheld"]),
            ["available_floor_bytes", "reserve_bytes", "total_memory_bytes"],
        )

    def test_materialized_fixture_projection_drops_the_raw_qasm(self):
        materialized = fixtures.materialize_fixture(PARAMS)
        projected = privacy.project_record(
            materialized, destination="model_decision_context"
        )
        self.assertNotIn("qasm", privacy.collect_keys(projected))
        self.assertNotIn("OPENQASM", canonical_bytes(projected).decode())
        self.assertEqual(projected["qasm_digest"], materialized["qasm_digest"])

    def test_analysis_result_projection_is_safe_for_the_model_surface(self):
        answer_key = fixtures.build_answer_key(PARAMS)
        analysis = result_protocol.build_analysis_result(
            analysis_id="analysis-1",
            counts={fixtures.allowed_outcomes(PARAMS)[0]: 598},
            answer_key=answer_key,
        )
        projected = privacy.project_record(
            analysis, destination="model_decision_context"
        )
        self.assertEqual(projected["evidence_conclusion"], "target_met")
        self.assertEqual(projected["sampling_state"], "sampling_sufficient_stop_sampling")
        self.assertEqual(projected["interval"]["lower"], 0.9950029413057535)
        privacy.assert_no_prohibited_keys(projected, destination="model_decision_context")

    def test_projection_never_carries_a_raw_counts_mapping(self):
        answer_key = fixtures.build_answer_key(PARAMS)
        analysis = result_protocol.build_analysis_result(
            analysis_id="analysis-1",
            counts={fixtures.allowed_outcomes(PARAMS)[0]: 598},
            answer_key=answer_key,
        )
        bundle = {"schema_id": "qcoder.bundle.v1", "analysis": analysis, "counts": {"x": 1}}
        projected = privacy.project_record(bundle, destination="protected_service")
        self.assertNotIn("counts", privacy.collect_keys(projected))


class TestProjectionFailsClosed(unittest.TestCase):
    def test_non_mapping_records_rejected(self):
        for record in ([], "record", 1, None, {}):
            with self.assertRaises(FocusedLoopError) as caught:
                privacy.project_record(record, destination="developer")
            self.assertEqual(caught.exception.category, "privacy_record_invalid")

    def test_non_string_keys_rejected(self):
        with self.assertRaises(FocusedLoopError) as caught:
            privacy.project_record({1: "a"}, destination="developer")
        self.assertEqual(caught.exception.category, "privacy_record_invalid")

    def test_unprojectable_binary_value_rejected(self):
        with self.assertRaises(FocusedLoopError) as caught:
            privacy.project_record(
                {"schema_id": "s", "blob": b"\x00\x01"}, destination="developer"
            )
        self.assertEqual(caught.exception.category, "privacy_unprojectable_value")

    def test_excessive_nesting_rejected(self):
        deep = {"schema_id": "s"}
        cursor = deep
        for _ in range(12):
            cursor["nested"] = {}
            cursor = cursor["nested"]
        with self.assertRaises(FocusedLoopError) as caught:
            privacy.project_record(deep, destination="developer")
        self.assertEqual(
            caught.exception.category, "privacy_projection_depth_exceeded"
        )

    def test_assert_helper_detects_a_leak(self):
        with self.assertRaises(FocusedLoopError) as caught:
            privacy.assert_no_prohibited_keys(
                {"qasm": "h q[0];"}, destination="model_decision_context"
            )
        self.assertEqual(
            caught.exception.category, "privacy_projection_leak_detected"
        )

    def test_assert_helper_passes_on_a_projection(self):
        for destination in privacy.DESTINATIONS:
            projected = privacy.project_record(LEAKY_RECORD, destination=destination)
            privacy.assert_no_prohibited_keys(projected, destination=destination)


if __name__ == "__main__":
    unittest.main()
