from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

import qcoder.current_loop as current_loop_module
from qcoder.context_bridge_mcp import build_client_binding_descriptor
from qcoder.current_loop import canonical_json, migrate_current_loop_state
from qcoder.current_loop_adaptive_intent import (
    ADAPTIVE_INTENT_DOCUMENT_SCHEMA_ID,
    ADAPTIVE_INTENT_INPUT_SCHEMA_ID,
    adaptive_intent_completeness_matrix,
    adaptive_intent_contract_snapshot,
    build_adaptive_intent_input_contract,
    canonicalize_adaptive_intent_document,
    consume_fields_file,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from tests.current_loop_test_support import activate_reviewed_legacy_fixture

BELL_REQUEST = "Use qCoder for this build context with the established adaptive-intent contract."


def _activate(workspace: Path, request: str = BELL_REQUEST):
    coordinator = CurrentLoopCoordinator(workspace_root=workspace)
    result = activate_reviewed_legacy_fixture(
        coordinator,
        original_request=request,
    )
    assert result["ok"] is True
    operation = result["next_invocation"]["operation_specific_invocation"]
    contract = operation["adaptive_intent_input_contract"]
    assert operation["input_contract_kind"] == "adaptive_intent_input"
    assert operation["bounded_control_input_contract"] is None
    return coordinator, result, contract


def _write_document(path: Path, document: object) -> None:
    path.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _fill_required(contract: dict, *, assumption: bool = False) -> Path:
    document = deepcopy(contract["fixed_payload"])
    values = {
        "normalized_goal": "Create and run the requested circuit.",
        "problem_size_meaning": "Two qubits, as stated by the customer.",
        "framework_requirement": "Qiskit, as stated by the customer.",
        "measurement_plan": "Measure both qubits and interpret their classical bits.",
        "execution_intent": "Use the requested local simulator.",
        "desired_output": "1024-shot counts and a concise explanation.",
    }
    for name, value in values.items():
        document["fields"][name] = {
            "value": value,
            "provenance": "user_stated" if name != "measurement_plan" else "derived",
        }
    if assumption:
        document["fields"]["explanation"] = {
            "value": "Use a short plain-language explanation.",
            "provenance": "assistant_proposed",
        }
    path = Path(contract["fields_file_transport"]["exact_qcoder_owned_path"])
    _write_document(path, document)
    return path


def test_binding_v11_publishes_dedicated_complete_adaptive_intent_contract() -> None:
    binding = build_client_binding_descriptor(
        coordinator_prefix=["/runtime/python", "-m", "qcoder", "current-loop"]
    )["client_binding_contract"]
    assert binding["contract_id"] == "qcoder.connected_assistant.client_binding.v26"
    contract = binding["adaptive_intent_input_contract"]
    assert contract["schema_id"] == ADAPTIVE_INTENT_INPUT_SCHEMA_ID
    assert set(contract["profiles"]) == {"generic_qiskit", "grover_search", "qaoa"}
    matrix = binding["adaptive_intent_input_completeness_matrix"]
    assert matrix == adaptive_intent_completeness_matrix()
    assert matrix["row_count"] > 0
    for count in (
        "missing_field_schema_count",
        "assistant_invented_qcoder_owned_value_count",
        "downstream_required_field_omission_count",
        "advertised_value_rejection_count",
        "parser_valid_assistant_value_omission_count",
    ):
        assert matrix[count] == 0
    assert contract == adaptive_intent_contract_snapshot()


def test_every_advertised_profile_field_and_provenance_is_validator_accepted(
    tmp_path: Path,
) -> None:
    snapshot = adaptive_intent_contract_snapshot()
    expected_rows = 0
    for profile_id in sorted(snapshot["profiles"]):
        path = tmp_path / f"{profile_id}.json"
        contract = build_adaptive_intent_input_contract(
            input_path=path,
            loop_ref=f"loop-{profile_id}",
            workspace_binding=str(tmp_path),
            state_revision=7,
            contract_revision=2,
            generation_governance="adaptive",
            internal_profile_classification=profile_id,
            internal_posture_mapping="exploratory_first_pass",
            request_baseline_digest="b" * 64,
            phase="activated",
            checkpoint="none",
        )
        catalog = contract["fields"]
        schema_fields = contract["document_schema"]["properties"]["fields"]
        assert set(schema_fields["properties"]) == {row["field_name"] for row in catalog}
        expected_rows += 14 + len(catalog)
        for row in catalog:
            for provenance in row["assistant_writable_provenance"]:
                document = deepcopy(contract["fixed_payload"])
                value_schema = row["json_schema"]
                accepted_types = value_schema["type"]
                if provenance == "unresolved":
                    value = None
                elif "integer" in accepted_types:
                    value = 2
                elif "array" in accepted_types:
                    value = ["bounded attributable value"]
                else:
                    value = "bounded attributable value"
                document["fields"][row["field_name"]] = {
                    "value": value,
                    "provenance": provenance,
                }
                _write_document(path, document)
                normalized = consume_fields_file(supplied_path=path, contract=contract)
                if (
                    provenance == "unresolved"
                    and row["status"] == "optional"
                    and not row["governing"]
                ):
                    assert row["field_name"] not in normalized
                else:
                    assert normalized[row["field_name"]]["provenance"] == provenance
    matrix = adaptive_intent_completeness_matrix()
    assert matrix["row_count"] == expected_rows


def test_local_state_v6_migrates_to_v7_without_quiet_history_reset(tmp_path: Path) -> None:
    coordinator, _, _ = _activate(tmp_path)
    state = coordinator.store.read()
    state["schema_id"] = "qcoder.current_loop.local_state.v6"
    state["schema_version"] = 6
    state["assistant_context_updates"] = [{"marker": "preserved"}]
    state["state_digest"] = current_loop_module._state_digest(state)
    coordinator.state_path.write_text(canonical_json(state), encoding="utf-8")
    migrated = migrate_current_loop_state(coordinator.store)
    assert migrated["schema_id"] == "qcoder.current_loop.local_state.v9"
    assert migrated["schema_version"] == 9
    assert migrated["assistant_context_updates"] == [{"marker": "preserved"}]


def test_bell_contract_prebinds_qcoder_values_and_one_passes_without_prompt(
    tmp_path: Path,
) -> None:
    coordinator, activation, contract = _activate(tmp_path)
    assert contract["internal_profile_classification"] == "generic_qiskit"
    assert contract["generation_governance"] == "adaptive"
    assert contract["internal_posture_mapping"] == "exploratory_first_pass"
    assert contract["loop_ref"] == coordinator.store.read()["loop_ref"]
    assert contract["workspace_binding"] == str(tmp_path)
    assert contract["request_baseline_digest"]
    assert contract["fixed_payload"]["schema_id"] == ADAPTIVE_INTENT_DOCUMENT_SCHEMA_ID
    assert contract["schema_id"] != contract["fixed_payload"]["schema_id"]
    assert all(
        row["ownership"] == "qcoder_owned_prebound_value"
        for row in contract["qcoder_owned_fixed_inputs"]
    )
    assert contract["fields_file_transport"]["encoding"] == "UTF-8"
    assert contract["fields_file_transport"]["assistant_may_choose_path"] is False
    document_schema = contract["document_schema"]
    assert document_schema["$schema"].endswith("draft/2020-12/schema")
    assert document_schema["properties"]["fields"]["additionalProperties"] is False
    assert set(document_schema["properties"]["fields"]["required"]) == {
        "normalized_goal",
        "problem_size_meaning",
        "framework_requirement",
        "measurement_plan",
        "execution_intent",
        "desired_output",
    }
    assert document_schema["properties"]["fields"]["properties"]["shots"]["properties"]["value"][
        "type"
    ] == ["integer", "null"]
    argv = activation["next_invocation"]["operation_specific_invocation"]["structured_argv"]
    path = Path(contract["fields_file_transport"]["exact_qcoder_owned_path"])
    assert argv[-2:] == ["--fields-file", str(path)]
    assert path.exists()

    result = coordinator.prepare_adaptive_intent(
        fields_file=_fill_required(contract, assumption=True)
    )
    assert result["ok"] is True
    assert result["phase"] == "generation_ready"
    assert result["details"]["intent_receipt"]["material_decision_required"] is False
    assert result["customer_interaction"]["requires_customer_response"] is False
    assert result["customer_interaction"]["primary_interaction_kind"] == (
        "no_customer_interaction_required"
    )
    assert result["next_invocation"]["operation_specific_invocation"]["operation"] == (
        "record_ide_authority"
    )
    assert not path.exists()


@pytest.mark.parametrize(
    ("customer_request", "profile_id"),
    (
        ("Use qCoder for this build. Prepare a Grover search circuit.", "grover_search"),
        ("Use qCoder for this build. Prepare a small QAOA circuit.", "qaoa"),
        ("Use qCoder for this build. Prepare a quantum Fourier transform.", "generic_qiskit"),
    ),
)
def test_non_bell_profile_is_qcoder_prebound(
    tmp_path: Path,
    customer_request: str,
    profile_id: str,
) -> None:
    workspace = tmp_path / profile_id
    workspace.mkdir()
    _, _, contract = _activate(workspace, customer_request)
    assert contract["internal_profile_classification"] == profile_id
    assert "internal_profile_classification" not in {
        row["field_name"] for row in contract["fields"]
    }


def test_non_bell_adaptive_request_constructs_and_continues_without_prompt(
    tmp_path: Path,
) -> None:
    request = (
        "Use qCoder for this build. Create a two-qubit Qiskit quantum Fourier "
        "transform example and run it on a local simulator with 256 shots."
    )
    coordinator, _, contract = _activate(tmp_path, request)
    path = _fill_required(contract)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["fields"]["shots"] = {"value": 256, "provenance": "user_stated"}
    _write_document(path, document)
    result = coordinator.prepare_adaptive_intent(fields_file=path)
    assert result["ok"] is True
    assert result["phase"] == "generation_ready"
    assert result["customer_interaction"]["requires_customer_response"] is False


def test_unresolved_material_value_groups_decision_and_blueprint_required_is_governed(
    tmp_path: Path,
) -> None:
    coordinator, _, contract = _activate(
        tmp_path,
        "Use qCoder for this current context; the algorithm decision is undecided.",
    )
    path = _fill_required(contract)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["fields"]["algorithm_choice"] = {
        "value": None,
        "provenance": "unresolved",
    }
    _write_document(path, document)
    result = coordinator.prepare_adaptive_intent(fields_file=path)
    assert result["ok"] is True
    assert result["checkpoint_kind"] == "decision_resolution"
    assert result["customer_interaction"]["primary_interaction_kind"] == (
        "material_decision_request"
    )
    assert result["customer_interaction"]["requires_customer_response"] is True
    assert isinstance(result["next_invocation"], dict)

    governed_workspace = tmp_path / "governed"
    governed_workspace.mkdir()
    governed, _, _ = _activate(governed_workspace)
    state = governed.store.read()
    # Reuse the supported domain transition so the contract digest is valid.
    from qcoder.current_loop_contract import set_generation_governance

    changed_result = set_generation_governance(
        state["current_loop_contract"],
        governance="blueprint_required",
        expected_contract_revision=state["current_loop_contract"]["contract_revision"],
        provenance="customer_selected_contract_setting",
    )
    governed._replace_contract(
        changed_result["contract"],
        cancel_pending_for_narrowing=True,
    )
    refreshed = governed._adaptive_intent_contract(governed.store.read(), initialize=True)
    result = governed.prepare_adaptive_intent(fields_file=_fill_required(refreshed))
    assert result["checkpoint_kind"] == "decision_resolution"
    assert result["details"]["intent_receipt"]["material_decision_required"] is True


@pytest.mark.parametrize("provenance", ("assistant_proposed", "assumed"))
def test_non_attributable_material_proposals_group_one_decision(
    tmp_path: Path,
    provenance: str,
) -> None:
    workspace = tmp_path / provenance
    workspace.mkdir()
    coordinator, _, contract = _activate(
        workspace,
        "Use qCoder for this current context; the algorithm decision is undecided.",
    )
    path = _fill_required(contract)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["fields"]["algorithm_choice"] = {
        "value": "A reversible candidate choice",
        "provenance": provenance,
    }
    _write_document(path, document)
    result = coordinator.prepare_adaptive_intent(fields_file=path)
    assert result["ok"] is True
    assert result["checkpoint_kind"] == "decision_resolution"
    assert result["details"]["intent_receipt"]["material_decision_fields"] == ["algorithm_choice"]
    assert result["customer_interaction"]["requires_customer_response"] is True


@pytest.mark.parametrize(
    ("mutation", "category"),
    (
        ("missing", "adaptive_intent_field_missing"),
        ("wrong_type", "adaptive_intent_field_type_invalid"),
        ("provenance", "adaptive_intent_provenance_invalid"),
        ("qcoder_provenance", "adaptive_intent_provenance_ownership_invalid"),
        ("materiality", "adaptive_intent_materiality_override_prohibited"),
        ("unknown", "adaptive_intent_field_unknown"),
        ("stale_state", "adaptive_intent_state_stale"),
        ("stale_contract", "adaptive_intent_contract_stale"),
        ("wrong_profile", "adaptive_intent_profile_invalid"),
    ),
)
def test_invalid_input_is_safe_recoverable_with_fresh_complete_invocation(
    tmp_path: Path,
    mutation: str,
    category: str,
) -> None:
    workspace = tmp_path / mutation
    workspace.mkdir()
    coordinator, _, contract = _activate(workspace)
    path = _fill_required(contract)
    document = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "missing":
        document["fields"].pop("normalized_goal")
    elif mutation == "wrong_type":
        document["fields"]["normalized_goal"]["value"] = {"not": "a string"}
    elif mutation == "provenance":
        document["fields"]["normalized_goal"]["provenance"] = "invented"
    elif mutation == "qcoder_provenance":
        document["fields"]["normalized_goal"]["provenance"] = "qcoder_classified"
    elif mutation == "materiality":
        document["fields"]["normalized_goal"]["material"] = False
    elif mutation == "unknown":
        document["fields"]["hidden"] = {"value": "x", "provenance": "derived"}
    elif mutation == "stale_state":
        document["state_revision"] -= 1
    elif mutation == "stale_contract":
        document["contract_revision"] -= 1
    elif mutation == "wrong_profile":
        document["internal_profile_classification"] = "grover_search"
    _write_document(path, document)
    result = coordinator.prepare_adaptive_intent(fields_file=path)
    assert result["ok"] is False
    assert result["category"] == category
    assert result["details"]["prior_valid_activation_preserved"] is True
    assert result["details"]["prior_valid_request_baseline_preserved"] is True
    invocation = result["next_invocation"]["operation_specific_invocation"]
    assert invocation["operation"] == "prepare_adaptive_intent"
    assert (
        invocation["adaptive_intent_input_contract"]["state_revision"]
        == (coordinator.store.read()["state_revision"])
    )
    assert invocation["hosted_access_permitted"] is False


def test_invalid_utf8_missing_file_replay_and_single_use_cleanup(tmp_path: Path) -> None:
    for case in ("utf8", "missing"):
        workspace = tmp_path / case
        workspace.mkdir()
        coordinator, _, contract = _activate(workspace)
        path = Path(contract["fields_file_transport"]["exact_qcoder_owned_path"])
        if case == "utf8":
            path.write_bytes(b"\xff")
            expected = "adaptive_intent_utf8_invalid"
        else:
            path.unlink()
            expected = "adaptive_intent_file_missing"
        result = coordinator.prepare_adaptive_intent(fields_file=path)
        assert result["category"] == expected

    workspace = tmp_path / "replay"
    workspace.mkdir()
    coordinator, _, contract = _activate(workspace)
    old_path = _fill_required(contract)
    assert coordinator.prepare_adaptive_intent(fields_file=old_path)["ok"] is True
    replay = coordinator.prepare_adaptive_intent(fields_file=old_path)
    assert replay["category"] == "adaptive_intent_file_replayed"


@pytest.mark.parametrize(
    ("payload", "category"),
    (
        (b"{", "adaptive_intent_json_invalid"),
        (b"[]", "adaptive_intent_document_type_invalid"),
        (b'{ "x": 1 }', "adaptive_intent_fixed_payload_mismatch"),
        (b"x" * 131_073, "adaptive_intent_file_oversize"),
    ),
)
def test_bounded_file_transport_rejects_malformed_or_oversize_input(
    tmp_path: Path,
    payload: bytes,
    category: str,
) -> None:
    workspace = tmp_path / category
    workspace.mkdir()
    coordinator, _, contract = _activate(workspace)
    path = Path(contract["fields_file_transport"]["exact_qcoder_owned_path"])
    path.write_bytes(payload)
    result = coordinator.prepare_adaptive_intent(fields_file=path)
    assert result["ok"] is False
    assert result["category"] == category
    assert result["details"]["received_private_content_echoed"] is False
    assert result["details"]["hosted_operation_permitted"] is False


def test_primary_interaction_envelope_is_compact(tmp_path: Path) -> None:
    coordinator, activation, contract = _activate(tmp_path)
    envelope = activation["customer_interaction"]
    assert envelope["next_invocation"]["full_invocation_location"] == (
        "coordinator_result.next_invocation"
    )
    assert "adaptive_intent_input_contract" not in envelope["next_invocation"]
    assert len(json.dumps(envelope)) < 8_000
    result = coordinator.prepare_adaptive_intent(fields_file=_fill_required(contract))
    assert len(json.dumps(result["customer_interaction"])) < 8_000


def test_bell_first_submission_normalizes_transport_without_semantic_reapproval(
    tmp_path: Path,
) -> None:
    coordinator, _, contract = _activate(tmp_path)
    before = coordinator.store.read()
    request_baseline = deepcopy(before["saved_artifacts"]["request_baseline"])
    path = _fill_required(contract)
    document = json.loads(path.read_text(encoding="utf-8"))
    reordered = {name: document[name] for name in reversed(tuple(document))}
    path.write_text(json.dumps(reordered, ensure_ascii=False, indent=2), encoding="utf-8")

    result = coordinator.prepare_adaptive_intent(fields_file=path)

    assert result["ok"] is True
    assert result["customer_interaction"]["requires_customer_response"] is False
    assert result["checkpoint_kind"] == "none"
    assert result["next_invocation"]["operation_specific_invocation"]["operation"] == (
        "record_ide_authority"
    )
    assert coordinator.store.read()["saved_artifacts"]["request_baseline"] == request_baseline
    assert "JSON" not in result["customer_summary"]
    assert "schema" not in result["customer_summary"].casefold()


def test_equivalent_transport_orders_have_one_canonical_serialization(
    tmp_path: Path,
) -> None:
    _, _, contract = _activate(tmp_path)
    path = _fill_required(contract)
    document = json.loads(path.read_text(encoding="utf-8"))
    text_a = json.dumps(document, ensure_ascii=False, indent=4)
    text_b = json.dumps(
        {name: document[name] for name in reversed(tuple(document))},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    parsed_a, canonical_a = canonicalize_adaptive_intent_document(text_a)
    parsed_b, canonical_b = canonicalize_adaptive_intent_document(text_b)
    assert parsed_a == parsed_b
    assert canonical_a == canonical_b
    assert canonical_a == json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def test_duplicate_key_is_semantic_conflict_not_silent_last_value(
    tmp_path: Path,
) -> None:
    coordinator, _, contract = _activate(tmp_path)
    path = _fill_required(contract)
    text = path.read_text(encoding="utf-8")
    prefix = '{"schema_id":"qcoder.current_loop.adaptive_intent_fields_document.v1",'
    assert text.startswith('{"checkpoint"')
    path.write_text(prefix + text[1:], encoding="utf-8")
    result = coordinator.prepare_adaptive_intent(fields_file=path)
    assert result["ok"] is False
    assert result["category"] == "adaptive_intent_semantic_conflict"
    assert "JSON" not in result["customer_summary"]
    assert "schema" not in result["customer_summary"].casefold()


def test_black_box_executes_only_delivered_contract_and_exact_invocation(
    tmp_path: Path,
) -> None:
    _, activation, contract = _activate(tmp_path)
    _fill_required(contract)
    invocation = activation["next_invocation"]["operation_specific_invocation"]
    argv = invocation["structured_argv"]
    assert all(isinstance(item, str) for item in argv)
    environment = dict(os.environ)
    source_root = Path(__file__).resolve().parents[1] / "src"
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(source_root) if not existing else os.pathsep.join((str(source_root), existing))
    )
    completed = subprocess.run(
        [sys.executable if index == 0 else item for index, item in enumerate(argv)],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    result = json.loads(completed.stdout)
    assert result["ok"] is True
    assert result["phase"] == "generation_ready"
    assert result["customer_interaction"]["requires_customer_response"] is False
    assert result["next_invocation"]["operation_specific_invocation"]["operation"] == (
        "record_ide_authority"
    )
