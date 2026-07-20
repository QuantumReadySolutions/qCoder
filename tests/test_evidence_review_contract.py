from __future__ import annotations

import json
from pathlib import Path

from qcoder.context_bridge_mcp import (
    EVIDENCE_CONFIDENCE_LABELS,
    EXPECTED_TOOLS,
    PROMPT_CONTEXT_MODES,
    TOOL_ALIASES,
    evidence_review_contract_snapshot,
    post_context_bridge,
    tool_descriptors,
)


EXPECTED_LABELS = [
    ("observed", "Observed"),
    ("user_provided", "User-provided"),
    ("inferred", "Inferred"),
    ("assumed", "Assumed"),
    ("not_proven", "Not proven"),
    ("suggested_next_check", "Suggested next check"),
]


class _Response:
    status = 200
    headers: dict[str, str] = {}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(
            {
                "ok": True,
                "tool_name": "get_guided_evidence_context",
                "context_status": "assistant_context_ready",
                "retention": "process_and_discard",
                "retained_artifacts": [],
            }
        ).encode("utf-8")


def _token_file(tmp_path: Path) -> Path:
    path = tmp_path / "token.txt"
    path.write_text("synthetic-token-not-printed", encoding="utf-8")
    path.chmod(0o600)
    return path


def test_contract_snapshot_has_exact_inventories_labels_and_boundaries() -> None:
    snapshot = evidence_review_contract_snapshot()
    assert snapshot["tool_names"] == list(EXPECTED_TOOLS)
    assert len(snapshot["tool_names"]) == 8
    assert snapshot["prompt_context_modes"] == sorted(PROMPT_CONTEXT_MODES)
    assert len(snapshot["prompt_context_modes"]) == 5
    assert [
        (item["value"], item["display"]) for item in snapshot["confidence_labels"]
    ] == EXPECTED_LABELS
    assert [
        (value, display) for value, display, _meaning in EVIDENCE_CONFIDENCE_LABELS
    ] == EXPECTED_LABELS
    assert snapshot["context_scope"] == "current_artifact_current_session"
    assert snapshot["retention"] == "process_and_discard"
    boundaries = " ".join(snapshot["boundaries"])
    assert "no hidden lookup" in boundaries
    assert "no project memory" in boundaries
    assert "no autonomous execution" in boundaries
    assert "no repository access or file editing" in boundaries


def test_discovery_exposes_no_new_tool_or_hidden_orchestration() -> None:
    names = [descriptor["name"] for descriptor in tool_descriptors()]
    assert names == list(EXPECTED_TOOLS)
    assert len(names) == 8
    assert all("evidence_review_summary" not in name for name in names)
    assert all("orchestrat" not in name for name in names)
    assert not set(TOOL_ALIASES) & set(names)


def test_legacy_aliases_are_accepted_without_becoming_discoverable(tmp_path: Path) -> None:
    captured_urls: list[str] = []

    def opener(request: object, timeout: int) -> _Response:
        assert timeout == 20
        captured_urls.append(request.full_url)  # type: ignore[attr-defined]
        body = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        assert body["tool_name"] == "get_guided_evidence_context"
        return _Response()

    result = post_context_bridge(
        base_url="https://example.invalid",
        token_file=_token_file(tmp_path),
        tool_name="get_context_from_share_safe_artifact",
        artifact_text="Synthetic share-safe current evidence summary.",
        opener=opener,
    )
    assert result["ok"] is True
    assert captured_urls == ["https://example.invalid/v0/internal/hosted-mcp/context"]


def test_tool_descriptions_state_bounded_evidence_review_semantics() -> None:
    descriptions = {item["name"]: item["description"] for item in tool_descriptors()}
    for label in (
        "Observed",
        "User-provided",
        "Inferred",
        "Assumed",
        "Not proven",
        "Suggested next check",
    ):
        assert label in descriptions["create_run_readiness_card"]
    assert (
        "Observed, User-provided, Inferred, Assumed"
        in descriptions["create_result_review_context_card"]
    )
    assert "user-controlled" in descriptions["create_next_check_plan"]
    assert "does not execute" in descriptions["create_next_check_plan"]
    assert "causal diagnosis" in descriptions["create_single_loop_evidence_diff"]
    assert "multi-run analysis" in descriptions["create_single_loop_evidence_diff"]


def test_review_current_evidence_entry_maps_only_to_existing_operations() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Review current evidence", 1)[1].split("## Quick start", 1)[0]
    expected_operations = {
        "create_run_readiness_card",
        "create_result_review_context_card",
        "create_single_loop_evidence_diff",
        "create_next_check_plan",
        "create_prompt_context",
    }
    assert all(operation in section for operation in expected_operations)
    assert "Evidence Review Summary" not in section
    assert "router" not in section.lower()
    assert "orchestration" not in section.lower()
    assert "manual share-safe Prompt Context handoff" in section
    assert "not a connected Context Bridge client" in section


def test_synthetic_walkthrough_exercises_labels_stages_and_nonclaims() -> None:
    root = Path(__file__).resolve().parents[1]
    walkthrough = (root / "examples" / "08_evidence_review.md").read_text(encoding="utf-8")
    for label in (
        "Observed",
        "User-provided",
        "Inferred",
        "Assumed",
        "Not proven",
        "Suggested next check",
    ):
        assert label in walkthrough
    for operation in (
        "create_context_session_card",
        "create_run_readiness_card",
        "create_result_review_context_card",
        "create_single_loop_evidence_diff",
        "create_next_check_plan",
        "create_prompt_context",
    ):
        assert operation in walkthrough
    lowered = walkthrough.lower()
    assert "execution is outside qcoder" in lowered
    assert "no lookup" in lowered
    assert "qcoder does not execute it" in lowered
    assert "chatgpt is not a connected context bridge integration" in lowered
