from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    CLIENT_BINDING_SCHEMA_VERSION,
    EXPECTED_TOOLS,
)
import qcoder.current_loop_binding_mcp as binding_mcp
from qcoder.current_loop_binding_mcp import (
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.review_before_generation import PROPOSAL_SCHEMA_ID
from qcoder.review_before_generation import (
    build_first_value,
    canonical_json,
    render_first_value_markdown,
)


ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "src/qcoder/model_packs/wi0440_bell_review_before_generation_v1.json"
D128_REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a Φ+ Bell state. "
    "Before generating the code, help me review how you interpret my request and the important "
    "implementation choices."
)


def proposal(
    mode: str = "inline",
    target: object = None,
    *,
    transaction_kind: str = "review_before_source_generation",
) -> dict[str, object]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    value["customer_constraints"] = []
    value["transaction_kind"] = transaction_kind
    value["source_delivery"] = {"mode": mode, "target": target}
    return value


def call(workspace: Path, arguments: dict[str, object]) -> dict[str, object]:
    workspace.mkdir(parents=True, exist_ok=True)
    response = handle_binding_jsonrpc_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "begin_current_loop", "arguments": arguments},
        },
        workspace_root=workspace,
    )
    assert response is not None
    return response["result"]["structuredContent"]


def confirm(workspace: Path, token: str, action: str = "Use recommended choices") -> dict:
    return call(
        workspace,
        {"review_action": action, "prior_result_token": token},
    )


def item_values(result: dict[str, object]) -> dict[str, str]:
    review = result["review_before_generation"]
    assert isinstance(review, dict)
    return {
        item["label"]: item["value"]
        for group in review["initial_decision_groups"]
        for item in group["items"]
    }


def stored_review(workspace: Path) -> dict:
    return CurrentLoopCoordinator(workspace_root=workspace).store.read()["coordinator"][
        "review_before_generation"
    ]


@pytest.mark.parametrize(
    "envelope",
    (
        {},
        {"intended_artifact_paths": {"source": "bell.py"}},
        {"selected_artifact_paths": ["bell.py"]},
        {
            "intended_artifact_paths": {"source": "bell.py"},
            "selected_artifact_paths": ["bell.py"],
        },
    ),
)
def test_exact_d128_invented_file_and_envelopes_converge_inline(
    tmp_path: Path, envelope: dict[str, object]
) -> None:
    clean = call(
        tmp_path / "clean",
        {"request_text": D128_REQUEST, "connected_assistant_proposal": proposal()},
    )
    invented = call(
        tmp_path / "invented",
        {
            "request_text": D128_REQUEST,
            "connected_assistant_proposal": proposal("workspace_file", "bell.py"),
            **envelope,
        },
    )
    assert clean["ok"] is invented["ok"] is True
    assert invented["review_before_generation"] == clean["review_before_generation"]
    assert item_values(invented)["Source delivery"] == "Inline after confirmation."
    assert "Proposed source target" not in item_values(invented)
    stored = stored_review(tmp_path / "invented")
    assert stored["intended_artifact_targets"] == {}
    assert stored["displayed_source_target"] is None


@pytest.mark.parametrize(
    "target",
    (None, "../bell.py", "/tmp/bell.py", "bell.qasm", "missing.py"),
)
def test_missing_unsafe_or_ungrounded_file_recommendation_silently_converges_inline(
    tmp_path: Path, target: object
) -> None:
    result = call(
        tmp_path / str(target).replace("/", "_"),
        {
            "request_text": D128_REQUEST,
            "connected_assistant_proposal": proposal("workspace_file", target),
        },
    )
    assert result["ok"] is True
    assert item_values(result)["Source delivery"] == "Inline after confirmation."
    assert "Proposed source target" not in item_values(result)


def test_ungrounded_review_does_not_enter_path_processing_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("path processing ran before confirmed authority")

    monkeypatch.setattr(binding_mcp, "normalize_selected_artifact_paths", forbidden)
    monkeypatch.setattr(binding_mcp, "normalize_intended_artifact_targets", forbidden)
    result = call(
        tmp_path,
        {
            "request_text": D128_REQUEST,
            "connected_assistant_proposal": proposal("workspace_file", "bell.py"),
            "intended_artifact_paths": {"source": "bell.py"},
            "selected_artifact_paths": ["bell.py"],
        },
    )
    assert result["ok"] is True


def test_grounded_file_is_visible_but_inert_until_exact_confirmation(tmp_path: Path) -> None:
    request = "Use qCoder to review the Qiskit Bell plan before generating the source in bell.py."
    result = call(
        tmp_path,
        {
            "request_text": request,
            "connected_assistant_proposal": proposal("workspace_file", "bell.py"),
        },
    )
    values = item_values(result)
    assert values["Source delivery"] == "Workspace file after confirmation."
    assert values["Proposed source target"] == "bell.py"
    before = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()["coordinator"]
    assert before.get("intended_artifact_targets", {}) == {}
    assert before["review_before_generation"]["intended_artifact_targets"] == {}
    confirmed = confirm(tmp_path, result["prior_result_token"])
    assert confirmed["generation_ready_context"]["exact_workspace_target"] == "bell.py"
    assert (
        confirmed["current_step_contract"]["permitted_native_action"]["exact_artifact_target"][
            "workspace_relative_path"
        ]
        == "bell.py"
    )
    assert confirmed["execution_authority"] == "not_requested"


def test_grounded_file_review_matches_deterministic_json_and_markdown_goldens() -> None:
    request = "Use qCoder to review the Qiskit Bell plan before generating the source in bell.py."
    first = build_first_value(request, proposal("workspace_file", "bell.py"))
    golden = ROOT / "tests/fixtures/wi0440_review_before_generation_v1/goldens"
    assert (
        canonical_json(first).encode("utf-8")
        == (golden / "bell-workspace-file-first-value.json").read_bytes()
    )
    assert (
        render_first_value_markdown(first).encode("utf-8")
        == (golden / "bell-workspace-file-first-value.md").read_bytes()
    )


@pytest.mark.parametrize(
    "case_text",
    (
        "Use qCoder to review this choice: Do not create bell.py; show source inline after confirmation.",
        "Use qCoder to review this example filename `bell.py` before generating source.",
        "Use qCoder to review whether bell.py or inline delivery is preferable before generating source.",
        "Use qCoder to review this correction: bell.py? No, show source inline after confirmation.",
    ),
)
def test_free_form_delivery_language_neither_grants_nor_denies_review_authority(
    tmp_path: Path, case_text: str
) -> None:
    workspace = tmp_path / str(abs(hash(case_text)))
    result = call(
        workspace,
        {
            "request_text": case_text,
            "connected_assistant_proposal": proposal("workspace_file", "bell.py"),
        },
    )
    assert result["ok"] is True
    assert item_values(result)["Proposed source target"] == "bell.py"
    assert stored_review(workspace)["intended_artifact_targets"] == {}


def test_visible_semantically_questionable_file_can_be_confirmed_or_revised_inline(
    tmp_path: Path,
) -> None:
    request = (
        "Use qCoder to review this delivery choice: Do not create bell.py; show the source inline "
        "after confirmation."
    )
    file_workspace = tmp_path / "confirm-file"
    file_review = call(
        file_workspace,
        {
            "request_text": request,
            "connected_assistant_proposal": proposal("workspace_file", "bell.py"),
        },
    )
    file_confirmed = confirm(file_workspace, file_review["prior_result_token"])
    assert file_confirmed["generation_ready_context"]["exact_workspace_target"] == "bell.py"

    revised_workspace = tmp_path / "revise-inline"
    first = call(
        revised_workspace,
        {
            "request_text": request,
            "connected_assistant_proposal": proposal("workspace_file", "bell.py"),
        },
    )
    choices = confirm(
        revised_workspace,
        first["prior_result_token"],
        "Review or change choices",
    )
    assert choices["state_mutated"] is False
    revised = call(
        revised_workspace,
        {
            "request_text": request,
            "connected_assistant_proposal": proposal("inline"),
            "prior_result_token": first["prior_result_token"],
        },
    )
    assert revised["ok"] is True
    assert item_values(revised)["Source delivery"] == "Inline after confirmation."
    stale = confirm(revised_workspace, first["prior_result_token"])
    assert stale["category"] == "review_confirmation_stale_token"
    inline = confirm(revised_workspace, revised["prior_result_token"])
    assert inline["generation_ready_context"]["exact_workspace_target"] is None
    assert inline["generation_ready_context"]["next_permitted_client_native_step"] == (
        "produce_inline_source"
    )


def test_revision_can_change_inline_to_file_and_target_a_to_b(tmp_path: Path) -> None:
    request = "Use qCoder to review source delivery to a.py or b.py before generation."
    workspace = tmp_path / "revision"
    inline = call(
        workspace,
        {"request_text": request, "connected_assistant_proposal": proposal()},
    )
    file_a = call(
        workspace,
        {
            "request_text": request,
            "connected_assistant_proposal": proposal("workspace_file", "a.py"),
            "prior_result_token": inline["prior_result_token"],
        },
    )
    file_b = call(
        workspace,
        {
            "request_text": request,
            "connected_assistant_proposal": proposal("workspace_file", "b.py"),
            "prior_result_token": file_a["prior_result_token"],
        },
    )
    assert confirm(workspace, file_a["prior_result_token"])["category"] == (
        "review_confirmation_stale_token"
    )
    confirmed = confirm(workspace, file_b["prior_result_token"])
    assert confirmed["generation_ready_context"]["exact_workspace_target"] == "b.py"


def test_hidden_or_changed_target_mutations_fail_closed(tmp_path: Path) -> None:
    request = "Use qCoder to review source generation in bell.py before creating it."
    for mutation in ("hidden", "display", "proposal"):
        workspace = tmp_path / mutation
        initial = call(
            workspace,
            {
                "request_text": request,
                "connected_assistant_proposal": proposal("workspace_file", "bell.py"),
            },
        )
        service = CurrentLoopCoordinator(workspace_root=workspace)
        state = service.store.read()
        coordinator = deepcopy(state["coordinator"])
        review = coordinator["review_before_generation"]
        if mutation == "hidden":
            review["intended_artifact_targets"] = {
                "source": {"workspace_relative_path": "hidden.py"}
            }
        elif mutation == "display":
            review["displayed_source_target"] = "changed.py"
        else:
            review["connected_assistant_proposal"]["source_delivery"]["target"] = "changed.py"
        service._replace_coordinator(coordinator)
        rejected = confirm(workspace, initial["prior_result_token"])
        assert rejected["ok"] is False
        assert service.store.read()["coordinator"]["phase"] == "intent_review"


def test_duplicate_file_confirmation_is_idempotent_without_broadening(tmp_path: Path) -> None:
    request = "Use qCoder to review source generation in bell.py before creating it."
    initial = call(
        tmp_path,
        {
            "request_text": request,
            "connected_assistant_proposal": proposal("workspace_file", "bell.py"),
        },
    )
    first = confirm(tmp_path, initial["prior_result_token"])
    duplicate = confirm(tmp_path, initial["prior_result_token"])
    assert duplicate["category"] == "review_confirmation_duplicate"
    assert duplicate["generation_ready_context"] == first["generation_ready_context"]
    assert duplicate["execution_authority"] == first["execution_authority"]


def test_selected_source_transaction_kind_mismatch_remains_strict(tmp_path: Path) -> None:
    request = (
        "Use qCoder to review proposed Qiskit Bell changes to the selected source before "
        "modifying it."
    )
    (tmp_path / "selected.py").write_text("ORIGINAL\n", encoding="utf-8")
    result = call(
        tmp_path,
        {
            "request_text": request,
            "connected_assistant_proposal": proposal("workspace_file", "selected.py"),
            "selected_artifact_paths": ["selected.py"],
        },
    )
    assert result["category"] == "review_request_proposal_transaction_kind_mismatch"
    assert not (tmp_path / ".qcoder" / "current-loop" / "state.json").exists()


def test_correct_selected_source_modification_remains_exact(tmp_path: Path) -> None:
    request = (
        "Use qCoder to review proposed Qiskit Bell changes to selected.py before modifying the "
        "selected source."
    )
    selected = tmp_path / "selected.py"
    selected.write_text("ORIGINAL\n", encoding="utf-8")
    result = call(
        tmp_path,
        {
            "request_text": request,
            "connected_assistant_proposal": proposal(
                "workspace_file",
                "selected.py",
                transaction_kind="review_before_source_modification",
            ),
            "selected_artifact_paths": ["selected.py"],
        },
    )
    assert result["ok"] is True
    assert item_values(result)["Proposed source target"] == "selected.py"
    assert selected.read_text(encoding="utf-8") == "ORIGINAL\n"


def test_proposal_v3_descriptor_and_inventory_are_exact() -> None:
    descriptor = binding_tool_descriptors()[0]
    proposal_schema = descriptor["inputSchema"]["properties"]["connected_assistant_proposal"]
    assert PROPOSAL_SCHEMA_ID.endswith(".v3")
    assert proposal_schema["properties"]["schema_version"] == {"const": 3}
    assert set(proposal_schema["properties"]["source_delivery"]["properties"]) == {
        "mode",
        "target",
    }
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v57"
    assert CLIENT_BINDING_SCHEMA_VERSION == 56
    assert len(EXPECTED_TOOLS) == 12
    assert [item["name"] for item in binding_tool_descriptors()] == [
        "begin_current_loop",
        "complete_current_step",
    ]


def test_d132_directive_parser_has_no_review_delivery_authority_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("superseded directive parser entered D-133 review path")

    monkeypatch.setattr(binding_mcp, "_resolve_request_source_target_authority", forbidden)
    request = "Use qCoder to review this example bell.py before generating source."
    result = call(
        tmp_path,
        {
            "request_text": request,
            "connected_assistant_proposal": proposal("workspace_file", "bell.py"),
        },
    )
    assert result["ok"] is True
    assert item_values(result)["Proposed source target"] == "bell.py"
