from __future__ import annotations

import io
import json
import socket
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pytest
from qcoder.cli import main
from qcoder.pro_preview.client import ProServiceClientError, ServiceErrorDetail


def _capture(argv: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(argv)
    return rc, out.getvalue(), err.getvalue()


def _write_qasm(path: Path) -> None:
    path.write_text(
        "OPENQASM 2.0;\n"
        'include "qelib1.inc";\n'
        "qreg q[2];\n"
        "creg c[2];\n"
        "h q[0];\n"
        "cx q[0], q[1];\n"
        "measure q[0] -> c[0];\n"
        "measure q[1] -> c[1];\n",
        encoding="utf-8",
    )


def test_status_with_no_config_is_clean(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("QCODER_PRO_TOKEN", raising=False)
    monkeypatch.delenv("QCODER_PRO_API_URL", raising=False)
    rc, out, _err = _capture(["pro", "status", "--json"])
    assert rc == 0
    payload = json.loads(out)
    assert payload["configured"] is False
    assert payload["token_present"] is False
    assert payload["token_source"] == "unset"
    assert payload["service_validation"] == "not_available"
    assert payload["cards_local"] is False
    assert payload["local_pro_analysis"] is False
    assert payload["confidential_analysis_local"] is False


def test_login_stores_token_without_echo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    token = "secret-token-for-test"
    rc, out, _err = _capture(["pro", "login", "--token", token])
    assert rc == 0
    assert token not in out
    cfg_path = tmp_path / ".qcoder" / "pro-preview" / "config.json"
    assert cfg_path.exists()
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert data["token"] == token


def test_install_configures_bootstrap_and_no_confidential_claim(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    rc, out, _err = _capture(["pro", "install", "--token", "install-token", "--json"])
    assert rc == 0
    payload = json.loads(out)
    assert payload["operation"] == "install"
    assert payload["configured"] is True
    assert payload["cards_local"] is False
    assert payload["local_pro_analysis"] is False
    assert payload["confidential_analysis_local"] is False
    assert payload["upload_performed"] is False


def test_status_json_hides_token_and_reports_sources(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _capture(["pro", "install", "--token", "stored-token", "--api-url", "https://cfg.example"])
    rc, out, _err = _capture(["pro", "status", "--json"])
    assert rc == 0
    payload = json.loads(out)
    assert payload["token_present"] is True
    assert payload["token_source"] == "config"
    assert payload["api_url_configured"] is True
    assert payload["api_url_source"] == "config"
    assert "stored-token" not in out


def test_validate_reports_config_and_boundary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _capture(["pro", "install", "--token", "validate-token"])
    rc, out, _err = _capture(["pro", "validate", "--json"])
    assert rc == 0
    payload = json.loads(out)
    assert payload["configured"] is True
    assert payload["status"] == "ok"
    assert payload["pro_v0_local_module_present"] is False
    assert payload["public_boundary_ok"] is True


def test_status_human_output_marks_default_preview_url_not_submit_ready(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("QCODER_PRO_TOKEN", raising=False)
    monkeypatch.delenv("QCODER_PRO_API_URL", raising=False)
    rc, out, _err = _capture(["pro", "status"])
    assert rc == 0
    assert "submit-ready service URL: not set" in out
    assert "pilot submit readiness: not ready" in out
    assert "default archived preview URL is informational" in out
    assert "api_url: configured (default)" not in out


def test_validate_human_output_separates_boundary_from_submit_readiness(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("QCODER_PRO_TOKEN", raising=False)
    monkeypatch.delenv("QCODER_PRO_API_URL", raising=False)
    rc, out, _err = _capture(["pro", "validate"])
    assert rc == 0
    assert "public package boundary checks: ok" in out
    assert "pilot submit readiness: not ready" in out
    assert "submit requirement: QRS-provided token + non-default service URL" in out
    assert "pro_v0" not in out


def test_login_and_install_human_output_use_public_wording(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    token = "token-for-wording-check"

    rc_login, out_login, _err_login = _capture(["pro", "login", "--token", token])
    assert rc_login == 0
    assert "Configured archived qCoder Pro pilot local token settings." in out_login
    assert "token hygiene: do not paste tokens into tickets, screenshots, or chat" in out_login
    assert "Pro Preview/V0" not in out_login
    assert "V0 local bootstrap" not in out_login

    rc_install, out_install, _err_install = _capture(["pro", "install", "--token", token])
    assert rc_install == 0
    assert "Configured archived qCoder Pro pilot local token settings." in out_install
    assert "token hygiene: do not paste tokens into tickets, screenshots, or chat" in out_install
    assert "Pro Preview/V0" not in out_install
    assert "V0 local bootstrap" not in out_install


def test_no_network_by_default_status(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    def _raise(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("network call attempted")

    monkeypatch.setattr(socket, "create_connection", _raise)
    rc, _out, _err = _capture(["pro", "status", "--json"])
    assert rc == 0


def test_workflow_dry_run_single_writes_manifest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    qasm = tmp_path / "single.qasm"
    manifest = tmp_path / "workflow.manifest.json"
    _write_qasm(qasm)
    rc, _out, _err = _capture(
        ["pro", "workflow", "--qasm", str(qasm), "--dry-run-manifest", str(manifest), "--json"]
    )
    assert rc == 0
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["schema_id"] == "qcoder.pro_preview.workflow_manifest.v0"
    assert payload["mode"] == "single"
    assert payload["inputs"]["qasm"]["bytes"] > 0
    assert payload["inputs"]["qasm"]["sha256"]
    assert payload["inputs"]["qasm"]["local_analysis"]["source_format"] == "qasm2"
    assert payload["boundary"]["upload_performed"] is False
    assert payload["boundary"]["network_performed"] is False
    assert payload["boundary"]["source_contents_included"] is False
    assert payload["boundary"]["cards_local"] is False
    assert payload["boundary"]["local_pro_analysis"] is False
    assert payload["boundary"]["confidential_analysis_local"] is False


def test_workflow_dry_run_pair_writes_manifest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    before_qasm = tmp_path / "before.qasm"
    after_qasm = tmp_path / "after.qasm"
    manifest = tmp_path / "pair.manifest.json"
    _write_qasm(before_qasm)
    _write_qasm(after_qasm)
    rc, _out, _err = _capture(
        [
            "pro",
            "workflow",
            "--before-qasm",
            str(before_qasm),
            "--after-qasm",
            str(after_qasm),
            "--dry-run-manifest",
            str(manifest),
        ]
    )
    assert rc == 0
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["mode"] == "pair"
    assert "before_qasm" in payload["inputs"]
    assert "after_qasm" in payload["inputs"]
    assert payload["inputs"]["before_qasm"]["local_analysis"]["source_format"] == "qasm2"


def test_workflow_dry_run_does_not_include_project_contents(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    qasm = tmp_path / "single.qasm"
    project_dir = tmp_path / "proj"
    nested_file = project_dir / "secret" / "data.txt"
    manifest = tmp_path / "workflow.manifest.json"
    _write_qasm(qasm)
    nested_file.parent.mkdir(parents=True, exist_ok=True)
    nested_file.write_text("sensitive", encoding="utf-8")
    rc, _out, _err = _capture(
        [
            "pro",
            "workflow",
            "--qasm",
            str(qasm),
            "--project-dir",
            str(project_dir),
            "--dry-run-manifest",
            str(manifest),
        ]
    )
    assert rc == 0
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["workflow"]["project_dir_supplied"] is True
    assert payload["workflow"]["project_dir_name"] == project_dir.name
    assert "files" not in payload["workflow"]
    assert payload["boundary"]["source_contents_included"] is False
    text = manifest.read_text(encoding="utf-8")
    assert "sensitive" not in text
    assert str(nested_file) not in text


def test_workflow_dry_run_no_network(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    qasm = tmp_path / "single.qasm"
    manifest = tmp_path / "workflow.manifest.json"
    _write_qasm(qasm)

    def _raise(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("network call attempted")

    monkeypatch.setattr(socket, "create_connection", _raise)
    rc, _out, _err = _capture(
        ["pro", "workflow", "--qasm", str(qasm), "--dry-run-manifest", str(manifest)]
    )
    assert rc == 0


def test_workflow_without_dry_run_still_fails_cleanly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    qasm = tmp_path / "single.qasm"
    _write_qasm(qasm)
    rc, _out, err = _capture(["pro", "workflow", "--qasm", str(qasm)])
    assert rc == 2
    assert "dry-run-manifest" in err
    assert "production hosted pro service" in err.lower()


def test_workflow_dry_run_requires_single_or_pair_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    manifest = tmp_path / "workflow.manifest.json"
    rc, _out, err = _capture(["pro", "workflow", "--dry-run-manifest", str(manifest)])
    assert rc == 2
    assert "requires --qasm or --before-qasm/--after-qasm" in err


def test_workflow_dry_run_rejects_mixed_single_and_pair(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    qasm = tmp_path / "single.qasm"
    before_qasm = tmp_path / "before.qasm"
    after_qasm = tmp_path / "after.qasm"
    manifest = tmp_path / "workflow.manifest.json"
    _write_qasm(qasm)
    _write_qasm(before_qasm)
    _write_qasm(after_qasm)
    rc, _out, err = _capture(
        [
            "pro",
            "workflow",
            "--qasm",
            str(qasm),
            "--before-qasm",
            str(before_qasm),
            "--after-qasm",
            str(after_qasm),
            "--dry-run-manifest",
            str(manifest),
        ]
    )
    assert rc == 2
    assert "choose either --qasm or --before-qasm/--after-qasm" in err


def test_workflow_dry_run_rejects_incomplete_pair(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    before_qasm = tmp_path / "before.qasm"
    manifest = tmp_path / "workflow.manifest.json"
    _write_qasm(before_qasm)
    rc, _out, err = _capture(
        [
            "pro",
            "workflow",
            "--before-qasm",
            str(before_qasm),
            "--dry-run-manifest",
            str(manifest),
        ]
    )
    assert rc == 2
    assert "pair mode requires both --before-qasm and --after-qasm" in err


def test_workflow_dry_run_manifest_path_must_be_writable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    qasm = tmp_path / "single.qasm"
    _write_qasm(qasm)
    unwritable_target = tmp_path / "manifest-dir"
    unwritable_target.mkdir()
    rc, _out, err = _capture(
        ["pro", "workflow", "--qasm", str(qasm), "--dry-run-manifest", str(unwritable_target)]
    )
    assert rc == 2
    assert "qcoder pro workflow:" in err


def test_workflow_dry_run_missing_qasm_file_fails_cleanly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    missing_qasm = tmp_path / "missing.qasm"
    manifest = tmp_path / "workflow.manifest.json"
    rc, _out, err = _capture(
        ["pro", "workflow", "--qasm", str(missing_qasm), "--dry-run-manifest", str(manifest)]
    )
    assert rc == 2
    assert "qcoder pro workflow:" in err


def test_workflow_submit_requires_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("QCODER_PRO_TOKEN", raising=False)
    qasm = tmp_path / "single.qasm"
    _write_qasm(qasm)
    rc, _out, err = _capture(
        [
            "pro",
            "workflow",
            "--qasm",
            str(qasm),
            "--submit",
            "--service-url",
            "http://127.0.0.1:8765",
        ]
    )
    assert rc == 2
    assert "requires a configured token" in err
    assert "Do not share your token" in err


def test_workflow_submit_requires_non_default_service_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("QCODER_PRO_TOKEN", "dev-token-123")
    monkeypatch.delenv("QCODER_PRO_API_URL", raising=False)
    qasm = tmp_path / "single.qasm"
    _write_qasm(qasm)
    rc, _out, err = _capture(["pro", "workflow", "--qasm", str(qasm), "--submit"])
    assert rc == 2
    assert "production hosted pro service" in err.lower()
    assert "service submit url is not configured" in err.lower()
    assert "share only redacted output and error/status codes" in err.lower()


def test_workflow_submit_posts_entitlements_then_workflow_and_strips_sensitive_fields(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("QCODER_PRO_TOKEN", "dev-token-123")
    qasm = tmp_path / "single.qasm"
    manifest_out = tmp_path / "sanitized.manifest.json"
    _write_qasm(qasm)

    calls: list[str] = []
    captured_manifest: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, *, base_url: str, timeout_s: float = 10.0) -> None:
            assert base_url == "http://127.0.0.1:8765"

        def post_entitlements_validate(self, token: str) -> dict[str, Any]:
            calls.append("entitlements")
            assert token == "dev-token-123"
            return {"schema_id": "qcoder.pro_service.entitlements.v0", "valid": True}

        def post_workflow(self, manifest: dict[str, Any], token: str) -> dict[str, Any]:
            calls.append("workflows")
            captured_manifest.update(manifest)
            assert token == "dev-token-123"
            return {
                "schema_id": "qcoder.pro_service.workflow_job.v0",
                "job_id": "job-123",
                "state": "succeeded",
                "analysis_performed": False,
                "confidential_analysis_performed": False,
                "cards_generated": False,
                "local_fake": True,
            }

    monkeypatch.setattr("qcoder.cli.ProServiceClient", FakeClient)
    rc, out, err = _capture(
        [
            "pro",
            "workflow",
            "--qasm",
            str(qasm),
            "--submit",
            "--service-url",
            "http://127.0.0.1:8765",
            "--manifest-out",
            str(manifest_out),
            "--json",
        ]
    )
    assert err == ""
    assert rc == 0
    payload = json.loads(out)
    assert payload["submitted"] is True
    assert payload["job_id"] == "job-123"
    assert payload["upload_performed"] is False
    assert payload["source_contents_included"] is False
    assert payload["network_performed"] is True
    assert payload["service_url_source"] == "flag"
    assert calls == ["entitlements", "workflows"]
    manifest_text = json.dumps(captured_manifest, sort_keys=True)
    assert "supplied_path" not in manifest_text
    assert '"source_contents":' not in manifest_text
    assert '"source_code":' not in manifest_text
    assert '"raw_qasm":' not in manifest_text
    assert '"qasm_text":' not in manifest_text
    assert '"operations":' not in manifest_text
    wire_boundary = captured_manifest["boundary"]
    assert wire_boundary["dry_run"] is False
    assert wire_boundary["upload_performed"] is False
    assert wire_boundary["network_performed"] is False
    assert wire_boundary["source_contents_included"] is False
    assert manifest_out.exists()


def test_workflow_submit_service_error_is_bounded_and_hides_token(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    token = "dev-secret-token-123"
    monkeypatch.setenv("QCODER_PRO_TOKEN", token)
    qasm = tmp_path / "single.qasm"
    _write_qasm(qasm)

    class FailingClient:
        def __init__(self, *, base_url: str, timeout_s: float = 10.0) -> None:
            assert base_url == "http://127.0.0.1:8765"

        def post_entitlements_validate(self, token: str) -> dict[str, Any]:
            raise ProServiceClientError(
                ServiceErrorDetail(
                    status_code=None,
                    error_code="SERVICE_UNAVAILABLE",
                    message="unable to reach configured service",
                )
            )

    monkeypatch.setattr("qcoder.cli.ProServiceClient", FailingClient)
    rc, out, err = _capture(
        [
            "pro",
            "workflow",
            "--qasm",
            str(qasm),
            "--submit",
            "--service-url",
            "http://127.0.0.1:8765",
        ]
    )
    assert rc == 2
    assert out == ""
    assert "SERVICE_UNAVAILABLE" in err
    assert token not in err


@pytest.mark.parametrize(
    ("argv", "expected_rc"),
    [
        (["pro", "signup"], 0),
        (["pro", "status"], 0),
        (["pro", "validate"], 0),
        (["pro", "login", "--token", "dev-token"], 0),
        (["pro", "install", "--token", "dev-token"], 0),
    ],
)
def test_non_workflow_pro_commands_do_not_create_service_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str], expected_rc: int
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    class ShouldNotConstruct:
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            raise AssertionError("service client should not be constructed")

    monkeypatch.setattr("qcoder.cli.ProServiceClient", ShouldNotConstruct)
    rc, _out, _err = _capture(argv)
    assert rc == expected_rc
