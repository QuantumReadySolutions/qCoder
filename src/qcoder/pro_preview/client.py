from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import Any, Mapping
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

PREVIEW_BASE_URL_ENV = "QCODER_PREVIEW_BASE_URL"
PREVIEW_TOKEN_ENV = "QCODER_PREVIEW_TOKEN"
STUDENT_BASE_URL_ENV = "QCODER_STUDENT_BASE_URL"
STUDENT_TOKEN_ENV = "QCODER_STUDENT_TOKEN"
PRO_API_URL_ENV = "QCODER_PRO_API_URL"
PRO_TOKEN_ENV = "QCODER_PRO_TOKEN"
BUILTIN_REVIEW_PATH = "/v0/demo/builtin-review"
STUDENT_GUIDED_EVIDENCE_PATH = "/v0/student/guided-evidence"
EXPLORER_CUSTOM_GUIDED_EVIDENCE_PATH = "/v0/explorer/custom-guided-evidence"
STUDENT_CUSTOM_GUIDED_EVIDENCE_PATH = "/v0/student/custom-guided-evidence"


@dataclass(frozen=True)
class PreviewClientConfig:
    base_url: str
    token: str


@dataclass(frozen=True)
class PreviewClientResponse:
    status_code: int
    payload: dict[str, Any] | None


class PreviewClientNetworkError(RuntimeError):
    """Raised when hosted Preview cannot be reached."""


def resolve_preview_client_config(
    *,
    base_url_override: str | None = None,
    env_map: Mapping[str, str] | None = None,
    include_student_aliases: bool = False,
) -> PreviewClientConfig:
    env = os.environ if env_map is None else env_map
    if include_student_aliases:
        env_base_url = str(
            env.get(STUDENT_BASE_URL_ENV)
            or env.get(PREVIEW_BASE_URL_ENV)
            or env.get(PRO_API_URL_ENV)
            or ""
        )
        token = str(env.get(STUDENT_TOKEN_ENV) or env.get(PREVIEW_TOKEN_ENV) or env.get(PRO_TOKEN_ENV) or "").strip()
    else:
        env_base_url = str(env.get(PREVIEW_BASE_URL_ENV) or env.get(PRO_API_URL_ENV) or "")
        token = str(env.get(PREVIEW_TOKEN_ENV) or env.get(PRO_TOKEN_ENV) or "").strip()
    base_url = _normalize_base_url(
        base_url_override
        if base_url_override is not None
        else env_base_url,
        include_student_aliases=include_student_aliases,
    )
    if not token:
        if include_student_aliases:
            raise ValueError(
                "missing qCoder Explorer Beta token; set QCODER_STUDENT_TOKEN, "
                "QCODER_PREVIEW_TOKEN, or QCODER_PRO_TOKEN"
            )
        raise ValueError(
            "missing hosted Preview token; set QCODER_PREVIEW_TOKEN or QCODER_PRO_TOKEN"
        )
    return PreviewClientConfig(base_url=base_url, token=token)


def call_builtin_review_demo(
    config: PreviewClientConfig, *, timeout_s: float = 10.0
) -> PreviewClientResponse:
    """Call the hosted Preview builtin-review demo endpoint.

    HTTP 401/403 are valid service responses and must not be treated as
    network failures.  HTTPError is a subclass of URLError, so keep this
    handler before the URLError handler.
    """
    request = Request(
        _join_service_url(config.base_url, BUILTIN_REVIEW_PATH),
        headers={"Authorization": f"Bearer {config.token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", 200))
            return PreviewClientResponse(status_code=status_code, payload=_safe_json_decode(body))
    except HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        return PreviewClientResponse(status_code=int(err.code), payload=_safe_json_decode(body))
    except URLError as exc:
        raise PreviewClientNetworkError(str(exc)) from exc


def call_student_guided_evidence(
    config: PreviewClientConfig, *, timeout_s: float = 10.0
) -> PreviewClientResponse:
    """Call the hosted Student guided-evidence endpoint."""
    request = Request(
        _join_service_url(config.base_url, STUDENT_GUIDED_EVIDENCE_PATH),
        headers={"Authorization": f"Bearer {config.token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", 200))
            return PreviewClientResponse(status_code=status_code, payload=_safe_json_decode(body))
    except HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        return PreviewClientResponse(status_code=int(err.code), payload=_safe_json_decode(body))
    except URLError as exc:
        raise PreviewClientNetworkError(str(exc)) from exc


def call_student_custom_guided_evidence(
    config: PreviewClientConfig,
    *,
    payload: dict[str, Any],
    timeout_s: float = 10.0,
) -> PreviewClientResponse:
    """Call the Explorer Beta derived-context guided-evidence endpoint."""
    request = Request(
        _join_service_url(config.base_url, EXPLORER_CUSTOM_GUIDED_EVIDENCE_PATH),
        data=json.dumps(payload, sort_keys=True).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {config.token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", 200))
            return PreviewClientResponse(status_code=status_code, payload=_safe_json_decode(body))
    except HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        return PreviewClientResponse(status_code=int(err.code), payload=_safe_json_decode(body))
    except URLError as exc:
        raise PreviewClientNetworkError(str(exc)) from exc


def summarize_demo_payload(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return []
    lines: list[str] = []
    for key in ("service", "mode", "status", "demo_level"):
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)):
            lines.append(f"  {key}: {value}")
    samples = payload.get("samples")
    if isinstance(samples, list):
        lines.append(f"  samples: {len(samples)}")
    return lines


def _normalize_base_url(raw_base_url: str, *, include_student_aliases: bool = False) -> str:
    base_url = raw_base_url.strip().rstrip("/")
    if not base_url:
        if include_student_aliases:
            raise ValueError(
                "missing qCoder Explorer Beta base URL; set QCODER_STUDENT_BASE_URL, "
                "QCODER_PREVIEW_BASE_URL, or QCODER_PRO_API_URL, or pass --base-url"
            )
        raise ValueError(
            "missing hosted Preview base URL; set QCODER_PREVIEW_BASE_URL or "
            "QCODER_PRO_API_URL, or pass --base-url"
        )
    return base_url


def _safe_json_decode(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
