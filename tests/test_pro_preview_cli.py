from __future__ import annotations

import io
import json
import socket
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from qcoder.cli import main


def _capture(argv: list[str]) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(argv)
    return rc, out.getvalue(), err.getvalue()


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


def test_no_network_by_default_status(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    def _raise(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("network call attempted")

    monkeypatch.setattr(socket, "create_connection", _raise)
    rc, _out, _err = _capture(["pro", "status", "--json"])
    assert rc == 0
