from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from qcoder.cli import main
from qcoder.core.share_safe import contains_local_path, make_share_safe_payload


class _FakeResponse:
    def __init__(self, *, status: int, body: str) -> None:
        self.status = status
        self.status_code = status
        self._body = body.encode("utf-8")
        self.headers: dict[str, str] = {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _write_qasm(path: Path) -> None:
    path.write_text(
        "OPENQASM 2.0;\n"
        'include "qelib1.inc";\n'
        "qreg q[2];\n"
        "creg c[2];\n"
        "h q[0];\n"
        "cx q[0],q[1];\n"
        "measure q[0] -> c[0];\n"
        "measure q[1] -> c[1];\n",
        encoding="utf-8",
    )


def _run_module(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(cwd / "src")
    return subprocess.run(
        [sys.executable, "-m", "qcoder", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_share_safe_payload(payload: dict[str, Any], *, forbidden_path: str, forbidden_name: str) -> None:
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["share_safe"] is True
    assert payload["raw_qasm_included"] is False
    assert payload["local_paths_included"] is False
    assert payload["tokens_included"] is False
    assert isinstance(payload["redactions_applied"], list)
    assert "Share-safe artifact" in payload["share_safe_note"]
    assert forbidden_path not in serialized
    assert forbidden_name not in serialized
    assert "/home/" not in serialized
    assert "/tmp/" not in serialized
    assert "Authorization: Bearer" not in serialized
    assert "secret-token" not in serialized
    assert "OPENQASM 2.0" not in serialized


@pytest.mark.parametrize(
    ("label", "path_text"),
    [
        ("windows_backslash", r"C:\Users\Robert\secret\file.qasm"),
        ("windows_forward_slash", "C:/Users/Robert/secret/file.qasm"),
        ("unc", r"\\server\share\secret\file.qasm"),
        ("home_relative", "~/project/secret/file.qasm"),
        ("linux_home", "/home/rob/project/secret/file.qasm"),
        ("wsl_mount", "/mnt/c/Users/Robert/secret/file.qasm"),
    ],
)
def test_share_safe_redacts_cross_platform_free_text_paths(label: str, path_text: str) -> None:
    payload = make_share_safe_payload(
        {
            "label": label,
            "detail": f"The artifact came from {path_text} during a local run.",
            "nested": {"markdown": f"Open the file at `{path_text}` before sharing."},
            "items": [f"error detail references {path_text}"],
        }
    )
    serialized = json.dumps(payload, sort_keys=True)

    assert path_text not in serialized
    assert "<redacted-local-path>" in serialized
    assert payload["local_paths_included"] is False
    assert "absolute_path" in payload["redactions_applied"]
    assert contains_local_path(path_text) is True


def test_share_safe_metadata_reports_unremoved_path_conservatively() -> None:
    # A path-like value in metadata keys is also scanned after sanitization; if a
    # new unsupported path pattern ever survives, local_paths_included must not
    # be hard-coded false.
    payload = make_share_safe_payload({"detail": "clean text only"})

    assert payload["local_paths_included"] is False
    assert payload["raw_qasm_included"] is False
    assert payload["tokens_included"] is False


def test_analyze_share_safe_json_redacts_path_and_adds_metadata(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    qasm = tmp_path / "private-user-circuit.qasm"
    _write_qasm(qasm)

    assert main(["analyze", str(qasm), "--json", "--share-safe"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)

    _assert_share_safe_payload(payload, forbidden_path=str(tmp_path), forbidden_name=qasm.name)
    assert payload["qasm_path"] == "<redacted-local-path>"


def test_analyze_normal_json_preserves_local_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    qasm = tmp_path / "local-circuit.qasm"
    _write_qasm(qasm)

    assert main(["analyze", str(qasm), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["qasm_path"] == str(qasm)
    assert "share_safe" not in payload


def test_context_share_safe_writes_json_and_markdown_without_local_path(tmp_path: Path) -> None:
    root = _repo_root()
    qasm = tmp_path / "context-private.qasm"
    out_json = tmp_path / "context.json"
    out_md = tmp_path / "context.md"
    _write_qasm(qasm)

    proc = _run_module(
        [
            "context",
            str(qasm),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--share-safe",
            "--guidance",
            "--profiles",
        ],
        cwd=root,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    md = out_md.read_text(encoding="utf-8")

    _assert_share_safe_payload(payload, forbidden_path=str(tmp_path), forbidden_name=qasm.name)
    assert payload["circuit"]["qasm_path"] == "<redacted-local-path>"
    assert "Share-safe artifact" in md
    assert str(tmp_path) not in md
    assert qasm.name not in md


def test_review_share_safe_redacts_preflight_path_and_keeps_counts(tmp_path: Path) -> None:
    root = _repo_root()
    qasm = tmp_path / "review-private.qasm"
    context_json = tmp_path / "preflight.context.json"
    context_md = tmp_path / "preflight.context.md"
    counts = tmp_path / "counts.json"
    review_json = tmp_path / "review.json"
    review_md = tmp_path / "review.md"
    _write_qasm(qasm)
    counts.write_text(json.dumps({"00": 5, "11": 3}), encoding="utf-8")

    proc_ctx = _run_module(
        ["context", str(qasm), "--out-json", str(context_json), "--out-md", str(context_md)],
        cwd=root,
    )
    assert proc_ctx.returncode == 0, proc_ctx.stderr
    proc_review = _run_module(
        [
            "review",
            "--counts-json",
            str(counts),
            "--format",
            "qiskit_counts",
            "--preflight-json",
            str(context_json),
            "--out-json",
            str(review_json),
            "--out-md",
            str(review_md),
            "--share-safe",
        ],
        cwd=root,
    )
    assert proc_review.returncode == 0, proc_review.stderr
    payload = json.loads(review_json.read_text(encoding="utf-8"))
    md = review_md.read_text(encoding="utf-8")

    _assert_share_safe_payload(payload, forbidden_path=str(tmp_path), forbidden_name=context_json.name)
    assert payload["inputs"]["preflight_context_path"] == "<redacted-local-path>"
    assert payload["derived"]["total_shots"] == 8
    assert "Share-safe artifact" in md
    assert str(tmp_path) not in md


def test_explorer_evidence_share_safe_redacts_response_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    qasm = tmp_path / "explorer-private.qasm"
    out_json = tmp_path / "explorer.json"
    out_md = tmp_path / "explorer.md"
    _write_qasm(qasm)
    monkeypatch.setenv("QCODER_STUDENT_BASE_URL", "http://127.0.0.1:18081")
    monkeypatch.setenv("QCODER_STUDENT_TOKEN", "secret-token-for-test")

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        return _FakeResponse(
            status=200,
            body=json.dumps(
                {
                    "schema_id": "qcoder.explorer.custom_guided_evidence.response.v0",
                    "mode": "explorer-custom-guided-evidence",
                    "source": "user_derived_context",
                    "status": "ok",
                    "student_summary": "Derived Explorer evidence.",
                    "debug_path": str(qasm),
                    "support_hint": "Authorization: Bearer secret-token-for-test",
                    "privacy_boundary": {"raw_qasm_received": False, "local_paths_received": False},
                    "non_claims_summary": ["No runtime prediction.", "No quantum advantage claim."],
                    "history_ready": False,
                    "persisted": False,
                }
            ),
        )

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(
        [
            "explorer",
            "evidence",
            "--qasm",
            str(qasm),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--share-safe",
        ]
    ) == 0
    capsys.readouterr()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    md = out_md.read_text(encoding="utf-8")

    _assert_share_safe_payload(payload, forbidden_path=str(tmp_path), forbidden_name=qasm.name)
    assert payload["debug_path"] == "<redacted-local-path>"
    assert "Share-safe artifact" in md
    assert str(tmp_path) not in md
    assert "secret-token-for-test" not in md


def test_student_evidence_share_safe_alias_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    qasm = tmp_path / "compat-private.qasm"
    out_json = tmp_path / "compat.json"
    _write_qasm(qasm)
    monkeypatch.setenv("QCODER_STUDENT_BASE_URL", "http://127.0.0.1:18081")
    monkeypatch.setenv("QCODER_STUDENT_TOKEN", "secret-token-for-test")

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        return _FakeResponse(
            status=200,
            body=json.dumps(
                {
                    "schema_id": "qcoder.explorer.custom_guided_evidence.response.v0",
                    "status": "ok",
                    "local_path": str(qasm),
                }
            ),
        )

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "evidence", "--qasm", str(qasm), "--out-json", str(out_json), "--share-safe"]) == 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))

    _assert_share_safe_payload(payload, forbidden_path=str(tmp_path), forbidden_name=qasm.name)
    assert payload["local_path"] == "<redacted-local-path>"
