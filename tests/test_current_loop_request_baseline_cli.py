from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import sys
from typing import Any

import pytest

from qcoder.cli import main as cli_main
from qcoder.current_loop import (
    CURRENT_LOOP_STATE_SCHEMA_ID,
    CURRENT_LOOP_STATE_SCHEMA_VERSION,
)


def _invoke(
    capsys: pytest.CaptureFixture[str],
    workspace: Path,
    *arguments: str,
) -> tuple[int, dict[str, Any]]:
    code = cli_main(
        [
            "current-loop",
            "--workspace",
            str(workspace),
            *arguments,
        ]
    )
    return code, json.loads(capsys.readouterr().out)


def _baseline(workspace: Path) -> dict[str, Any]:
    path = workspace / ".qcoder/current-loop/artifacts/request-baseline.json"
    return json.loads(path.read_bytes().decode("utf-8"))


def _approve(
    capsys: pytest.CaptureFixture[str],
    workspace: Path,
) -> dict[str, Any]:
    code, result = _invoke(capsys, workspace, "activate", "--approve")
    assert code == 0
    return result


def test_inline_capture_is_exact_nonactivating_and_hosted_call_free(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "inline"
    workspace.mkdir()
    request = 'Create and run a simple "Bell" circuit — locally.\n'

    def unexpected_hosted_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("capture_must_not_call_protected")

    monkeypatch.setattr(
        "qcoder.current_loop_coordinator.ContextBridgeTransport.call",
        unexpected_hosted_call,
    )
    code, result = _invoke(
        capsys,
        workspace,
        "activate",
        "--request",
        request,
    )

    assert code == 0
    assert result["checkpoint_kind"] == "activation_request_baseline_review"
    assert result["details"]["original_request"] == request
    assert result["details"]["activation_performed"] is False
    assert result["details"]["canonical_request_baseline_created"] is False
    assert result["details"]["protected_call_performed"] is False
    assert not (workspace / ".qcoder/current-loop/artifacts").exists()
    state = json.loads((workspace / ".qcoder/current-loop/state.json").read_bytes().decode("utf-8"))
    assert state["schema_id"] == CURRENT_LOOP_STATE_SCHEMA_ID
    assert state["schema_version"] == CURRENT_LOOP_STATE_SCHEMA_VERSION
    assert state["state_kind"] == "pending_activation"
    assert state["pending_activation_capture"]["original_request"] == request
    assert state["pending_activation_capture"]["protected_call_performed"] is False


def test_file_capture_preserves_exact_utf8_quotes_and_newline_bytes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "file workspace"
    workspace.mkdir()
    request_file = tmp_path / "request files" / "request $ [exact].txt"
    request_file.parent.mkdir()
    raw = 'First line\r\n"Quoted" café — 第二行\nFinal line\r\n'.encode("utf-8")
    request_file.write_bytes(raw)

    code, result = _invoke(
        capsys,
        workspace,
        "activate",
        "--request-file",
        str(request_file),
    )

    assert code == 0
    assert result["details"]["request_transport"] == "file"
    assert result["details"]["original_request"].encode("utf-8") == raw


class _BinaryStdin:
    def __init__(self, payload: bytes, *, tty: bool = False):
        self.buffer = BytesIO(payload)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_explicit_stdin_capture_is_exact_and_rejects_empty_or_tty(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = "Multiline stdin\nwith quotes ' \" and Ω.\n"
    workspace = tmp_path / "stdin"
    workspace.mkdir()
    monkeypatch.setattr(sys, "stdin", _BinaryStdin(request.encode("utf-8")))
    code, result = _invoke(capsys, workspace, "activate", "--request-stdin")
    assert code == 0
    assert result["details"]["request_transport"] == "stdin"
    assert result["details"]["original_request"] == request

    empty_workspace = tmp_path / "empty-stdin"
    empty_workspace.mkdir()
    monkeypatch.setattr(sys, "stdin", _BinaryStdin(b""))
    code, rejected = _invoke(
        capsys,
        empty_workspace,
        "activate",
        "--request-stdin",
    )
    assert code == 2
    assert rejected["schema_id"] == "qcoder.current_loop.bootstrap_rejection.v1"
    assert rejected["error_category"] == "request_input_empty"
    assert rejected["assistant_should_stop"] is True
    assert rejected["hosted_operation_permitted"] is False
    assert rejected["raw_request_content_included"] is False

    tty_workspace = tmp_path / "tty-stdin"
    tty_workspace.mkdir()
    monkeypatch.setattr(sys, "stdin", _BinaryStdin(b"ignored", tty=True))
    code, rejected = _invoke(
        capsys,
        tty_workspace,
        "activate",
        "--request-stdin",
    )
    assert code == 2
    assert rejected["error_category"] == "request_stdin_requires_noninteractive_input"
    assert rejected["assistant_should_stop"] is True
    assert rejected["hosted_operation_permitted"] is False


def test_file_and_stdin_reject_invalid_utf8(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_file = tmp_path / "invalid utf8 request.txt"
    request_file.write_bytes(b"\xff\xfe")
    file_workspace = tmp_path / "invalid-file"
    file_workspace.mkdir()
    with pytest.raises(SystemExit) as file_error:
        cli_main(
            [
                "current-loop",
                "--workspace",
                str(file_workspace),
                "activate",
                "--request-file",
                str(request_file),
            ]
        )
    assert file_error.value.code == 2
    assert "request_input_invalid_utf8" in capsys.readouterr().err

    stdin_workspace = tmp_path / "invalid-stdin"
    stdin_workspace.mkdir()
    monkeypatch.setattr(sys, "stdin", _BinaryStdin(b"\x80"))
    code, rejected = _invoke(
        capsys,
        stdin_workspace,
        "activate",
        "--request-stdin",
    )
    assert code == 2
    assert rejected["error_category"] == "request_input_invalid_utf8"
    assert rejected["assistant_should_stop"] is True
    assert rejected["hosted_operation_permitted"] is False


def test_request_sources_are_mutually_exclusive(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "exclusive"
    workspace.mkdir()
    request_file = tmp_path / "request.txt"
    request_file.write_text("Synthetic request", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli_main(
            [
                "current-loop",
                "--workspace",
                str(workspace),
                "activate",
                "--request",
                "Synthetic request",
                "--request-file",
                str(request_file),
            ]
        )
    assert exc.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_combined_approval_reuses_pending_bytes_and_keeps_posture_separate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "approval"
    workspace.mkdir()
    request = "Create and run a simple Bell circuit.\n"
    code, staged = _invoke(capsys, workspace, "activate", "--request", request)
    assert code == 0
    assert staged["details"]["original_request"] == request

    approved = _approve(capsys, workspace)

    assert approved["checkpoint_kind"] == "posture"
    assert approved["details"]["activation_authority_transmitted"] is True
    assert approved["details"]["posture_authority_transmitted"] is False
    assert _baseline(workspace)["original_request"] == request
    active_state = json.loads(
        (workspace / ".qcoder/current-loop/state.json").read_bytes().decode("utf-8")
    )
    assert active_state["state_kind"] == "active_loop"
    assert "pending_activation_capture" not in active_state


def test_approval_without_capture_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "missing"
    workspace.mkdir()
    code, result = _invoke(capsys, workspace, "activate", "--approve")
    assert code == 2
    assert result["category"] == "activation_capture_required"
    assert not (workspace / ".qcoder").exists()


def test_new_request_with_approval_cannot_bypass_exact_review(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "no-bypass"
    workspace.mkdir()
    request = "Use qCoder for this build. Keep the Blueprint unchanged."
    code, result = _invoke(
        capsys,
        workspace,
        "activate",
        "--request",
        request,
        "--approve",
    )
    assert code == 0
    assert result["category"] == "new_request_requires_exact_baseline_review"
    assert result["details"]["activation_performed"] is False
    assert result["details"]["original_request"] == request


def test_correction_replaces_pending_capture_and_never_canonicalizes_prior_text(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "correction"
    workspace.mkdir()
    first = "Create a circuit."
    corrected = "Create and run a simple Bell circuit."
    _invoke(capsys, workspace, "activate", "--request", first)
    code, restaged = _invoke(capsys, workspace, "activate", "--request", corrected)
    assert code == 0
    assert restaged["details"]["original_request"] == corrected
    approved = _approve(capsys, workspace)
    assert approved["details"]["original_request"] == corrected
    baseline = _baseline(workspace)
    assert baseline["original_request"] == corrected
    assert first not in json.dumps(baseline)


def test_additive_fields_require_exact_user_spans_and_interpretation_stays_proposed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = (
        "Use qCoder for this build. Work only inside this folder. Use an exploratory first pass."
    )
    workspace = tmp_path / "additive"
    workspace.mkdir()
    code, staged = _invoke(
        capsys,
        workspace,
        "activate",
        "--request",
        request,
        "--constraint",
        "Work only inside this folder.",
        "--choice",
        "Use an exploratory first pass.",
        "--assistant-interpretation",
        "Create one bounded first implementation.",
    )
    assert code == 0
    assert staged["details"]["original_request"] == request
    assert staged["details"]["explicit_constraints"][0]["provenance"] == "user_stated"
    assert staged["details"]["explicit_choices"][0]["provenance"] == "user_stated"
    assert staged["details"]["assistant_interpretation"]["provenance_role"] == (
        "assistant_proposed"
    )
    assert staged["details"]["assistant_interpretation"]["confirmation_state"] == (
        "pending_intent_review"
    )
    _approve(capsys, workspace)
    baseline = _baseline(workspace)
    assert baseline["original_request"] == request
    assert baseline["explicit_constraints"] == ["Work only inside this folder."]
    assert baseline["explicit_choices"] == ["Use an exploratory first pass."]
    assert baseline["assistant_interpretation"]["provenance_role"] == ("assistant_proposed")

    rejected_workspace = tmp_path / "paraphrase"
    rejected_workspace.mkdir()
    code, rejected = _invoke(
        capsys,
        rejected_workspace,
        "activate",
        "--request",
        request,
        "--constraint",
        "Stay in the current folder.",
    )
    assert code == 2
    assert rejected["category"] == "request_baseline_constraint_not_verbatim"
    assert not (rejected_workspace / ".qcoder").exists()


def test_label_provenance_is_fail_closed_and_default_is_system_generated(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    default_workspace = tmp_path / "default-label"
    default_workspace.mkdir()
    _, staged = _invoke(
        capsys,
        default_workspace,
        "activate",
        "--request",
        "Create a simple circuit.",
    )
    assert staged["details"]["label"] == {
        "value": "qCoder current build",
        "provenance": "system_generated",
    }

    user_workspace = tmp_path / "user-label"
    user_workspace.mkdir()
    request = "Use label Bell study for this build."
    code, user_label = _invoke(
        capsys,
        user_workspace,
        "activate",
        "--request",
        request,
        "--label",
        "Bell study",
        "--label-provenance",
        "user_provided",
    )
    assert code == 0
    assert user_label["details"]["label"]["provenance"] == "user_provided"

    rejected_workspace = tmp_path / "invented-label"
    rejected_workspace.mkdir()
    code, rejected = _invoke(
        capsys,
        rejected_workspace,
        "activate",
        "--request",
        "Create a simple circuit.",
        "--label",
        "bell-circuit-demo",
    )
    assert code == 2
    assert rejected["category"] == "request_baseline_label_provenance_required"


def test_complete_message_fidelity_survives_additive_extraction(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = (
        "Use qCoder for this build. Use an exploratory first pass. "
        "Review only the exact files I approve. Continue unchanged if I choose. "
        "Do not change the Blueprint without explicit confirmation."
    )
    workspace = tmp_path / "complete-message"
    workspace.mkdir()
    _, staged = _invoke(
        capsys,
        workspace,
        "activate",
        "--request",
        request,
        "--choice",
        "Use an exploratory first pass.",
        "--constraint",
        "Review only the exact files I approve.",
        "--constraint",
        "Do not change the Blueprint without explicit confirmation.",
    )
    assert staged["details"]["original_request"] == request
    _approve(capsys, workspace)
    assert _baseline(workspace)["original_request"] == request


def test_request_limit_is_codepoint_bounded_without_truncation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    within_workspace = tmp_path / "within-limit"
    within_workspace.mkdir()
    within = "Ω" * 20_000
    code, result = _invoke(
        capsys,
        within_workspace,
        "activate",
        "--request",
        within,
    )
    assert code == 0
    assert result["details"]["original_request"] == within
    assert result["details"]["original_request_codepoint_length"] == 20_000

    over_workspace = tmp_path / "over-limit"
    over_workspace.mkdir()
    with pytest.raises(SystemExit) as exc:
        cli_main(
            [
                "current-loop",
                "--workspace",
                str(over_workspace),
                "activate",
                "--request",
                "x" * 20_001,
            ]
        )
    assert exc.value.code == 2
    assert "request_baseline_original_request_too_large" in capsys.readouterr().err


def test_pending_status_survives_restart_without_search(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "restart"
    workspace.mkdir()
    request = "Create and run a simple Bell circuit."
    _invoke(capsys, workspace, "activate", "--request", request)
    code, status = _invoke(capsys, workspace, "status")
    assert code == 0
    assert status["checkpoint_kind"] == "activation_request_baseline_review"
    assert status["details"]["original_request"] == request
    assert status["details"]["activation_performed"] is False
    assert status["next_invocation"]["required_flags"] == ["--approve"]


def test_abandon_explicitly_invalidates_pending_capture(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "abandon-pending"
    workspace.mkdir()
    _invoke(
        capsys,
        workspace,
        "activate",
        "--request",
        "Synthetic pending request.",
    )
    code, abandoned = _invoke(capsys, workspace, "abandon", "--approve")
    assert code == 0
    assert abandoned["details"]["pending_capture_invalidated"] is True
    assert abandoned["details"]["activation_performed"] is False
    assert not (workspace / ".qcoder/current-loop/state.json").exists()
