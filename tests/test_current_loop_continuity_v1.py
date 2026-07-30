from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from qcoder.algorithm_blueprint import with_artifact_digest
from qcoder.blueprint_decisions import (
    ACTION_IDS,
    build_decision_records,
    catalog_entries,
    pack_decision_record_set,
)
from qcoder.context_bridge_mcp import (
    EXPECTED_TOOLS,
    LOCAL_SELECTED_NEXT_LOOP_SEED_FIELD,
    PROMPT_CONTEXT_MODES,
    handle_jsonrpc_message,
    tool_descriptors,
)
from qcoder.current_loop import (
    CURRENT_LOOP_STATE_SCHEMA_ID,
    LEGACY_CURRENT_LOOP_STATE_SCHEMA_ID,
    LOOP_INSTANCE_RECORD_MAX_BYTES,
    LOOP_INSTANCE_RECORD_SCHEMA_ID,
    NEXT_LOOP_SEED_SCHEMA_ID,
    SELECTED_ARTIFACT_AUTHORIZATION_SCHEMA_ID,
    UNCHANGED_CONTINUATION_SCHEMA_ID,
    CurrentLoopConflict,
    CurrentLoopError,
    CurrentLoopStore,
    activate_current_loop,
    activate_next_loop_from_seed,
    build_changed_next_loop_seed,
    build_loop_instance_record,
    build_next_loop_seed,
    build_unchanged_continuation,
    canonical_json,
    canonical_operation_request_sha256,
    check_current_loop_freshness,
    current_loop_contract_snapshot,
    decision_inventory_binding,
    expand_next_loop_seed,
    loop_instance_record_error,
    mark_local_dependency_stale,
    new_loop_ref,
    next_loop_seed_error,
    propose_selected_artifact_authorization,
    refresh_loop_instance_record,
    save_exact_canonical_artifact,
    selected_artifact_authorization_error,
    set_artifact_authorization,
    share_safe_artifact_authorization_projection,
    stale_recovery_result,
    unchanged_continuation_error,
    update_selected_artifact_authorization,
)


LINEAGE = "session-artifact-0123456789abcdef"
PROFILE_COUNTS = {
    "generic_qiskit": 19,
    "grover_search": 12,
    "qaoa": 17,
}


def _ref(character: str) -> str:
    return f"session-artifact-{character * 32}"


def _artifact(artifact_type: str, character: str, **values: object) -> dict[str, object]:
    return with_artifact_digest(
        {
            "schema_id": f"qcoder.{artifact_type}.v1",
            "schema_version": 1,
            "artifact_type": artifact_type,
            "artifact_ref": _ref(character),
            **values,
        }
    )


def _blueprint(
    profile: str = "generic_qiskit",
    posture: str = "blueprint_guided",
    character: str = "b",
) -> dict[str, object]:
    records = build_decision_records(
        profile_id=profile,
        current_lineage_reference=LINEAGE,
        parent_artifact_references=[{"artifact_ref": _ref("a")}],
    )
    return with_artifact_digest(
        {
            "schema_id": "qcoder.implementation_blueprint.v1",
            "schema_version": 1,
            "artifact_type": "implementation_blueprint",
            "artifact_ref": _ref(character),
            "selected_profile": profile,
            "confirmation_state": "confirmed",
            "generation_posture": posture,
            "decision_loop": {
                "gate": "readiness_resolution_v1",
                "catalog_version": 1,
            },
            "blueprint_decision_records": pack_decision_record_set(
                profile_id=profile, decision_records=records
            ),
            "persistent": False,
        }
    )


def _evolved(working_blueprint: dict[str, object], character: str = "e") -> dict[str, object]:
    from qcoder.blueprint_decisions import unpack_decision_record_set

    return with_artifact_digest(
        {
            "schema_id": "qcoder.evolved_blueprint.v1",
            "schema_version": 1,
            "artifact_type": "evolved_blueprint",
            "derived_artifact_reference": (f"derived-{character * 24}"),
            "decision_records": unpack_decision_record_set(
                working_blueprint["blueprint_decision_records"]
            ),
            "changed_decisions": [
                working_blueprint["blueprint_decision_records"]["records"][0]["decision_ref"]
            ],
            "provenance_entries": [
                {
                    "role": "user_confirmed_carry_forward",
                    "proposal_ref": f"proposal-{'a' * 24}",
                    "selected_action": "accept_and_add_to_blueprint",
                }
            ],
            "parent_mutated": False,
            "hidden_lookup_performed": False,
            "retention": "process_and_discard",
        }
    )


def _activate(
    tmp_path: Path, posture: str = "blueprint_guided"
) -> tuple[CurrentLoopStore, dict[str, object]]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = activate_current_loop(
        workspace_root=workspace,
        generation_posture=posture,
        explicit_authority=True,
    )
    return CurrentLoopStore.for_workspace(workspace), result


def _write_artifact(path: Path, artifact: dict[str, object]) -> None:
    path.write_text(
        json.dumps(artifact, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_contract_snapshot_is_local_bounded_and_does_not_add_inventory() -> None:
    snapshot = current_loop_contract_snapshot()
    assert snapshot["schemas"] == {
        "loop_instance_record": LOOP_INSTANCE_RECORD_SCHEMA_ID,
        "next_loop_seed": NEXT_LOOP_SEED_SCHEMA_ID,
        "unchanged_continuation": UNCHANGED_CONTINUATION_SCHEMA_ID,
        "selected_artifact_authorization": (SELECTED_ARTIFACT_AUTHORIZATION_SCHEMA_ID),
        "local_state": CURRENT_LOOP_STATE_SCHEMA_ID,
        "previous_local_state": "qcoder.current_loop.local_state.v6",
        "older_local_state": "qcoder.current_loop.local_state.v2",
        "legacy_local_state": LEGACY_CURRENT_LOOP_STATE_SCHEMA_ID,
        "current_loop_contract": "qcoder.current_loop.contract.v2",
    }
    assert snapshot["maximum_parent_loop_references"] == 1
    assert snapshot["server_lookup"] is False
    assert snapshot["graph_traversal"] is False
    assert snapshot["historical_index"] is False
    assert len(EXPECTED_TOOLS) == 12
    assert len(PROMPT_CONTEXT_MODES) == 5
    assert len(PROFILE_COUNTS) == 3
    assert len(ACTION_IDS) == 7
    assert len(tool_descriptors()) == 12


@pytest.mark.parametrize("profile,expected_count", PROFILE_COUNTS.items())
@pytest.mark.parametrize("posture", ("blueprint_guided", "exploratory_first_pass"))
def test_both_postures_use_one_catalog_complete_working_blueprint_class(
    profile: str, expected_count: int, posture: str
) -> None:
    blueprint = _blueprint(profile, posture)
    binding = decision_inventory_binding(blueprint)
    assert blueprint["artifact_type"] == "implementation_blueprint"
    assert binding["profile_id"] == profile
    assert binding["decision_count"] == expected_count
    assert binding["decision_count"] == len(catalog_entries(profile))


def test_incomplete_inventory_fails_without_reconstruction() -> None:
    blueprint = _blueprint()
    damaged = deepcopy(blueprint)
    from qcoder.blueprint_decisions import unpack_decision_record_set

    records = unpack_decision_record_set(damaged["blueprint_decision_records"])
    damaged["decision_records"] = records[:-1]
    damaged.pop("blueprint_decision_records")
    damaged = with_artifact_digest(damaged)
    with pytest.raises(CurrentLoopError, match="blueprint_decision_inventory_incomplete"):
        decision_inventory_binding(damaged)


def test_loop_refs_are_random_non_content_derived_and_thin() -> None:
    blueprint = _blueprint()
    first = build_loop_instance_record(
        loop_ref=new_loop_ref(),
        generation_posture="blueprint_guided",
        governing_blueprint=blueprint,
    )
    second = build_loop_instance_record(
        loop_ref=new_loop_ref(),
        generation_posture="blueprint_guided",
        governing_blueprint=blueprint,
    )
    assert first["loop_ref"] != second["loop_ref"]
    assert first["artifact_digest"] != second["artifact_digest"]
    assert len(canonical_json(first).encode()) < LOOP_INSTANCE_RECORD_MAX_BYTES
    serialized = canonical_json(first).lower()
    assert "raw_source" not in serialized
    assert "local_path" not in serialized
    assert "/home/" not in serialized
    assert first["server_lookup"] is False
    assert first["graph_traversal"] is False


def test_zero_or_one_parent_and_branching_is_reference_only() -> None:
    parent = new_loop_ref()
    child_one = build_loop_instance_record(
        loop_ref=new_loop_ref(),
        parent_loop_ref=parent,
        generation_posture="blueprint_guided",
    )
    child_two = build_loop_instance_record(
        loop_ref=new_loop_ref(),
        parent_loop_ref=parent,
        generation_posture="exploratory_first_pass",
    )
    assert child_one["parent_loop_ref"] == child_two["parent_loop_ref"]
    assert child_one["loop_ref"] != child_two["loop_ref"]
    assert child_one["graph_traversal"] is False
    assert "children" not in child_one
    with pytest.raises(CurrentLoopError, match="parent_loop_ref_invalid"):
        build_loop_instance_record(
            loop_ref=new_loop_ref(),
            parent_loop_ref="parent-a,parent-b",
            generation_posture="blueprint_guided",
        )


def test_activation_is_explicit_local_inspectable_and_private(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_path = workspace / ".qcoder" / "current-loop" / "state.json"
    assert not state_path.exists()
    with pytest.raises(CurrentLoopError, match="current_loop_activation_authority_required"):
        activate_current_loop(
            workspace_root=workspace,
            generation_posture="blueprint_guided",
            explicit_authority=False,
        )
    result = activate_current_loop(
        workspace_root=workspace,
        generation_posture="blueprint_guided",
        explicit_authority=True,
    )
    assert state_path.exists()
    assert Path(result["loop_instance_record_path"]).exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["directory_scan_performed"] is False
    assert state["watcher_active"] is False
    assert state["upload_performed"] is False
    assert state["automatic_gitignore_edit"] is False
    assert not (workspace / ".gitignore").exists()
    if os.name != "nt":
        assert state_path.parent.stat().st_mode & 0o777 == 0o700
        assert state_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(CurrentLoopConflict, match="current_loop_already_active"):
        activate_current_loop(
            workspace_root=workspace,
            generation_posture="blueprint_guided",
            explicit_authority=True,
        )


def test_external_state_requires_explicit_selection(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "explicit" / "state.json"
    store = CurrentLoopStore(
        state_path=external,
        workspace_root=workspace,
        explicit_external=True,
    )
    assert store.explicit_external is True
    with pytest.raises(
        CurrentLoopError,
        match="current_loop_external_state_requires_explicit_selection",
    ):
        CurrentLoopStore(
            state_path=external,
            workspace_root=workspace,
            explicit_external=False,
        )


def test_artifact_authorization_full_user_action_lifecycle(tmp_path: Path) -> None:
    source = tmp_path / "bell.py"
    qasm = tmp_path / "bell.qasm"
    result = tmp_path / "counts.json"
    source.write_text("print('selected')\n", encoding="utf-8")
    qasm.write_text("OPENQASM 2.0;\n", encoding="utf-8")
    result.write_text('{"00": 10, "11": 10}\n', encoding="utf-8")
    loop_ref = new_loop_ref()
    proposed = propose_selected_artifact_authorization(
        loop_ref=loop_ref,
        proposed_artifacts=[
            {"artifact_role": "source", "local_path": source},
            {"artifact_role": "circuit_qasm", "local_path": qasm},
        ],
    )
    assert proposed["state"] == "proposed"
    assert all(item["content_digest"] is None for item in proposed["items"])
    removed = update_selected_artifact_authorization(
        proposed,
        action="remove_one",
        selected_path=qasm,
        explicit_action_provenance="user removed the QASM",
    )
    added = update_selected_artifact_authorization(
        removed,
        action="add_one_explicitly",
        selected_path=result,
        artifact_role="results",
        explicit_action_provenance="user explicitly added results",
    )
    approved = update_selected_artifact_authorization(
        added,
        action="approve_all",
        explicit_action_provenance="user approved the exact displayed set",
    )
    assert approved["state"] == "approved"
    assert all(item["content_digest"] for item in approved["items"])
    assert selected_artifact_authorization_error(approved) is None
    projection = share_safe_artifact_authorization_projection(approved)
    assert projection["local_paths_included"] is False
    assert str(tmp_path) not in canonical_json(projection)
    declined = update_selected_artifact_authorization(
        proposed,
        action="decline",
        explicit_action_provenance="user declined review",
    )
    assert declined["state"] == "declined"


def test_exact_artifact_save_is_atomic_verified_and_non_overwriting(
    tmp_path: Path,
) -> None:
    store, activated = _activate(tmp_path)
    artifact = _artifact("request_baseline", "a", request="bounded")
    path = store.workspace_root / "bell.request-baseline.json"
    saved = save_exact_canonical_artifact(
        store=store,
        role="request_baseline",
        artifact=artifact,
        destination=path,
        expected_revision=activated["state"]["state_revision"],
    )
    assert saved["wrapper_added"] is False
    assert json.loads(path.read_text(encoding="utf-8")) == artifact
    changed = _artifact("request_baseline", "a", request="different")
    with pytest.raises(CurrentLoopError, match="canonical_artifact_overwrite_conflict"):
        save_exact_canonical_artifact(
            store=store,
            role="request_baseline",
            artifact=changed,
            destination=path,
            expected_revision=saved["state_revision"],
        )
    with pytest.raises(CurrentLoopError, match="canonical_artifact_path_escape"):
        save_exact_canonical_artifact(
            store=store,
            role="request_baseline",
            artifact=artifact,
            destination=tmp_path / "escaped.json",
            expected_revision=saved["state_revision"],
        )


def test_state_deletion_leaves_customer_and_saved_artifacts(tmp_path: Path) -> None:
    store, activated = _activate(tmp_path)
    source = store.workspace_root / "bell.py"
    source.write_text("print('customer file')\n", encoding="utf-8")
    artifact = _artifact("request_baseline", "a", request="bounded")
    saved_path = store.workspace_root / "bell.request-baseline.json"
    saved = save_exact_canonical_artifact(
        store=store,
        role="request_baseline",
        artifact=artifact,
        destination=saved_path,
        expected_revision=activated["state"]["state_revision"],
    )
    assert saved["saved"] is True
    result = store.delete_state(explicit_authority=True)
    assert result["protected_deletion_required"] is False
    assert source.exists()
    assert saved_path.exists()
    assert not store.state_path.exists()


def test_freshness_detects_changed_source_and_blocks_dependents(
    tmp_path: Path,
) -> None:
    store, activated = _activate(tmp_path)
    source = store.workspace_root / "bell.py"
    source.write_text("first\n", encoding="utf-8")
    proposed = propose_selected_artifact_authorization(
        loop_ref=activated["state"]["loop_ref"],
        proposed_artifacts=[{"artifact_role": "source", "local_path": source}],
    )
    approved = update_selected_artifact_authorization(
        proposed,
        action="approve_all",
        explicit_action_provenance="explicit source approval",
    )
    state = set_artifact_authorization(
        store=store,
        authorization=approved,
        expected_revision=activated["state"]["state_revision"],
    )
    assert (
        check_current_loop_freshness(store=store, expected_revision=state["state_revision"])[
            "fresh"
        ]
        is True
    )
    source.write_text("second\n", encoding="utf-8")
    stale = check_current_loop_freshness(store=store, expected_revision=state["state_revision"])
    assert stale["fresh"] is False
    assert stale["protected_request_allowed"] is False
    assert stale["events"][0]["category"] == "source_changed"
    assert stale["events"][0]["assistant_reconstruction_allowed"] is False


def test_missing_selected_file_and_missing_manifestation_are_bounded(
    tmp_path: Path,
) -> None:
    store, activated = _activate(tmp_path)
    qasm = store.workspace_root / "bell.qasm"
    qasm.write_text("OPENQASM 2.0;\n", encoding="utf-8")
    proposed = propose_selected_artifact_authorization(
        loop_ref=activated["state"]["loop_ref"],
        proposed_artifacts=[{"artifact_role": "circuit_qasm", "local_path": qasm}],
    )
    approved = update_selected_artifact_authorization(
        proposed,
        action="approve_all",
        explicit_action_provenance="explicit circuit approval",
    )
    state = set_artifact_authorization(
        store=store,
        authorization=approved,
        expected_revision=activated["state"]["state_revision"],
    )
    qasm.unlink()
    stale = check_current_loop_freshness(store=store, expected_revision=state["state_revision"])
    assert stale["events"][0]["category"] == "selected_file_missing"
    missing = stale_recovery_result(
        "manifestation_missing", affected_artifacts=["circuit_manifestation"]
    )
    assert missing["reextraction_required"] is True
    assert missing["renewed_authorization_required"] is False


def test_modified_canonical_blueprint_marks_lineage_stale(tmp_path: Path) -> None:
    store, activated = _activate(tmp_path)
    blueprint = _blueprint()
    path = store.workspace_root / "bell.working-blueprint.json"
    saved = save_exact_canonical_artifact(
        store=store,
        role="working_blueprint",
        artifact=blueprint,
        destination=path,
        expected_revision=activated["state"]["state_revision"],
    )
    modified = deepcopy(blueprint)
    modified["confirmation_state"] = "proposed"
    modified = with_artifact_digest(modified)
    _write_artifact(path, modified)
    result = check_current_loop_freshness(store=store, expected_revision=saved["state_revision"])
    assert result["events"][0]["category"] == "governing_blueprint_changed"


def test_state_cas_lock_corruption_wrong_schema_and_interrupted_temp(
    tmp_path: Path,
) -> None:
    store, activated = _activate(tmp_path)
    state = store.read()
    first = store.replace(state, expected_revision=state["state_revision"])
    with pytest.raises(CurrentLoopConflict, match="concurrent_state_update"):
        store.replace(state, expected_revision=state["state_revision"])
    interrupted = store.state_path.with_name(".state.json.interrupted.tmp")
    interrupted.write_text("{", encoding="utf-8")
    assert store.read()["state_revision"] == first["state_revision"]
    store.state_path.write_text("{", encoding="utf-8")
    with pytest.raises(CurrentLoopError, match="current_loop_state_corrupt"):
        store.read()
    wrong = deepcopy(activated["state"])
    wrong["schema_id"] = "qcoder.future.current_loop.local_state.v2"
    wrong["state_digest"] = "0" * 64
    store.state_path.write_text(json.dumps(wrong), encoding="utf-8")
    with pytest.raises(CurrentLoopError, match="current_loop_state_version_invalid"):
        store.read()


def test_lock_contention_times_out_without_auto_merge(tmp_path: Path) -> None:
    store, _activated = _activate(tmp_path)
    contender = CurrentLoopStore.for_workspace(store.workspace_root, lock_timeout_seconds=0.05)
    with store.lock():
        with pytest.raises(CurrentLoopConflict, match="current_loop_lock_timeout"):
            with contender.lock():
                pass


def test_symlink_state_and_selected_files_fail_closed(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("native Windows symlink creation requires host policy")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (workspace / ".qcoder").symlink_to(target, target_is_directory=True)
    with pytest.raises(CurrentLoopError, match="current_loop_state_symlink_rejected"):
        activate_current_loop(
            workspace_root=workspace,
            generation_posture="blueprint_guided",
            explicit_authority=True,
        )


def test_unchanged_continuation_requires_explicit_act_and_no_evolved_blueprint() -> None:
    blueprint = _blueprint()
    loop = build_loop_instance_record(
        loop_ref=new_loop_ref(),
        generation_posture="blueprint_guided",
        governing_blueprint=blueprint,
    )
    contract = _artifact(
        "output_evidence_contract",
        "c",
        parent_artifact_digest=blueprint["artifact_digest"],
    )
    with pytest.raises(CurrentLoopError, match="unchanged_continuation_explicit_action_required"):
        build_unchanged_continuation(
            loop_instance_record=loop,
            governing_working_blueprint=blueprint,
            retained_evidence={},
            explicit_user_action={"confirmed": False},
            required_parent_artifacts={
                "governing_blueprint": (
                    "implementation_blueprint",
                    blueprint,
                ),
                "output_evidence_contract": contract,
            },
            next_permitted_operation_family="create_generation_context_pack",
        )
    result = build_unchanged_continuation(
        loop_instance_record=loop,
        governing_working_blueprint=blueprint,
        retained_evidence={},
        explicit_user_action={
            "confirmed": True,
            "provenance": "direct_user_action",
            "statement": "Continue with the current Blueprint.",
        },
        required_parent_artifacts={
            "governing_blueprint": (
                "implementation_blueprint",
                blueprint,
            ),
            "output_evidence_contract": contract,
        },
        next_permitted_operation_family="create_generation_context_pack",
    )
    continuation = result["unchanged_continuation"]
    seed = result["next_loop_seed"]
    assert unchanged_continuation_error(continuation) is None
    assert next_loop_seed_error(seed) is None
    assert continuation["governing_decisions_changed"] is False
    assert continuation["evolved_blueprint_created"] is False
    assert continuation["proposal_adopted"] is False
    assert seed["continuation_outcome"] == "unchanged_continuation"
    assert seed["governing_blueprint"]["artifact_digest"] == blueprint["artifact_digest"]


def test_unadopted_proposal_remains_unconfirmed() -> None:
    blueprint = _blueprint()
    proposal = _artifact(
        "carry_forward_proposal",
        "p",
        proposal_ref=f"proposal-{'p' * 24}",
        proposal_state="unconfirmed",
    )
    loop = build_loop_instance_record(
        loop_ref=new_loop_ref(),
        generation_posture="blueprint_guided",
        governing_blueprint=blueprint,
    )
    result = build_unchanged_continuation(
        loop_instance_record=loop,
        governing_working_blueprint=blueprint,
        retained_evidence={},
        explicit_user_action={
            "confirmed": True,
            "provenance": "explicit_api_authority",
            "statement": "Continue unchanged and do not adopt the proposal.",
        },
        required_parent_artifacts={
            "governing_blueprint": (
                "implementation_blueprint",
                blueprint,
            )
        },
        next_permitted_operation_family="create_generation_context_pack",
        unadopted_proposal=proposal,
    )
    continuation = result["unchanged_continuation"]
    assert continuation["proposal_adopted"] is False
    assert continuation["unadopted_proposal"]["artifact_digest"] == proposal["artifact_digest"]
    assert "confirmation" not in canonical_json(result).lower()


def test_changed_seed_references_evolved_blueprint_and_preserves_working() -> None:
    working = _blueprint()
    before = deepcopy(working)
    evolved = _evolved(working)
    output_contract = _artifact(
        "output_evidence_contract",
        "c",
        parent_artifact_digest=evolved["artifact_digest"],
    )
    seed = build_changed_next_loop_seed(
        source_loop_ref=new_loop_ref(),
        evolved_blueprint=evolved,
        required_parent_artifacts={
            "governing_blueprint": ("implementation_blueprint", evolved),
            "output_evidence_contract": output_contract,
        },
        next_permitted_operation_family="create_generation_context_pack",
    )
    assert seed["continuation_outcome"] == "confirmed_change"
    assert seed["governing_blueprint"]["artifact_digest"] == evolved["artifact_digest"]
    assert working == before


def test_seed_expansion_requires_exact_explicit_parents_and_matches_direct_request(
    tmp_path: Path,
) -> None:
    blueprint = _blueprint()
    contract = _artifact(
        "output_evidence_contract",
        "c",
        parent_artifact_digest=blueprint["artifact_digest"],
    )
    seed = build_next_loop_seed(
        source_loop_ref=new_loop_ref(),
        continuation_outcome="unchanged_continuation",
        governing_blueprint=blueprint,
        required_parent_artifacts={
            "governing_blueprint": (
                "implementation_blueprint",
                blueprint,
            ),
            "output_evidence_contract": contract,
        },
        next_permitted_operation_family="create_generation_context_pack",
    )
    seed_file = tmp_path / "seed.json"
    blueprint_file = tmp_path / "blueprint.json"
    contract_file = tmp_path / "contract.json"
    _write_artifact(seed_file, seed)
    _write_artifact(blueprint_file, blueprint)
    _write_artifact(contract_file, contract)
    parent_files = {
        "governing_blueprint": blueprint_file,
        "output_evidence_contract": contract_file,
    }
    expanded = expand_next_loop_seed(
        seed_file=seed_file,
        parent_files=parent_files,
        tool_name="create_generation_context_pack",
    )
    direct = {
        "implementation_blueprint": blueprint,
        "output_evidence_contract": contract,
    }
    assert expanded["tool_input"] == direct
    assert expanded["canonical_request_sha256"] == (
        canonical_operation_request_sha256(
            tool_name="create_generation_context_pack",
            tool_input=direct,
        )
    )
    assert expanded["server_lookup_performed"] is False
    with pytest.raises(CurrentLoopError, match="next_loop_seed_parent_set_incomplete"):
        expand_next_loop_seed(
            seed_file=seed_file,
            parent_files={"governing_blueprint": blueprint_file},
            tool_name="create_generation_context_pack",
        )
    substituted = deepcopy(contract)
    substituted["expected_evidence"] = ["different"]
    substituted = with_artifact_digest(substituted)
    _write_artifact(contract_file, substituted)
    with pytest.raises(CurrentLoopError, match="parent_digest_mismatch"):
        expand_next_loop_seed(
            seed_file=seed_file,
            parent_files=parent_files,
            tool_name="create_generation_context_pack",
        )


def test_next_loop_activation_is_explicit_and_does_not_reopen_parent(
    tmp_path: Path,
) -> None:
    blueprint = _blueprint()
    contract = _artifact(
        "output_evidence_contract",
        "c",
        parent_artifact_digest=blueprint["artifact_digest"],
    )
    source_loop = new_loop_ref()
    seed = build_next_loop_seed(
        source_loop_ref=source_loop,
        continuation_outcome="unchanged_continuation",
        governing_blueprint=blueprint,
        required_parent_artifacts={
            "governing_blueprint": ("implementation_blueprint", blueprint),
            "output_evidence_contract": contract,
        },
        next_permitted_operation_family="create_generation_context_pack",
    )
    seed_file = tmp_path / "seed.json"
    blueprint_file = tmp_path / "blueprint.json"
    contract_file = tmp_path / "contract.json"
    _write_artifact(seed_file, seed)
    _write_artifact(blueprint_file, blueprint)
    _write_artifact(contract_file, contract)
    workspace = tmp_path / "next"
    workspace.mkdir()
    activated = activate_next_loop_from_seed(
        workspace_root=workspace,
        generation_posture="blueprint_guided",
        explicit_authority=True,
        seed_file=seed_file,
        parent_files={
            "governing_blueprint": blueprint_file,
            "output_evidence_contract": contract_file,
        },
        tool_name="create_generation_context_pack",
    )
    assert activated["state"]["parent_loop_ref"] == source_loop
    assert activated["state"]["automatic_reopen"] is False
    assert activated["expanded_next_operation"]["server_lookup_performed"] is False


def test_adapter_selected_seed_expands_existing_operation_without_new_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blueprint = _blueprint()
    contract = _artifact(
        "output_evidence_contract",
        "c",
        parent_artifact_digest=blueprint["artifact_digest"],
    )
    seed = build_next_loop_seed(
        source_loop_ref=new_loop_ref(),
        continuation_outcome="unchanged_continuation",
        governing_blueprint=blueprint,
        required_parent_artifacts={
            "governing_blueprint": ("implementation_blueprint", blueprint),
            "output_evidence_contract": contract,
        },
        next_permitted_operation_family="create_generation_context_pack",
    )
    files = {}
    for role, artifact in (
        ("seed", seed),
        ("governing_blueprint", blueprint),
        ("output_evidence_contract", contract),
    ):
        path = tmp_path / f"{role}.json"
        _write_artifact(path, artifact)
        files[role] = path
    captured: dict[str, object] = {}

    def fake_post_context_bridge(**values: object) -> dict[str, object]:
        captured.update(values)
        return {
            "ok": True,
            "tool_name": "create_generation_context_pack",
            "retained_artifacts": [],
        }

    monkeypatch.setattr(
        "qcoder.context_bridge_mcp.post_context_bridge",
        fake_post_context_bridge,
    )
    response = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "create_generation_context_pack",
                "arguments": {LOCAL_SELECTED_NEXT_LOOP_SEED_FIELD: True},
            },
        },
        base_url="https://example.invalid",
        token_file=tmp_path / "token.txt",
        selected_next_loop_seed_file=files["seed"],
        selected_next_loop_parent_files={
            "governing_blueprint": files["governing_blueprint"],
            "output_evidence_contract": files["output_evidence_contract"],
        },
    )
    assert response["result"]["isError"] is False
    arguments = captured["tool_arguments"]
    assert arguments["implementation_blueprint"] == blueprint
    assert arguments["output_evidence_contract"] == contract
    assert arguments["decision_loop"] == "readiness_resolution_v1"
    assert arguments["profile_decision_catalog_version"] == 1
    assert arguments["current_lineage_reference"] == LINEAGE
    assert captured["expected_request_digest"] == (
        canonical_operation_request_sha256(
            tool_name="create_generation_context_pack",
            tool_input=arguments,
        )
    )
    assert LOCAL_SELECTED_NEXT_LOOP_SEED_FIELD not in arguments
    assert len(EXPECTED_TOOLS) == 12


def test_adapter_selected_seed_without_local_configuration_fails_closed(
    tmp_path: Path,
) -> None:
    response = handle_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "create_generation_context_pack",
                "arguments": {LOCAL_SELECTED_NEXT_LOOP_SEED_FIELD: True},
            },
        },
        base_url="https://example.invalid",
        token_file=tmp_path / "token.txt",
    )
    payload = response["result"]["structuredContent"]
    assert response["result"]["isError"] is True
    assert payload["error_category"] == "selected_next_loop_seed_not_configured"


def test_refresh_loop_record_uses_only_exact_saved_artifacts(tmp_path: Path) -> None:
    store, activated = _activate(tmp_path)
    blueprint = _blueprint()
    saved = save_exact_canonical_artifact(
        store=store,
        role="working_blueprint",
        artifact=blueprint,
        destination=store.workspace_root / "bell.working-blueprint.json",
        expected_revision=activated["state"]["state_revision"],
    )
    refreshed = refresh_loop_instance_record(
        store=store,
        expected_revision=saved["state_revision"],
        explicit_authority=True,
    )
    record = refreshed["loop_instance_record"]
    assert record["governing_blueprint"]["artifact_digest"] == blueprint["artifact_digest"]
    assert record["decision_inventory_binding"]["decision_count"] == 19
    assert loop_instance_record_error(record) is None


def test_partial_and_standalone_artifacts_remain_explicit_and_missing_stays_missing() -> None:
    circuit = _artifact("circuit_manifestation", "c", stage="logical_circuit")
    result = _artifact("result_manifestation", "r", stage="run_results")
    circuit_only = build_loop_instance_record(
        loop_ref=new_loop_ref(),
        generation_posture="exploratory_first_pass",
        stage_artifacts={"circuit_manifestation": circuit},
        stage_availability={
            "python_source": "not_supplied",
            "logical_circuit": "available",
            "run_results": "not_run",
        },
    )
    result_only = build_loop_instance_record(
        loop_ref=new_loop_ref(),
        generation_posture="exploratory_first_pass",
        stage_artifacts={"result_manifestation": result},
        stage_availability={
            "python_source": "not_supplied",
            "logical_circuit": "not_supplied",
            "run_results": "available",
        },
    )
    assert set(circuit_only["stage_artifacts"]) == {"circuit_manifestation"}
    assert set(result_only["stage_artifacts"]) == {"result_manifestation"}
    assert circuit_only["stage_availability"]["run_results"] == "not_run"
    assert result_only["stage_availability"]["python_source"] == "not_supplied"


@pytest.mark.parametrize(
    "category",
    (
        "selected_file_changed",
        "selected_file_missing",
        "selected_set_changed",
        "manifestation_missing",
        "canonical_artifact_modified",
        "parent_digest_mismatch",
        "loop_instance_record_mismatch",
        "next_loop_seed_mismatch",
        "concurrent_state_update",
        "source_changed",
        "circuit_changed",
        "result_changed",
        "governing_blueprint_changed",
    ),
)
def test_every_stale_category_is_bounded_and_forbids_chat_repair(
    category: str,
) -> None:
    result = stale_recovery_result(category)
    assert result["category"] == category
    assert result["customer_explanation"]
    assert result["affected_artifacts"]
    assert result["blocked_transition"]
    assert result["supported_recovery"]
    assert result["assistant_reconstruction_allowed"] is False


def test_explicit_dependency_invalidation_and_state_revision(tmp_path: Path) -> None:
    store, activated = _activate(tmp_path)
    state = mark_local_dependency_stale(
        store=store,
        category="circuit_changed",
        affected_artifacts=["circuit_manifestation", "result_manifestation"],
        expected_revision=activated["state"]["state_revision"],
    )
    assert state["stage_freshness"]["circuit_manifestation"] == "stale"
    assert state["stage_freshness"]["result_manifestation"] == "stale"
    assert state["freshness_events"][0]["blocked_transition"] == (
        "dependent_context_loop_transition"
    )


def test_contracts_reject_future_versions_and_prohibited_fields() -> None:
    record = build_loop_instance_record(
        loop_ref=new_loop_ref(),
        generation_posture="blueprint_guided",
    )
    future = deepcopy(record)
    future["schema_version"] = 2
    future = with_artifact_digest(future)
    assert loop_instance_record_error(future) == ("loop_instance_record_version_invalid")
    prohibited = deepcopy(record)
    prohibited["raw_source"] = "forbidden"
    prohibited = with_artifact_digest(prohibited)
    assert loop_instance_record_error(prohibited) == ("loop_instance_record_prohibited_field")


def test_no_token_path_or_protected_policy_in_portable_contracts() -> None:
    blueprint = _blueprint()
    seed = build_next_loop_seed(
        source_loop_ref=new_loop_ref(),
        continuation_outcome="unchanged_continuation",
        governing_blueprint=blueprint,
        required_parent_artifacts={"governing_blueprint": ("implementation_blueprint", blueprint)},
        next_permitted_operation_family="create_generation_context_pack",
    )
    serialized = canonical_json(seed).lower()
    assert "token" not in serialized
    assert "local_path" not in serialized
    assert "/home/" not in serialized
    assert "protected_policy" not in serialized
    assert seed["server_lookup"] is False
    assert seed["project_reopen"] is False
