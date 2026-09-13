"""Deterministic fixture generation, family invariants, and the anti-hard-code rule."""

import inspect
import unittest

from qcoder.focused_loop import (
    applicability,
    contracts,
    fixtures,
    identities,
    mps_floor,
    privacy,
    result_protocol,
)
from qcoder.focused_loop.canonical import FocusedLoopError, is_digest

PRIMARY_MEASURED_PAIRS = ((31, 32), (30, 33), (29, 34), (28, 35), (27, 36), (26, 37))
HELDOUT_MEASURED_PAIRS = ((27, 28), (26, 29), (25, 30), (24, 31), (23, 32), (22, 33))

#: A third, differently-centred instance produced by the same generator.
THIRD_PARAMETERS = fixtures.family_parameters_at_cut(
    fixture_id="FX-CLIF-GENERATED-03", cut_left_index=40
)


def _expected_qasm(*, cut_left, depth=15, measured=6, qubits=64):
    """Render the expected QASM by an independent, explicitly written code path."""
    lines = ["OPENQASM 2.0;", 'include "qelib1.inc";', f"qreg q[{qubits}];"]
    lines.append(f"creg c[{2 * measured}];")
    pairs = [(cut_left - offset, cut_left + 1 + offset) for offset in range(depth)]
    for left, right in pairs:
        lines.append(f"h q[{left}];")
        lines.append(f"cx q[{left}],q[{right}];")
    for index, (left, right) in enumerate(pairs[:measured]):
        lines.append(f"measure q[{left}] -> c[{2 * index}];")
        lines.append(f"measure q[{right}] -> c[{2 * index + 1}];")
    return "\n".join(lines) + "\n"


class TestPrimaryFixtureRecipe(unittest.TestCase):
    def setUp(self):
        self.params = fixtures.PRIMARY_FAMILY_PARAMETERS
        self.qasm = fixtures.render_fixture_qasm(self.params)

    def test_identities_are_the_frozen_ones(self):
        self.assertEqual(self.params.fixture_id, identities.PRIMARY_FIXTURE_ID)
        self.assertEqual(self.params.fixture_name, identities.PRIMARY_FIXTURE_NAME)
        self.assertEqual(self.params.qubit_count, 64)
        self.assertEqual(self.params.nested_depth, 15)
        self.assertEqual(self.params.measured_pair_count, 6)

    def test_nested_pairs_follow_the_declared_recipe(self):
        pairs = fixtures.nested_pairs(self.params)
        self.assertEqual(len(pairs), 15)
        for offset, (left, right) in enumerate(pairs):
            self.assertEqual(left, 31 - offset)
            self.assertEqual(right, 32 + offset)

    def test_measured_pairs_are_the_six_innermost(self):
        self.assertEqual(fixtures.measured_pairs(self.params), PRIMARY_MEASURED_PAIRS)

    def test_qasm_matches_an_independently_rendered_expectation(self):
        self.assertEqual(self.qasm, _expected_qasm(cut_left=31))

    def test_qasm_header_and_registers(self):
        self.assertTrue(self.qasm.startswith("OPENQASM 2.0;\ninclude \"qelib1.inc\";\n"))
        self.assertIn("qreg q[64];", self.qasm)
        self.assertIn("creg c[12];", self.qasm)
        self.assertEqual(self.qasm.count("creg "), 1)
        self.assertEqual(self.qasm.count("qreg "), 1)

    def test_circuit_is_clifford_noiseless_and_static(self):
        self.assertEqual(self.qasm.count("h q["), 15)
        self.assertEqual(self.qasm.count("cx q["), 15)
        for forbidden in ("t q[", "tdg", "rz(", "u3(", "reset", "if(", "barrier", "noise"):
            self.assertNotIn(forbidden, self.qasm)

    def test_measurements_only_touch_the_six_innermost_pairs(self):
        measure_lines = [line for line in self.qasm.splitlines() if line.startswith("measure")]
        self.assertEqual(len(measure_lines), 12)
        expected = []
        for index, (left, right) in enumerate(PRIMARY_MEASURED_PAIRS):
            expected.append(f"measure q[{left}] -> c[{2 * index}];")
            expected.append(f"measure q[{right}] -> c[{2 * index + 1}];")
        self.assertEqual(measure_lines, expected)

    def test_measurement_is_terminal(self):
        lines = self.qasm.splitlines()
        first_measure = next(i for i, line in enumerate(lines) if line.startswith("measure"))
        self.assertTrue(all(line.startswith("measure") for line in lines[first_measure:]))

    def test_bit_ordering_is_recorded_explicitly(self):
        assignments = fixtures.classical_bit_assignments(self.params)
        self.assertEqual([item["bit_index"] for item in assignments], list(range(12)))
        self.assertEqual(
            [item["qubit_index"] for item in assignments],
            [31, 32, 30, 33, 29, 34, 28, 35, 27, 36, 26, 37],
        )
        self.assertEqual(
            [item["role"] for item in assignments], ["left", "right"] * 6
        )

    def test_no_filesystem_or_personal_path_in_the_artifact(self):
        for forbidden in ("/", "\\", "home", "Users", "tmp"):
            self.assertNotIn(forbidden, self.qasm)


class TestDeterminism(unittest.TestCase):
    def test_identical_inputs_produce_byte_identical_qasm_and_digests(self):
        for params in (
            fixtures.PRIMARY_FAMILY_PARAMETERS,
            fixtures.HELDOUT_FAMILY_PARAMETERS,
            THIRD_PARAMETERS,
        ):
            first = fixtures.materialize_fixture(params)
            second = fixtures.materialize_fixture(params)
            self.assertEqual(first["qasm"].encode("utf-8"), second["qasm"].encode("utf-8"))
            self.assertEqual(first["qasm_digest"], second["qasm_digest"])
            self.assertEqual(
                first["fixture_manifest_digest"], second["fixture_manifest_digest"]
            )
            self.assertEqual(first["objective_digest"], second["objective_digest"])
            self.assertEqual(first["answer_key_digest"], second["answer_key_digest"])

    def test_equal_parameters_rebuilt_from_scratch_agree(self):
        rebuilt = fixtures.NestedBellFamilyParameters(
            fixture_id=identities.PRIMARY_FIXTURE_ID,
            fixture_name=identities.PRIMARY_FIXTURE_NAME,
            cut_left_index=31,
        )
        self.assertEqual(rebuilt, fixtures.PRIMARY_FAMILY_PARAMETERS)
        self.assertEqual(
            fixtures.materialize_fixture(rebuilt)["qasm_digest"],
            fixtures.materialize_fixture(fixtures.PRIMARY_FAMILY_PARAMETERS)["qasm_digest"],
        )

    def test_different_cuts_produce_different_qasm_digests(self):
        digests = {
            fixtures.materialize_fixture(params)["qasm_digest"]
            for params in (
                fixtures.PRIMARY_FAMILY_PARAMETERS,
                fixtures.HELDOUT_FAMILY_PARAMETERS,
                THIRD_PARAMETERS,
            )
        }
        self.assertEqual(len(digests), 3)

    def test_digests_are_well_formed(self):
        materialized = fixtures.materialize_fixture(fixtures.PRIMARY_FAMILY_PARAMETERS)
        for key in (
            "qasm_digest",
            "fixture_manifest_digest",
            "objective_digest",
            "answer_key_digest",
            "chi_required_claim_digest",
        ):
            self.assertTrue(is_digest(materialized[key]), key)


class TestManifestAndAnswerKey(unittest.TestCase):
    def setUp(self):
        self.params = fixtures.PRIMARY_FAMILY_PARAMETERS
        self.manifest = fixtures.build_fixture_manifest(self.params)
        self.answer_key = fixtures.build_answer_key(self.params)

    def test_manifest_records_the_required_facts(self):
        self.assertEqual(self.manifest["schema_id"], identities.FIXTURE_MANIFEST_SCHEMA_ID)
        self.assertEqual(self.manifest["generator_id"], identities.GENERATOR_ID)
        self.assertEqual(self.manifest["generator_version"], identities.GENERATOR_VERSION)
        self.assertEqual(self.manifest["declared_inputs"]["fixture_id"], "FX-CLIF-ACCEPT-01")
        self.assertEqual(self.manifest["declared_inputs"]["fixture_version"], "1")
        self.assertEqual(self.manifest["classical_register"], {
            "name": "c",
            "width": 12,
            "dedicated_to_measured_pairs": True,
        })
        self.assertEqual(self.manifest["valid_support_size"], 64)
        self.assertEqual(self.manifest["privacy_class"], "public_synthetic_fixture")
        self.assertEqual(self.manifest["expected_disposition"], "accept_target_met")
        self.assertEqual(self.manifest["ordering_assumption"], "natural_order")
        self.assertEqual(self.manifest["non_clifford_gate_count"], 0)
        self.assertFalse(self.manifest["mid_circuit_measurement"])
        self.assertFalse(self.manifest["reset_used"])
        self.assertFalse(self.manifest["dynamic_operations"])
        self.assertEqual(
            self.manifest["qasm_digest"],
            fixtures.qasm_digest(fixtures.render_fixture_qasm(self.params)),
        )

    def test_manifest_carries_no_raw_qasm_text(self):
        self.assertNotIn("qasm", self.manifest)
        self.assertNotIn("OPENQASM", str(self.manifest))

    def test_answer_key_records_six_parity_constraints(self):
        constraints = self.answer_key["parity_constraints"]
        self.assertEqual(len(constraints), 6)
        for index, constraint in enumerate(constraints):
            left, right = PRIMARY_MEASURED_PAIRS[index]
            self.assertEqual(constraint["constraint_id"], f"bell_parity_{index}")
            self.assertEqual(constraint["left_qubit"], left)
            self.assertEqual(constraint["right_qubit"], right)
            self.assertEqual(constraint["left_bit"], 2 * index)
            self.assertEqual(constraint["right_bit"], 2 * index + 1)
            self.assertEqual(constraint["stabilizer"], f"Z[{left}]*Z[{right}]")
            self.assertEqual(constraint["expected_eigenvalue"], 1)

    def test_valid_support_is_exactly_sixty_four_outcomes(self):
        support = self.answer_key["valid_support"]
        self.assertEqual(support["size"], 64)
        outcomes = support["allowed_outcomes"]
        self.assertEqual(len(outcomes), 64)
        self.assertEqual(len(set(outcomes)), 64)
        self.assertEqual(outcomes, sorted(outcomes))
        for outcome in outcomes:
            self.assertEqual(len(outcome), 12)
            for index in range(6):
                left = outcome[12 - 1 - 2 * index]
                right = outcome[12 - 1 - (2 * index + 1)]
                self.assertEqual(left, right)

    def test_answer_key_carries_chi_floor_and_limitation(self):
        self.assertEqual(self.answer_key["chi_required"], 32768)
        self.assertEqual(
            self.answer_key["coefficient_floor"]["payload_floor_bytes"], 45_812_985_536
        )
        self.assertEqual(
            sorted(self.answer_key["coefficient_floor_exclusions"]),
            sorted(identities.MPS_FLOOR_EXCLUSIONS),
        )
        self.assertEqual(self.answer_key["limitations"], [identities.AER_MPS_LIMITATION])

    def test_constraint_id_helper(self):
        self.assertEqual(
            fixtures.answer_key_constraint_ids(self.answer_key),
            tuple(f"bell_parity_{index}" for index in range(6)),
        )
        with self.assertRaises(FocusedLoopError):
            fixtures.answer_key_constraint_ids({"schema_id": "other"})


class TestHeldOutSibling(unittest.TestCase):
    def test_heldout_is_centred_on_the_q27_q28_cut(self):
        params = fixtures.HELDOUT_FAMILY_PARAMETERS
        self.assertEqual(params.fixture_id, identities.HELDOUT_FIXTURE_ID)
        self.assertEqual(params.cut_left_index, 27)
        self.assertEqual(fixtures.measured_pairs(params), HELDOUT_MEASURED_PAIRS)
        self.assertEqual(
            fixtures.render_fixture_qasm(params), _expected_qasm(cut_left=27)
        )

    def test_heldout_identities_are_returned_without_writing_artifacts(self):
        returned = fixtures.fixture_identities(fixtures.HELDOUT_FAMILY_PARAMETERS)
        self.assertEqual(
            sorted(returned),
            [
                "answer_key_digest",
                "chi_required_claim_digest",
                "declared_inputs",
                "fixture_manifest_digest",
                "objective_digest",
                "qasm_digest",
            ],
        )
        self.assertNotIn("qasm", returned)


class TestFamilyInvariantsAcrossInstances(unittest.TestCase):
    """The held-out and a generated third instance flow through identical code."""

    INSTANCES = (
        fixtures.PRIMARY_FAMILY_PARAMETERS,
        fixtures.HELDOUT_FAMILY_PARAMETERS,
        THIRD_PARAMETERS,
    )

    def test_every_instance_shares_the_family_invariants(self):
        receipt = contracts.build_synthetic_resource_receipt()
        for params in self.INSTANCES:
            materialized = fixtures.materialize_fixture(params)
            answer_key = materialized["answer_key"]
            floor = materialized["coefficient_floor"]
            self.assertEqual(answer_key["chi_required"], 32768, params.fixture_id)
            self.assertEqual(answer_key["valid_support"]["size"], 64, params.fixture_id)
            self.assertEqual(floor["payload_floor_bytes"], 45_812_985_536, params.fixture_id)

            evaluations = applicability.evaluate_regime_methods(
                applicability_prefix=params.fixture_id,
                coefficient_floor=floor,
                safe_envelope_bytes=receipt["safe_envelope_bytes"],
            )
            exact = evaluations[identities.METHOD_MPS_EXACT]
            self.assertFalse(exact["selected"])
            self.assertEqual(exact["rejection_reason"], "resource_lower_bound_exceeded")
            self.assertEqual(
                exact["feasibility"], "infeasible_lower_bound_exceeds_envelope"
            )

            approximate = evaluations[identities.METHOD_MPS_APPROXIMATE]
            self.assertFalse(approximate["selected"])
            self.assertEqual(approximate["rejection_reason"], "exactness_policy_conflict")

            stabilizer = evaluations[identities.METHOD_STABILIZER]
            self.assertTrue(stabilizer["selected"])
            self.assertTrue(all(stabilizer["gates"].values()))
            self.assertEqual(
                applicability.selected_method(evaluations), identities.METHOD_STABILIZER
            )

    def test_every_instance_reaches_target_met_on_clean_evidence(self):
        for params in self.INSTANCES:
            answer_key = fixtures.build_answer_key(params)
            counts = {fixtures.allowed_outcomes(params)[0]: identities.FIXED_SHOTS}
            analysis = result_protocol.build_analysis_result(
                analysis_id=f"{params.fixture_id}:analysis",
                counts=counts,
                answer_key=answer_key,
            )
            self.assertEqual(analysis["evidence_conclusion"], "target_met", params.fixture_id)
            action = result_protocol.build_next_action(
                action_id=f"{params.fixture_id}:action", analysis_result=analysis
            )
            self.assertEqual(action["action"], "stop_goal_met")

    def test_instances_have_distinct_manifests_but_identical_invariants(self):
        manifests = {
            fixtures.build_fixture_manifest(params)["record_digest"]
            for params in self.INSTANCES
        }
        self.assertEqual(len(manifests), 3)


class TestGeneratorValidation(unittest.TestCase):
    def test_cut_out_of_range_is_rejected(self):
        for cut in (13, 49, 0, 63):
            with self.assertRaises(FocusedLoopError) as caught:
                fixtures.family_parameters_at_cut(fixture_id="FX-X", cut_left_index=cut)
            self.assertEqual(caught.exception.category, "fixture_cut_out_of_range")

    def test_in_range_cuts_are_accepted(self):
        for cut in (14, 31, 27, 40, 48):
            params = fixtures.family_parameters_at_cut(fixture_id="FX-X", cut_left_index=cut)
            self.assertEqual(fixtures.valid_support_size(params), 64)

    def test_measured_pair_count_must_not_exceed_depth(self):
        params = fixtures.NestedBellFamilyParameters(
            fixture_id="FX-X", fixture_name="N", cut_left_index=31, measured_pair_count=16
        )
        with self.assertRaises(FocusedLoopError) as caught:
            fixtures.nested_pairs(params)
        self.assertEqual(caught.exception.category, "fixture_measured_pair_count_invalid")

    def test_non_parameter_input_is_rejected(self):
        with self.assertRaises(FocusedLoopError) as caught:
            fixtures.render_fixture_qasm({"cut_left_index": 31})
        self.assertEqual(caught.exception.category, "fixture_parameters_invalid")

    def test_blank_fixture_id_is_rejected(self):
        params = fixtures.NestedBellFamilyParameters(
            fixture_id="", fixture_name="N", cut_left_index=31
        )
        with self.assertRaises(FocusedLoopError) as caught:
            fixtures.nested_pairs(params)
        self.assertEqual(caught.exception.category, "fixture_id_invalid")


class TestAntiHardCodeRule(unittest.TestCase):
    DECISION_MODULES = (mps_floor, applicability, result_protocol, privacy)

    def test_decision_modules_never_mention_a_fixture_id(self):
        for module in self.DECISION_MODULES:
            source = inspect.getsource(module)
            for token in (
                identities.PRIMARY_FIXTURE_ID,
                identities.HELDOUT_FIXTURE_ID,
                identities.PRIMARY_FIXTURE_NAME,
                "PRIMARY_FIXTURE",
                "HELDOUT_FIXTURE",
            ):
                self.assertNotIn(token, source, f"{module.__name__} mentions {token}")

    def test_decision_modules_carry_no_digest_allowlist(self):
        known = {
            fixtures.materialize_fixture(params)["qasm_digest"]
            for params in TestFamilyInvariantsAcrossInstances.INSTANCES
        }
        for module in self.DECISION_MODULES + (fixtures, contracts):
            source = inspect.getsource(module)
            for digest in known:
                self.assertNotIn(digest, source)

    def test_generated_third_instance_is_not_a_declared_constant(self):
        source = inspect.getsource(fixtures)
        self.assertNotIn("FX-CLIF-GENERATED-03", source)
        self.assertNotIn("cut_left_index=40", source)


if __name__ == "__main__":
    unittest.main()
