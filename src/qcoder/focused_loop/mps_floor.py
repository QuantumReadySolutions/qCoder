"""Exact MPS bond-rank and dense-coefficient memory-floor arithmetic for the focused loop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from qcoder.focused_loop import identities
from qcoder.focused_loop.canonical import (
    FocusedLoopError,
    bounded_text,
    bounded_text_list,
    digest_excluding,
    enum_value,
    strict_int,
)
from qcoder.focused_loop.contracts import (
    EVIDENCE_CLASS_EXACT_FAMILY_SPECIFIC,
    ORDERING_ASSUMPTION_NATURAL_ORDER,
    ORDERING_ASSUMPTIONS,
    seal_record,
)

#: One complex128 amplitude.
COMPLEX128_BYTES = 16

#: Physical dimension of a qubit site.
PHYSICAL_DIMENSION = 2

MAX_QUBIT_COUNT = 256

#: Self-digest field of the embedded coefficient-floor sub-record. The floor is a
#: sub-record of the chi claim and the answer key; the frozen identity set defines no
#: standalone schema id for it, so it is identified by ``procedure_id``.
FLOOR_DIGEST_FIELD = "floor_digest"

FLOOR_BOUND_KIND = "lower_bound_payload_only"

#: The chi claim is scoped to the declared construction only and generalizes to nothing.
CHI_CLAIM_SCOPE = "declared_natural_order_nested_bell_construction_only"
CHI_CLAIM_NON_CLAIMS = (
    "not_a_claim_about_aer_mps_internal_qubit_reordering",
    "not_a_claim_about_alternative_internal_representations",
    "not_a_claim_about_arbitrary_clifford_circuits",
    "not_a_claim_about_transpiler_or_optimizer_transformations",
)


def normalized_pairs(
    pairs: Sequence[Sequence[int]], *, qubit_count: int
) -> tuple[tuple[int, int], ...]:
    """Validate and normalize a nested-pair list into ``(left, right)`` tuples."""
    width = strict_int(
        qubit_count, category="mps_qubit_count_invalid", minimum=2, maximum=MAX_QUBIT_COUNT
    )
    if not isinstance(pairs, Sequence) or isinstance(pairs, (str, bytes, bytearray)) or not pairs:
        raise FocusedLoopError("mps_pair_list_invalid")
    normalized: list[tuple[int, int]] = []
    seen: set[int] = set()
    for pair in pairs:
        if (
            not isinstance(pair, Sequence)
            or isinstance(pair, (str, bytes, bytearray))
            or len(pair) != 2
        ):
            raise FocusedLoopError("mps_pair_list_invalid")
        left = strict_int(pair[0], category="mps_pair_index_invalid", minimum=0, maximum=width - 1)
        right = strict_int(pair[1], category="mps_pair_index_invalid", minimum=0, maximum=width - 1)
        if left >= right:
            raise FocusedLoopError("mps_pair_order_invalid")
        if left in seen or right in seen:
            raise FocusedLoopError("mps_pair_qubit_reused")
        seen.add(left)
        seen.add(right)
        normalized.append((left, right))
    return tuple(normalized)


def bond_rank_profile(
    *, qubit_count: int, pairs: Sequence[Sequence[int]]
) -> tuple[int, ...]:
    """Return the exact bond ranks ``chi_0 .. chi_(n-2)`` of the declared construction.

    Bond ``i`` lies between site ``i`` and site ``i + 1`` and carries one factor of two
    for every nested pair ``(l, r)`` with ``l <= i < r``.
    """
    normalized = normalized_pairs(pairs, qubit_count=qubit_count)
    return tuple(
        2 ** sum(1 for left, right in normalized if left <= index < right)
        for index in range(qubit_count - 1)
    )


def site_bond_dimensions(
    *, qubit_count: int, pairs: Sequence[Sequence[int]]
) -> tuple[tuple[int, int], ...]:
    """Return ``(chi_left, chi_right)`` per site, with rank one at both boundaries."""
    profile = bond_rank_profile(qubit_count=qubit_count, pairs=pairs)
    return tuple(
        (
            1 if site == 0 else profile[site - 1],
            1 if site == qubit_count - 1 else profile[site],
        )
        for site in range(qubit_count)
    )


def chi_required(*, qubit_count: int, pairs: Sequence[Sequence[int]]) -> int:
    """Return the maximum exact bond rank of the declared construction."""
    return max(bond_rank_profile(qubit_count=qubit_count, pairs=pairs))


def coefficient_count(*, qubit_count: int, pairs: Sequence[Sequence[int]]) -> int:
    """Return the exact dense complex128 coefficient count of the MPS tensor set."""
    return sum(
        PHYSICAL_DIMENSION * left * right
        for left, right in site_bond_dimensions(qubit_count=qubit_count, pairs=pairs)
    )


def payload_floor_bytes(*, qubit_count: int, pairs: Sequence[Sequence[int]]) -> int:
    """Return ``16 * sum_sites(2 * chi_left * chi_right)`` in bytes."""
    return COMPLEX128_BYTES * coefficient_count(qubit_count=qubit_count, pairs=pairs)


def build_coefficient_floor(
    *,
    qubit_count: int,
    pairs: Sequence[Sequence[int]],
    exclusions: Sequence[str] = identities.MPS_FLOOR_EXCLUSIONS,
) -> dict[str, Any]:
    """Build the coefficient-floor sub-record with its mandatory exclusions."""
    dimensions = site_bond_dimensions(qubit_count=qubit_count, pairs=pairs)
    coefficients = sum(PHYSICAL_DIMENSION * left * right for left, right in dimensions)
    floor_bytes = COMPLEX128_BYTES * coefficients
    recorded = bounded_text_list(list(exclusions), category="mps_floor_exclusions_invalid")
    if set(recorded) != set(identities.MPS_FLOOR_EXCLUSIONS):
        raise FocusedLoopError("mps_floor_exclusions_incomplete")
    payload: dict[str, Any] = {
        "procedure_id": identities.MPS_FLOOR_PROCEDURE_ID,
        "bound_kind": FLOOR_BOUND_KIND,
        "coefficient_bytes": COMPLEX128_BYTES,
        "physical_dimension": PHYSICAL_DIMENSION,
        "qubit_count": len(dimensions),
        "coefficient_count": coefficients,
        "payload_floor_bytes": floor_bytes,
        "payload_floor_gib": floor_bytes / (1024**3),
        "exclusions": sorted(recorded),
    }
    payload[FLOOR_DIGEST_FIELD] = digest_excluding(payload, field=FLOOR_DIGEST_FIELD)
    return payload


def build_chi_required_claim(
    *,
    claim_id: str,
    qubit_count: int,
    pairs: Sequence[Sequence[int]],
    ordering_assumption: str = ORDERING_ASSUMPTION_NATURAL_ORDER,
) -> dict[str, Any]:
    """Build the ``chi_required_claim.v1`` record with its mandatory limitation."""
    profile = bond_rank_profile(qubit_count=qubit_count, pairs=pairs)
    floor = build_coefficient_floor(qubit_count=qubit_count, pairs=pairs)
    maximum = max(profile)
    payload: dict[str, Any] = {
        "schema_id": identities.CHI_REQUIRED_CLAIM_SCHEMA_ID,
        "regime_id": identities.REGIME_ID,
        "claim_id": bounded_text(claim_id, category="chi_claim_id_invalid"),
        "derivation_id": identities.CHI_DERIVATION_ID,
        "derivation_version": identities.CHI_DERIVATION_VERSION,
        "ordering_assumption": enum_value(
            ordering_assumption,
            allowed=ORDERING_ASSUMPTIONS,
            category="chi_claim_ordering_assumption_invalid",
        ),
        "evidence_class": EVIDENCE_CLASS_EXACT_FAMILY_SPECIFIC,
        "qubit_count": qubit_count,
        "nested_pair_count": len(normalized_pairs(pairs, qubit_count=qubit_count)),
        "chi_required": maximum,
        "chi_required_log2": maximum.bit_length() - 1,
        "maximum_bond_index": profile.index(maximum),
        "boundary_bond_rank": 1,
        "coefficient_floor": floor,
        "limitations": [identities.AER_MPS_LIMITATION],
        "claim_scope": CHI_CLAIM_SCOPE,
        "non_claims": list(CHI_CLAIM_NON_CLAIMS),
    }
    return seal_record(payload)


def compare_floor_to_envelope(
    *, floor: Mapping[str, Any], safe_envelope_bytes: int
) -> dict[str, Any]:
    """Compare a coefficient floor against a safe envelope. Never proves feasibility."""
    if not isinstance(floor, Mapping) or floor.get("procedure_id") != (
        identities.MPS_FLOOR_PROCEDURE_ID
    ):
        raise FocusedLoopError("mps_floor_record_invalid")
    floor_bytes = strict_int(
        floor.get("payload_floor_bytes"), category="mps_floor_record_invalid", minimum=1
    )
    envelope = strict_int(
        safe_envelope_bytes, category="resource_safe_envelope_invalid", minimum=1
    )
    exceeds = floor_bytes > envelope
    return {
        "payload_floor_bytes": floor_bytes,
        "safe_envelope_bytes": envelope,
        "excess_bytes": floor_bytes - envelope if exceeds else 0,
        "headroom_bytes": 0 if exceeds else envelope - floor_bytes,
        "floor_exceeds_envelope": exceeds,
        "exclusions": list(floor.get("exclusions", ())),
    }
