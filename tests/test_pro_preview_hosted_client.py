from __future__ import annotations

import io
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from qcoder.cli import main
from qcoder.pro_preview.client import resolve_preview_client_config


class _FakeResponse:
    def __init__(self, *, status: int, body: str) -> None:
        self.status = status
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


def _set_preview_env(monkeypatch: pytest.MonkeyPatch, *, base_url: str, token: str) -> None:
    monkeypatch.setenv("QCODER_PREVIEW_BASE_URL", base_url)
    monkeypatch.setenv("QCODER_PREVIEW_TOKEN", token)


def _clear_preview_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("QCODER_PREVIEW_BASE_URL", "QCODER_PREVIEW_TOKEN", "QCODER_PRO_API_URL", "QCODER_PRO_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def test_preview_env_config_loads_primary_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token="dummy-preview-token-for-test")
    config = resolve_preview_client_config()
    assert config.base_url == "http://127.0.0.1:18081"
    assert config.token == "dummy-preview-token-for-test"


def test_preview_env_config_loads_fallback_pro_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_preview_env(monkeypatch)
    monkeypatch.setenv("QCODER_PRO_API_URL", "http://127.0.0.1:18081")
    monkeypatch.setenv("QCODER_PRO_TOKEN", "dummy-preview-token-for-test")
    config = resolve_preview_client_config()
    assert config.base_url == "http://127.0.0.1:18081"
    assert config.token == "dummy-preview-token-for-test"


def test_preview_base_url_flag_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token="dummy-preview-token-for-test")
    config = resolve_preview_client_config(base_url_override="http://127.0.0.1:18082")
    assert config.base_url == "http://127.0.0.1:18082"


def test_preview_missing_base_url_error_is_actionable(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _clear_preview_env(monkeypatch)
    monkeypatch.setenv("QCODER_PREVIEW_TOKEN", "dummy-preview-token-for-test")
    code = main(["pro", "preview", "status"])
    captured = capsys.readouterr()
    assert code == 2
    assert "QCODER_PREVIEW_BASE_URL" in captured.err
    assert "QCODER_PRO_API_URL" in captured.err


def test_preview_missing_token_error_is_actionable(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _clear_preview_env(monkeypatch)
    monkeypatch.setenv("QCODER_PREVIEW_BASE_URL", "http://127.0.0.1:18081")
    code = main(["pro", "preview", "status"])
    captured = capsys.readouterr()
    assert code == 2
    assert "QCODER_PREVIEW_TOKEN" in captured.err
    assert "QCODER_PRO_TOKEN" in captured.err


def test_preview_sends_authorization_header(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "dummy-preview-token-for-test"
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token=token)
    captured: dict[str, str] = {}

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        captured["authorization"] = req.headers["Authorization"]
        captured["url"] = req.full_url
        return _FakeResponse(status=200, body='{"status":"ok"}')

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["pro", "preview", "status"]) == 0
    assert captured["authorization"] == f"Bearer {token}"
    assert captured["url"] == "http://127.0.0.1:18081/v0/demo/builtin-review"


def test_preview_dummy_token_never_appears_in_stdout(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    token = "dummy-preview-token-for-test"
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token=token)

    def _fake_urlopen(_req: Any, timeout: float = 0) -> _FakeResponse:
        return _FakeResponse(status=200, body='{"status":"ok"}')

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    code = main(["pro", "preview", "status"])
    captured = capsys.readouterr()
    assert code == 0
    assert token not in captured.out


def test_preview_dummy_token_never_appears_in_stderr(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    token = "dummy-preview-token-for-test"
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token=token)

    def _fake_urlopen(_req: Any, timeout: float = 0) -> _FakeResponse:
        return _FakeResponse(status=200, body='{"status":"ok"}')

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    code = main(["pro", "preview", "status"])
    captured = capsys.readouterr()
    assert code == 0
    assert token not in captured.err


def test_preview_authorization_header_value_never_appears_in_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token="dummy-preview-token-for-test")

    def _fake_urlopen(_req: Any, timeout: float = 0) -> _FakeResponse:
        return _FakeResponse(status=200, body='{"status":"ok"}')

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    code = main(["pro", "preview", "status"])
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert code == 0
    assert "Bearer dummy-preview-token-for-test" not in combined
    assert "Authorization" not in combined


def test_preview_http_200_prints_safe_pass_summary(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token="dummy-preview-token-for-test")

    def _fake_urlopen(_req: Any, timeout: float = 0) -> _FakeResponse:
        return _FakeResponse(
            status=200,
            body='{"service":"protected-qrs-service","mode":"cloud-preview-demo","status":"ok","demo_level":"level_2","samples":[{},{}]}',
        )

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    code = main(["pro", "preview", "status"])
    captured = capsys.readouterr()
    assert code == 0
    assert "PASS (HTTP 200)" in captured.out
    assert "protected-qrs-service" in captured.out
    assert "samples: 2" in captured.out


def test_preview_http_401_prints_safe_token_message(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    token = "wrong-token-for-test"
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token=token)

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        raise HTTPError(req.full_url, 401, "Unauthorized", hdrs={}, fp=io.BytesIO(b'{"status":"error"}'))

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    code = main(["pro", "preview", "status"])
    captured = capsys.readouterr()
    assert code == 1
    assert "missing, invalid, or revoked" in captured.err
    assert token not in captured.err


def test_preview_http_403_prints_safe_access_blocked_message(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    token = "dummy-preview-token-for-test"
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token=token)

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        raise HTTPError(req.full_url, 403, "Forbidden", hdrs={}, fp=io.BytesIO(b'{"status":"error"}'))

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    code = main(["pro", "preview", "status"])
    captured = capsys.readouterr()
    assert code == 1
    assert "Private/outer service access" in captured.err
    assert token not in captured.err


def test_preview_network_failure_prints_safe_unreachable_message(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    token = "dummy-preview-token-for-test"
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token=token)

    def _fake_urlopen(_req: Any, timeout: float = 0) -> _FakeResponse:
        raise URLError("connection refused")

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    code = main(["pro", "preview", "status"])
    captured = capsys.readouterr()
    assert code == 2
    assert "Base URL may be unreachable" in captured.err
    assert token not in captured.err


def test_preview_accepts_localhost_proxy_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token="dummy-preview-token-for-test")

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        assert req.full_url.startswith("http://127.0.0.1:18081/")
        return _FakeResponse(status=200, body='{"status":"ok"}')

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["pro", "preview", "status"]) == 0


def test_preview_status_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str | None] = {}

    def _fake_run(*, base_url_override: str | None) -> int:
        captured["base_url_override"] = base_url_override
        return 0

    monkeypatch.setattr("qcoder.cli._run_pro_preview_demo_check", _fake_run)
    assert main(["pro", "preview", "status", "--base-url", "http://127.0.0.1:18081"]) == 0
    assert captured["base_url_override"] == "http://127.0.0.1:18081"


def test_preview_demo_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str | None] = {}

    def _fake_run(*, base_url_override: str | None) -> int:
        captured["base_url_override"] = base_url_override
        return 0

    monkeypatch.setattr("qcoder.cli._run_pro_preview_demo_check", _fake_run)
    assert main(["pro", "preview", "demo", "--base-url", "http://127.0.0.1:18081"]) == 0
    assert captured["base_url_override"] == "http://127.0.0.1:18081"
