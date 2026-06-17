from __future__ import annotations

import io
from typing import Any
from urllib.error import HTTPError

import pytest

from qcoder.cli import main


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


def test_student_status_dispatches_to_preview_check_and_forwards_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str | None] = {}

    def _fake_run(
        *,
        base_url_override: str | None,
        label: str = "qCoder Pro Preview demo",
        error_prefix: str = "qcoder pro preview",
    ) -> int:
        captured["base_url_override"] = base_url_override
        captured["label"] = label
        captured["error_prefix"] = error_prefix
        return 0

    monkeypatch.setattr("qcoder.cli._run_pro_preview_demo_check", _fake_run)
    assert main(["student", "status", "--base-url", "http://127.0.0.1:18081"]) == 0
    assert captured == {
        "base_url_override": "http://127.0.0.1:18081",
        "label": "qCoder Student demo",
        "error_prefix": "qcoder student",
    }


def test_student_demo_dispatches_to_preview_check_and_forwards_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str | None] = {}

    def _fake_run(
        *,
        base_url_override: str | None,
        label: str = "qCoder Pro Preview demo",
        error_prefix: str = "qcoder pro preview",
    ) -> int:
        captured["base_url_override"] = base_url_override
        captured["label"] = label
        captured["error_prefix"] = error_prefix
        return 0

    monkeypatch.setattr("qcoder.cli._run_pro_preview_demo_check", _fake_run)
    assert main(["student", "demo", "--base-url", "http://127.0.0.1:18082"]) == 0
    assert captured == {
        "base_url_override": "http://127.0.0.1:18082",
        "label": "qCoder Student demo",
        "error_prefix": "qcoder student",
    }


def test_student_status_calls_builtin_review_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token="dummy-preview-token-for-test")
    captured: dict[str, str] = {}

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        captured["url"] = req.full_url
        return _FakeResponse(status=200, body='{"status":"ok"}')

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "status"]) == 0
    assert captured["url"] == "http://127.0.0.1:18081/v0/demo/builtin-review"


def test_student_authorization_header_sent_but_not_printed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    token = "dummy-preview-token-for-test"
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token=token)
    captured: dict[str, str] = {}

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        captured["authorization"] = req.headers["Authorization"]
        return _FakeResponse(status=200, body='{"status":"ok"}')

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "status"]) == 0
    out = capsys.readouterr()
    combined = out.out + out.err
    assert captured["authorization"] == f"Bearer {token}"
    assert token not in combined
    assert f"Bearer {token}" not in combined
    assert "Authorization" not in combined


def test_student_localhost_http_200_returns_pass(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token="dummy-preview-token-for-test")

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        assert req.full_url.startswith("http://127.0.0.1:18081/")
        return _FakeResponse(
            status=200,
            body='{"service":"protected-qrs-service","status":"ok","samples":[{},{}]}',
        )

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "status"]) == 0
    out = capsys.readouterr()
    assert "qCoder Student demo: PASS (HTTP 200)" in out.out
    assert "samples: 2" in out.out


def test_student_missing_base_url_returns_existing_actionable_env_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clear_preview_env(monkeypatch)
    monkeypatch.setenv("QCODER_PREVIEW_TOKEN", "dummy-preview-token-for-test")
    assert main(["student", "status"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("qcoder student: missing hosted Preview base URL")
    assert "QCODER_PREVIEW_BASE_URL" in err
    assert "QCODER_PRO_API_URL" in err
    assert "qcoder pro preview" not in err
    assert "Pro Preview" not in err


def test_student_missing_token_returns_existing_actionable_env_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clear_preview_env(monkeypatch)
    monkeypatch.setenv("QCODER_PREVIEW_BASE_URL", "http://127.0.0.1:18081")
    assert main(["student", "status"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("qcoder student: missing hosted Preview token")
    assert "QCODER_PREVIEW_TOKEN" in err
    assert "QCODER_PRO_TOKEN" in err
    assert "qcoder pro preview" not in err
    assert "Pro Preview" not in err


def test_student_http_401_returns_safe_token_message(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    token = "wrong-token-for-test"
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token=token)

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        raise HTTPError(req.full_url, 401, "Unauthorized", hdrs={}, fp=io.BytesIO(b'{"status":"error"}'))

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "status"]) == 1
    err = capsys.readouterr().err
    assert "missing, invalid, or revoked" in err
    assert token not in err
    assert "qcoder pro preview" not in err
    assert "Pro Preview" not in err
