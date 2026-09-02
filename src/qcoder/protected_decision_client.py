"""Public protected-decision transport boundary with truthful offline behavior."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from qcoder.protected_capability import (
    ProtectedCapabilityCategory,
    ProtectedCapabilityOutcome,
    protected_capability_outcome,
)
from qcoder.protected_decision_validation import validate_request, validate_response

Transport = Callable[[Mapping[str, Any]], Mapping[str, Any]]


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
        response = validate_response(self._transport(request), now=current)
        if response["request_digest"] != request["request_digest"]:
            raise ValueError("protected_response_request_binding_mismatch")
        outcome = protected_capability_outcome(response["outcome"])
        return outcome, response.get("proposal")
