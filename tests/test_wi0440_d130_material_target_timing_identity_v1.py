from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from packaging.version import Version
import pytest

from qcoder import __version__
from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    CLIENT_BINDING_SCHEMA_VERSION,
    EXPECTED_TOOLS,
)
import qcoder.current_loop_binding_mcp as binding_mcp
from qcoder.current_loop_binding_mcp import binding_tool_descriptors, handle_binding_jsonrpc_message
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.current_loop_operator_timing import (
    OperatorTimingEvidenceError,
    clear_stdio_operator_timing,
    consume_stdio_operator_timing,
)
from qcoder.review_before_generation import CUSTOMER_ACTIONS


ROOT = Path(__file__).parents[1]
BELL_FIXTURE = ROOT / "src/qcoder/model_packs/wi0440_bell_review_before_generation_v1.json"
EXACT_D128_REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a Φ+ Bell state. "
    "Before generating the code, help me review how you interpret my request and the important "
    "implementation choices."
)
MODIFICATION_REQUEST = (
    "Use qCoder to review proposed Qiskit Bell changes to the selected source before modifying it."
)
NEGATED_TARGET_REQUEST = (
    "Use qCoder to review a Qiskit Bell program before generating source. Do not create bell.py; "
    "show the source inline after confirmation."
)


def proposal(*, transaction_kind: str = "review_before_source_generation") -> dict[str, object]:
    value = json.loads(BELL_FIXTURE.read_text(encoding="utf-8"))
    value["transaction_kind"] = transaction_kind
    value["customer_constraints"] = []
    if transaction_kind == "review_before_source_modification":
        value["source_delivery"] = {"mode": "workspace_file", "target": "selected.py"}
    return value


def binding_call(workspace: Path, arguments: dict[str, object]) -> dict[str, object]:
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


def first_value_source_target(result: dict[str, object]) -> str | None:
    review = result["review_before_generation"]
    assert isinstance(review, dict)
    matches = [
        item["value"]
        for group in review["initial_decision_groups"]
        for item in group["items"]
        if item["label"] == "Proposed source target"
    ]
    assert len(matches) <= 1
    return matches[0] if matches else None


def confirm(workspace: Path, token: object) -> dict[str, object]:
    assert isinstance(token, str)
    return binding_call(
        workspace,
        {"review_action": "Use recommended choices", "prior_result_token": token},
    )


def test_generation_label_cannot_discard_material_native_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "material-mismatch"
    workspace.mkdir()
    selected = workspace / "selected.py"
    selected.write_text("ORIGINAL\n", encoding="utf-8")
    arguments = {
        "request_text": MODIFICATION_REQUEST,
        "connected_assistant_proposal": proposal(),
        "selected_artifact_paths": ["selected.py"],
    }

    def normalization_must_not_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("mode mismatch must reject before target normalization")

    monkeypatch.setattr(
        binding_mcp, "normalize_selected_artifact_paths", normalization_must_not_run
    )
    monkeypatch.setattr(
        binding_mcp, "normalize_intended_artifact_targets", normalization_must_not_run
    )
    result = binding_call(workspace, arguments)
    assert result["ok"] is False
    assert result["category"] == "review_request_proposal_transaction_kind_mismatch"
    assert result["state_mutated"] is False
    assert result["selected_artifact_identity_discarded"] is False
    assert arguments["selected_artifact_paths"] == ["selected.py"]
    assert selected.read_text(encoding="utf-8") == "ORIGINAL\n"
    assert not (workspace / ".qcoder" / "current-loop" / "state.json").exists()


def test_correct_modification_kind_requires_and_preserves_exact_native_selection(
    tmp_path: Path,
) -> None:
    selected_proposal = proposal(transaction_kind="review_before_source_modification")
    missing = binding_call(
        tmp_path / "missing",
        {"request_text": MODIFICATION_REQUEST, "connected_assistant_proposal": selected_proposal},
    )
    assert missing["category"] == "review_source_modification_selection_required"

    workspace = tmp_path / "selected"
    workspace.mkdir()
    (workspace / "selected.py").write_text("ORIGINAL\n", encoding="utf-8")
    result = binding_call(
        workspace,
        {
            "request_text": MODIFICATION_REQUEST,
            "connected_assistant_proposal": selected_proposal,
            "selected_artifact_paths": ["selected.py"],
        },
    )
    assert result["ok"] is True
    assert first_value_source_target(result) == "selected.py"
    state = CurrentLoopCoordinator(workspace_root=workspace).store.read()
    review = state["coordinator"]["review_before_generation"]
    assert review["displayed_source_target"] == "selected.py"
    assert review["intended_artifact_targets"] == {}
    assert (workspace / "selected.py").read_text(encoding="utf-8") == "ORIGINAL\n"


def test_generation_kind_rejects_ambiguous_generation_modification_request(tmp_path: Path) -> None:
    request = (
        "Use qCoder to review whether to generate a new source program or modify the selected "
        "source before acting."
    )
    result = binding_call(
        tmp_path,
        {"request_text": request, "connected_assistant_proposal": proposal()},
    )
    assert result["category"] == "review_request_source_transaction_ambiguous"
    assert result["state_mutated"] is False
    assert "new source plan or changes" in result["customer_clarification"]


NEGATED_TARGET_VARIANTS = (
    pytest.param({}, id="no-target"),
    pytest.param({"intended_artifact_paths": {"source": "bell.py"}}, id="negated-target"),
    pytest.param({"intended_artifact_paths": {"source": "invented.py"}}, id="invented-target"),
    pytest.param(
        {
            "intended_artifact_paths": {"source": "bell.py"},
            "selected_artifact_paths": ["invented.py"],
        },
        id="both-target-forms",
    ),
)


@pytest.mark.parametrize("target_arguments", NEGATED_TARGET_VARIANTS)
def test_negated_filename_never_creates_workspace_authority(
    tmp_path: Path, target_arguments: dict[str, object]
) -> None:
    result = binding_call(
        tmp_path,
        {
            "request_text": NEGATED_TARGET_REQUEST,
            "connected_assistant_proposal": proposal(),
            **target_arguments,
        },
    )
    assert result["ok"] is True
    assert first_value_source_target(result) is None
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    review = state["coordinator"]["review_before_generation"]
    assert review["intended_artifact_targets"] == {}
    assert review["displayed_source_target"] is None
    confirmed = confirm(tmp_path, result["prior_result_token"])
    context = confirmed["generation_ready_context"]
    assert context["category"] == "confirmed_plan_generation_ready_inline_source"
    assert context["exact_workspace_target"] is None
    assert context["next_permitted_client_native_step"] == "produce_inline_source"
    assert "current_step_contract" not in confirmed
    confirmed_state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    coordinator = confirmed_state["coordinator"]
    assert coordinator["intended_artifact_targets"] == {}
    assert coordinator["current_step_status"] == "action_ready"


def test_all_negated_filename_variants_share_semantics_and_projection(tmp_path: Path) -> None:
    projections: list[dict[str, object]] = []
    revisions: list[str] = []
    for index, parameter in enumerate(NEGATED_TARGET_VARIANTS):
        workspace = tmp_path / str(index)
        result = binding_call(
            workspace,
            {
                "request_text": NEGATED_TARGET_REQUEST,
                "connected_assistant_proposal": proposal(),
                **parameter.values[0],
            },
        )
        projections.append(deepcopy(result["review_before_generation"]))
        state = CurrentLoopCoordinator(workspace_root=workspace).store.read()
        revisions.append(state["coordinator"]["review_before_generation"]["review_revision"])
    assert all(value == projections[0] for value in projections[1:])
    assert len(set(revisions)) == 1


@pytest.mark.parametrize(
    "request_text",
    [
        'Use qCoder to review a Bell plan before generating source; "bell.py" is only an example.',
        "Use qCoder to review a Bell plan before generating source, for example bell.py, but show it inline.",
    ],
)
def test_quoted_and_example_only_filenames_do_not_grant_target_authority(
    tmp_path: Path, request_text: str
) -> None:
    result = binding_call(
        tmp_path,
        {
            "request_text": request_text,
            "connected_assistant_proposal": proposal(),
            "intended_artifact_paths": {"source": "bell.py"},
        },
    )
    assert result["ok"] is True
    assert first_value_source_target(result) is None


def test_affirmative_exact_target_is_displayed_bound_and_preserved_through_confirmation(
    tmp_path: Path,
) -> None:
    request = "Use qCoder to review a Bell plan before generating source in bell.py."
    inline = binding_call(
        tmp_path / "missing",
        {"request_text": request, "connected_assistant_proposal": proposal()},
    )
    assert inline["ok"] is True
    wrong = binding_call(
        tmp_path / "wrong",
        {
            "request_text": request,
            "connected_assistant_proposal": proposal(),
            "intended_artifact_paths": {"source": "other.py"},
        },
    )
    assert wrong["ok"] is True
    assert first_value_source_target(wrong) is None

    workspace = tmp_path / "exact"
    result_proposal = proposal()
    result_proposal["source_delivery"] = {"mode": "workspace_file", "target": "bell.py"}
    result = binding_call(
        workspace,
        {"request_text": request, "connected_assistant_proposal": result_proposal},
    )
    assert result["ok"] is True
    assert first_value_source_target(result) == "bell.py"
    markdown_values = json.dumps(result["review_before_generation"], sort_keys=True)
    assert markdown_values.count("bell.py") == 1
    before = CurrentLoopCoordinator(workspace_root=workspace).store.read()
    stored = before["coordinator"]["review_before_generation"]
    assert stored["displayed_source_target"] == "bell.py"
    confirmed = confirm(workspace, result["prior_result_token"])
    context = confirmed["generation_ready_context"]
    assert context["exact_workspace_target"] == "bell.py"
    assert context["next_permitted_client_native_step"] == "write_exact_workspace_source"
    assert (
        confirmed["current_step_contract"]["permitted_native_action"]["exact_artifact_target"][
            "workspace_relative_path"
        ]
        == "bell.py"
    )


def test_d128_four_envelopes_remain_target_free_and_quiet(tmp_path: Path) -> None:
    variants = (
        {},
        {"intended_artifact_paths": {"source": "invented.py"}},
        {"selected_artifact_paths": ["invented.py"]},
        {
            "intended_artifact_paths": {"source": "invented.py"},
            "selected_artifact_paths": ["selected.py"],
        },
    )
    reviews = []
    for index, target_arguments in enumerate(variants):
        result = binding_call(
            tmp_path / str(index),
            {
                "request_text": EXACT_D128_REQUEST,
                "connected_assistant_proposal": proposal(),
                **target_arguments,
            },
        )
        assert result["ok"] is True
        assert first_value_source_target(result) is None
        assert result["review_before_generation"]["customer_actions"] == list(CUSTOMER_ACTIONS)
        serialized = json.dumps(result, sort_keys=True).casefold()
        assert "activation_acknowledgement" not in serialized
        assert "qcoder is ready" not in serialized
        reviews.append(result["review_before_generation"])
    assert all(value == reviews[0] for value in reviews[1:])


def _run_stdio_server(
    workspace: Path,
    state_root: Path,
    generation: str,
    session: str,
) -> tuple[dict[str, object], subprocess.CompletedProcess[str]]:
    state_root.mkdir(parents=True, exist_ok=True)
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "begin_current_loop",
            "arguments": {
                "request_text": EXACT_D128_REQUEST,
                "connected_assistant_proposal": proposal(),
            },
        },
    }
    process_environment = dict(os.environ)
    process_environment["PYTHONPATH"] = str(ROOT / "src")
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "qcoder",
            "current-loop",
            "--workspace",
            str(workspace),
            "--connection-state-root",
            str(state_root),
            "--connection-generation",
            generation,
            "--connection-session-sha256",
            session,
            "serve-binding-mcp",
        ],
        cwd=ROOT,
        input=json.dumps(message) + "\n",
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
        env=process_environment,
    )
    lines = [line for line in process.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    return json.loads(lines[0]), process


def test_real_stdio_timing_is_externally_consumable_once_and_hidden(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "operator-state"
    generation = "a" * 64
    session = "b" * 64
    response, server = _run_stdio_server(workspace, state_root, generation, session)
    assert server.stderr == ""
    serialized_response = json.dumps(response, sort_keys=True).casefold()
    assert "timing" not in serialized_response
    assert "monotonic" not in serialized_response

    process_environment = dict(os.environ)
    process_environment["PYTHONPATH"] = str(ROOT / "src")
    consumed = subprocess.run(
        [
            sys.executable,
            "-m",
            "qcoder.current_loop_operator_timing",
            "--state-root",
            str(state_root),
            "--setup-generation",
            generation,
            "--session-sha256",
            session,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
        env=process_environment,
    )
    evidence = json.loads(consumed.stdout)["timing_evidence"]
    assert evidence["processing_ns"] >= 0
    assert evidence["return_ns"] >= 0
    assert evidence["total_ns"] == evidence["processing_ns"] + evidence["return_ns"]
    assert evidence["customer_visible"] is False
    assert evidence["model_visible"] is False
    assert evidence["sensitive_payload_included"] is False
    serialized_evidence = json.dumps(evidence, sort_keys=True).casefold()
    for forbidden in (
        EXACT_D128_REQUEST.casefold(),
        "connected_assistant_proposal",
        "review-result-",
        "credential",
        "bell.py",
        "openqasm",
        str(workspace).casefold(),
    ):
        assert forbidden not in serialized_evidence

    second = subprocess.run(
        [
            sys.executable,
            "-m",
            "qcoder.current_loop_operator_timing",
            "--state-root",
            str(state_root),
            "--setup-generation",
            generation,
            "--session-sha256",
            session,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        env=process_environment,
    )
    assert second.returncode == 2
    assert json.loads(second.stdout)["category"] == "operator_timing_evidence_not_found"


def test_stdio_timing_rejects_cross_session_and_stale_then_cleans_up(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "operator-state"
    generation = "c" * 64
    session = "d" * 64
    _run_stdio_server(workspace, state_root, generation, session)
    with pytest.raises(OperatorTimingEvidenceError, match="cross_session"):
        consume_stdio_operator_timing(
            state_root=state_root,
            setup_generation=generation,
            session_sha256="e" * 64,
        )
    time.sleep(0.01)
    with pytest.raises(OperatorTimingEvidenceError, match="stale"):
        consume_stdio_operator_timing(
            state_root=state_root,
            setup_generation=generation,
            session_sha256=session,
            maximum_age_seconds=0.001,
        )
    clear_stdio_operator_timing(state_root=state_root)
    with pytest.raises(OperatorTimingEvidenceError, match="not_found"):
        consume_stdio_operator_timing(
            state_root=state_root,
            setup_generation=generation,
            session_sha256=session,
        )


def test_d130_contract_identity_and_inventory_are_exact() -> None:
    descriptor = binding_tool_descriptors()[0]
    review_contract = descriptor["x-qcoder-review-before-generation"]
    assert review_contract["transaction_kind_bound_before_target_discard"] is True
    assert review_contract["request_path_presence_is_anti_invention_only"] is True
    assert review_contract["free_form_delivery_language_interpreted_by_qcoder"] is False
    assert review_contract["post_confirmation_write_target_displayed_before_confirmation"] is True
    assert review_contract["target_free_review_remains_target_free_after_confirmation"] is True
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v57"
    assert CLIENT_BINDING_SCHEMA_VERSION == 56
    assert __version__ == "0.6.0a24.post0.dev7+review.confirmed.delivery.v1"
    assert Version(__version__) > Version("0.6.0a24.post0.dev3+review.before.generation.v1")
    assert len(EXPECTED_TOOLS) == 12
    assert [item["name"] for item in binding_tool_descriptors()] == [
        "begin_current_loop",
        "complete_current_step",
    ]
