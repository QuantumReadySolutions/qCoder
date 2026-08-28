"""Bounded customer-first projection for Algorithm Blueprint review."""

from __future__ import annotations

from typing import Any, Mapping


FIRST_VALUE_GROUPS = (
    (
        "goal_and_scope",
        "Goal and scope",
        ("normalized_goal", "problem_size_meaning"),
    ),
    (
        "implementation",
        "Implementation",
        ("framework_requirement", "measurement_plan"),
    ),
    (
        "execution_and_output",
        "Execution and output",
        ("execution_intent", "desired_output"),
    ),
)


def first_value_dialogue_contract_snapshot() -> dict[str, Any]:
    """Return the client-neutral D-105 Blueprint decision boundary."""

    return {
        "schema_id": "qcoder.algorithm_blueprint.first_value_dialogue.v1",
        "schema_version": 1,
        "recommended_interpretation_first": True,
        "customer_actions": ["Use recommended choices", "Review or change choices"],
        "initial_decision_group_maximum": 3,
        "remaining_consequential_choices": "progressively_disclosed_on_review",
        "explicit_confirmation_before_source_generation": True,
        "automatic_confirmation": False,
        "routine_setup_tool_schema_workflow_choreography_narration": False,
        "real_blockers_and_material_customer_decisions_visible": True,
    }


def build_first_value_dialogue(
    card: Mapping[str, Any],
    *,
    proposed_interpretation: Mapping[str, Any] | None = None,
    unresolved_field_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Project only reviewed recommendations and bounded decision controls."""

    card_interpretation = card.get("interpretation")
    interpretation: Mapping[str, Any] = (
        card_interpretation
        if isinstance(card_interpretation, Mapping)
        else proposed_interpretation
        if isinstance(proposed_interpretation, Mapping)
        else {}
    )
    presented: set[str] = set()
    groups: list[dict[str, Any]] = []
    for group_id, label, field_ids in FIRST_VALUE_GROUPS:
        values = {
            field_id: interpretation[field_id]
            for field_id in field_ids
            if isinstance(interpretation.get(field_id), str)
            and str(interpretation[field_id]).strip()
        }
        if values:
            groups.append(
                {
                    "group_id": group_id,
                    "label": label,
                    "recommended_values": values,
                }
            )
            presented.update(values)
    unresolved = card.get("unresolved_questions")
    unresolved_fields = (
        [str(field) for field in unresolved if isinstance(field, str)]
        if isinstance(unresolved, list)
        else list(unresolved_field_ids or [])
    )
    remaining = sorted(
        (set(str(key) for key in interpretation) | set(unresolved_fields)) - presented
    )
    return {
        "schema_id": "qcoder.algorithm_blueprint.first_value_dialogue.v1",
        "schema_version": 1,
        "recommended_interpretation": {
            key: interpretation[key] for key in sorted(presented) if key in interpretation
        },
        "customer_actions": ["Use recommended choices", "Review or change choices"],
        "initial_decision_groups": groups[:3],
        "initial_decision_group_count": min(len(groups), 3),
        "initial_decision_group_maximum": 3,
        "progressive_disclosure": {
            "available": bool(remaining),
            "revealed_by": "Review or change choices",
            "remaining_field_ids": remaining,
        },
        "confirmation_state": card.get("confirmation_state"),
        "explicit_confirmation_required_before_source_generation": True,
        "automatic_confirmation": False,
        "routine_procedural_narration": False,
    }
