from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

import qcoder.context_bridge_mcp as context_bridge_mcp
import qcoder.current_loop_binding_mcp as binding_mcp
from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    CLIENT_BINDING_SCHEMA_VERSION,
    EXPECTED_TOOLS,
    build_client_binding_descriptor,
)
from qcoder.current_loop_binding_mcp import (
    binding_tool_descriptors,
    consume_last_binding_timing,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator
from qcoder.review_before_generation import (
    CUSTOMER_ACTIONS,
    PROPOSAL_SCHEMA_ID,
    build_first_value,
    canonical_json,
    render_first_value_markdown,
)


EXACT_REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a Φ+ Bell state. "
    "Before generating the code, help me review how you interpret my request and the important "
    "implementation choices."
)
ROOT = Path(__file__).parents[1]
BELL_FIXTURE = ROOT / "src/qcoder/model_packs/wi0440_bell_review_before_generation_v1.json"
MATRIX_FIXTURE = (
    ROOT / "src/qcoder/model_packs/wi0440_review_before_generation_class_matrix_v1.json"
)


def proposal_for(algorithm: str = "Bell") -> dict[str, object]:
    proposal = json.loads(BELL_FIXTURE.read_text(encoding="utf-8"))
    if algorithm == "Bell":
        return proposal
    profile = json.loads(MATRIX_FIXTURE.read_text(encoding="utf-8"))["profiles"][algorithm]
    proposal["customer_constraints"] = []
    proposal["recommended_interpretation"] = profile["recommended_interpretation"]
    proposal["implementation_recommendations"] = [
        "Use Qiskit QuantumCircuit.",
        profile["quantum_scope"],
        profile["construction"],
        profile["measurement_mapping"],
        profile["output_structure"],
    ]
    proposal["output_artifact"] = profile["intended_artifact"]
    for index, key in ((1, "construction"), (2, "measurement_mapping"), (3, "output_structure")):
        proposal["material_choices"][index]["recommendation"] = profile[key]
    return proposal


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


def _without_token(value: dict[str, object]) -> dict[str, object]:
    result = deepcopy(value)
    result.pop("prior_result_token", None)
    return result


TARGET_VARIANTS = (
    pytest.param({}, id="clean"),
    pytest.param(
        {"intended_artifact_paths": {"source": "invented/bell.py"}},
        id="invented-intended",
    ),
    pytest.param({"selected_artifact_paths": ["invented/bell.py"]}, id="invented-selected"),
    pytest.param(
        {
            "intended_artifact_paths": {"source": "invented/intended.py"},
            "selected_artifact_paths": ["invented/selected.py"],
        },
        id="both-invented",
    ),
)


@pytest.mark.parametrize("target_arguments", TARGET_VARIANTS)
def test_exact_d128_request_converges_in_one_operation_without_target_authority(
    tmp_path: Path, target_arguments: dict[str, object]
) -> None:
    result = binding_call(
        tmp_path,
        {
            "request_text": EXACT_REQUEST,
            "connected_assistant_proposal": proposal_for(),
            **target_arguments,
        },
    )
    assert result["ok"] is True
    assert set(result) == {
        "ok",
        "review_before_generation",
        "prior_result_token",
        "generation_authority",
        "execution_authority",
        "source_or_qasm_created",
        "file_mutation_performed",
        "execution_performed",
        "protected_service_called",
    }
    assert result["review_before_generation"]["customer_actions"] == list(CUSTOMER_ACTIONS)
    assert result["generation_authority"] == "held_for_exact_review_confirmation"
    assert result["execution_authority"] == "not_requested"
    assert all(
        result[key] is False
        for key in (
            "source_or_qasm_created",
            "file_mutation_performed",
            "execution_performed",
            "protected_service_called",
        )
    )
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    review = state["coordinator"]["review_before_generation"]
    assert review["intended_artifact_targets"] == {}
    assert review["selected_artifact_identity_sha256"] == []
    serialized = json.dumps({"result": result, "state": state}, ensure_ascii=False, sort_keys=True)
    assert "invented/" not in serialized
    assert not (tmp_path / "invented").exists()


def test_all_four_exact_envelopes_have_identical_semantics_and_projection(tmp_path: Path) -> None:
    results: list[dict[str, object]] = []
    revisions: list[str] = []
    for index, parameters in enumerate(TARGET_VARIANTS):
        target_arguments = parameters.values[0]
        workspace = tmp_path / str(index)
        results.append(
            binding_call(
                workspace,
                {
                    "request_text": EXACT_REQUEST,
                    "connected_assistant_proposal": proposal_for(),
                    **target_arguments,
                },
            )
        )
        state = CurrentLoopCoordinator(workspace_root=workspace).store.read()
        revisions.append(state["coordinator"]["review_before_generation"]["review_revision"])
    assert all(_without_token(item) == _without_token(results[0]) for item in results[1:])
    assert len(set(revisions)) == 1


def test_irrelevant_targets_are_discarded_before_path_normalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = binding_mcp.normalize_intended_artifact_targets

    def reject_selected(*args: object, **kwargs: object) -> list[object]:
        raise AssertionError("selected target normalizer must not receive an irrelevant target")

    def observe_intended(value: object, **kwargs: object) -> object:
        assert value is None
        return original(value, **kwargs)

    monkeypatch.setattr(binding_mcp, "normalize_selected_artifact_paths", reject_selected)
    monkeypatch.setattr(binding_mcp, "normalize_intended_artifact_targets", observe_intended)
    result = binding_call(
        tmp_path,
        {
            "request_text": EXACT_REQUEST,
            "connected_assistant_proposal": proposal_for(),
            "intended_artifact_paths": {"source": "never/inspect.py"},
            "selected_artifact_paths": ["never/read.py"],
        },
    )
    assert result["ok"] is True


@pytest.mark.parametrize(
    "request_text",
    [
        "Use qCoder to review how you interpret my request before writing code.",
        "Use qCoder to help me decide implementation choices before generating source.",
        "Use qCoder to discuss the plan first, then wait for confirmation.",
        "Use qCoder to review the proposed Qiskit approach before creating the program.",
    ],
)
def test_review_class_paraphrases_converge_with_irrelevant_host_target(
    tmp_path: Path, request_text: str
) -> None:
    clean = binding_call(
        tmp_path / "clean",
        {"request_text": request_text, "connected_assistant_proposal": proposal_for()},
    )
    host_variant = binding_call(
        tmp_path / "host",
        {
            "request_text": request_text,
            "connected_assistant_proposal": proposal_for(),
            "intended_artifact_paths": {"source": "host-invented.py"},
        },
    )
    assert _without_token(host_variant) == _without_token(clean)


def test_material_source_modification_selection_remains_strict(tmp_path: Path) -> None:
    request = "Use qCoder to review proposed changes to selected.py before modifying source."
    proposal = proposal_for()
    proposal["customer_constraints"] = []
    proposal["transaction_kind"] = "review_before_source_modification"
    proposal["source_delivery"] = {"mode": "workspace_file", "target": "selected.py"}
    missing = binding_call(
        tmp_path / "missing",
        {"request_text": request, "connected_assistant_proposal": proposal},
    )
    assert missing["ok"] is False
    assert "selection_required" in str(missing["category"])

    workspace = tmp_path / "selected"
    workspace.mkdir()
    (workspace / "selected.py").write_text("ORIGINAL\n", encoding="utf-8")
    selected = binding_call(
        workspace,
        {
            "request_text": request,
            "connected_assistant_proposal": proposal,
            "selected_artifact_paths": ["selected.py"],
        },
    )
    assert selected["ok"] is True
    state = CurrentLoopCoordinator(workspace_root=workspace).store.read()
    review = state["coordinator"]["review_before_generation"]
    assert review["intended_artifact_targets"] == {}
    assert review["displayed_source_target"] == "selected.py"
    assert (workspace / "selected.py").read_text(encoding="utf-8") == "ORIGINAL\n"


def test_exact_customer_named_target_and_direct_generation_remain_strict(tmp_path: Path) -> None:
    request = "Use qCoder to review the plan before generating source in exact-bell.py."
    proposal = proposal_for()
    proposal["customer_constraints"] = []
    inline = binding_call(
        tmp_path / "review-missing",
        {"request_text": request, "connected_assistant_proposal": proposal},
    )
    assert inline["ok"] is True
    proposal["source_delivery"] = {"mode": "workspace_file", "target": "exact-bell.py"}
    exact = binding_call(
        tmp_path / "review-exact",
        {
            "request_text": request,
            "connected_assistant_proposal": proposal,
        },
    )
    assert exact["ok"] is True
    direct = binding_call(
        tmp_path / "direct",
        {
            "request_text": "Use qCoder to create a small Qiskit program in direct.py now.",
            "intended_artifact_paths": {"source": "direct.py"},
        },
    )
    assert direct["ok"] is True
    assert "review_before_generation" not in direct


def test_descriptor_and_full_compact_instructions_are_branch_consistent() -> None:
    descriptor = binding_tool_descriptors()[0]
    review_example = descriptor["x-qcoder-review-before-generation-happy-path"]
    assert set(review_example) == {"request_text", "connected_assistant_proposal"}
    assert "intended_artifact_paths" in descriptor["x-qcoder-direct-generation-happy-path"]
    assert "selected_artifact_paths" in descriptor["x-qcoder-selected-file-workflow-happy-path"]
    description = descriptor["description"]
    assert "source_delivery recommendation" in description
    assert "prevents invention" in description
    assert "first authority for source delivery and workspace write" in description
    full = context_bridge_mcp.CLIENT_ACTIVATION_INSTRUCTIONS
    compact = context_bridge_mcp._compact_client_activation_instructions()
    for instructions in (full, compact):
        assert "review before generation" in instructions.casefold()
        assert "anti-invention" in instructions.casefold()
        assert "direct generation" in instructions.casefold()
        assert "selected-file" in instructions.casefold()
        assert "active-loop" in instructions.casefold()
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v57"
    assert CLIENT_BINDING_SCHEMA_VERSION == 56
    assert PROPOSAL_SCHEMA_ID.endswith(".v3")
    assert len(EXPECTED_TOOLS) == 12
    assert [item["name"] for item in binding_tool_descriptors()] == [
        "begin_current_loop",
        "complete_current_step",
    ]


def test_success_result_contains_no_qcoder_readiness_or_procedure_narration(tmp_path: Path) -> None:
    result = binding_call(
        tmp_path,
        {"request_text": EXACT_REQUEST, "connected_assistant_proposal": proposal_for()},
    )
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True).casefold()
    for forbidden in (
        "activation_acknowledgement",
        "qcoder is ready",
        "retry",
        "recovery",
        "route",
        "schema_id",
        "state_revision",
        "review_revision",
        "tool procedure",
    ):
        assert forbidden not in serialized
    assert result["prior_result_token"].startswith("review-result-")
    customer = json.dumps(result["review_before_generation"], ensure_ascii=False)
    assert "review-result-" not in customer


@pytest.mark.parametrize("algorithm", ["Bell", "GHZ"])
def test_compact_review_does_not_duplicate_material_choice_inventory(algorithm: str) -> None:
    request = (
        EXACT_REQUEST
        if algorithm == "Bell"
        else "Use qCoder to review a concrete GHZ Qiskit construction before generating source."
    )
    first = build_first_value(request, proposal_for(algorithm))
    assert [group["label"] for group in first["initial_decision_groups"]] == [
        "Goal and scope",
        "Implementation",
        "Output and authority",
    ]
    assert first["customer_actions"] == list(CUSTOMER_ACTIONS)
    values = [
        str(item["value"]).casefold().strip().rstrip(".")
        for group in first["initial_decision_groups"]
        for item in group["items"]
    ]
    assert len(values) == len(set(values))
    assert all(
        not str(item["label"]).startswith("Material choice:")
        for group in first["initial_decision_groups"]
        for item in group["items"]
    )
    markdown = render_first_value_markdown(first)
    assert [line for line in markdown.splitlines() if line.startswith("## ")] == [
        "## Goal and scope",
        "## Implementation",
        "## Output and authority",
    ]


def test_non_bell_compact_review_matches_deterministic_ghz_golden() -> None:
    request = "Use qCoder to review a concrete GHZ Qiskit construction before generating source."
    first = build_first_value(request, proposal_for("GHZ"))
    golden_dir = ROOT / "tests/fixtures/wi0440_review_before_generation_v1/goldens"
    assert (
        canonical_json(first).encode("utf-8") == (golden_dir / "ghz-first-value.json").read_bytes()
    )
    assert (
        render_first_value_markdown(first).encode("utf-8")
        == (golden_dir / "ghz-first-value.md").read_bytes()
    )


def test_simulated_host_transcript_has_one_qcoder_operation_and_no_retry(tmp_path: Path) -> None:
    transcript: list[dict[str, object]] = [{"role": "customer", "text": EXACT_REQUEST}]
    result = binding_call(
        tmp_path,
        {
            "request_text": EXACT_REQUEST,
            "connected_assistant_proposal": proposal_for(),
            "intended_artifact_paths": {"source": "host-guessed.py"},
        },
    )
    transcript.append({"role": "qcoder", "operation": "begin_current_loop", "result": result})
    transcript.append(
        {"role": "assistant", "review": result["review_before_generation"], "source": None}
    )
    assert sum(item.get("operation") == "begin_current_loop" for item in transcript) == 1
    serialized = json.dumps(transcript, ensure_ascii=False, sort_keys=True).casefold()
    assert "host-guessed.py" not in serialized
    assert "retry" not in serialized
    assert "recovery" not in serialized
    assert "activation_acknowledgement" not in serialized
    assert "openqasm" not in serialized


def test_local_timing_is_process_and_discard_and_not_projected(tmp_path: Path) -> None:
    result = binding_call(
        tmp_path,
        {"request_text": EXACT_REQUEST, "connected_assistant_proposal": proposal_for()},
    )
    timing = consume_last_binding_timing()
    assert timing is not None
    assert timing["process_and_discard"] is True
    assert timing["customer_visible"] is False
    assert (
        timing["operation_entry_monotonic_seconds"]
        <= timing["processing_complete_monotonic_seconds"]
    )
    assert (
        timing["processing_complete_monotonic_seconds"]
        <= timing["result_return_boundary_monotonic_seconds"]
    )
    assert timing["total_qcoder_local_seconds"] >= timing["processing_seconds"] >= 0
    assert consume_last_binding_timing() is None
    serialized = json.dumps(result, sort_keys=True)
    assert "timing" not in serialized
    assert "monotonic" not in serialized


def test_generated_descriptor_identity_is_deterministic() -> None:
    first = build_client_binding_descriptor(coordinator_prefix=["qcoder"])[
        "client_binding_contract"
    ]
    second = build_client_binding_descriptor(coordinator_prefix=["qcoder"])[
        "client_binding_contract"
    ]
    first_bytes = json.dumps(first, sort_keys=True, separators=(",", ":")).encode("utf-8")
    second_bytes = json.dumps(second, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert first_bytes == second_bytes
    assert sha256(first_bytes).hexdigest()
    development = json.loads((ROOT / "development-version.json").read_text(encoding="utf-8"))
    assert development["binding"] == CLIENT_BINDING_CONTRACT_ID
    assert development["binding_schema"] == CLIENT_BINDING_SCHEMA_VERSION
