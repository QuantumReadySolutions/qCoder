from __future__ import annotations

import io
import json
from typing import Any
from urllib.error import HTTPError, URLError

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


def _set_student_env(monkeypatch: pytest.MonkeyPatch, *, base_url: str, token: str) -> None:
    monkeypatch.setenv("QCODER_STUDENT_BASE_URL", base_url)
    monkeypatch.setenv("QCODER_STUDENT_TOKEN", token)


def _clear_preview_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "QCODER_STUDENT_BASE_URL",
        "QCODER_STUDENT_TOKEN",
        "QCODER_PREVIEW_BASE_URL",
        "QCODER_PREVIEW_TOKEN",
        "QCODER_PRO_API_URL",
        "QCODER_PRO_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def test_student_status_dispatches_to_preview_check_and_forwards_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str | bool | None] = {}

    def _fake_run(
        *,
        base_url_override: str | None,
        mode: str,
        json_output: bool,
    ) -> int:
        captured["base_url_override"] = base_url_override
        captured["mode"] = mode
        captured["json_output"] = json_output
        return 0

    monkeypatch.setattr("qcoder.cli._run_student_builtin_review_check", _fake_run)
    assert main(["student", "status", "--base-url", "http://127.0.0.1:18081"]) == 0
    assert captured == {
        "base_url_override": "http://127.0.0.1:18081",
        "mode": "status",
        "json_output": False,
    }


def test_student_demo_dispatches_to_preview_check_and_forwards_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str | bool | None] = {}

    def _fake_run(
        *,
        base_url_override: str | None,
        mode: str,
        json_output: bool,
    ) -> int:
        captured["base_url_override"] = base_url_override
        captured["mode"] = mode
        captured["json_output"] = json_output
        return 0

    monkeypatch.setattr("qcoder.cli._run_student_builtin_review_check", _fake_run)
    assert main(["student", "demo", "--base-url", "http://127.0.0.1:18082"]) == 0
    assert captured == {
        "base_url_override": "http://127.0.0.1:18082",
        "mode": "demo",
        "json_output": False,
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


def test_student_evidence_calls_guided_evidence_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token="dummy-preview-token-for-test")
    captured: dict[str, str] = {}

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        captured["url"] = req.full_url
        return _FakeResponse(
            status=200,
            body='{"schema_id":"qcoder.student_guided_evidence.v0","mode":"student-guided-evidence"}',
        )

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "evidence"]) == 0
    assert captured["url"] == "http://127.0.0.1:18081/v0/student/guided-evidence"


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


def test_student_evidence_authorization_header_sent_but_not_printed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    token = "dummy-preview-token-for-test"
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token=token)
    captured: dict[str, str] = {}

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        captured["authorization"] = req.headers["Authorization"]
        return _FakeResponse(
            status=200,
            body='{"schema_id":"qcoder.student_guided_evidence.v0","mode":"student-guided-evidence"}',
        )

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "evidence"]) == 0
    out = capsys.readouterr()
    combined = out.out + out.err
    assert captured["authorization"] == f"Bearer {token}"
    assert token not in combined
    assert f"Bearer {token}" not in combined
    assert "Authorization" not in combined


def test_student_status_renders_access_framing_and_next_step(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token="dummy-preview-token-for-test")

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        assert req.full_url.startswith("http://127.0.0.1:18081/")
        return _FakeResponse(
            status=200,
            body=(
                '{"service":"protected-qrs-service","status":"ok","samples":[{},{}],'
                '"demo_level":"student_beta_builtin_review",'
                '"demo_scope":"qCoder Student built-in teaching demo"}'
            ),
        )

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "status"]) == 0
    out = capsys.readouterr()
    assert "qCoder Student access: OK" in out.out
    assert "qCoder Student demo: PASS" not in out.out
    assert "Next: try qcoder student demo, then qcoder student evidence." in out.out
    assert "teaching_demo_samples: 2" in out.out
    assert "demo_level" not in out.out
    assert "demo_scope" not in out.out


def test_student_demo_renders_teaching_demo_and_hides_meta(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token="dummy-preview-token-for-test")

    def _fake_urlopen(_req: Any, timeout: float = 0) -> _FakeResponse:
        return _FakeResponse(
            status=200,
            body=(
                '{"student_summary":"This demo shows how qCoder explains a built-in circuit.",'
                '"mode":"student-guided-demo",'
                '"samples":[{"plain_summary":"A tiny Bell-style example."},{}],'
                '"demo_level":"student_beta_builtin_review",'
                '"demo_scope":"qCoder Student built-in teaching demo"}'
            ),
        )

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "demo"]) == 0
    out = capsys.readouterr()
    assert "qCoder Student built-in teaching demo: PASS (HTTP 200)" in out.out
    assert "summary: This demo shows how qCoder explains a built-in circuit." in out.out
    assert "samples: 2" in out.out
    assert "sample 1: A tiny Bell-style example." in out.out
    assert "demo_level" not in out.out
    assert "demo_scope" not in out.out


def test_student_evidence_http_200_prints_safe_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token="dummy-preview-token-for-test")

    def _fake_urlopen(_req: Any, timeout: float = 0) -> _FakeResponse:
        return _FakeResponse(
            status=200,
            body=(
                '{"schema_id":"qcoder.student_guided_evidence.v0",'
                '"mode":"student-guided-evidence",'
                '"student_summary":"This is a learner-friendly guided evidence summary.",'
                '"anatomy_label":"bell_pair_teaching_example",'
                '"history_ready":true,'
                '"persisted":false,'
                '"samples":[{'
                '"id":"a",'
                '"plain_summary":"This sample creates and checks a two-qubit relationship.",'
                '"anatomy_label":"entanglement_intro",'
                '"beginner_metrics":{"qubits":2,"two_qubit_gates":1},'
                '"sample_fingerprint":"hidden-sample-fingerprint"'
                '},{"id":"b","plain_summary":"This sample compares a simple measurement pattern."}],'
                '"beginner_metrics":{"samples":2},'
                '"glossary":{"anatomy_label":"A short name for the circuit shape.",'
                '"two_qubit_gates":"Operations touching two qubits."},'
                '"generated_basis":"hidden-generated-basis",'
                '"demo_level":"student_beta_builtin_review",'
                '"demo_scope":"qCoder Student built-in teaching demo",'
                '"extra_secret_like_field":"do-not-print"}'
            ),
        )

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "evidence"]) == 0
    out = capsys.readouterr()
    assert "qCoder Student evidence: PASS (HTTP 200)" in out.out
    assert "summary: This is a learner-friendly guided evidence summary." in out.out
    assert "anatomy_label: bell_pair_teaching_example" in out.out
    assert "sample 1: This sample creates and checks a two-qubit relationship." in out.out
    assert "sample 1 anatomy: entanglement_intro" in out.out
    assert "sample 1 beginner_metrics: qubits=2, two_qubit_gates=1" in out.out
    assert "beginner_metrics: samples=2" in out.out
    assert "glossary:" in out.out
    assert "anatomy_label: A short name for the circuit shape." in out.out
    assert "samples: 2" in out.out
    assert "schema_id" not in out.out
    assert "sample_fingerprint" not in out.out
    assert "generated_basis" not in out.out
    assert "demo_level" not in out.out
    assert "demo_scope" not in out.out
    assert "do-not-print" not in out.out
    assert "extra_secret_like_field" not in out.out


def test_student_evidence_json_exposes_raw_payload(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token="dummy-preview-token-for-test")

    def _fake_urlopen(_req: Any, timeout: float = 0) -> _FakeResponse:
        return _FakeResponse(
            status=200,
            body=(
                '{"schema_id":"qcoder.student_guided_evidence.v0",'
                '"sample_fingerprint":"intentional-json-field",'
                '"generated_basis":"hosted-demo",'
                '"samples":[]}'
            ),
        )

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "evidence", "--json"]) == 0
    out = capsys.readouterr()
    payload = json.loads(out.out)
    assert payload["schema_id"] == "qcoder.student_guided_evidence.v0"
    assert payload["sample_fingerprint"] == "intentional-json-field"
    assert payload["generated_basis"] == "hosted-demo"


def test_student_missing_base_url_returns_existing_actionable_env_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clear_preview_env(monkeypatch)
    monkeypatch.setenv("QCODER_PREVIEW_TOKEN", "dummy-preview-token-for-test")
    assert main(["student", "status"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("qcoder student: missing qCoder Student base URL")
    assert "QCODER_STUDENT_BASE_URL" in err
    assert "QCODER_PREVIEW_BASE_URL" in err
    assert "QCODER_PRO_API_URL" in err
    assert "qcoder pro preview" not in err
    assert "Pro Preview" not in err


def test_student_evidence_missing_base_url_returns_student_prefix(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clear_preview_env(monkeypatch)
    monkeypatch.setenv("QCODER_PREVIEW_TOKEN", "dummy-preview-token-for-test")
    assert main(["student", "evidence"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("qcoder student: missing qCoder Student base URL")
    assert "QCODER_STUDENT_BASE_URL" in err
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
    assert err.startswith("qcoder student: missing qCoder Student token")
    assert "QCODER_STUDENT_TOKEN" in err
    assert "QCODER_PREVIEW_TOKEN" in err
    assert "QCODER_PRO_TOKEN" in err
    assert "qcoder pro preview" not in err
    assert "Pro Preview" not in err


def test_student_evidence_missing_token_returns_student_prefix(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clear_preview_env(monkeypatch)
    monkeypatch.setenv("QCODER_PREVIEW_BASE_URL", "http://127.0.0.1:18081")
    assert main(["student", "evidence"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("qcoder student: missing qCoder Student token")
    assert "QCODER_STUDENT_TOKEN" in err
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
    assert "missing, invalid, revoked, or lacks Student access" in err
    assert token not in err
    assert "qcoder pro preview" not in err
    assert "Pro Preview" not in err


def test_student_evidence_http_401_returns_safe_auth_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    token = "wrong-token-for-test"
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token=token)

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        raise HTTPError(
            req.full_url,
            401,
            "Unauthorized",
            hdrs={},
            fp=io.BytesIO(b'{"error_code":"SCOPE_MISSING","message":"do not print token"}'),
        )

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "evidence"]) == 1
    err = capsys.readouterr().err
    assert "qCoder Student evidence: FAIL (HTTP 401)" in err
    assert "missing, invalid, revoked, or lacks Student evidence access" in err
    assert token not in err
    assert "Bearer" not in err
    assert "Authorization" not in err
    assert "SCOPE_MISSING" not in err


def test_student_evidence_http_403_returns_safe_auth_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    token = "wrong-scope-token-for-test"
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token=token)

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        raise HTTPError(req.full_url, 403, "Forbidden", hdrs={}, fp=io.BytesIO(b'{"error_code":"SCOPE_MISSING"}'))

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "evidence"]) == 1
    err = capsys.readouterr().err
    assert "qCoder Student evidence: FAIL (HTTP 403)" in err
    assert "does not have access to Student evidence" in err
    assert token not in err
    assert "Authorization" not in err


def test_student_evidence_network_failure_is_student_friendly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    token = "dummy-preview-token-for-test"
    _set_preview_env(monkeypatch, base_url="http://127.0.0.1:18081", token=token)

    def _fake_urlopen(_req: Any, timeout: float = 0) -> _FakeResponse:
        raise URLError("connection refused")

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "evidence"]) == 2
    err = capsys.readouterr().err
    assert "qCoder Student evidence: FAIL (network)" in err
    assert "check your base URL" in err
    assert token not in err
    assert "Authorization" not in err


def test_student_env_aliases_take_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_preview_env(monkeypatch)
    monkeypatch.setenv("QCODER_STUDENT_BASE_URL", "http://127.0.0.1:18081")
    monkeypatch.setenv("QCODER_STUDENT_TOKEN", "student-token-for-test")
    monkeypatch.setenv("QCODER_PREVIEW_BASE_URL", "http://127.0.0.1:18082")
    monkeypatch.setenv("QCODER_PREVIEW_TOKEN", "preview-token-for-test")
    captured: dict[str, str] = {}

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        captured["url"] = req.full_url
        captured["authorization"] = req.headers["Authorization"]
        return _FakeResponse(status=200, body='{"status":"ok"}')

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "status"]) == 0
    assert captured["url"] == "http://127.0.0.1:18081/v0/demo/builtin-review"
    assert captured["authorization"] == "Bearer student-token-for-test"


def test_student_preview_and_pro_env_compatibility_still_work(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_preview_env(monkeypatch)
    monkeypatch.setenv("QCODER_PRO_API_URL", "http://127.0.0.1:18083")
    monkeypatch.setenv("QCODER_PRO_TOKEN", "pro-token-for-test")
    captured: dict[str, str] = {}

    def _fake_urlopen(req: Any, timeout: float = 0) -> _FakeResponse:
        captured["url"] = req.full_url
        captured["authorization"] = req.headers["Authorization"]
        return _FakeResponse(status=200, body='{"status":"ok"}')

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    assert main(["student", "demo"]) == 0
    assert captured["url"] == "http://127.0.0.1:18083/v0/demo/builtin-review"
    assert captured["authorization"] == "Bearer pro-token-for-test"
