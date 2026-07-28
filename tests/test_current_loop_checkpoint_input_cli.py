from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import sys
from typing import Any

import pytest

from qcoder.cli import main as cli_main
from qcoder.current_loop_checkpoint_input import CHECKPOINT_INPUT_SCHEMA_ID


class _BinaryStdin:
    def __init__(self, payload: bytes, *, tty: bool = False):
        self.buffer = BytesIO(payload)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


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


def _activate(capsys: pytest.CaptureFixture[str], workspace: Path) -> None:
    code, result = _invoke(
        capsys,
        workspace,
        "activate",
        "--request",
        "Use qCoder for this build. Create one synthetic circuit.",
    )
    assert code == 0
    assert result["checkpoint_kind"] == "activation_request_baseline_review"
    code, result = _invoke(
        capsys,
        workspace,
        "activate",
        "--approve",
        "--posture",
        "exploratory_first_pass",
        "--approve-posture",
        "--posture-provenance",
        "user_confirmed_assistant_recommendation",
    )
    assert code == 0
    assert result["phase"] == "intent_review"


def _payload(summary: str) -> bytes:
    return json.dumps(
        {
            "schema_id": CHECKPOINT_INPUT_SCHEMA_ID,
            "schema_version": 1,
            "operation": "prepare_generation",
            "checkpoint_kind": "intent_review",
            "fields": [
                {
                    "name": "profile_id",
                    "value": "generic_qiskit",
                    "provenance": "assistant_proposed",
                },
                {
                    "name": "proposed_interpretation",
                    "value": {"summary": summary},
                    "provenance": "assistant_proposed",
                },
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def test_checkpoint_input_file_and_stdin_preserve_exact_utf8(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact = "`00`/`11` $(printf sentinel) '$X' ${VARIABLE} \\\\ Ω 😀\nsecond\tline"
    workspace = tmp_path / "file workspace"
    workspace.mkdir()
    _activate(capsys, workspace)
    input_file = tmp_path / "checkpoint input $ with spaces.json"
    input_file.write_bytes(_payload(exact))
    code, result = _invoke(
        capsys,
        workspace,
        "stage-checkpoint-input",
        "--operation",
        "prepare_generation",
        "--checkpoint-kind",
        "intent_review",
        "--checkpoint-input-file",
        str(input_file),
    )
    assert code == 0
    assert result["checkpoint_kind"] == "checkpoint_input_review"
    displayed = {
        field["field"]: field["value"] for field in result["details"]["complete_staged_values"]
    }
    assert displayed["proposed_interpretation"]["summary"] == exact
    assert result["details"]["protected_call_performed"] is False

    corrected = exact + "\ncorrected"
    monkeypatch.setattr(sys, "stdin", _BinaryStdin(_payload(corrected)))
    code, result = _invoke(
        capsys,
        workspace,
        "stage-checkpoint-input",
        "--operation",
        "prepare_generation",
        "--checkpoint-kind",
        "intent_review",
        "--checkpoint-input-stdin",
    )
    assert code == 0
    displayed = {
        field["field"]: field["value"] for field in result["details"]["complete_staged_values"]
    }
    assert displayed["proposed_interpretation"]["summary"] == corrected


def test_checkpoint_input_sources_are_exclusive_and_tty_fails_without_waiting(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "exclusive"
    workspace.mkdir()
    _activate(capsys, workspace)
    input_file = tmp_path / "input.json"
    input_file.write_bytes(_payload("Exact input."))
    with pytest.raises(SystemExit) as exclusive:
        cli_main(
            [
                "current-loop",
                "--workspace",
                str(workspace),
                "stage-checkpoint-input",
                "--operation",
                "prepare_generation",
                "--checkpoint-kind",
                "intent_review",
                "--checkpoint-input-stdin",
                "--checkpoint-input-file",
                str(input_file),
            ]
        )
    assert exclusive.value.code == 2
    capsys.readouterr()

    monkeypatch.setattr(sys, "stdin", _BinaryStdin(b"", tty=True))
    with pytest.raises(SystemExit) as tty:
        cli_main(
            [
                "current-loop",
                "--workspace",
                str(workspace),
                "stage-checkpoint-input",
                "--operation",
                "prepare_generation",
                "--checkpoint-kind",
                "intent_review",
                "--checkpoint-input-stdin",
            ]
        )
    assert tty.value.code == 2
    assert "checkpoint_input_stdin_requires_noninteractive_input" in capsys.readouterr().err


def test_checkpoint_input_content_and_approval_cannot_bypass_review(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "no-bypass"
    workspace.mkdir()
    _activate(capsys, workspace)
    input_file = tmp_path / "no-bypass.json"
    input_file.write_bytes(_payload("Exact content must be reviewed first."))
    with pytest.raises(SystemExit) as exc_info:
        cli_main(
            [
                "current-loop",
                "--workspace",
                str(workspace),
                "stage-checkpoint-input",
                "--operation",
                "prepare_generation",
                "--checkpoint-kind",
                "intent_review",
                "--checkpoint-input-file",
                str(input_file),
                "--approve",
            ]
        )
    assert exc_info.value.code == 2
    assert "unrecognized arguments: --approve" in capsys.readouterr().err
    assert not (workspace / ".qcoder/current-loop/artifacts/working-blueprint.json").exists()


def test_checkpoint_input_invalid_utf8_and_empty_fail_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "invalid"
    workspace.mkdir()
    _activate(capsys, workspace)
    for name, raw, category in (
        ("invalid.json", b"\xff", "checkpoint_input_utf8_invalid"),
        ("empty.json", b"", "checkpoint_input_empty"),
    ):
        path = tmp_path / name
        path.write_bytes(raw)
        with pytest.raises(SystemExit) as exc_info:
            cli_main(
                [
                    "current-loop",
                    "--workspace",
                    str(workspace),
                    "stage-checkpoint-input",
                    "--operation",
                    "prepare_generation",
                    "--checkpoint-kind",
                    "intent_review",
                    "--checkpoint-input-file",
                    str(path),
                ]
            )
        assert exc_info.value.code == 2
        assert category in capsys.readouterr().err
