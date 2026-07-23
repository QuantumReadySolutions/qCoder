from __future__ import annotations

from copy import deepcopy
import json

import pytest

from qcoder.algorithm_blueprint import (
    ALGORITHM_BLUEPRINT_ARTIFACT_DISCRIMINATORS,
    PROFILE_IDS,
    algorithm_blueprint_contract_snapshot,
)
from qcoder.blueprint_decisions import (
    ACTION_IDS,
    CONTROL_TREATMENTS,
    DECISION_LOOP_GATE,
    GENERATION_EFFECTS,
    MOTIF_MAPPING_VERSION,
    PROFILE_DECISION_CATALOG_ID,
    PROFILE_DECISION_CATALOG_VERSION,
    PROFILE_DECISION_ID_VERSION,
    READINESS_RESULTS,
    RESOLUTION_CONTEXTS,
    RESOLUTION_STATES,
    SEMANTIC_CLASSIFICATIONS,
    USER_DISPOSITIONS,
    applicable_actions_for_decision,
    bound_error,
    build_decision_records,
    build_structured_decision_requests,
    calculate_blueprint_readiness,
    catalog_entries,
    confirm_decision_resolution_pack,
    decision_record_error,
    decision_reference_valid,
    decision_resolution_pack_error,
    pack_decision_record_set,
    profile_decision_catalog_snapshot,
    propose_decision_resolution_pack,
    unpack_decision_record_set,
)
from qcoder.context_bridge_mcp import (
    EXPECTED_TOOLS,
    PROMPT_CONTEXT_MODES,
    validate_optional_payload,
)
from qcoder.development_evidence import (
    ALIGNMENT_STATUSES,
    CHOICE_ORIGINS,
    EVIDENCE_CONFIDENCE_LABELS,
    MOTIF_REGISTRY,
    MOTIF_HIERARCHY_LEVELS,
)


LINEAGE = "session-artifact-0123456789abcdef"
PARENT = {
    "artifact_type": "implementation_blueprint",
    "artifact_digest": "a" * 64,
}


def _disposition(
    *,
    state: str = "resolved",
    user: str = "selected_choice",
    effect: str = "non_blocking",
    origin: str = "blueprint_confirmed",
) -> dict[str, object]:
    return {
        "resolution_state": state,
        "user_disposition": user,
        "generation_effect": effect,
        "selected_value": "synthetic_choice",
        "blueprint_representation_state": "represented",
        "choice_origin": origin,
        "evidence_confidence": "User-provided",
        "alignment_status": "appears_aligned",
    }


def _ready_dispositions(profile: str) -> dict[str, dict[str, object]]:
    result = {}
    for definition in catalog_entries(profile):
        if definition["generation_relevant"]:
            result[definition["profile_decision_id"]] = _disposition()
        else:
            result[definition["profile_decision_id"]] = _disposition(
                state="evidence_deferred",
                user="deferred_to_later_evidence",
                effect="non_blocking",
                origin="profile_expected",
            )
    return result


def _records(
    profile: str = "generic_qiskit",
    dispositions: object | None = None,
) -> list[dict[str, object]]:
    return build_decision_records(
        profile_id=profile,
        current_lineage_reference=LINEAGE,
        parent_artifact_references=[PARENT],
        dispositions=dispositions,
    )


def _selected_record(
    records: list[dict[str, object]], profile_decision_id: str
) -> dict[str, object]:
    return next(item for item in records if item["profile_decision_id"] == profile_decision_id)


def test_exact_contract_inventories_and_authorities() -> None:
    assert READINESS_RESULTS == (
        "ready_to_generate",
        "ready_with_bounded_discretion",
        "blocked_pending_decisions",
    )
    assert RESOLUTION_STATES == (
        "proposed",
        "resolved",
        "unresolved",
        "conflicting",
        "evidence_deferred",
        "not_applicable",
    )
    assert USER_DISPOSITIONS == (
        "selected_choice",
        "bounded_alternatives",
        "bounded_value_range",
        "deferred_to_source_evidence",
        "deferred_to_later_evidence",
        "left_unresolved",
        "not_supplied",
    )
    assert GENERATION_EFFECTS == ("non_blocking", "bounded_discretion", "blocking")
    assert RESOLUTION_CONTEXTS == (
        "blueprint_readiness",
        "source_alignment",
        "current_build_context",
    )
    assert len(ACTION_IDS) == 7
    snapshot = profile_decision_catalog_snapshot()
    assert snapshot["catalog_id"] == PROFILE_DECISION_CATALOG_ID
    assert snapshot["catalog_version"] == PROFILE_DECISION_CATALOG_VERSION
    assert snapshot["decision_id_version"] == PROFILE_DECISION_ID_VERSION
    assert snapshot["motif_mapping_version"] == MOTIF_MAPPING_VERSION
    assert tuple(snapshot["choice_origins"]) == CHOICE_ORIGINS
    assert tuple(snapshot["evidence_confidence_labels"]) == EVIDENCE_CONFIDENCE_LABELS
    assert tuple(snapshot["alignment_statuses"]) == ALIGNMENT_STATUSES
    assert SEMANTIC_CLASSIFICATIONS == (
        "evidence_observation",
        "decision_candidate",
        "blueprint_decision",
        "stage_manifestation",
    )
    assert CONTROL_TREATMENTS == (
        "keep_fixed",
        "allow_variation_within_bounds",
        "avoid",
        "defer",
        "current_implementation_detail",
    )
    assert tuple(snapshot["motif_hierarchy_levels"]) == MOTIF_HIERARCHY_LEVELS


def _controlled_observation() -> tuple[list[dict[str, object]], dict[str, object]]:
    records = _records("generic_qiskit", _ready_dispositions("generic_qiskit"))
    target = _selected_record(records, "generic_qiskit.controlled_operations")
    target.update(
        {
            "semantic_classification": "evidence_observation",
            "control_treatment": "current_implementation_detail",
            "resolution_state": "evidence_deferred",
            "user_disposition": "deferred_to_later_evidence",
            "generation_effect": "non_blocking",
            "blueprint_representation_state": "deferred",
            "choice_origin": "introduced_after_blueprint",
            "evidence_confidence": "Observed",
            "alignment_status": "introduced",
            "related_source_findings": ["source-finding-varied-controlled-structure"],
            "provenance_entries": [
                {
                    "choice_origin": "introduced_after_blueprint",
                    "source_finding_ref": "source-finding-varied-controlled-structure",
                    "non_causal": True,
                }
            ],
            "motif_hierarchy": [
                {
                    "motif_id": "qiskit.controlled.operations",
                    "hierarchy_level": 1,
                    "hierarchy_label": "micro_motif",
                }
            ],
        }
    )
    assert decision_record_error(target) is None
    return records, target


def test_controlled_micro_motif_remains_observation_and_is_not_adoptable() -> None:
    records, target = _controlled_observation()
    actions = applicable_actions_for_decision(target, resolution_context="source_alignment")
    assert "accept_and_add_to_blueprint" not in actions
    assert actions == [
        "clarify_requirement",
        "request_logical_circuit_evidence",
        "leave_unresolved",
    ]
    before = calculate_blueprint_readiness(profile_id="generic_qiskit", decision_records=records)
    with pytest.raises(ValueError, match="evidence_observation_promoted_without_decision"):
        propose_decision_resolution_pack(
            resolution_context="source_alignment",
            selected_action="accept_and_add_to_blueprint",
            profile_id="generic_qiskit",
            decision_records=records,
            parent_artifacts=[PARENT],
            selected_decision_references=[target["decision_ref"]],
            proposed_updates=[
                {
                    "decision_ref": target["decision_ref"],
                    "resolution_state": "resolved",
                    "user_disposition": "selected_choice",
                    "generation_effect": "non_blocking",
                    "blueprint_representation_state": "represented_in_derived_blueprint",
                }
            ],
            source_finding_references=target["related_source_findings"],
            current_lineage_reference=LINEAGE,
        )
    after = calculate_blueprint_readiness(profile_id="generic_qiskit", decision_records=records)
    assert before == after


def test_current_implementation_detail_can_be_left_unresolved_without_adoption() -> None:
    records, target = _controlled_observation()
    pack = propose_decision_resolution_pack(
        resolution_context="source_alignment",
        selected_action="leave_unresolved",
        profile_id="generic_qiskit",
        decision_records=records,
        parent_artifacts=[PARENT],
        selected_decision_references=[target["decision_ref"]],
        proposed_updates=[
            {
                "decision_ref": target["decision_ref"],
                "semantic_classification": "evidence_observation",
                "control_treatment": "current_implementation_detail",
                "resolution_state": "evidence_deferred",
                "user_disposition": "deferred_to_later_evidence",
                "generation_effect": "non_blocking",
                "blueprint_representation_state": "deferred",
            }
        ],
        source_finding_references=target["related_source_findings"],
        current_lineage_reference=LINEAGE,
    )
    assert pack["readiness_impact"]["before"] == pack["readiness_impact"]["after"]
    assert pack["control_treatments"][0]["treatment"] == ("current_implementation_detail")
    assert pack["proposed_derived_artifact_types"] == ["unresolved_decision_outcome"]


def test_structured_request_explains_without_answering_or_promoting() -> None:
    records, target = _controlled_observation()
    request = next(
        item
        for item in build_structured_decision_requests(
            profile_id="generic_qiskit", decision_records=records
        )
        if item["decision_ref"] == target["decision_ref"]
    )
    assert request["semantic_classification"] == "evidence_observation"
    assert request["available_control_treatments"] == [
        "defer",
        "current_implementation_detail",
    ]
    assert request["assistant_must_not_answer_or_confirm"] is True
    assert request["motif_hierarchy"][0]["hierarchy_label"] == "micro_motif"
    assert "accept_and_add_to_blueprint" not in request["contextually_applicable_actions"]


def test_three_profiles_have_unique_ordered_decisions_and_canonical_motifs() -> None:
    all_ids: set[str] = set()
    for profile in PROFILE_IDS:
        entries = catalog_entries(profile)
        assert entries
        assert [item["canonical_order"] for item in entries] == list(range(1, len(entries) + 1))
        for item in entries:
            assert item["profile_id"] == profile
            assert item["profile_decision_id"] not in all_ids
            all_ids.add(item["profile_decision_id"])
            assert set(item["canonical_motif_ids"]) <= set(MOTIF_REGISTRY)
    assert tuple(profile_decision_catalog_snapshot()["profile_ids"]) == PROFILE_IDS


def test_decision_references_are_opaque_unique_and_not_content_derived() -> None:
    first = _records()
    second = _records()
    assert all(decision_reference_valid(item["decision_ref"]) for item in first)
    assert len({item["decision_ref"] for item in first}) == len(first)
    assert {item["decision_ref"] for item in first}.isdisjoint(
        item["decision_ref"] for item in second
    )
    serialized = json.dumps(first, sort_keys=True)
    assert "synthetic_choice" not in "".join(item["decision_ref"] for item in first)
    assert "/home/" not in serialized


@pytest.mark.parametrize("profile", PROFILE_IDS)
def test_record_set_round_trip_is_lossless_and_transport_bounded(profile: str) -> None:
    records = _records(profile, _ready_dispositions(profile))
    packed = pack_decision_record_set(profile_id=profile, decision_records=records)
    assert unpack_decision_record_set(packed) == records
    assert validate_optional_payload(packed) == "ok"
    assert all(
        item["shared_context_reference"] == "blueprint_decision_record_set.v1"
        for item in packed["records"]
    )


@pytest.mark.parametrize("profile", PROFILE_IDS)
def test_fully_resolved_profile_is_ready_and_transport_bounded(profile: str) -> None:
    records = _records(profile, _ready_dispositions(profile))
    summary = calculate_blueprint_readiness(profile_id=profile, decision_records=records)
    assert summary["aggregate_readiness_result"] == "ready_to_generate"
    assert summary["generation_context_eligibility"] is True
    assert (
        validate_optional_payload(
            pack_decision_record_set(profile_id=profile, decision_records=records)
        )
        == "ok"
    )


def test_undisposed_and_confirmed_blueprint_still_blocks() -> None:
    records = _records()
    summary = calculate_blueprint_readiness(profile_id="generic_qiskit", decision_records=records)
    assert summary["aggregate_readiness_result"] == "blocked_pending_decisions"
    assert summary["generation_context_eligibility"] is False
    assert summary["blocking_decision_references"]


def test_valid_bounded_alternatives_are_ready_with_exact_discretion() -> None:
    dispositions = _ready_dispositions("grover_search")
    decision_id = "grover_search.oracle_approach"
    dispositions[decision_id] = {
        **_disposition(
            state="unresolved",
            user="bounded_alternatives",
            effect="bounded_discretion",
        ),
        "user_approved_bounds": {
            "bound_type": "finite_alternative_set",
            "allowed": ["phase_oracle", "bit_flip_oracle"],
            "source_visible_evidence_expected_later": "oracle call shape",
            "review_rule": "compare the selected source with the allowed set",
        },
        "explicitly_disallowed_choices": ["unbounded_oracle_choice"],
    }
    records = _records("grover_search", dispositions)
    summary = calculate_blueprint_readiness(profile_id="grover_search", decision_records=records)
    bounded = _selected_record(records, decision_id)
    assert summary["aggregate_readiness_result"] == "ready_with_bounded_discretion"
    assert summary["bounded_discretion_decision_references"] == [bounded["decision_ref"]]
    assert bounded["user_approved_bounds"]["allowed"] == [
        "phase_oracle",
        "bit_flip_oracle",
    ]


@pytest.mark.parametrize(
    ("bound", "expected"),
    [
        ({"bound_type": "finite_alternative_set", "allowed": []}, "bounded_alternatives_empty"),
        (
            {
                "bound_type": "numeric_or_ordinal_range",
                "lower_bound": 3,
                "upper_bound": 1,
                "domain": "integer",
                "unit": "layers",
                "lower_inclusive": True,
                "upper_inclusive": True,
                "source_visible_evidence_expected_later": "depth",
                "review_rule": "inspect depth",
            },
            "bounded_value_range_invalid",
        ),
        (
            {
                "bound_type": "numeric_or_ordinal_range",
                "lower_bound": 1,
                "upper_bound": 3,
                "domain": "integer",
                "unit": "meters",
                "lower_inclusive": True,
                "upper_inclusive": True,
                "source_visible_evidence_expected_later": "depth",
                "review_rule": "inspect depth",
            },
            "bounded_value_range_unit_invalid",
        ),
    ],
)
def test_invalid_bounds_are_rejected(bound: dict[str, object], expected: str) -> None:
    decision_id = (
        "qaoa.mixer" if bound.get("bound_type") == "finite_alternative_set" else "qaoa.repetitions"
    )
    definition = next(
        item for item in catalog_entries("qaoa") if item["profile_decision_id"] == decision_id
    )
    assert bound_error(bound, definition) == expected


def test_supported_numeric_range_is_bounded_discretion() -> None:
    dispositions = _ready_dispositions("qaoa")
    dispositions["qaoa.repetitions"] = {
        **_disposition(
            state="unresolved",
            user="bounded_value_range",
            effect="bounded_discretion",
        ),
        "user_approved_bounds": {
            "bound_type": "numeric_or_ordinal_range",
            "lower_bound": 1,
            "upper_bound": 3,
            "domain": "integer",
            "unit": "layers",
            "lower_inclusive": True,
            "upper_inclusive": True,
            "source_visible_evidence_expected_later": "source-visible layer count",
            "review_rule": "compare the observed layer count with the supplied range",
        },
        "explicitly_disallowed_choices": ["depth_outside_1_to_3"],
    }
    summary = calculate_blueprint_readiness(
        profile_id="qaoa",
        decision_records=_records("qaoa", dispositions),
    )
    assert summary["aggregate_readiness_result"] == "ready_with_bounded_discretion"


def test_version_parent_profile_unknown_and_duplicate_fail_closed() -> None:
    records = _records("grover_search", _ready_dispositions("grover_search"))
    assert (
        calculate_blueprint_readiness(
            profile_id="grover_search", decision_records=records, catalog_version=999
        )["aggregate_readiness_result"]
        == "blocked_pending_decisions"
    )
    assert (
        calculate_blueprint_readiness(
            profile_id="grover_search", decision_records=records, required_parents_present=False
        )["aggregate_readiness_result"]
        == "blocked_pending_decisions"
    )
    unknown = deepcopy(records)
    unknown[0]["applicability"] = "unknown"
    assert (
        calculate_blueprint_readiness(profile_id="grover_search", decision_records=unknown)[
            "aggregate_readiness_result"
        ]
        == "blocked_pending_decisions"
    )
    duplicate = deepcopy(records)
    duplicate[1]["decision_ref"] = duplicate[0]["decision_ref"]
    assert (
        calculate_blueprint_readiness(profile_id="grover_search", decision_records=duplicate)[
            "aggregate_readiness_result"
        ]
        == "blocked_pending_decisions"
    )


def test_evidence_deferred_is_non_blocking_only_when_catalog_allows() -> None:
    dispositions = _ready_dispositions("grover_search")
    nonblocking = dispositions["grover_search.logical_circuit_evidence"]
    assert nonblocking["user_disposition"] == "deferred_to_later_evidence"
    ready = calculate_blueprint_readiness(
        profile_id="grover_search",
        decision_records=_records("grover_search", dispositions),
    )
    assert ready["aggregate_readiness_result"] == "ready_to_generate"
    dispositions["grover_search.oracle_approach"] = _disposition(
        state="evidence_deferred",
        user="deferred_to_source_evidence",
        effect="non_blocking",
    )
    blocked = calculate_blueprint_readiness(
        profile_id="grover_search",
        decision_records=_records("grover_search", dispositions),
    )
    assert blocked["aggregate_readiness_result"] == "blocked_pending_decisions"


def _proposal(
    action: str,
    context: str = "source_alignment",
) -> tuple[list[dict[str, object]], dict[str, object], list[dict[str, object]]]:
    records = _records("grover_search", _ready_dispositions("grover_search"))
    target = _selected_record(records, "grover_search.oracle_approach")
    target["resolution_state"] = "unresolved"
    target["user_disposition"] = "not_supplied"
    target["generation_effect"] = "blocking"
    target["choice_origin"] = "introduced_after_blueprint"
    target["evidence_confidence"] = "Observed"
    target["alignment_status"] = "introduced"
    target["related_source_findings"] = ["source-finding-oracle-1"]
    target["provenance_entries"] = [
        {
            "choice_origin": "introduced_after_blueprint",
            "source_finding_ref": "source-finding-oracle-1",
        }
    ]
    updates = [
        {
            "decision_ref": target["decision_ref"],
            "semantic_classification": "blueprint_decision",
            "control_treatment": "keep_fixed",
            "semantic_role": "Oracle implementation used by the supplied Grover search blueprint.",
            "applicable_scope": "The explicitly supplied oracle subroutine for this blueprint lineage.",
            "relationship_to_requirement": "Resolves the supplied oracle-approach requirement.",
            "related_requirement_references": ["requirement-oracle-approach"],
            "evidence_expectation": ["source-visible oracle construction"],
            "future_review_rule": "Compare the selected source oracle with the confirmed oracle approach.",
            "remaining_non_proofs": [
                "Acceptance does not prove oracle correctness or Grover identity."
            ],
            "resolution_state": "resolved",
            "user_disposition": "selected_choice",
            "generation_effect": "non_blocking",
            "blueprint_representation_state": "represented_in_derived_blueprint",
            "provenance_entries": target["provenance_entries"]
            + [{"user_disposition": "selected_choice"}],
        }
    ]
    parents = [PARENT]
    pack = propose_decision_resolution_pack(
        resolution_context=context,
        selected_action=action,
        profile_id="grover_search",
        decision_records=records,
        parent_artifacts=parents,
        selected_decision_references=[target["decision_ref"]],
        proposed_updates=updates,
        source_finding_references=(
            ["source-finding-oracle-1"] if context == "source_alignment" else None
        ),
        current_lineage_reference=LINEAGE,
        proposal_ref="proposal-0123456789abcdefghijkl",
        prospective_derived_references=["derived-0123456789abcdefghijkl"],
    )
    return records, pack, parents


def test_one_resolution_pack_supports_both_contexts() -> None:
    _, source_pack, _ = _proposal("accept_and_add_to_blueprint")
    _, readiness_pack, _ = _proposal("clarify_requirement", "blueprint_readiness")
    assert source_pack["section_type"] == readiness_pack["section_type"]
    assert source_pack["resolution_context"] == "source_alignment"
    assert readiness_pack["resolution_context"] == "blueprint_readiness"
    assert source_pack["executed"] is False
    assert source_pack["persistent"] is False


@pytest.mark.parametrize("action", ACTION_IDS)
def test_all_seven_actions_materialize_only_after_confirmation(action: str) -> None:
    context = (
        "source_alignment"
        if action
        in {
            "accept_and_add_to_blueprint",
            "ask_assistant_to_regenerate",
            "request_logical_circuit_evidence",
        }
        else "blueprint_readiness"
    )
    records, pack, parents = _proposal(action, context)
    before = deepcopy(parents)
    with pytest.raises(ValueError, match="explicit_resolution_confirmation_required"):
        confirm_decision_resolution_pack(
            decision_resolution_pack=pack,
            parent_artifacts=parents,
            decision_records=records,
            selected_action=action,
            confirmed=False,
            confirmation_payload=pack["explicit_confirmation_requirements"]["confirmation_payload"],
        )
    result = confirm_decision_resolution_pack(
        decision_resolution_pack=pack,
        parent_artifacts=parents,
        decision_records=records,
        selected_action=action,
        confirmed=True,
        confirmation_payload=pack["explicit_confirmation_requirements"]["confirmation_payload"],
    )
    assert parents == before
    assert result["parent_artifacts_mutated"] is False
    assert result["hidden_lookup_performed"] is False
    assert result["retained_artifacts"] == []
    assert result["materialized_artifact"]["selected_action"] == action
    if action == "ask_assistant_to_regenerate":
        assert result["materialized_artifact"]["assistant_invoked"] is False
    if action == "request_logical_circuit_evidence":
        assert result["materialized_artifact"]["evidence_obtained"] is False
    if action == "leave_unresolved":
        assert result["materialized_artifact"]["generation_context_pack_produced"] is False


def test_confirmation_is_idempotent_and_preserves_source_origin() -> None:
    records, pack, parents = _proposal("accept_and_add_to_blueprint")
    kwargs = {
        "decision_resolution_pack": pack,
        "parent_artifacts": parents,
        "decision_records": records,
        "selected_action": "accept_and_add_to_blueprint",
        "confirmed": True,
        "confirmation_payload": pack["explicit_confirmation_requirements"]["confirmation_payload"],
    }
    first = confirm_decision_resolution_pack(**kwargs)
    second = confirm_decision_resolution_pack(**kwargs)
    assert first == second
    updated = _selected_record(
        first["materialized_artifact"]["decision_records"],
        "grover_search.oracle_approach",
    )
    assert updated["choice_origin"] == "introduced_after_blueprint"
    assert updated["evidence_confidence"] == "Observed"
    assert updated["alignment_status"] == "introduced"
    assert updated["provenance_entries"][0]["source_finding_ref"] == ("source-finding-oracle-1")


def test_altered_parent_action_payload_or_pack_is_rejected() -> None:
    records, pack, parents = _proposal("accept_and_add_to_blueprint")
    altered = deepcopy(pack)
    altered["selected_action"] = "leave_unresolved"
    assert decision_resolution_pack_error(altered) == "resolution_proposal_altered"
    with pytest.raises(ValueError, match="resolution_parent_mismatch"):
        confirm_decision_resolution_pack(
            decision_resolution_pack=pack,
            parent_artifacts=[{**PARENT, "artifact_digest": "b" * 64}],
            decision_records=records,
            selected_action="accept_and_add_to_blueprint",
            confirmed=True,
            confirmation_payload=pack["explicit_confirmation_requirements"]["confirmation_payload"],
        )
    with pytest.raises(ValueError, match="resolution_confirmation_payload_mismatch"):
        confirm_decision_resolution_pack(
            decision_resolution_pack=pack,
            parent_artifacts=parents,
            decision_records=records,
            selected_action="accept_and_add_to_blueprint",
            confirmed=True,
            confirmation_payload={"decision_updates": []},
        )


def test_axes_remain_independent() -> None:
    records = _records("qaoa", _ready_dispositions("qaoa"))
    record = deepcopy(records[0])
    record["choice_origin"] = "introduced_after_blueprint"
    record["evidence_confidence"] = "Assumed"
    record["alignment_status"] = "conflicting"
    record["resolution_state"] = "resolved"
    assert decision_record_error(record) is None
    assert record["choice_origin"] != record["resolution_state"]


def test_legacy_contract_shape_and_capability_inventories_remain_stable() -> None:
    snapshot = algorithm_blueprint_contract_snapshot()
    assert snapshot["profile_decision_catalog"]["decision_loop_gate"] == DECISION_LOOP_GATE
    assert len(EXPECTED_TOOLS) == 12
    assert len(PROMPT_CONTEXT_MODES) == 5
    assert tuple(snapshot["profile_ids"]) == PROFILE_IDS
    assert (
        ALGORITHM_BLUEPRINT_ARTIFACT_DISCRIMINATORS["create_source_blueprint_alignment_review"][
            "value"
        ]
        == "source_blueprint_alignment_review"
    )
    for tool in snapshot["tool_names"]:
        assert "decision_loop" in snapshot["tool_input_fields"][tool]
        assert "decision_loop" not in snapshot["required_request_properties"][tool]


def test_no_hidden_state_later_stage_result_or_causal_claim() -> None:
    serialized = json.dumps(profile_decision_catalog_snapshot(), sort_keys=True).lower()
    assert "no authorship, intent, or causal attribution" in serialized
    assert "ai-selected" not in serialized
    assert "model-selected" not in serialized
    assert profile_decision_catalog_snapshot()["later_stage_analyzers"] == []
    assert profile_decision_catalog_snapshot()["persistent"] is False
    assert profile_decision_catalog_snapshot()["hidden_lookup"] is False
