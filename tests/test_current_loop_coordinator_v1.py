from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from qcoder.algorithm_blueprint import with_artifact_digest
from qcoder.blueprint_decisions import (
    ACTION_IDS,
    build_decision_records,
    catalog_entries,
    pack_decision_record_set,
    unpack_decision_record_set,
    with_consistency_digest,
)
from qcoder.context_bridge_mcp import EXPECTED_TOOLS, PROMPT_CONTEXT_MODES
from qcoder.cli import _parse_current_loop_scalar, main as cli_main
from qcoder.context_loop import (
    build_carry_forward_proposal,
    build_current_build_context,
    build_portable_current_build_context,
    context_loop_contract_snapshot,
    materialize_evolved_blueprint,
)
from qcoder.current_loop import CurrentLoopStore, decision_inventory_binding
from qcoder.current_loop_coordinator import (
    CHECKPOINT_KINDS,
    CLIENT_NAMES,
    PHASES,
    STATE_STATUSES,
    CurrentLoopCoordinator,
    consequence_projection,
    coordinator_contract_snapshot,
    infer_requested_posture,
)
import qcoder.current_loop_coordinator as current_loop_coordinator_module


PROFILE_COUNTS = {
    "generic_qiskit": 19,
    "grover_search": 12,
    "qaoa": 17,
}


def _reference(index: int) -> str:
    return f"session-artifact-{index:032x}"


def _artifact(
    artifact_type: str,
    index: int,
    **values: object,
) -> dict[str, Any]:
    return with_artifact_digest(
        {
            "schema_id": f"qcoder.{artifact_type}.v1",
            "schema_version": 1,
            "artifact_type": artifact_type,
            "artifact_ref": _reference(index),
            **values,
        }
    )


def _user_dispositions(profile_id: str) -> list[dict[str, str]]:
    return [
        {
            "profile_decision_id": item["profile_decision_id"],
            "resolution_state": "resolved",
            "user_disposition": "selected_choice",
            "generation_effect": "non_blocking",
            "choice_origin": "human_specified",
        }
        for item in catalog_entries(profile_id)
    ]


def _protected_dispositions(profile_id: str) -> list[dict[str, Any]]:
    return [
        {
            **item,
            "semantic_classification": "blueprint_decision",
            "control_treatment": "keep_fixed",
            "semantic_role": (
                f"Canonical {item['profile_decision_id']} decision for this lineage."
            ),
            "applicable_scope": "current_lineage",
            "relationship_to_requirement": ("Controls one explicitly reviewed generation choice."),
            "related_requirement_references": [f"requirement:{item['profile_decision_id']}"],
            "evidence_expectation": [
                "Future selected evidence can be reviewed against this decision."
            ],
            "future_review_rule": ("Compare only explicitly supplied bounded evidence."),
            "remaining_non_proofs": [
                "This decision does not prove correctness or runtime behavior."
            ],
            "available_control_treatments": [
                "keep_fixed",
                "allow_variation_within_bounds",
                "defer",
            ],
            "blueprint_representation_state": "represented",
            "provenance_entries": [
                {
                    "role": "user_reviewed_profile_disposition",
                    "preserves_original_request": True,
                }
            ],
        }
        for item in _user_dispositions(profile_id)
    ]


class PublicBuilderTransport:
    """Protected-side test double built only from canonical public contracts."""

    def __init__(
        self,
        *,
        drop_current_portable: bool = False,
        drop_proposal_portable: bool = False,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._counter = 100
        self._record_sets: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.proposal_arguments: dict[str, Any] | None = None
        self.proposal: dict[str, Any] | None = None
        self.drop_current_portable = drop_current_portable
        self.drop_proposal_portable = drop_proposal_portable

    def _next_ref(self) -> str:
        self._counter += 1
        return _reference(self._counter)

    def call(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        supplied = deepcopy(dict(arguments))
        self.calls.append((tool_name, supplied))
        if tool_name == "create_algorithm_intent_card":
            return self._intent(supplied)
        if tool_name == "create_implementation_blueprint":
            if supplied.get("resolution_phase") == "propose":
                return self._proposal(supplied)
            return self._blueprint(supplied)
        if tool_name == "create_generation_context_pack":
            return {
                "ok": True,
                "generation_context_pack": _artifact(
                    "generation_context_pack",
                    self._counter + 1,
                    governing_blueprint_reference={
                        "artifact_ref": supplied["implementation_blueprint"].get("artifact_ref"),
                        "digest": supplied["implementation_blueprint"].get("artifact_digest"),
                    },
                    raw_artifacts_included=False,
                    retention="process_and_discard",
                ),
            }
        if tool_name == "create_source_blueprint_alignment_review":
            return {
                "ok": True,
                "source_blueprint_alignment_review": _artifact(
                    "source_blueprint_alignment_review",
                    self._counter + 2,
                    alignment_status="represented",
                    generation_effect="non_blocking",
                    non_proofs=["Source evidence does not prove runtime behavior."],
                ),
            }
        if tool_name == "create_result_review_context_card":
            return {
                "ok": True,
                "result_review_context_card": _artifact(
                    "result_review_context_card",
                    self._counter + 3,
                    result_evidence_status="represented",
                    generation_effect="non_blocking",
                    non_proofs=["Observed counts do not prove correctness."],
                ),
            }
        if tool_name == "create_context_session_card":
            return self._current_build(supplied)
        raise AssertionError(f"unexpected protected operation: {tool_name}")

    def _intent(self, supplied: Mapping[str, Any]) -> dict[str, Any]:
        profile_id = str(supplied["profile_id"])
        lineage = str(supplied["current_lineage_reference"])
        key = (profile_id, lineage)
        records = self._record_sets.get(key)
        if records is None:
            records = build_decision_records(
                profile_id=profile_id,
                current_lineage_reference=lineage,
                parent_artifact_references=[{"artifact_ref": lineage}],
                dispositions=_protected_dispositions(profile_id),
            )
            self._record_sets[key] = records
        confirmed = supplied.get("requested_confirmation_state") == "confirmed"
        card = _artifact(
            "algorithm_intent_card",
            self._counter + 4 if confirmed else self._counter + 5,
            selected_profile=profile_id,
            confirmation_state="confirmed" if confirmed else "needs_clarification",
            user_reviewed_assertion_supplied=confirmed,
            decision_loop={
                "gate": "readiness_resolution_v1",
                "catalog_version": 1,
            },
            blueprint_decision_records=pack_decision_record_set(
                profile_id=profile_id,
                decision_records=records,
            ),
            original_request_preserved=True,
            assistant_interpretation_attributed=True,
            hidden_intent_claimed=False,
            retention="process_and_discard",
        )
        return {"ok": True, "algorithm_intent_card": card}

    def _blueprint(self, supplied: Mapping[str, Any]) -> dict[str, Any]:
        card = supplied["algorithm_intent_card"]
        records = unpack_decision_record_set(card["blueprint_decision_records"])
        profile_id = records[0]["selected_profile"]
        blueprint = _artifact(
            "implementation_blueprint",
            self._counter + 6,
            selected_profile=profile_id,
            confirmation_state="confirmed",
            decision_loop={
                "gate": "readiness_resolution_v1",
                "catalog_version": 1,
            },
            blueprint_decision_records=pack_decision_record_set(
                profile_id=profile_id,
                decision_records=records,
            ),
            blueprint_readiness_summary={
                "aggregate_readiness_result": "ready_to_generate",
                "generation_context_eligibility": True,
                "blocking_decision_references": [],
                "bounded_discretion_decision_references": [],
                "evidence_deferred_decision_references": [],
                "non_proof": "Readiness is contract-relative.",
            },
            parent_intent_reference={
                "artifact_ref": card["artifact_ref"],
                "digest": card["artifact_digest"],
            },
            retention="process_and_discard",
        )
        output_contract = _artifact(
            "output_evidence_contract",
            self._counter + 7,
            working_blueprint_reference={
                "artifact_ref": blueprint["artifact_ref"],
                "digest": blueprint["artifact_digest"],
            },
            raw_artifact_transfer_required=False,
            retention="process_and_discard",
        )
        return {
            "ok": True,
            "implementation_blueprint": blueprint,
            "output_evidence_contract": output_contract,
        }

    def _current_build(self, supplied: Mapping[str, Any]) -> dict[str, Any]:
        optional = {
            name: supplied.get(name)
            for name in (
                "generation_context",
                "python_manifestation",
                "circuit_manifestation",
                "result_manifestation",
            )
            if isinstance(supplied.get(name), Mapping)
        }
        current = build_current_build_context(
            profile_id=supplied["working_blueprint"]["selected_profile"],
            request_baseline=supplied["request_baseline"],
            working_blueprint=supplied["working_blueprint"],
            stage_availability=supplied["stage_availability"],
            lineage=supplied["decision_evidence_lineage"],
            artifact_references={},
            **optional,
        )
        records = unpack_decision_record_set(
            supplied["working_blueprint"]["blueprint_decision_records"]
        )
        portable = build_portable_current_build_context(
            current_build_context=current,
            decision_records=records,
            decision_evidence_lineage=supplied["decision_evidence_lineage"],
            readiness=supplied["working_blueprint"]["blueprint_readiness_summary"],
        )
        result = {
            "ok": True,
            "current_build_context": current,
            "portable_current_build_context": portable,
        }
        if self.drop_current_portable:
            result.pop("portable_current_build_context")
        return result

    def _proposal(self, supplied: Mapping[str, Any]) -> dict[str, Any]:
        records = [deepcopy(item) for item in supplied["decision_records"]]
        proposal = build_carry_forward_proposal(
            selected_action=supplied["selected_action"],
            profile_id=supplied["profile_id"],
            decision_records=records,
            parent_artifacts=supplied["evidence_parent_artifacts"],
            current_build_context=supplied["current_build_context"],
            selected_decision_references=supplied["selected_decision_references"],
            proposed_updates=supplied["proposed_updates"],
            current_lineage_reference=supplied["current_lineage_reference"],
            remaining_uncertainty=supplied["remaining_uncertainty"],
            generation_context_effect=supplied["generation_context_effect"],
            proposal_ref="proposal-coordinator-proof-0001",
            prospective_derived_references=["derived-coordinator-proof-0001"],
        )
        proposal = with_consistency_digest(
            {key: deepcopy(value) for key, value in proposal.items() if key != "consistency_digest"}
            | {
                "proposal_state": "unconfirmed",
                "derived_artifact_materialized": False,
            }
        )
        lineage = next(
            parent
            for parent in supplied["evidence_parent_artifacts"]
            if parent.get("artifact_type") == "decision_evidence_lineage"
        )
        portable = build_portable_current_build_context(
            current_build_context=supplied["current_build_context"],
            decision_records=records,
            decision_evidence_lineage=lineage,
            readiness=supplied["working_blueprint"].get("blueprint_readiness_summary"),
            carry_forward_proposal=proposal,
        )
        self.proposal_arguments = deepcopy(dict(supplied))
        self.proposal = proposal
        result = {
            "ok": True,
            "carry_forward_proposal": proposal,
            "portable_current_build_context": portable,
            "proposal_state": "unconfirmed",
            "derived_artifact_materialized": False,
        }
        if self.drop_proposal_portable:
            result.pop("portable_current_build_context")
        return result

    def confirm_selected_bundle(
        self,
        *,
        selected_bundle_file: str | Path,
        semantic_confirmation: str,
    ) -> dict[str, Any]:
        assert self.proposal is not None
        assert self.proposal_arguments is not None
        portable = json.loads(Path(selected_bundle_file).read_text(encoding="utf-8"))
        assert portable["carry_forward_proposal"]["proposal_ref"] == self.proposal["proposal_ref"]
        assert self.proposal["proposal_ref"] in semantic_confirmation
        result = materialize_evolved_blueprint(
            decision_resolution_pack=self.proposal,
            parent_artifacts=self.proposal_arguments["evidence_parent_artifacts"],
            working_blueprint=self.proposal_arguments["working_blueprint"],
            decision_records=self.proposal_arguments["decision_records"],
            selected_action=self.proposal_arguments["selected_action"],
            confirmed=True,
            confirmation_payload=self.proposal["explicit_confirmation_requirements"][
                "confirmation_payload"
            ],
            provenance_entries=[],
        )
        return {"ok": True, "evolved_blueprint": result["evolved_blueprint"]}


def _coordinator(
    tmp_path: Path,
    transport: PublicBuilderTransport | None = None,
) -> tuple[CurrentLoopCoordinator, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return (
        CurrentLoopCoordinator(
            workspace_root=workspace,
            transport=transport,
        ),
        workspace,
    )


def _activate_and_prepare(
    coordinator: CurrentLoopCoordinator,
    *,
    profile_id: str = "generic_qiskit",
    posture: str = "exploratory_first_pass",
) -> dict[str, Any]:
    request = (
        "Use qCoder for a quick first pass on a small local quantum circuit."
        if posture == "exploratory_first_pass"
        else "Use qCoder with deliberate Blueprint control before generation."
    )
    activated = coordinator.activate(
        original_request=request,
        generation_posture=posture,
        explicit_authority=True,
        assistant_interpretation={"summary": "A separately attributed proposal."},
    )
    assert activated["ok"] is True
    clarification = coordinator.prepare_generation(
        profile_id=profile_id,
        proposed_interpretation={"normalized_goal": "Build one bounded example."},
        decision_dispositions=_user_dispositions(profile_id),
        explicit_intent_approval=False,
    )
    assert clarification["details"]["intent_confirmation_state"] == ("needs_clarification")
    confirmed = coordinator.prepare_generation(
        profile_id=profile_id,
        proposed_interpretation={"normalized_goal": "Build one bounded example."},
        decision_dispositions=_user_dispositions(profile_id),
        reviewed_profile_answers={
            "framework_requirement": "Use the explicitly selected SDK.",
        },
        explicit_intent_approval=True,
        confirmation_assertion="I approve this interpretation for this generation.",
    )
    assert confirmed["ok"] is True
    return confirmed


def test_contract_surface_is_additive_and_inventory_is_unchanged() -> None:
    snapshot = coordinator_contract_snapshot()
    assert snapshot["schemas"]["result"] == "qcoder.current_loop.coordinator_result.v2"
    assert snapshot["checkpoint_result_protocol"]["schema_version"] == 2
    assert all(snapshot["checkpoint_result_protocol"].values())
    contract_digest = hashlib.sha256(
        json.dumps(
            context_loop_contract_snapshot(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    assert contract_digest == ("2f985d84fcb046b18142617c0239e7a8ef81073acae8783e118b87cab1b7987e")
    assert snapshot["phases"] == list(PHASES)
    assert snapshot["state_statuses"] == list(STATE_STATUSES)
    assert snapshot["checkpoint_kinds"] == list(CHECKPOINT_KINDS)
    assert snapshot["recovery_categories"] == [
        "authorization_declined",
        "authorization_partial",
        "canonical_artifact_modified",
        "client_state_conflict",
        "ide_write_or_run_denied",
        "local_state_corrupt",
        "loop_already_active",
        "loop_not_activated",
        "parent_digest_mismatch",
        "posture_required",
        "protected_operation_rejected",
        "protected_service_unavailable",
        "protected_truth_insufficient",
        "reconstruction_attempt_refused",
        "seed_incomplete",
        "selected_file_missing",
        "selected_file_stale",
        "unsupported_schema",
    ]
    assert snapshot["connected_clients"] == list(CLIENT_NAMES)
    assert snapshot["protected_operation_added"] is False
    assert snapshot["mcp_tool_added"] is False
    assert snapshot["assistant_reconstruction_allowed"] is False
    assert len(EXPECTED_TOOLS) == 12
    assert len(PROMPT_CONTEXT_MODES) == 5
    assert len(PROFILE_COUNTS) == 3
    assert len(ACTION_IDS) == 7


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Use qCoder for a quick first pass.", "exploratory_first_pass"),
        (
            "Use qCoder with deliberate Blueprint control.",
            "blueprint_guided",
        ),
        ("Use qCoder.", None),
        ("Review this Python.", None),
    ],
)
def test_posture_is_only_classified_from_explicit_wording(
    prompt: str, expected: str | None
) -> None:
    assert infer_requested_posture(prompt) == expected


def test_activation_requires_authority_and_preserves_original_words(
    tmp_path: Path,
) -> None:
    coordinator, workspace = _coordinator(tmp_path)
    offered = coordinator.activation_offer("Use qCoder.")
    assert offered["category"] == "posture_required"
    assert offered["details"]["activation_performed"] is False
    denied = coordinator.activate(
        original_request="Use qCoder for a quick first pass.",
        generation_posture="exploratory_first_pass",
        explicit_authority=False,
    )
    assert denied["checkpoint_kind"] == "activation"
    assert not (workspace / ".qcoder").exists()
    words = "Use qCoder for a quick first pass. Keep my exact words."
    activated = coordinator.activate(
        original_request=words,
        generation_posture="exploratory_first_pass",
        explicit_authority=True,
        assistant_interpretation={"summary": "Assistant proposal"},
    )
    assert activated["ok"] is True
    baseline_path = workspace / ".qcoder/current-loop/artifacts/request-baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert baseline["original_request"] == words
    assert baseline["provenance_entries"][0]["role"] == "user_stated"
    assert baseline["provenance_entries"][1]["role"] == "assistant_proposed"
    assert activated["details"]["ide_write_or_run_authorized"] is False
    assert activated["details"]["artifact_review_authorized"] is False


@pytest.mark.parametrize("profile_id,expected_count", PROFILE_COUNTS.items())
@pytest.mark.parametrize("posture", ("exploratory_first_pass", "blueprint_guided"))
def test_clarification_recovery_preserves_complete_profile_inventory(
    tmp_path: Path,
    profile_id: str,
    expected_count: int,
    posture: str,
) -> None:
    transport = PublicBuilderTransport()
    coordinator, workspace = _coordinator(tmp_path, transport)
    result = _activate_and_prepare(coordinator, profile_id=profile_id, posture=posture)
    assert result["details"]["decision_inventory"]["decision_count"] == (expected_count)
    intent = json.loads(
        (workspace / ".qcoder/current-loop/artifacts/algorithm-intent-card.json").read_text(
            encoding="utf-8"
        )
    )
    blueprint = json.loads(
        (workspace / ".qcoder/current-loop/artifacts/working-blueprint.json").read_text(
            encoding="utf-8"
        )
    )
    assert decision_inventory_binding(intent) == decision_inventory_binding(blueprint)
    assert blueprint["artifact_type"] == "implementation_blueprint"
    intent_calls = [
        arguments for tool, arguments in transport.calls if tool == "create_algorithm_intent_card"
    ]
    assert len(intent_calls) == 2
    assert all(
        call["decision_loop"] == "readiness_resolution_v1"
        and call["profile_decision_catalog_version"] == 1
        and "blueprint_decision_records" not in call
        for call in intent_calls
    )
    review_files = list(
        (workspace / ".qcoder/current-loop/artifacts").glob("algorithm-intent-review-*.json")
    )
    assert len(review_files) == 1


def _write_local_artifacts(workspace: Path) -> list[dict[str, Any]]:
    source = workspace / "bell.py"
    source.write_text(
        "from qiskit import QuantumCircuit\n"
        "circuit = QuantumCircuit(2, 2)\n"
        "circuit.h(0)\n"
        "circuit.cx(0, 1)\n"
        "circuit.measure([0, 1], [0, 1])\n",
        encoding="utf-8",
    )
    qasm = workspace / "bell.qasm"
    qasm.write_text(
        'OPENQASM 2.0;\ninclude "qelib1.inc";\n'
        "qreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\n"
        "measure q[0] -> c[0];\nmeasure q[1] -> c[1];\n",
        encoding="utf-8",
    )
    result = workspace / "bell.counts.json"
    result.write_text(
        json.dumps({"counts": {"00": 511, "11": 513}, "shots": 1024}),
        encoding="utf-8",
    )
    return [
        {
            "role": "source",
            "path": str(source),
            "provenance": "assistant_created",
        },
        {
            "role": "circuit_qasm",
            "path": str(qasm),
            "provenance": "assistant_created",
        },
        {
            "role": "results",
            "path": str(result),
            "provenance": "assistant_created",
        },
    ]


def _through_current_build(
    tmp_path: Path,
    *,
    transport: PublicBuilderTransport | None = None,
    expected_review_ok: bool = True,
) -> tuple[
    CurrentLoopCoordinator,
    PublicBuilderTransport,
    Path,
    dict[str, Any],
]:
    transport = transport or PublicBuilderTransport()
    coordinator, workspace = _coordinator(tmp_path, transport)
    _activate_and_prepare(coordinator)
    authority = coordinator.record_ide_authority(allowed=True, explicit_user_action=True)
    assert authority["details"]["artifact_review_authorized"] is False
    registered = coordinator.register_artifacts(candidates=_write_local_artifacts(workspace))
    assert registered["details"]["directory_scanned"] is False
    assert registered["details"]["review_authorized"] is False
    authorized = coordinator.authorize_artifacts(
        action="approve_all",
        explicit_action_provenance="direct_user_action",
    )
    assert authorized["details"]["authorization_state"] == "approved"
    assert authorized["details"]["ide_write_or_run_implied"] is False
    assert authorized["details"]["share_safe_projection"]["local_paths_included"] is False
    processed = coordinator.process_authorized_artifacts()
    assert processed["ok"] is True, processed
    assert set(processed["details"]["extracted_roles"]) >= {
        "source_evidence",
        "python_manifestation",
        "circuit_manifestation",
        "result_manifestation",
        "source_blueprint_alignment",
        "result_review_context_card",
    }
    assert processed["details"]["raw_source_sent"] is False
    assert processed["details"]["raw_qasm_sent"] is False
    assert processed["details"]["raw_results_sent"] is False
    review = coordinator.review_build()
    assert review["ok"] is expected_review_ok
    if expected_review_ok:
        assert review["phase"] == "continuation_choice"
    return coordinator, transport, workspace, review


def test_three_authorities_extraction_and_exact_saving(tmp_path: Path) -> None:
    coordinator, transport, workspace, review = _through_current_build(tmp_path)
    state = CurrentLoopStore.for_workspace(workspace).read()
    assert state["artifact_authorization"]["state"] == "approved"
    assert state["directory_scan_performed"] is False
    assert state["watcher_active"] is False
    protected_serialized = json.dumps(transport.calls, sort_keys=True)
    assert str(workspace) not in protected_serialized
    assert "QuantumCircuit(2, 2)" not in protected_serialized
    assert '"00": 511' not in protected_serialized
    assert review["details"]["readiness_calculated_locally"] is False
    assert review["details"]["expanded_truth_preserved"] is True
    for role, descriptor in state["saved_artifacts"].items():
        artifact = json.loads(Path(descriptor["local_path"]).read_text(encoding="utf-8"))
        assert (
            artifact.get("artifact_digest") == descriptor["artifact_digest"]
            or artifact.get("consistency_digest") == descriptor["artifact_digest"]
        ), role
    assert coordinator.private_performance_snapshot()["manual_serialization_actions"] == 0


def test_authorization_decline_partial_and_stale_recovery(
    tmp_path: Path,
) -> None:
    transport = PublicBuilderTransport()
    coordinator, workspace = _coordinator(tmp_path, transport)
    _activate_and_prepare(coordinator)
    coordinator.record_ide_authority(allowed=True, explicit_user_action=True)
    candidates = _write_local_artifacts(workspace)
    coordinator.register_artifacts(candidates=candidates)
    partial = coordinator.authorize_artifacts(
        action="remove_one",
        selected_path=candidates[-1]["path"],
        explicit_action_provenance="direct_user_action",
    )
    assert partial["category"] == "authorization_partial"
    approved = coordinator.authorize_artifacts(
        action="approve_all",
        explicit_action_provenance="direct_user_action",
    )
    assert approved["ok"] is True
    Path(candidates[0]["path"]).write_text("changed = True\n", encoding="utf-8")
    stale = coordinator.process_authorized_artifacts()
    assert stale["category"] == "selected_file_stale"
    assert stale["details"]["reauthorization_required"] is True


def test_authorization_add_one_and_decline_are_exact_local_actions(
    tmp_path: Path,
) -> None:
    transport = PublicBuilderTransport()
    coordinator, workspace = _coordinator(tmp_path, transport)
    _activate_and_prepare(coordinator)
    coordinator.record_ide_authority(allowed=True, explicit_user_action=True)
    candidates = _write_local_artifacts(workspace)
    coordinator.register_artifacts(candidates=candidates[:1])
    added = coordinator.authorize_artifacts(
        action="add_one_explicitly",
        selected_path=candidates[1]["path"],
        artifact_role="circuit_qasm",
        artifact_type="circuit_qasm",
        explicit_action_provenance="direct_user_action",
    )
    assert added["category"] == "authorization_partial"
    assert added["details"]["share_safe_projection"]["artifact_count"] == 2
    declined = coordinator.authorize_artifacts(
        action="decline",
        explicit_action_provenance="direct_user_action",
    )
    assert declined["category"] == "authorization_declined"
    assert declined["details"]["authorization_state"] == "declined"
    assert declined["details"]["paths_transmitted"] is False


@pytest.mark.parametrize(
    ("selected_roles", "expected_saved", "failed_run"),
    [
        (("source",), {"source_evidence", "python_manifestation"}, False),
        (("circuit_qasm",), {"circuit_manifestation"}, False),
        (
            ("source", "circuit_qasm"),
            {
                "source_evidence",
                "python_manifestation",
                "circuit_manifestation",
            },
            False,
        ),
        (
            ("source", "circuit_qasm", "results"),
            {
                "source_evidence",
                "python_manifestation",
                "circuit_manifestation",
                "result_manifestation",
            },
            True,
        ),
    ],
)
def test_coordinated_partial_and_failed_run_paths(
    tmp_path: Path,
    selected_roles: tuple[str, ...],
    expected_saved: set[str],
    failed_run: bool,
) -> None:
    transport = PublicBuilderTransport()
    coordinator, workspace = _coordinator(tmp_path, transport)
    _activate_and_prepare(coordinator)
    coordinator.record_ide_authority(allowed=True, explicit_user_action=True)
    candidates = _write_local_artifacts(workspace)
    selected = [candidate for candidate in candidates if candidate["role"] in selected_roles]
    if failed_run:
        result_candidate = next(
            candidate for candidate in selected if candidate["role"] == "results"
        )
        Path(result_candidate["path"]).write_text(
            json.dumps(
                {
                    "status": "failed",
                    "error_category": "bounded_local_run_failure",
                }
            ),
            encoding="utf-8",
        )
    coordinator.register_artifacts(candidates=selected)
    coordinator.authorize_artifacts(
        action="approve_all",
        explicit_action_provenance="direct_user_action",
    )
    processed = coordinator.process_authorized_artifacts()
    assert processed["ok"] is True, processed
    state = CurrentLoopStore.for_workspace(workspace).read()
    assert expected_saved <= set(state["saved_artifacts"])
    if failed_run:
        result = json.loads(
            Path(state["saved_artifacts"]["result_manifestation"]["local_path"]).read_text(
                encoding="utf-8"
            )
        )
        assert result["stage_availability"] == "not_run"
        assert result["raw_error_included"] is False
    review = coordinator.review_build()
    assert review["ok"] is True
    current = json.loads(
        Path(
            CurrentLoopStore.for_workspace(workspace).read()["saved_artifacts"][
                "current_build_context"
            ]["local_path"]
        ).read_text(encoding="utf-8")
    )
    if "results" not in selected_roles:
        assert current["stage_availability"]["run_results"] == "not_run"


def test_failed_run_replaces_unapproved_error_text_with_safe_category(
    tmp_path: Path,
) -> None:
    transport = PublicBuilderTransport()
    coordinator, workspace = _coordinator(tmp_path, transport)
    _activate_and_prepare(coordinator)
    coordinator.record_ide_authority(allowed=True, explicit_user_action=True)
    candidates = _write_local_artifacts(workspace)
    result_candidate = next(candidate for candidate in candidates if candidate["role"] == "results")
    Path(result_candidate["path"]).write_text(
        json.dumps(
            {
                "status": "failed",
                "error_category": "raw exception included a private runtime detail",
            }
        ),
        encoding="utf-8",
    )
    coordinator.register_artifacts(candidates=candidates)
    coordinator.authorize_artifacts(
        action="approve_all",
        explicit_action_provenance="direct_user_action",
    )
    processed = coordinator.process_authorized_artifacts()
    assert processed["ok"] is True
    manifestation = json.loads(
        (workspace / ".qcoder/current-loop/artifacts/result-manifestation.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifestation["safe_failure_category"] == "local_run_failed"
    assert "raw exception" not in json.dumps(transport.calls)


def test_consequence_projection_uses_explicit_fields_only() -> None:
    truth = {
        "generation_effect": "blocking",
        "alignment_status": "mismatch",
        "stage_availability": "not_run",
        "non_proofs": ["This does not prove correctness."],
        "unknown_protected_value": "do not guess",
    }
    projection = consequence_projection(truth)
    assert projection["readiness_calculated_locally"] is False
    assert projection["action_eligibility_calculated_locally"] is False
    assert projection["lineage_calculated_locally"] is False
    assert projection["recommendation_calculated_locally"] is False
    assert projection["additional_evidence_available_count"] >= 1
    assert projection["groups"]["Needs your decision"]
    assert projection["groups"]["New or changed"]
    assert projection["groups"]["Missing or later evidence"]
    assert projection["groups"]["Unproven"]


def test_consequence_projection_does_not_guess_readiness_or_action_meaning() -> None:
    projection = consequence_projection(
        {
            "aggregate_readiness_result": "blocked_pending_decisions",
            "applicable_actions": ["clarify_requirement"],
            "readiness": "future_unknown_value",
            "remaining_uncertainty": ["A supplied result does not prove correctness."],
        }
    )
    needs_decision = projection["groups"]["Needs your decision"]
    represented = projection["groups"]["Represented and no action needed"]
    assert any(item["source_field"] == "$.aggregate_readiness_result" for item in needs_decision)
    assert all(item["source_field"] != "$.readiness" for item in represented)
    assert projection["additional_evidence_available_count"] >= 2
    assert projection["groups"]["Unproven"]


def test_unchanged_continuation_never_materializes_or_adopts(
    tmp_path: Path,
) -> None:
    coordinator, _transport, workspace, _review = _through_current_build(tmp_path)
    checkpoint = coordinator.continue_unchanged(
        explicit_user_action=False,
        user_statement="",
    )
    assert checkpoint["checkpoint_kind"] == "governing_change_confirmation"
    result = coordinator.continue_unchanged(
        explicit_user_action=True,
        user_statement="Continue with the current Blueprint.",
    )
    assert result["ok"] is True
    assert result["details"]["governing_decisions_changed"] is False
    assert result["details"]["evolved_blueprint_created"] is False
    assert result["details"]["proposal_adopted"] is False
    seed = json.loads(
        (workspace / ".qcoder/current-loop/artifacts/next-loop-seed.json").read_text(
            encoding="utf-8"
        )
    )
    blueprint = json.loads(
        (workspace / ".qcoder/current-loop/artifacts/working-blueprint.json").read_text(
            encoding="utf-8"
        )
    )
    assert seed["continuation_outcome"] == "unchanged_continuation"
    assert seed["governing_blueprint"]["artifact_digest"] == blueprint["artifact_digest"]
    assert (
        "evolved_blueprint"
        not in CurrentLoopStore.for_workspace(workspace).read()["saved_artifacts"]
    )


def test_one_proposal_selected_bundle_confirmation_and_next_loop(
    tmp_path: Path,
) -> None:
    coordinator, transport, workspace, _review = _through_current_build(tmp_path)
    blueprint = json.loads(
        (workspace / ".qcoder/current-loop/artifacts/working-blueprint.json").read_text(
            encoding="utf-8"
        )
    )
    records = unpack_decision_record_set(blueprint["blueprint_decision_records"])
    selected = next(
        record for record in records if record["profile_decision_id"] == "generic_qiskit.shots"
    )
    proposal_result = coordinator.propose_change(
        decision_ref=selected["decision_ref"],
        selected_action="accept_and_add_to_blueprint",
        proposed_value=2048,
        control_treatment="keep_fixed",
        explicit_user_selection=True,
    )
    assert proposal_result["ok"] is True, proposal_result
    assert proposal_result["details"]["proposal_state"] == "unconfirmed"
    assert proposal_result["details"]["decision_update_count"] == 1
    assert proposal_result["details"]["derived_artifact_materialized"] is False
    assert proposal_result["details"]["confirmation_transport_attached"] is False
    assert transport.proposal is not None
    assert len(transport.proposal["decisions_unchanged"]) == 18
    protected_proposals = [
        call
        for call in transport.calls
        if call[0] == "create_implementation_blueprint"
        and call[1].get("resolution_phase") == "propose"
    ]
    assert len(protected_proposals) == 1
    portable_path = (
        workspace / ".qcoder/current-loop/artifacts/"
        "current-build-context.proposal-bearing.portable.json"
    )
    portable = json.loads(portable_path.read_text(encoding="utf-8"))
    assert portable["carry_forward_proposal"] == transport.proposal
    refused = coordinator.confirm_change(
        semantic_confirmation="Confirm some other proposal.",
        explicit_user_confirmation=True,
    )
    assert refused["checkpoint_kind"] == "governing_change_confirmation"
    proposal_ref = transport.proposal["proposal_ref"]
    confirmed = coordinator.confirm_change(
        semantic_confirmation=f"I confirm proposal {proposal_ref}.",
        explicit_user_confirmation=True,
    )
    assert confirmed["ok"] is True
    assert confirmed["details"]["selected_bundle_used"] is True
    assert confirmed["details"]["parent_reconstructed"] is False
    assert confirmed["details"]["working_blueprint_mutated"] is False
    evolved_path = workspace / ".qcoder/current-loop/artifacts/evolved-blueprint.json"
    evolved = json.loads(evolved_path.read_text(encoding="utf-8"))
    seed_path = workspace / ".qcoder/current-loop/artifacts/next-loop-seed.json"
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    assert seed["continuation_outcome"] == "confirmed_change"
    assert seed["governing_blueprint"]["artifact_digest"] == evolved["artifact_digest"]
    next_workspace = tmp_path / "next-workspace"
    next_workspace.mkdir()
    parent_paths = {
        item["artifact_role"]: (
            evolved_path
            if item["artifact_role"] == "governing_blueprint"
            else workspace / ".qcoder/current-loop/artifacts/output-evidence-contract.json"
        )
        for item in seed["required_parent_artifact_inventory"]
    }
    started = coordinator.start_next(
        next_workspace_root=next_workspace,
        generation_posture="exploratory_first_pass",
        seed_file=seed_path,
        parent_files=parent_paths,
        explicit_authority=True,
    )
    assert started["ok"] is True, started
    assert started["details"]["server_lookup_performed"] is False
    assert started["details"]["parent_traversal_performed"] is False
    assert started["details"]["canonical_request_expanded_locally"] is True
    assert (
        CurrentLoopStore.for_workspace(next_workspace).read()["parent_loop_ref"]
        == seed["source_loop_ref"]
    )


def test_current_build_review_fails_closed_without_portable(
    tmp_path: Path,
) -> None:
    coordinator, _transport, workspace, review = _through_current_build(
        tmp_path,
        transport=PublicBuilderTransport(drop_current_portable=True),
        expected_review_ok=False,
    )
    assert review["category"] == "protected_truth_insufficient"
    state = CurrentLoopStore.for_workspace(workspace).read()
    assert "pre_proposal_portable_current_build_context" not in state["saved_artifacts"]
    assert coordinator.status()["state_status"] == "blocked"


def test_proposal_fails_closed_without_proposal_bearing_portable(
    tmp_path: Path,
) -> None:
    transport = PublicBuilderTransport(drop_proposal_portable=True)
    coordinator, _transport, workspace, _review = _through_current_build(
        tmp_path,
        transport=transport,
    )
    blueprint = json.loads(
        (workspace / ".qcoder/current-loop/artifacts/working-blueprint.json").read_text(
            encoding="utf-8"
        )
    )
    selected = next(
        record
        for record in unpack_decision_record_set(blueprint["blueprint_decision_records"])
        if record["profile_decision_id"] == "generic_qiskit.shots"
    )
    result = coordinator.propose_change(
        decision_ref=selected["decision_ref"],
        selected_action="accept_and_add_to_blueprint",
        proposed_value=2048,
        control_treatment="keep_fixed",
        explicit_user_selection=True,
    )
    assert result["category"] == "protected_truth_insufficient"
    state = CurrentLoopStore.for_workspace(workspace).read()
    assert "carry_forward_proposal" not in state["saved_artifacts"]
    assert "proposal_bearing_portable_current_build_context" not in state["saved_artifacts"]


@pytest.mark.parametrize(
    "role,filename,content",
    [
        ("source", "only.py", "value = 1\n"),
        (
            "circuit_qasm",
            "only.qasm",
            "OPENQASM 2.0;\nqreg q[1];\n",
        ),
        ("results", "only.json", '{"counts":{"0":2,"1":2},"shots":4}'),
    ],
)
def test_standalone_review_needs_no_activation_and_preserves_missing_stages(
    tmp_path: Path,
    role: str,
    filename: str,
    content: str,
) -> None:
    coordinator, workspace = _coordinator(tmp_path)
    selected = workspace / filename
    selected.write_text(content, encoding="utf-8")
    destination = workspace / f"{filename}.evidence.json"
    result = coordinator.standalone_review(
        role=role,
        path=selected,
        destination=destination,
        related_circuit_ref=(_reference(900) if role == "results" else None),
    )
    assert result["ok"] is True
    assert result["details"]["loop_activated"] is False
    assert result["details"]["missing_stages_preserved"] is True
    assert destination.exists()
    assert not (workspace / ".qcoder").exists()


def test_reconstruction_and_unavailable_transport_fail_closed(
    tmp_path: Path,
) -> None:
    coordinator, _workspace = _coordinator(tmp_path)
    refused = coordinator.refuse_reconstruction("working_blueprint")
    assert refused["category"] == "reconstruction_attempt_refused"
    assert refused["details"]["artifact_reconstructed"] is False
    assert refused["details"]["schema_repair_attempted"] is False
    coordinator.activate(
        original_request="Use qCoder for a quick first pass.",
        generation_posture="exploratory_first_pass",
        explicit_authority=True,
    )
    unavailable = coordinator.prepare_generation(
        profile_id="generic_qiskit",
        proposed_interpretation={"summary": "proposal"},
        explicit_intent_approval=True,
    )
    assert unavailable["category"] == "protected_service_unavailable"
    assert unavailable["details"]["local_state_intact"] is True


@pytest.mark.parametrize(
    ("prompt", "profile", "posture"),
    [
        (
            "Use qCoder for a quick first pass on a Bell circuit.",
            "generic_qiskit",
            "exploratory_first_pass",
        ),
        (
            "Use qCoder with deliberate Blueprint control for Bell.",
            "generic_qiskit",
            "blueprint_guided",
        ),
        (
            "Fastest first attempt for Grover marked state 101.",
            "grover_search",
            "exploratory_first_pass",
        ),
        (
            "Use deliberate Blueprint control for ambiguous Grover state.",
            "grover_search",
            "blueprint_guided",
        ),
        (
            "Quick first pass for local QAOA depth two; no execution yet.",
            "qaoa",
            "exploratory_first_pass",
        ),
        (
            "Blueprint review for QAOA with ambiguous parameters.",
            "qaoa",
            "blueprint_guided",
        ),
    ],
)
def test_ordinary_prompt_paraphrase_matrix_reaches_complete_lineage(
    tmp_path: Path,
    prompt: str,
    profile: str,
    posture: str,
) -> None:
    transport = PublicBuilderTransport()
    coordinator, _workspace = _coordinator(tmp_path, transport)
    assert infer_requested_posture(prompt) == posture
    activated = coordinator.activate(
        original_request=prompt,
        generation_posture=posture,
        explicit_authority=True,
    )
    assert activated["ok"] is True
    result = coordinator.prepare_generation(
        profile_id=profile,
        proposed_interpretation={"normalized_goal": prompt},
        decision_dispositions=_user_dispositions(profile),
        reviewed_profile_answers={"problem_size_meaning": "Explicitly bounded."},
        explicit_intent_approval=True,
        confirmation_assertion="Approved for this generation.",
    )
    assert result["details"]["decision_inventory"]["decision_count"] == (PROFILE_COUNTS[profile])
    assert result["details"]["ide_write_or_run_authorized"] is False


def test_named_clients_share_one_contract_without_client_product_truth() -> None:
    snapshot = coordinator_contract_snapshot()
    assert snapshot["connected_clients"] == [
        "cursor",
        "claude_code",
        "codex",
    ]
    assert snapshot["customer_serialization_required"] is False
    assert snapshot["assistant_reconstruction_allowed"] is False
    assert snapshot["protected_operation_added"] is False
    assert "local_run_failed" in snapshot["safe_local_failure_categories"]


def test_performance_counts_public_coordinator_operations_not_state_writes(
    tmp_path: Path,
) -> None:
    coordinator, _workspace = _coordinator(tmp_path, PublicBuilderTransport())
    activated = coordinator.activate(
        original_request="Use qCoder for a quick first pass.",
        generation_posture="exploratory_first_pass",
        explicit_authority=True,
    )
    assert activated["ok"] is True
    assert coordinator.private_performance_snapshot()["coordinator_calls"] == 1
    status = coordinator.status()
    assert status["ok"] is True
    assert coordinator.private_performance_snapshot()["coordinator_calls"] == 2


def test_abandon_without_authority_does_not_advance_or_complete_loop(
    tmp_path: Path,
) -> None:
    coordinator, workspace = _coordinator(tmp_path, PublicBuilderTransport())
    activated = coordinator.activate(
        original_request="Use qCoder with deliberate Blueprint control.",
        generation_posture="blueprint_guided",
        explicit_authority=True,
    )
    assert activated["phase"] == "intent_review"
    refused = coordinator.abandon(explicit_authority=False)
    assert refused["checkpoint_kind"] == "activation"
    assert refused["phase"] == "intent_review"
    state = CurrentLoopStore.for_workspace(workspace).read()
    assert state["completion_state"] == "in_progress"


def test_start_next_cannot_advance_before_current_loop_is_ready(
    tmp_path: Path,
) -> None:
    coordinator, _workspace = _coordinator(tmp_path, PublicBuilderTransport())
    activated = coordinator.activate(
        original_request="Use qCoder for a quick first pass.",
        generation_posture="exploratory_first_pass",
        explicit_authority=True,
    )
    assert activated["phase"] == "intent_review"
    result = coordinator.start_next(
        next_workspace_root=tmp_path / "premature-next",
        generation_posture="exploratory_first_pass",
        seed_file=tmp_path / "missing-seed.json",
        parent_files={},
        explicit_authority=False,
    )
    assert result["ok"] is False
    assert coordinator.status()["phase"] == "intent_review"
    assert not (tmp_path / "premature-next").exists()


def test_recovery_checkpoint_preserves_separate_ide_authority(
    tmp_path: Path,
) -> None:
    coordinator, _workspace = _coordinator(tmp_path, PublicBuilderTransport())
    _activate_and_prepare(coordinator)
    denied = coordinator.record_ide_authority(
        allowed=False,
        explicit_user_action=True,
    )
    assert denied["category"] == "ide_write_or_run_denied"
    assert denied["checkpoint_kind"] == "ide_write_or_run"


def test_current_loop_cli_activation_status_and_standalone_smoke(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "cli-workspace"
    workspace.mkdir()
    status_code = cli_main(["current-loop", "--workspace", str(workspace), "status"])
    status = json.loads(capsys.readouterr().out)
    assert status_code == 2
    assert status["category"] == "loop_not_activated"

    activate_code = cli_main(
        [
            "current-loop",
            "--workspace",
            str(workspace),
            "activate",
            "--request",
            "Use qCoder for a quick first pass.",
            "--posture",
            "exploratory_first_pass",
            "--approve",
        ]
    )
    activated = json.loads(capsys.readouterr().out)
    assert activate_code == 0
    assert activated["phase"] == "intent_review"
    assert activated["details"]["artifact_review_authorized"] is False

    status_code = cli_main(["current-loop", "--workspace", str(workspace), "status"])
    status = json.loads(capsys.readouterr().out)
    assert status_code == 0
    assert status["phase"] == "intent_review"

    standalone_workspace = tmp_path / "standalone"
    standalone_workspace.mkdir()
    source = standalone_workspace / "selected.py"
    destination = standalone_workspace / "selected.source-evidence.json"
    source.write_text("value = 1\n", encoding="utf-8")
    standalone_code = cli_main(
        [
            "current-loop",
            "--workspace",
            str(standalone_workspace),
            "standalone-review",
            "--role",
            "source",
            "--path",
            str(source),
            "--destination",
            str(destination),
        ]
    )
    standalone = json.loads(capsys.readouterr().out)
    assert standalone_code == 0
    assert standalone["details"]["loop_activated"] is False
    assert destination.exists()
    assert not (standalone_workspace / ".qcoder").exists()


def test_current_loop_cli_parses_semantic_scalars_without_structured_json() -> None:
    assert _parse_current_loop_scalar("2048") == 2048
    assert _parse_current_loop_scalar("2.5") == 2.5
    assert _parse_current_loop_scalar("true") is True
    assert _parse_current_loop_scalar("simple_flat") == "simple_flat"
    with pytest.raises(ValueError, match="current_loop_scalar_value_required"):
        _parse_current_loop_scalar('{"selected_value": 2048}')


def _assert_actionable_checkpoint(result: Mapping[str, Any]) -> None:
    assert result["state_status"] == "checkpoint_required"
    assert result["supported_next_action"]
    assert isinstance(result["next_invocation"], dict)
    assert isinstance(result["required_authority_input"], dict)
    assert isinstance(result["awaiting_confirmation_fields"], list)
    assert result["confirmation_transmission_state"] in {
        "not_supplied",
        "supplied",
        "clarification_required",
        "confirmed",
        "declined",
    }
    assert result["identical_repeat_prohibited"] is True
    assert result["next_invocation"]["token_contents_embedded"] is False
    assert result["next_invocation"]["private_workspace_path_embedded"] is False
    assert result["next_invocation"]["canonical_artifact_reconstruction_required"] is False


def test_every_checkpoint_result_is_deterministically_actionable(tmp_path: Path) -> None:
    coordinator = CurrentLoopCoordinator(workspace_root=tmp_path)
    for checkpoint_kind in CHECKPOINT_KINDS:
        phase = "continuation_choice" if checkpoint_kind == "none" else "activated"
        result = coordinator._result_without_state(
            operation="contract_test",
            ok=True,
            phase=phase,
            state_status="checkpoint_required",
            checkpoint_kind=checkpoint_kind,
            summary="Synthetic checkpoint contract test.",
        )
        _assert_actionable_checkpoint(result)
        assert result["schema_id"] == "qcoder.current_loop.coordinator_result.v2"
        assert result["schema_version"] == 2


def test_current_loop_cli_intent_review_confirmation_sequence_is_actionable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "cli-intent-sequence"
    workspace.mkdir()
    transport = PublicBuilderTransport()
    monkeypatch.setattr(
        current_loop_coordinator_module,
        "ContextBridgeTransport",
        lambda **_values: transport,
    )
    activate = [
        "current-loop",
        "--workspace",
        str(workspace),
        "activate",
        "--request",
        "Use qCoder for a quick first pass on a synthetic Bell circuit.",
        "--posture",
        "exploratory_first_pass",
        "--approve",
    ]
    assert cli_main(activate) == 0
    activated = json.loads(capsys.readouterr().out)
    _assert_actionable_checkpoint(activated)

    prepare = [
        "current-loop",
        "--workspace",
        str(workspace),
        "prepare-generation",
        "--base-url",
        "https://example.invalid",
        "--token-file",
        str(tmp_path / "token.txt"),
        "--profile",
        "generic_qiskit",
        "--interpretation-summary",
        "Build one bounded synthetic Bell circuit.",
        "--profile-answer",
        "framework_requirement=Qiskit-compatible Python.",
    ]
    assert cli_main(prepare) == 0
    proposed = json.loads(capsys.readouterr().out)
    assert proposed["category"] == "intent_confirmation_required"
    assert proposed["confirmation_transmission_state"] == "not_supplied"
    assert "--confirm-intent" in proposed["next_invocation"]["required_flags"]
    assert proposed["details"]["protected_call_made"] is True
    _assert_actionable_checkpoint(proposed)
    assert len(transport.calls) == 1

    assert cli_main(prepare) == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["category"] == "confirmation_not_transmitted"
    assert repeated["details"]["protected_call_made"] is False
    assert repeated["details"]["identical_pending_review_reused"] is True
    assert "--confirm-intent" in repeated["next_invocation"]["required_flags"]
    _assert_actionable_checkpoint(repeated)
    assert len(transport.calls) == 1

    assert cli_main([*prepare, "--confirm-intent"]) == 0
    confirmed = json.loads(capsys.readouterr().out)
    assert confirmed["phase"] == "generation_ready"
    assert confirmed["details"]["intent_confirmed"] is True
    assert confirmed["details"]["confirmation_transmission_state"] == "confirmed"
    _assert_actionable_checkpoint(confirmed)
    assert [name for name, _arguments in transport.calls] == [
        "create_algorithm_intent_card",
        "create_algorithm_intent_card",
        "create_implementation_blueprint",
        "create_generation_context_pack",
    ]
    confirmed_intent_arguments = transport.calls[1][1]
    assert confirmed_intent_arguments["requested_confirmation_state"] == "confirmed"
    assert confirmed_intent_arguments["confirmation_assertion"] == {"user_reviewed": True}


def test_current_loop_cli_distinguishes_transmitted_clarification(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ClarifyingTransport(PublicBuilderTransport):
        def _intent(self, supplied: Mapping[str, Any]) -> dict[str, Any]:
            result = super()._intent(supplied)
            if supplied.get("requested_confirmation_state") != "confirmed":
                return result
            card = deepcopy(result["algorithm_intent_card"])
            card.pop("artifact_digest")
            card.update(
                {
                    "confirmation_state": "needs_clarification",
                    "unresolved_questions": ["framework_requirement"],
                }
            )
            return {"ok": True, "algorithm_intent_card": with_artifact_digest(card)}

    workspace = tmp_path / "cli-clarification"
    workspace.mkdir()
    transport = ClarifyingTransport()
    monkeypatch.setattr(
        current_loop_coordinator_module,
        "ContextBridgeTransport",
        lambda **_values: transport,
    )
    assert (
        cli_main(
            [
                "current-loop",
                "--workspace",
                str(workspace),
                "activate",
                "--request",
                "Use qCoder for a quick first pass.",
                "--posture",
                "exploratory_first_pass",
                "--approve",
            ]
        )
        == 0
    )
    capsys.readouterr()
    prepare = [
        "current-loop",
        "--workspace",
        str(workspace),
        "prepare-generation",
        "--base-url",
        "https://example.invalid",
        "--token-file",
        str(tmp_path / "token.txt"),
        "--profile",
        "generic_qiskit",
        "--interpretation-summary",
        "Build one bounded example.",
    ]
    assert cli_main(prepare) == 0
    capsys.readouterr()
    assert cli_main([*prepare, "--confirm-intent"]) == 0
    clarification = json.loads(capsys.readouterr().out)
    assert clarification["category"] == "intent_clarification_required"
    assert clarification["category"] != "confirmation_not_transmitted"
    assert clarification["confirmation_transmission_state"] == "supplied"
    assert clarification["details"]["confirmation_transmission_state"] == "supplied"
    assert clarification["awaiting_confirmation_fields"] == ["framework_requirement"]
    assert clarification["details"]["protected_call_made"] is True
    _assert_actionable_checkpoint(clarification)
    calls_after_clarification = len(transport.calls)
    assert cli_main([*prepare, "--confirm-intent"]) == 0
    repeated = json.loads(capsys.readouterr().out)
    assert repeated["category"] == "intent_clarification_unchanged"
    assert repeated["confirmation_transmission_state"] == "supplied"
    assert repeated["awaiting_confirmation_fields"] == ["framework_requirement"]
    assert repeated["details"]["protected_call_made"] is False
    assert len(transport.calls) == calls_after_clarification


@pytest.mark.parametrize(
    ("subcommand", "flags"),
    [
        ("activate", ("--approve",)),
        ("prepare-generation", ("--confirm-intent", "--confirmation")),
        ("record-ide-authority", ("--allow", "--explicit")),
        ("register-artifacts", ("--allow-external",)),
        ("authorize-artifacts", ("--action",)),
        ("continue-unchanged", ("--approve", "--decline-proposal")),
        ("propose-change", ("--approve-selection",)),
        ("confirm-change", ("--approve",)),
        ("start-next", ("--approve",)),
        ("abandon", ("--approve",)),
    ],
)
def test_current_loop_authority_flags_document_fail_closed_human_authority(
    subcommand: str,
    flags: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli_main(["current-loop", subcommand, "--help"])
    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    for flag in flags:
        assert flag in help_text
    normalized_help = " ".join(help_text.lower().split())
    assert "omission is not" in normalized_help
    assert "never infer or manufacture" in normalized_help


def test_public_transport_confirmation_semantics_match_bounded_live_contract() -> None:
    transport = PublicBuilderTransport()
    response = transport.call(
        "create_algorithm_intent_card",
        {
            "original_user_intent": "Build one synthetic reviewed example.",
            "profile_id": "generic_qiskit",
            "proposed_interpretation": {"normalized_goal": "Build one bounded example."},
            "decision_dispositions": [],
            "requested_confirmation_state": "confirmed",
            "confirmation_assertion": {"user_reviewed": True},
            "current_lineage_reference": _reference(500),
        },
    )
    assert response["algorithm_intent_card"]["confirmation_state"] == "confirmed"
    live_gate4_contract = {
        "response_sha256": ("12a05346542f9decbe70281c2bcd726841b0bdb36e0d1f33c6e615feb6e78fd0"),
        "requested_confirmation_state": "confirmed",
        "decision_dispositions_count": 0,
        "confirmation_state": "confirmed",
    }
    assert live_gate4_contract["decision_dispositions_count"] == 0
    assert (
        live_gate4_contract["confirmation_state"]
        == (response["algorithm_intent_card"]["confirmation_state"])
    )
