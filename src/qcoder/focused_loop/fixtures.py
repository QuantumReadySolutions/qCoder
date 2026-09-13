"""Deterministic nested-Bell fixture generation for the first focused-loop family."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from qcoder.focused_loop import identities
from qcoder.focused_loop.canonical import FocusedLoopError, bounded_text
from qcoder.focused_loop.contracts import (
    EVIDENCE_CLASS_EXACT_FAMILY_SPECIFIC,
    ORDERING_ASSUMPTION_NATURAL_ORDER,
    build_evidence_objective,
    seal_record,
)
from qcoder.focused_loop.mps_floor import build_chi_required_claim, build_coefficient_floor

#: Classical-bit ordering of the counts keys produced by this family. Qiskit renders a
#: classical register with the highest bit index leftmost, so ``c[0]`` is the rightmost
#: character of every counts key. Recorded explicitly; never inferred.
COUNTS_BITSTRING_ORDERING = "qiskit_creg_little_endian_c0_rightmost_v1"

#: Bit-to-qubit assignment convention: measured pair ``j`` occupies ``c[2j]`` (left
#: qubit) and ``c[2j+1]`` (right qubit), innermost pair first.
BIT_ASSIGNMENT_CONVENTION = "innermost_pair_first_left_even_right_odd_v1"

INITIAL_STATE = "all_zero_computational_basis"
GATE_SET_CLASS = "clifford_only"
NOISE_MODEL = "noiseless"
PRIVACY_CLASS = "public_synthetic_fixture"
EXPECTED_DISPOSITION = "accept_target_met"

QASM_HEADER = ('OPENQASM 2.0;', 'include "qelib1.inc";')

FIXTURE_VERSION = "1"


@dataclass(frozen=True)
class NestedBellFamilyParameters:
    """Declared inputs of one nested-Bell fixture instance.

    The family is fully parameterized by the cut position. The primary and held-out
    instances differ only in ``cut_left_index``; no production code path branches on a
    fixture id or digest.
    """

    fixture_id: str
    fixture_name: str
    cut_left_index: int
    qubit_count: int = 64
    nested_depth: int = 15
    measured_pair_count: int = 6
    fixture_version: str = FIXTURE_VERSION
    quantum_register: str = "q"
    classical_register: str = "c"


PRIMARY_FAMILY_PARAMETERS = NestedBellFamilyParameters(
    fixture_id=identities.PRIMARY_FIXTURE_ID,
    fixture_name=identities.PRIMARY_FIXTURE_NAME,
    cut_left_index=31,
)

HELDOUT_FAMILY_PARAMETERS = NestedBellFamilyParameters(
    fixture_id=identities.HELDOUT_FIXTURE_ID,
    fixture_name=identities.PRIMARY_FIXTURE_NAME,
    cut_left_index=27,
)


def _validated(parameters: NestedBellFamilyParameters) -> NestedBellFamilyParameters:
    if not isinstance(parameters, NestedBellFamilyParameters):
        raise FocusedLoopError("fixture_parameters_invalid")
    bounded_text(parameters.fixture_id, category="fixture_id_invalid")
    bounded_text(parameters.fixture_name, category="fixture_name_invalid")
    bounded_text(parameters.fixture_version, category="fixture_version_invalid")
    if not parameters.quantum_register.isidentifier():
        raise FocusedLoopError("fixture_register_name_invalid")
    if not parameters.classical_register.isidentifier():
        raise FocusedLoopError("fixture_register_name_invalid")
    if parameters.qubit_count < 2 or parameters.nested_depth < 1:
        raise FocusedLoopError("fixture_geometry_invalid")
    if not 1 <= parameters.measured_pair_count <= parameters.nested_depth:
        raise FocusedLoopError("fixture_measured_pair_count_invalid")
    left_outermost = parameters.cut_left_index - (parameters.nested_depth - 1)
    right_outermost = parameters.cut_left_index + parameters.nested_depth
    if left_outermost < 0 or right_outermost > parameters.qubit_count - 1:
        raise FocusedLoopError("fixture_cut_out_of_range")
    return parameters


def nested_pairs(parameters: NestedBellFamilyParameters) -> tuple[tuple[int, int], ...]:
    """Return the nested pairs innermost first: ``left = cut - j``, ``right = cut + 1 + j``."""
    params = _validated(parameters)
    return tuple(
        (params.cut_left_index - offset, params.cut_left_index + 1 + offset)
        for offset in range(params.nested_depth)
    )


def measured_pairs(parameters: NestedBellFamilyParameters) -> tuple[tuple[int, int], ...]:
    """Return the measured innermost pairs in the recorded order."""
    params = _validated(parameters)
    return nested_pairs(params)[: params.measured_pair_count]


def classical_bit_assignments(
    parameters: NestedBellFamilyParameters,
) -> tuple[dict[str, Any], ...]:
    """Return the explicit bit-index to qubit-index assignment of the measured register."""
    assignments: list[dict[str, Any]] = []
    for index, (left, right) in enumerate(measured_pairs(parameters)):
        assignments.append(
            {"bit_index": 2 * index, "qubit_index": left, "pair_index": index, "role": "left"}
        )
        assignments.append(
            {"bit_index": 2 * index + 1, "qubit_index": right, "pair_index": index, "role": "right"}
        )
    return tuple(assignments)


def classical_register_width(parameters: NestedBellFamilyParameters) -> int:
    """Return the dedicated classical register width."""
    return 2 * _validated(parameters).measured_pair_count


def valid_support_size(parameters: NestedBellFamilyParameters) -> int:
    """Return the exact number of ideal outcomes: one free bit per measured pair."""
    return 2 ** _validated(parameters).measured_pair_count


def allowed_outcomes(parameters: NestedBellFamilyParameters) -> tuple[str, ...]:
    """Return every ideal counts key, ascending, in the recorded counts ordering."""
    params = _validated(parameters)
    width = classical_register_width(params)
    outcomes: list[str] = []
    for mask in range(valid_support_size(params)):
        bits = ["0"] * width
        for pair_index in range(params.measured_pair_count):
            value = "1" if (mask >> pair_index) & 1 else "0"
            bits[2 * pair_index] = value
            bits[2 * pair_index + 1] = value
        outcomes.append("".join(reversed(bits)))
    return tuple(sorted(outcomes))


def parity_constraints(parameters: NestedBellFamilyParameters) -> tuple[dict[str, Any], ...]:
    """Return the exact equality constraints, one per measured pair."""
    return tuple(
        {
            "constraint_id": f"bell_parity_{index}",
            "left_qubit": left,
            "right_qubit": right,
            "left_bit": 2 * index,
            "right_bit": 2 * index + 1,
            "relation": "classical_bit_equality",
            "stabilizer": f"Z[{left}]*Z[{right}]",
            "expected_eigenvalue": 1,
        }
        for index, (left, right) in enumerate(measured_pairs(parameters))
    )


def render_fixture_qasm(parameters: NestedBellFamilyParameters) -> str:
    """Render the canonical OpenQASM 2 text for one fixture instance."""
    params = _validated(parameters)
    quantum = params.quantum_register
    classical = params.classical_register
    lines = list(QASM_HEADER)
    lines.append(f"qreg {quantum}[{params.qubit_count}];")
    lines.append(f"creg {classical}[{classical_register_width(params)}];")
    for left, right in nested_pairs(params):
        lines.append(f"h {quantum}[{left}];")
        lines.append(f"cx {quantum}[{left}],{quantum}[{right}];")
    for assignment in classical_bit_assignments(params):
        lines.append(
            f"measure {quantum}[{assignment['qubit_index']}]"
            f" -> {classical}[{assignment['bit_index']}];"
        )
    return "\n".join(lines) + "\n"


def qasm_digest(qasm_text: str) -> str:
    """Return the SHA-256 hex digest over the exact UTF-8 bytes of ``qasm_text``."""
    if not isinstance(qasm_text, str) or not qasm_text:
        raise FocusedLoopError("fixture_qasm_invalid")
    return sha256(qasm_text.encode("utf-8")).hexdigest()


def declared_inputs(parameters: NestedBellFamilyParameters) -> dict[str, Any]:
    """Return the canonical-serializable declared inputs of the generator."""
    params = _validated(parameters)
    return {
        "fixture_id": params.fixture_id,
        "fixture_name": params.fixture_name,
        "fixture_version": params.fixture_version,
        "qubit_count": params.qubit_count,
        "cut_left_index": params.cut_left_index,
        "cut_right_index": params.cut_left_index + 1,
        "nested_depth": params.nested_depth,
        "measured_pair_count": params.measured_pair_count,
        "quantum_register": params.quantum_register,
        "classical_register": params.classical_register,
    }


def build_fixture_manifest(parameters: NestedBellFamilyParameters) -> dict[str, Any]:
    """Build the fixture manifest record for one instance."""
    params = _validated(parameters)
    payload: dict[str, Any] = {
        "schema_id": identities.FIXTURE_MANIFEST_SCHEMA_ID,
        "regime_id": identities.REGIME_ID,
        "generator_id": identities.GENERATOR_ID,
        "generator_version": identities.GENERATOR_VERSION,
        "declared_inputs": declared_inputs(params),
        "initial_state": INITIAL_STATE,
        "gate_set_class": GATE_SET_CLASS,
        "noise_model": NOISE_MODEL,
        "non_clifford_gate_count": 0,
        "reset_used": False,
        "mid_circuit_measurement": False,
        "dynamic_operations": False,
        "nested_pairs": [list(pair) for pair in nested_pairs(params)],
        "measured_pairs": [list(pair) for pair in measured_pairs(params)],
        "classical_register": {
            "name": params.classical_register,
            "width": classical_register_width(params),
            "dedicated_to_measured_pairs": True,
        },
        "classical_bit_assignments": list(classical_bit_assignments(params)),
        "bit_assignment_convention": BIT_ASSIGNMENT_CONVENTION,
        "counts_bitstring_ordering": COUNTS_BITSTRING_ORDERING,
        "ordering_assumption": ORDERING_ASSUMPTION_NATURAL_ORDER,
        "qasm_digest": qasm_digest(render_fixture_qasm(params)),
        "valid_support_size": valid_support_size(params),
        "privacy_class": PRIVACY_CLASS,
        "expected_disposition": EXPECTED_DISPOSITION,
    }
    return seal_record(payload)


def build_answer_key(parameters: NestedBellFamilyParameters) -> dict[str, Any]:
    """Build the answer-key record: parity constraints, valid support, chi and floor."""
    params = _validated(parameters)
    pairs = nested_pairs(params)
    floor = build_coefficient_floor(qubit_count=params.qubit_count, pairs=pairs)
    claim = build_chi_required_claim(
        claim_id=f"{params.fixture_id}:chi_required",
        qubit_count=params.qubit_count,
        pairs=pairs,
    )
    payload: dict[str, Any] = {
        "schema_id": identities.ANSWER_KEY_SCHEMA_ID,
        "regime_id": identities.REGIME_ID,
        "fixture_id": params.fixture_id,
        "fixture_version": params.fixture_version,
        "generator_id": identities.GENERATOR_ID,
        "generator_version": identities.GENERATOR_VERSION,
        "evidence_class": EVIDENCE_CLASS_EXACT_FAMILY_SPECIFIC,
        "ordering_assumption": ORDERING_ASSUMPTION_NATURAL_ORDER,
        "counts_bitstring_ordering": COUNTS_BITSTRING_ORDERING,
        "classical_register_width": classical_register_width(params),
        "parity_constraints": list(parity_constraints(params)),
        "valid_support": {
            "size": valid_support_size(params),
            "characterization": "every_measured_pair_reports_equal_classical_bits",
            "enumeration_rule": "one_free_bit_per_measured_pair",
            "allowed_outcomes": list(allowed_outcomes(params)),
        },
        "chi_required": claim["chi_required"],
        "chi_derivation_id": identities.CHI_DERIVATION_ID,
        "chi_derivation_version": identities.CHI_DERIVATION_VERSION,
        "coefficient_floor": floor,
        "coefficient_floor_exclusions": list(floor["exclusions"]),
        "limitations": [identities.AER_MPS_LIMITATION],
    }
    return seal_record(payload)


def build_fixture_objective(parameters: NestedBellFamilyParameters) -> dict[str, Any]:
    """Build the evidence objective bound to one fixture instance."""
    params = _validated(parameters)
    return build_evidence_objective(objective_id=f"{params.fixture_id}:predicate_satisfaction")


def materialize_fixture(parameters: NestedBellFamilyParameters) -> dict[str, Any]:
    """Materialize one fixture instance: QASM, manifest, objective, answer key, digests.

    Generation is a pure function of the declared inputs: identical inputs always
    produce byte-identical QASM and identical digests. Nothing is read from or written
    to the filesystem.
    """
    params = _validated(parameters)
    qasm = render_fixture_qasm(params)
    manifest = build_fixture_manifest(params)
    objective = build_fixture_objective(params)
    answer_key = build_answer_key(params)
    claim = build_chi_required_claim(
        claim_id=f"{params.fixture_id}:chi_required",
        qubit_count=params.qubit_count,
        pairs=nested_pairs(params),
    )
    return {
        "declared_inputs": declared_inputs(params),
        "qasm": qasm,
        "qasm_digest": qasm_digest(qasm),
        "fixture_manifest": manifest,
        "fixture_manifest_digest": manifest["record_digest"],
        "objective": objective,
        "objective_digest": objective["record_digest"],
        "answer_key": answer_key,
        "answer_key_digest": answer_key["record_digest"],
        "chi_required_claim": claim,
        "chi_required_claim_digest": claim["record_digest"],
        "coefficient_floor": claim["coefficient_floor"],
    }


def fixture_identities(parameters: NestedBellFamilyParameters) -> dict[str, Any]:
    """Return only the identities and digests of one instance, without the QASM text."""
    materialized = materialize_fixture(parameters)
    return {
        key: value
        for key, value in materialized.items()
        if key
        in (
            "declared_inputs",
            "qasm_digest",
            "fixture_manifest_digest",
            "objective_digest",
            "answer_key_digest",
            "chi_required_claim_digest",
        )
    }


def family_parameters_at_cut(
    *, fixture_id: str, cut_left_index: int, fixture_name: str = identities.PRIMARY_FIXTURE_NAME
) -> NestedBellFamilyParameters:
    """Build family parameters for an arbitrary declared cut position."""
    return _validated(
        NestedBellFamilyParameters(
            fixture_id=fixture_id,
            fixture_name=fixture_name,
            cut_left_index=cut_left_index,
        )
    )


def answer_key_constraint_ids(answer_key: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the constraint ids of an answer key in their recorded order."""
    if not isinstance(answer_key, Mapping) or answer_key.get("schema_id") != (
        identities.ANSWER_KEY_SCHEMA_ID
    ):
        raise FocusedLoopError("answer_key_record_invalid")
    constraints = answer_key.get("parity_constraints")
    if not isinstance(constraints, Sequence) or not constraints:
        raise FocusedLoopError("answer_key_record_invalid")
    return tuple(str(constraint["constraint_id"]) for constraint in constraints)
