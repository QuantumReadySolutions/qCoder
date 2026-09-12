"""Public protected-decision transport boundary with truthful offline behavior."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping
import http.client
import re
import ssl
from urllib.parse import urlsplit

from qcoder import protected_blueprint_contract as blueprint

from qcoder.protected_capability import (
    ProtectedCapabilityCategory,
    ProtectedCapabilityOutcome,
    protected_capability_outcome,
)
from qcoder.protected_decision_validation import validate_request, validate_response

Transport = Callable[[Mapping[str, Any]], Mapping[str, Any]]

# Operational credential admission is not generic HTTPS syntax validation.
# No Stage D candidate destination has yet been authenticated/staged. Keep this
# exact (endpoint, release) set empty until that distinct source-bound step.
# Never populate it from CLI/environment input or a service response.
APPROVED_NATIVE_BLUEPRINT_DESTINATIONS: frozenset[tuple[str, str]] = frozenset()


def require_native_blueprint_destination(endpoint: str, release: str) -> None:
    if (endpoint, release) not in APPROVED_NATIVE_BLUEPRINT_DESTINATIONS:
        raise blueprint.ContractError("destination_not_admitted")


class ProtectedDecisionClient:
    """Validate one fixed contract; never select a fallback or grant local authority."""

    def __init__(self, *, transport: Transport | None = None) -> None:
        self._transport = transport

    def request(
        self, value: Mapping[str, Any], *, now: datetime | None = None
    ) -> tuple[ProtectedCapabilityOutcome, dict[str, Any] | None]:
        current = now or datetime.now(timezone.utc)
        request = validate_request(value, now=current)
        if self._transport is None:
            return (
                protected_capability_outcome(ProtectedCapabilityCategory.UNAVAILABLE),
                None,
            )
        response = validate_response(
            self._transport(request), now=now or datetime.now(timezone.utc)
        )
        if response["request_digest"] != request["request_digest"]:
            raise ValueError("protected_response_request_binding_mismatch")
        outcome = protected_capability_outcome(response["outcome"])
        return outcome, response.get("proposal")


class BlueprintHTTPTransport:
    """One HTTPS dispatch, bounded identity encoding, no redirect or retry.

    Endpoint/release are local configuration, never taken from a service response.
    Authentication is transient and separate from the canonical intent body.
    """

    def __init__(self, endpoint: str, *, timeout: float = 10.0):
        try:
            url = urlsplit(endpoint)
            port = url.port
        except ValueError:
            raise blueprint.ContractError("destination") from None
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path != blueprint.ROUTE
            or port not in (None, 443)
            or not 0 < timeout <= 10
        ):
            raise blueprint.ContractError("destination")
        self._host, self._path, self._timeout = url.hostname, url.path, timeout

    def _connection(self):
        return http.client.HTTPSConnection(
            self._host, timeout=self._timeout, context=ssl.create_default_context()
        )

    def exchange(self, request, *, bearer: str, caller_token: str = ""):
        if (
            type(bearer) is not str
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", bearer)
            or type(caller_token) is not str
            or (caller_token and not re.fullmatch(r"[A-Za-z0-9_.-]{1,8192}", caller_token))
        ):
            raise blueprint.ContractError("authentication_shape")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "X-QCoder-Entitlement-Token": bearer,
        }
        if caller_token:
            headers["Authorization"] = "Bearer " + caller_token
        connection = self._connection()
        try:
            connection.request("POST", self._path, body=blueprint.encode(request), headers=headers)
            response = connection.getresponse()
            pairs = response.getheaders()
            lowered = [k.lower() for k, _ in pairs]
            if len(lowered) != len(set(lowered)):
                raise blueprint.ContractError("duplicate_header")
            fields = {k.lower(): v for k, v in pairs}
            if (
                fields.get("content-type") != "application/json"
                or fields.get("content-encoding", "identity") != "identity"
                or "transfer-encoding" in fields
                or fields.get("cache-control") != "no-store"
            ):
                raise blueprint.ContractError("response_headers")
            length = fields.get("content-length", "")
            if (
                not 1 <= len(length) <= len(str(blueprint.MAX_BYTES))
                or not length.isascii()
                or not length.isdecimal()
                or not 0 < int(length) <= blueprint.MAX_BYTES
            ):
                raise blueprint.ContractError("response_size")
            raw = response.read(blueprint.MAX_BYTES + 1)
            if len(raw) != int(length):
                raise blueprint.ContractError("response_size")
            obj = blueprint.decode(raw)
            if response.status == 200:
                return obj
            # Error adaptation is exact and never retains an arbitrary error body.
            categories = {
                400: {"invalid"},
                401: {"unauthorized", "expired"},
                409: {"replay"},
                429: {"quota_limited"},
                503: {"unavailable"},
                422: {"unsupported"},
            }
            if (
                set(obj) != {"category"}
                or type(obj["category"]) is not str
                or obj["category"] not in categories.get(response.status, set())
            ):
                raise blueprint.ContractError("http_response")
            raise blueprint.ContractError(obj["category"])
        except (OSError, http.client.HTTPException):
            raise blueprint.ContractError("transport_unavailable") from None
        finally:
            connection.close()


class BlueprintClient:
    """Keep the complete envelope through validation and later local review."""

    def __init__(
        self, transport: BlueprintHTTPTransport | None, *, release: str, clock=blueprint.now_utc
    ):
        self.transport, self.release, self.clock = transport, release, clock

    def recommend(self, request, *, bearer, caller_token=""):
        normalized = blueprint.validate_request(request, self.clock())
        if self.transport is None:
            raise blueprint.ContractError("unavailable")
        response = self.transport.exchange(normalized, bearer=bearer, caller_token=caller_token)
        return blueprint.validate_response(response, normalized, self.release, self.clock())
