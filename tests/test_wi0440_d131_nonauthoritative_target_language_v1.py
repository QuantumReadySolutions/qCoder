from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from packaging.version import Version
import pytest

pytestmark = pytest.mark.skip(
    reason=(
        "D-133 supersedes free-form review target-authority inference; orthogonal safety, "
        "confirmation, timing, descriptor, and inventory invariants are retained in D-133 and "
        "their original focused suites."
    )
)

from qcoder import __version__
from qcoder.context_bridge_mcp import (
    CLIENT_BINDING_CONTRACT_ID,
    CLIENT_BINDING_SCHEMA_VERSION,
    EXPECTED_TOOLS,
    build_client_binding_descriptor,
)
import qcoder.current_loop_binding_mcp as binding_mcp
from qcoder.current_loop_binding_mcp import binding_tool_descriptors, handle_binding_jsonrpc_message
from qcoder.current_loop_coordinator import CurrentLoopCoordinator


ROOT = Path(__file__).parents[1]
BELL_FIXTURE = ROOT / "src/qcoder/model_packs/wi0440_bell_review_before_generation_v1.json"
ACTIVATION_PREFIX = "Use qCoder to review a Qiskit Bell plan before generating source. "
EXACT_D131_REQUESTS = (
    "The filename 'bell.py' is only an example; show source inline after confirmation.",
    "The filename `bell.py` is only an example; show source inline after confirmation.",
    "The filename bell.py is only an example; show source inline after confirmation.",
    "Save as bell.py only for comparison; show source inline after confirmation.",
    "Save it as bell.py? No, show source inline after confirmation.",
)
IRRELEVANT_ENVELOPES = (
    {},
    {"intended_artifact_paths": {"source": "bell.py"}},
    {"selected_artifact_paths": ["invented.py"]},
    {
        "intended_artifact_paths": {"source": "bell.py"},
        "selected_artifact_paths": ["invented.py"],
    },
)


def proposal(*, transaction_kind: str = "review_before_source_generation") -> dict[str, object]:
    value = json.loads(BELL_FIXTURE.read_text(encoding="utf-8"))
    value["transaction_kind"] = transaction_kind
    value["customer_constraints"] = []
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


def source_target(result: dict[str, object]) -> str | None:
    review = result["review_before_generation"]
    assert isinstance(review, dict)
    values = [
        item["value"]
        for group in review["initial_decision_groups"]
        for item in group["items"]
        if item["label"] == "Source target"
    ]
    assert len(values) <= 1
    return values[0] if values else None


def confirmation(workspace: Path, token: object) -> dict[str, object]:
    assert isinstance(token, str)
    return binding_call(
        workspace,
        {"review_action": "Use recommended choices", "prior_result_token": token},
    )


def activated(fragment: str) -> str:
    return ACTIVATION_PREFIX + fragment


@pytest.mark.parametrize("exact_reproduction", EXACT_D131_REQUESTS)
def test_exact_d131_reproductions_converge_across_all_four_envelopes(
    tmp_path: Path, exact_reproduction: str
) -> None:
    reviews: list[dict[str, object]] = []
    revisions: list[str] = []
    request = activated(exact_reproduction)
    for index, target_arguments in enumerate(IRRELEVANT_ENVELOPES):
        workspace = tmp_path / str(index)
        result = binding_call(
            workspace,
            {
                "request_text": request,
                "connected_assistant_proposal": proposal(),
                **deepcopy(target_arguments),
            },
        )
        assert result["ok"] is True
        assert source_target(result) is None
        serialized = json.dumps(result, sort_keys=True).casefold()
        for forbidden in ("invented.py", "source target", "retry", "recovery"):
            assert forbidden not in serialized
        state = CurrentLoopCoordinator(workspace_root=workspace).store.read()
        stored = state["coordinator"]["review_before_generation"]
        assert stored["displayed_source_target"] is None
        assert stored["intended_artifact_targets"] == {}
        reviews.append(deepcopy(result["review_before_generation"]))
        revisions.append(stored["review_revision"])

        confirmed = confirmation(workspace, result["prior_result_token"])
        context = confirmed["generation_ready_context"]
        assert context["category"] == "confirmed_plan_generation_ready_inline_source"
        assert context["exact_workspace_target"] is None
        assert context["next_permitted_client_native_step"] == "produce_inline_source"
        assert "current_step_contract" not in confirmed
        assert confirmed["execution_authority"] == "not_requested"

    assert all(item == reviews[0] for item in reviews[1:])
    assert len(set(revisions)) == 1


@pytest.mark.parametrize(
    "fragment",
    (
        'The filename "bell.py" is only an example; show source inline.',
        "The filename 'bell.py' is only an example; show source inline.",
        "The filename “bell.py” is only an example; show source inline.",
        "The filename ‘bell.py’ is only an example; show source inline.",
        "The filename `bell.py` is only an example; show source inline.",
        "The filename ``bell.py`` is only an example; show source inline.",
        "For example, bell.py; show source inline.",
        "A possible filename is bell.py, but show source inline.",
        "Do not create bell.py; show source inline.",
        "bell.py is only an example; show source inline.",
        "Save as bell.py only for comparison; show source inline.",
        "bell.py might be a possible name; show source inline.",
        "bell.py? No, show source inline.",
        "Maybe use bell.py, but show the source inline.",
        "Could the file be bell.py? Show source inline instead.",
        "If a file were needed, bell.py would be an example.",
        "Compare bell.py with ghz.py, but show source inline.",
        "bell.py versus ghz.py; do not create either file.",
        "Do not use bell.py; generate inline instead.",
        "For example, bell.py or ghz.py; show source inline.",
        "Compare bell.py and ghz.py; create neither.",
        "THE FILENAME Bell.PY IS ONLY AN EXAMPLE; SHOW SOURCE INLINE.",
        "For illustration—bell.py—show source inline instead.",
    ),
)
def test_quote_example_comparison_hypothetical_and_rejection_are_target_free(
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
    assert result["ok"] is True
    assert source_target(result) is None
    state = CurrentLoopCoordinator(workspace_root=tmp_path).store.read()
    stored = state["coordinator"]["review_before_generation"]
    assert stored["displayed_source_target"] is None
    assert stored["intended_artifact_targets"] == {}


def test_irrelevant_paths_are_discarded_before_normalization_or_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_intended = binding_mcp.normalize_intended_artifact_targets

    def selected_must_not_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("irrelevant selected path reached normalization")

    def intended_receives_no_path(value: object, *args: object, **kwargs: object) -> object:
        assert value is None
        return original_intended(value, *args, **kwargs)

    monkeypatch.setattr(binding_mcp, "normalize_selected_artifact_paths", selected_must_not_run)
    monkeypatch.setattr(
        binding_mcp, "normalize_intended_artifact_targets", intended_receives_no_path
    )
    result = binding_call(
        tmp_path,
        {
            "request_text": activated(EXACT_D131_REQUESTS[0]),
            "connected_assistant_proposal": proposal(),
            "intended_artifact_paths": {"source": "bell.py"},
            "selected_artifact_paths": ["invented.py"],
        },
    )
    assert result["ok"] is True
    assert source_target(result) is None


@pytest.mark.parametrize(
    "fragment",
    (
        "Save as bell.py or show the source inline.",
        "Create bell.py and create ghz.py after confirmation.",
        "Create bell.py and ghz.py after confirmation.",
    ),
)
def test_unresolved_or_multiple_affirmative_targets_clarify_without_mutation(
    tmp_path: Path, fragment: str
) -> None:
    result = binding_call(
        tmp_path,
        {"request_text": activated(fragment), "connected_assistant_proposal": proposal()},
    )
    assert result["ok"] is False
    assert result["category"] == "review_source_target_authority_ambiguous"
    assert result["state_mutated"] is False
    assert not (tmp_path / ".qcoder" / "current-loop" / "state.json").exists()


def test_one_affirmative_target_excludes_rejected_or_example_alternatives(tmp_path: Path) -> None:
    requests = (
        "Create bell.py; do not create draft.py.",
        "The example name is draft.py; generate source in bell.py.",
        "The example is `draft.py`; generate the source in bell.py.",
    )
    for index, fragment in enumerate(requests):
        workspace = tmp_path / str(index)
        result = binding_call(
            workspace,
            {
                "request_text": activated(fragment),
                "connected_assistant_proposal": proposal(),
                "intended_artifact_paths": {"source": "bell.py"},
            },
        )
        assert result["ok"] is True
        assert source_target(result) == "bell.py"
        wrong = binding_call(
            tmp_path / f"wrong-{index}",
            {
                "request_text": activated(fragment),
                "connected_assistant_proposal": proposal(),
                "intended_artifact_paths": {"source": "draft.py"},
            },
        )
        assert wrong["category"] == "review_source_target_not_named_by_customer"
        assert wrong["state_mutated"] is False


def test_affirmative_target_is_strict_visible_revision_bound_and_exact_after_confirmation(
    tmp_path: Path,
) -> None:
    request = "Use qCoder to review a Bell plan before generating source in bell.py."
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

    workspace = tmp_path / "exact"
    initial = binding_call(
        workspace,
        {
            "request_text": request,
            "connected_assistant_proposal": proposal(),
            "intended_artifact_paths": {"source": "bell.py"},
        },
    )
    assert source_target(initial) == "bell.py"
    state = CurrentLoopCoordinator(workspace_root=workspace).store.read()
    stored = state["coordinator"]["review_before_generation"]
    assert stored["displayed_source_target"] == "bell.py"
    assert stored["intended_artifact_targets"]["source"]["workspace_relative_path"] == "bell.py"
    confirmed = confirmation(workspace, initial["prior_result_token"])
    assert confirmed["generation_ready_context"]["exact_workspace_target"] == "bell.py"
    assert (
        confirmed["current_step_contract"]["permitted_native_action"]["exact_artifact_target"][
            "workspace_relative_path"
        ]
        == "bell.py"
    )
    assert confirmed["execution_authority"] == "not_requested"


@pytest.mark.parametrize(
    "fragment",
    (
        "The filename 'bell.py' is only an example; show source inline.",
        "The filename bell.py is only an example; show source inline.",
        "Save as bell.py only for comparison; show source inline.",
        "Save it as bell.py? No, show source inline.",
    ),
)
def test_nonauthoritative_target_cannot_be_inserted_into_stored_inline_review(
    tmp_path: Path, fragment: str
) -> None:
    initial = binding_call(
        tmp_path,
        {
            "request_text": activated(fragment),
            "connected_assistant_proposal": proposal(),
        },
    )
    coordinator_service = CurrentLoopCoordinator(workspace_root=tmp_path)
    state = coordinator_service.store.read()
    coordinator = deepcopy(state["coordinator"])
    coordinator["review_before_generation"]["intended_artifact_targets"] = {
        "source": {"workspace_relative_path": "bell.py"}
    }
    coordinator_service._replace_coordinator(coordinator)
    rejected = confirmation(tmp_path, initial["prior_result_token"])
    assert rejected["ok"] is False
    assert rejected["category"] == "review_confirmation_target_display_binding_invalid"
    after = coordinator_service.store.read()["coordinator"]
    assert after["phase"] == "intent_review"
    assert after["current_step_status"] != "awaiting_external_client_action"


def test_displayed_stored_and_confirmed_target_mutations_fail_closed(tmp_path: Path) -> None:
    request = "Use qCoder to review a Bell plan before generating source in bell.py."
    for mutation in ("stored-display-field", "projected-value"):
        workspace = tmp_path / mutation
        initial = binding_call(
            workspace,
            {
                "request_text": request,
                "connected_assistant_proposal": proposal(),
                "intended_artifact_paths": {"source": "bell.py"},
            },
        )
        coordinator_service = CurrentLoopCoordinator(workspace_root=workspace)
        state = coordinator_service.store.read()
        coordinator = deepcopy(state["coordinator"])
        review = coordinator["review_before_generation"]
        if mutation == "stored-display-field":
            review["displayed_source_target"] = "draft.py"
        else:
            for group in review["first_value"]["initial_decision_groups"]:
                for item in group["items"]:
                    if item["label"] == "Source target":
                        item["value"] = "draft.py"
        coordinator_service._replace_coordinator(coordinator)
        rejected = confirmation(workspace, initial["prior_result_token"])
        assert rejected["ok"] is False
        assert rejected["category"] == "review_confirmation_target_display_binding_invalid"
        assert coordinator_service.store.read()["coordinator"]["phase"] == "intent_review"


def test_selected_source_modification_kind_remains_strict(tmp_path: Path) -> None:
    request = (
        "Use qCoder to review proposed Qiskit Bell changes to the selected source before "
        "modifying it."
    )
    workspace = tmp_path / "mismatch"
    workspace.mkdir()
    (workspace / "selected.py").write_text("ORIGINAL\n", encoding="utf-8")
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
    assert (workspace / "selected.py").read_text(encoding="utf-8") == "ORIGINAL\n"

    correct = proposal(transaction_kind="review_before_source_modification")
    missing = binding_call(
        tmp_path / "missing",
        {"request_text": request, "connected_assistant_proposal": correct},
    )
    assert missing["category"] == "review_source_modification_selection_required"
    accepted_workspace = tmp_path / "accepted"
    accepted_workspace.mkdir()
    (accepted_workspace / "selected.py").write_text("ORIGINAL\n", encoding="utf-8")
    accepted = binding_call(
        accepted_workspace,
        {
            "request_text": request,
            "connected_assistant_proposal": correct,
            "selected_artifact_paths": ["selected.py"],
        },
    )
    assert accepted["ok"] is True
    assert source_target(accepted) == "selected.py"


def test_simulated_host_transcripts_cover_target_language_without_corrective_submission(
    tmp_path: Path,
) -> None:
    target_free_requests = (
        "Use qCoder to review a Bell plan before generating source.",
        (
            "Use qCoder to review a Bell plan before generating source. Do not create bell.py; "
            "show source inline."
        ),
        *(activated(item) for item in EXACT_D131_REQUESTS),
    )
    for index, request in enumerate(target_free_requests):
        workspace = tmp_path / f"target-free-{index}"
        customer_events = [{"role": "customer", "request": request}]
        qcoder_events = [
            binding_call(
                workspace,
                {
                    "request_text": request,
                    "connected_assistant_proposal": proposal(),
                    "intended_artifact_paths": {"source": "invented.py"},
                },
            )
        ]
        assert len(customer_events) == 1
        assert len(qcoder_events) == 1
        assert qcoder_events[0]["ok"] is True
        assert source_target(qcoder_events[0]) is None
        serialized = json.dumps(qcoder_events[0], sort_keys=True).casefold()
        for forbidden in ("qcoder is ready", "retry", "recovery", "invented.py"):
            assert forbidden not in serialized

    mismatch_workspace = tmp_path / "modification-mismatch"
    mismatch_workspace.mkdir()
    (mismatch_workspace / "selected.py").write_text("ORIGINAL\n", encoding="utf-8")
    mismatch = binding_call(
        mismatch_workspace,
        {
            "request_text": (
                "Use qCoder to review proposed Qiskit Bell changes to the selected source before "
                "modifying it."
            ),
            "connected_assistant_proposal": proposal(),
            "selected_artifact_paths": ["selected.py"],
        },
    )
    assert mismatch["category"] == "review_request_proposal_transaction_kind_mismatch"
    assert mismatch["state_mutated"] is False

    ambiguous = binding_call(
        tmp_path / "ambiguous",
        {
            "request_text": activated("Save as bell.py or show the source inline."),
            "connected_assistant_proposal": proposal(),
        },
    )
    assert ambiguous["category"] == "review_source_target_authority_ambiguous"
    assert ambiguous["state_mutated"] is False

    exact_workspace = tmp_path / "exact-target"
    exact = binding_call(
        exact_workspace,
        {
            "request_text": "Use qCoder to review a Bell plan before generating source in bell.py.",
            "connected_assistant_proposal": proposal(),
            "intended_artifact_paths": {"source": "bell.py"},
        },
    )
    exact_confirmed = confirmation(exact_workspace, exact["prior_result_token"])
    assert exact_confirmed["generation_ready_context"]["exact_workspace_target"] == "bell.py"
    assert exact_confirmed["execution_authority"] == "not_requested"


def test_canonical_descriptor_construction_and_dev5_identity_are_exact() -> None:
    descriptor = build_client_binding_descriptor(coordinator_prefix=["qcoder"])[
        "client_binding_contract"
    ]
    canonical = json.dumps(
        descriptor,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert descriptor["contract_id"] == CLIENT_BINDING_CONTRACT_ID
    assert descriptor["schema_version"] == CLIENT_BINDING_SCHEMA_VERSION
    assert CLIENT_BINDING_CONTRACT_ID == "qcoder.connected_assistant.client_binding.v57"
    assert CLIENT_BINDING_SCHEMA_VERSION == 56
    assert len(canonical) == 238_216
    assert sha256(canonical).hexdigest() == (
        "df61ba96f2bf440f019261d7b38961c7d3b5cdb87f8607082b1688b2190db5ce"
    )
    assert __version__ == "0.6.0a24.post0.dev7+review.confirmed.delivery.v1"
    assert Version(__version__) > Version("0.6.0a24.post0.dev4+review.before.generation.v2")
    assert len(EXPECTED_TOOLS) == 12
    assert [descriptor["name"] for descriptor in binding_tool_descriptors()] == [
        "begin_current_loop",
        "complete_current_step",
    ]
    contract = binding_tool_descriptors()[0]["x-qcoder-review-before-generation"]
    assert contract["target_authority_requires_one_unambiguous_directive"] is True
    assert contract["nonauthoritative_filename_contexts_fail_target_free"] is True
