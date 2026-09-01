from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from packaging.version import Version
import pytest

from qcoder import __version__
from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    CLIENT_BINDING_SCHEMA_VERSION,
    EXPECTED_TOOLS,
    build_client_binding_descriptor,
)
import qcoder.current_loop_binding_mcp as binding_mcp
from qcoder.current_loop_binding_mcp import (
    _request_source_target_directive_diagnostics,
    _resolve_request_source_target_authority,
    binding_tool_descriptors,
    handle_binding_jsonrpc_message,
)
from qcoder.current_loop_coordinator import CurrentLoopCoordinator


ROOT = Path(__file__).parents[1]
BELL_FIXTURE = ROOT / "src/qcoder/model_packs/wi0440_bell_review_before_generation_v1.json"
ACTIVATION = "Use qCoder to review a Qiskit source plan before generation. "
PROHIBITIONS = (
    "I prefer not to create bell.py; return source inline after confirmation.",
    "Avoid creating bell.py; show source inline after confirmation.",
    "Refrain from writing bell.py; show source inline after confirmation.",
)
TARGET_FREE_ENVELOPES = (
    {},
    {"intended_artifact_paths": {"source": "bell.py"}},
    {"selected_artifact_paths": ["bell.py"]},
    {
        "intended_artifact_paths": {"source": "bell.py"},
        "selected_artifact_paths": ["bell.py"],
    },
)


def proposal(*, transaction_kind: str = "review_before_source_generation") -> dict[str, object]:
    value = json.loads(BELL_FIXTURE.read_text(encoding="utf-8"))
    value["transaction_kind"] = transaction_kind
    value["customer_constraints"] = []
    return value


def activated(fragment: str) -> str:
    return ACTIVATION + fragment


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


def source_target(result: dict[str, object]) -> str | None:
    review = result["review_before_generation"]
    values = [
        item["value"]
        for group in review["initial_decision_groups"]
        for item in group["items"]
        if item["label"] == "Source target"
    ]
    assert len(values) <= 1
    return values[0] if values else None


def confirm(workspace: Path, token: object) -> dict[str, object]:
    assert isinstance(token, str)
    return binding_call(
        workspace,
        {"review_action": "Use recommended choices", "prior_result_token": token},
    )


def assert_target_free_confirmation(workspace: Path, result: dict[str, object]) -> None:
    assert result["ok"] is True
    assert source_target(result) is None
    serialized = json.dumps(result, sort_keys=True).casefold()
    assert "write_exact_workspace_source" not in serialized
    confirmed = confirm(workspace, result["prior_result_token"])
    context = confirmed["generation_ready_context"]
    assert context["category"] == "confirmed_plan_generation_ready_inline_source"
    assert context["exact_workspace_target"] is None
    assert context["next_permitted_client_native_step"] == "produce_inline_source"
    assert "current_step_contract" not in confirmed
    assert confirmed["execution_authority"] == "not_requested"


@pytest.mark.parametrize("fragment", PROHIBITIONS)
@pytest.mark.parametrize("envelope", TARGET_FREE_ENVELOPES)
def test_exact_d132_prohibitions_converge_target_free_for_all_envelopes(
    tmp_path: Path, fragment: str, envelope: dict[str, object]
) -> None:
    workspace = tmp_path / sha256((fragment + repr(envelope)).encode()).hexdigest()[:12]
    result = binding_call(
        workspace,
        {
            "request_text": activated(fragment),
            "connected_assistant_proposal": proposal(),
            **deepcopy(envelope),
        },
    )
    assert_target_free_confirmation(workspace, result)
    state = CurrentLoopCoordinator(workspace_root=workspace).store.read()["coordinator"]
    stored = state["review_before_generation"]
    assert stored["displayed_source_target"] is None
    assert stored["intended_artifact_targets"] == {}


@pytest.mark.parametrize(
    "fragment",
    (
        "Do not create bell.py; show source inline.",
        "Do not write bell.py; return source inline.",
        "Never save bell.py; produce source inline.",
        "Please avoid ever creating bell.py; show source inline.",
        "Please refrain from writing bell.py; show source inline.",
        "I would prefer not to create bell.py; show source inline.",
    ),
)
def test_bounded_prohibition_grammar_is_not_three_exact_strings(
    tmp_path: Path, fragment: str
) -> None:
    result = binding_call(
        tmp_path,
        {
            "request_text": activated(fragment),
            "connected_assistant_proposal": proposal(),
            "intended_artifact_paths": {"source": "bell.py"},
        },
    )
    assert_target_free_confirmation(tmp_path, result)


@pytest.mark.parametrize(
    ("fragment", "expected_states", "expected_targets"),
    (
        (
            "The example filename is bell.py; generate source in bell.py.",
            ["non_authoritative", "affirmative"],
            ["bell.py", "bell.py"],
        ),
        (
            "The example filename is draft.py, but generate source in bell.py.",
            ["non_authoritative", "affirmative"],
            ["draft.py", "bell.py"],
        ),
        (
            "Use `draft.py` only as an example, then generate source in bell.py.",
            ["non_authoritative", "affirmative"],
            ["draft.py", "bell.py"],
        ),
        (
            'The sample is "bell.py"; save the source to bell.py.',
            ["non_authoritative", "affirmative"],
            ["bell.py", "bell.py"],
        ),
        (
            "Do not create bell.py; create bell.py after confirmation.",
            ["non_authoritative", "affirmative"],
            ["bell.py", "bell.py"],
        ),
        (
            "Compare draft.py with an earlier output; create bell.py.",
            ["non_authoritative", "affirmative"],
            ["draft.py", "bell.py"],
        ),
    ),
)
def test_prior_nonauthoritative_unit_does_not_poison_later_affirmative_unit(
    tmp_path: Path,
    fragment: str,
    expected_states: list[str],
    expected_targets: list[str],
) -> None:
    request = activated(fragment)
    diagnostics = _request_source_target_directive_diagnostics(request)
    assert [item["state"] for item in diagnostics] == expected_states
    assert [item["target"] for item in diagnostics] == expected_targets
    missing = binding_call(
        tmp_path / "missing",
        {"request_text": request, "connected_assistant_proposal": proposal()},
    )
    assert missing["category"] == "review_source_target_required"
    accepted_workspace = tmp_path / "accepted"
    accepted = binding_call(
        accepted_workspace,
        {
            "request_text": request,
            "connected_assistant_proposal": proposal(),
            "intended_artifact_paths": {"source": "bell.py"},
        },
    )
    assert accepted["ok"] is True
    assert source_target(accepted) == "bell.py"
    confirmed = confirm(accepted_workspace, accepted["prior_result_token"])
    assert confirmed["generation_ready_context"]["exact_workspace_target"] == "bell.py"
    assert confirmed["execution_authority"] == "not_requested"


@pytest.mark.parametrize(
    "fragment",
    (
        "Save as bell.py or show the source inline.",
        "Show source inline or save as bell.py.",
        "Generate source inline, then create bell.py.",
        "Create bell.py, then show source inline.",
    ),
)
@pytest.mark.parametrize("envelope", TARGET_FREE_ENVELOPES)
def test_output_mode_conflicts_are_order_independent_for_all_envelopes(
    tmp_path: Path, fragment: str, envelope: dict[str, object]
) -> None:
    result = binding_call(
        tmp_path,
        {
            "request_text": activated(fragment),
            "connected_assistant_proposal": proposal(),
            **deepcopy(envelope),
        },
    )
    assert result["ok"] is False
    assert result["category"] == "review_source_target_authority_ambiguous"
    assert result["state_mutated"] is False
    assert not (tmp_path / ".qcoder/current-loop/state.json").exists()


def test_explicit_file_to_inline_replacement_is_target_free(tmp_path: Path) -> None:
    request = activated("Save as bell.py — actually, show it inline instead.")
    diagnostics = _request_source_target_directive_diagnostics(request)
    assert diagnostics[-1]["state"] == "non_authoritative"
    assert diagnostics[-1]["reason"] == "superseded_by_explicit_correction"
    for index, envelope in enumerate(TARGET_FREE_ENVELOPES):
        workspace = tmp_path / str(index)
        result = binding_call(
            workspace,
            {
                "request_text": request,
                "connected_assistant_proposal": proposal(),
                **deepcopy(envelope),
            },
        )
        assert_target_free_confirmation(workspace, result)


def test_explicit_inline_to_file_replacement_is_strict(tmp_path: Path) -> None:
    request = activated("Show it inline — actually, save it as bell.py instead.")
    missing = binding_call(
        tmp_path / "missing",
        {"request_text": request, "connected_assistant_proposal": proposal()},
    )
    assert missing["category"] == "review_source_target_required"
    accepted = binding_call(
        tmp_path / "accepted",
        {
            "request_text": request,
            "connected_assistant_proposal": proposal(),
            "intended_artifact_paths": {"source": "bell.py"},
        },
    )
    assert accepted["ok"] is True
    assert source_target(accepted) == "bell.py"


@pytest.mark.parametrize(
    "fragment",
    (
        "Create bell.py.",
        "Write the source to bell.py.",
        "Save the program as bell.py.",
        "Generate source in bell.py.",
        "Put the generated source in bell.py.",
        "Output the generated source to bell.py.",
        "Store the generated source in bell.py.",
    ),
)
def test_clear_positive_placement_verbs_bind_only_exact_target(
    tmp_path: Path, fragment: str
) -> None:
    request = activated(fragment)
    resolution = _resolve_request_source_target_authority(request)
    assert resolution.state == "affirmative"
    assert resolution.affirmative_targets == ("bell.py",)
    missing = binding_call(
        tmp_path / "missing",
        {"request_text": request, "connected_assistant_proposal": proposal()},
    )
    assert missing["category"] == "review_source_target_required"
    wrong = binding_call(
        tmp_path / "wrong",
        {
            "request_text": request,
            "connected_assistant_proposal": proposal(),
            "intended_artifact_paths": {"source": "draft.py"},
        },
    )
    assert wrong["category"] == "review_source_target_not_named_by_customer"
    accepted = binding_call(
        tmp_path / "accepted",
        {
            "request_text": request,
            "connected_assistant_proposal": proposal(),
            "intended_artifact_paths": {"source": "bell.py"},
        },
    )
    assert source_target(accepted) == "bell.py"


@pytest.mark.parametrize(
    "fragment",
    (
        "Route the generated source toward bell.py.",
        "Associate the generated source with bell.py.",
        "Let bell.py receive the generated source.",
    ),
)
@pytest.mark.parametrize("envelope", TARGET_FREE_ENVELOPES)
def test_unknown_target_bearing_directives_fail_to_ambiguity_for_all_envelopes(
    tmp_path: Path, fragment: str, envelope: dict[str, object]
) -> None:
    result = binding_call(
        tmp_path,
        {
            "request_text": activated(fragment),
            "connected_assistant_proposal": proposal(),
            **deepcopy(envelope),
        },
    )
    assert result["category"] == "review_source_target_authority_ambiguous"
    assert result["state_mutated"] is False


@pytest.mark.parametrize(
    ("fragment", "state", "target"),
    (
        ("Create bell.py rather than draft.py.", "affirmative", "bell.py"),
        ("Show source inline rather than save as bell.py.", "target_free", None),
        ("The example is draft.py; however, create bell.py.", "affirmative", "bell.py"),
        ("Use this destination: create bell.py.", "affirmative", "bell.py"),
        ("Save as bell.py? No, show source inline.", "target_free", None),
    ),
)
def test_bounded_directive_boundaries_and_corrections(
    fragment: str, state: str, target: str | None
) -> None:
    resolution = _resolve_request_source_target_authority(activated(fragment))
    assert resolution.state == state
    assert resolution.affirmative_targets == ((target,) if target else ())


def test_multiple_target_resolution_table(tmp_path: Path) -> None:
    one = activated("The example is draft.py; generate source in bell.py.")
    assert _resolve_request_source_target_authority(one).affirmative_targets == ("bell.py",)
    two = activated("Create bell.py; write source to ghz.py.")
    assert _resolve_request_source_target_authority(two).state == "ambiguous"
    all_non_authoritative = activated(
        "For example, bell.py or ghz.py; show source inline after confirmation."
    )
    assert _resolve_request_source_target_authority(all_non_authoritative).state == "target_free"
    result = binding_call(
        tmp_path,
        {
            "request_text": two,
            "connected_assistant_proposal": proposal(),
            "intended_artifact_paths": {"source": "bell.py"},
        },
    )
    assert result["category"] == "review_source_target_authority_ambiguous"
    assert result["state_mutated"] is False


@pytest.mark.parametrize(
    "fragment",
    (
        PROHIBITIONS[0],
        "Route the generated source toward bell.py.",
        "Save as bell.py or show the source inline.",
    ),
)
def test_no_path_processing_occurs_before_authority_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fragment: str
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("path processing ran before target authority resolution")

    monkeypatch.setattr(binding_mcp, "normalize_selected_artifact_paths", forbidden)
    original_intended = binding_mcp.normalize_intended_artifact_targets

    def intended_none_only(value: object, *args: object, **kwargs: object) -> object:
        assert value is None
        return original_intended(value, *args, **kwargs)

    monkeypatch.setattr(binding_mcp, "normalize_intended_artifact_targets", intended_none_only)
    result = binding_call(
        tmp_path,
        {
            "request_text": activated(fragment),
            "connected_assistant_proposal": proposal(),
            "intended_artifact_paths": {"source": "bell.py"},
            "selected_artifact_paths": ["bell.py"],
        },
    )
    if fragment == PROHIBITIONS[0]:
        assert result["ok"] is True
    else:
        assert result["category"] == "review_source_target_authority_ambiguous"
        assert result["state_mutated"] is False


def test_selected_source_generation_modification_mismatch_remains_strict(tmp_path: Path) -> None:
    request = (
        "Use qCoder to review proposed Qiskit Bell changes to the selected source before "
        "modifying it."
    )
    workspace = tmp_path / "mismatch"
    workspace.mkdir()
    selected = workspace / "selected.py"
    selected.write_text("ORIGINAL\n", encoding="utf-8")
    mismatch = binding_call(
        workspace,
        {
            "request_text": request,
            "connected_assistant_proposal": proposal(),
            "selected_artifact_paths": ["selected.py"],
        },
    )
    assert mismatch["category"] == "review_request_proposal_transaction_kind_mismatch"
    assert mismatch["state_mutated"] is False
    assert selected.read_text(encoding="utf-8") == "ORIGINAL\n"
    correct = proposal(transaction_kind="review_before_source_modification")
    missing = binding_call(
        tmp_path / "missing",
        {"request_text": request, "connected_assistant_proposal": correct},
    )
    assert missing["category"] == "review_source_modification_selection_required"


def test_tristate_diagnostics_are_bounded_ephemeral_and_not_model_visible(tmp_path: Path) -> None:
    request = activated("The example filename is draft.py; generate source in bell.py.")
    diagnostics = _request_source_target_directive_diagnostics(request)
    assert [item["state"] for item in diagnostics] == ["non_authoritative", "affirmative"]
    for item in diagnostics:
        assert set(item) == {
            "target",
            "target_span",
            "directive_unit",
            "directive_span",
            "state",
            "reason",
        }
        assert item["reason"] in {
            "illustrative",
            "bounded_affirmative_source_directive",
        }
    result = binding_call(
        tmp_path,
        {
            "request_text": request,
            "connected_assistant_proposal": proposal(),
            "intended_artifact_paths": {"source": "bell.py"},
        },
    )
    serialized = json.dumps(result, sort_keys=True)
    for forbidden in (
        "directive_span",
        "directive_unit",
        "bounded_affirmative_source_directive",
        "illustrative",
    ):
        assert forbidden not in serialized


def test_dev6_v56_descriptor_identity_and_inventory() -> None:
    descriptor = build_client_binding_descriptor(coordinator_prefix=["qcoder"])[
        "client_binding_contract"
    ]
    canonical = json.dumps(
        descriptor, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert descriptor["contract_id"] == "qcoder.connected_assistant.client_binding.v56"
    assert descriptor["schema_version"] == 55
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v56"
    assert CLIENT_BINDING_SCHEMA_VERSION == 55
    assert len(canonical) == 238_216
    assert sha256(canonical).hexdigest() == (
        "df61ba96f2bf440f019261d7b38961c7d3b5cdb87f8607082b1688b2190db5ce"
    )
    assert __version__ == "0.6.0a24.post0.dev6+review.before.generation.v4"
    assert Version(__version__) > Version("0.6.0a24.post0.dev5+review.before.generation.v3")
    assert len(EXPECTED_TOOLS) == 12
    assert [item["name"] for item in binding_tool_descriptors()] == [
        "begin_current_loop",
        "complete_current_step",
    ]
    contract = binding_tool_descriptors()[0]["x-qcoder-review-before-generation"]
    assert contract["target_authority_directive_units_ordered_and_local"] is True
    assert contract["target_authority_states"] == [
        "affirmative",
        "non_authoritative",
        "unresolved",
    ]
    assert contract["assistant_target_fields_resolve_customer_ambiguity"] is False
