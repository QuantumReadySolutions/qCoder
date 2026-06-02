from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError

import pytest

from qcoder.pro_preview.client import ProServiceClient, ProServiceClientError


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.status = status
        self._wire = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._wire

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        return None


def test_post_entitlements_validate_posts_expected_path_and_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["auth"] = req.headers.get("Authorization")
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse({"schema_id": "qcoder.pro_service.entitlements.v0", "valid": True})

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    client = ProServiceClient(base_url="http://127.0.0.1:8765")
    payload = client.post_entitlements_validate("dev-token-123")
    assert payload["valid"] is True
    assert captured["url"] == "http://127.0.0.1:8765/v0/entitlements/validate"
    assert captured["auth"] == "Bearer dev-token-123"
    assert captured["body"] == {}
    assert captured["timeout"] == 10.0


def test_post_workflow_posts_manifest_json(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse({"schema_id": "qcoder.pro_service.workflow_job.v0", "job_id": "job-123", "state": "succeeded"})

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    client = ProServiceClient(base_url="http://localhost:8765/")
    payload = client.post_workflow({"schema_id": "qcoder.pro_preview.workflow_manifest.v0"}, "dev-token-123")
    assert payload["job_id"] == "job-123"
    assert captured["url"] == "http://localhost:8765/v0/workflows"
    assert captured["body"] == {"schema_id": "qcoder.pro_preview.workflow_manifest.v0"}


def test_http_error_maps_to_bounded_error_details(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
        body = io.BytesIO(json.dumps({"error_code": "ENTITLEMENT_INVALID", "message": "token rejected"}).encode("utf-8"))
        raise HTTPError(req.full_url, 401, "Unauthorized", hdrs=None, fp=body)

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    client = ProServiceClient(base_url="http://127.0.0.1:8765")
    with pytest.raises(ProServiceClientError) as excinfo:
        client.post_entitlements_validate("dev-token-123")
    assert excinfo.value.detail.status_code == 401
    assert excinfo.value.detail.error_code == "ENTITLEMENT_INVALID"
    assert "token rejected" in excinfo.value.detail.message


def test_url_error_maps_to_service_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_urlopen(req, timeout=0):  # type: ignore[no-untyped-def]
        raise URLError("connection refused")

    monkeypatch.setattr("qcoder.pro_preview.client.urlopen", _fake_urlopen)
    client = ProServiceClient(base_url="http://127.0.0.1:8765")
    with pytest.raises(ProServiceClientError) as excinfo:
        client.post_workflow({"schema_id": "qcoder.pro_preview.workflow_manifest.v0"}, "dev-token-123")
    assert excinfo.value.detail.error_code == "SERVICE_UNAVAILABLE"
