from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ServiceErrorDetail:
    status_code: int | None
    error_code: str | None
    message: str


class ProServiceClientError(RuntimeError):
    """Raised when a Pro Preview service request fails."""

    def __init__(self, detail: ServiceErrorDetail) -> None:
        self.detail = detail
        super().__init__(detail.message)


class ProServiceClient:
    """Small stdlib HTTP client for explicit Pro workflow submit."""

    def __init__(self, *, base_url: str, timeout_s: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout_s = timeout_s

    def post_entitlements_validate(self, token: str) -> dict[str, Any]:
        return self._post_json("/v0/entitlements/validate", payload={}, token=token)

    def post_workflow(self, manifest: dict[str, Any], token: str) -> dict[str, Any]:
        return self._post_json("/v0/workflows", payload=manifest, token=token)

    def _post_json(self, path: str, *, payload: dict[str, Any], token: str) -> dict[str, Any]:
        url = _join_service_url(self._base_url, path)
        request = Request(
            url=url,
            method="POST",
            data=json.dumps(payload, sort_keys=True).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_s) as response:
                raw = response.read()
                status = getattr(response, "status", 200)
        except HTTPError as exc:
            detail = _parse_http_error(exc)
            raise ProServiceClientError(detail) from exc
        except URLError as exc:
            raise ProServiceClientError(
                ServiceErrorDetail(
                    status_code=None,
                    error_code="SERVICE_UNAVAILABLE",
                    message="unable to reach configured service",
                )
            ) from exc

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProServiceClientError(
                ServiceErrorDetail(
                    status_code=status,
                    error_code="INVALID_SERVICE_RESPONSE",
                    message="service returned non-JSON response",
                )
            ) from exc

        if not isinstance(parsed, dict):
            raise ProServiceClientError(
                ServiceErrorDetail(
                    status_code=status,
                    error_code="INVALID_SERVICE_RESPONSE",
                    message="service response must be a JSON object",
                )
            )
        return parsed


def _join_service_url(base_url: str, path: str) -> str:
    if not path.startswith("/"):
        raise ValueError("service path must start with '/'")
    return urljoin(base_url, path.lstrip("/"))


def _parse_http_error(exc: HTTPError) -> ServiceErrorDetail:
    status_code = exc.code
    raw_text = ""
    try:
        raw_text = exc.read(4096).decode("utf-8", errors="replace")
    except Exception:
        raw_text = ""

    error_code: str | None = None
    message: str | None = None
    if raw_text:
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            raw_error_code = parsed.get("error_code")
            raw_message = parsed.get("message")
            if isinstance(raw_error_code, str) and raw_error_code:
                error_code = raw_error_code
            if isinstance(raw_message, str) and raw_message:
                message = raw_message

    if message:
        safe_message = message
    else:
        safe_message = f"service returned HTTP {status_code}"
    return ServiceErrorDetail(status_code=status_code, error_code=error_code, message=safe_message)
