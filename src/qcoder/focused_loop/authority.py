"""Separate ``execution_authority.v1`` record and the single-use attempt ledger.

Authority is a distinct object from the plan and is never inferred. qCoder does not
derive authority from chat, from a prior grant, from adjacency, or from the mere
existence of a committed plan. One authority binds to exactly one ``plan_digest`` and
carries exactly one single-use ``attempt_identity``; the ledger below enforces that at
most one qualified execution attempt may consume that identity.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from qcoder.focused_loop.canonical import (
    FocusedLoopError,
    bounded_text,
    digest_excluding,
    digest_text,
    enum_value,
    strict_bool,
    strict_float,
    strict_mapping,
)
from qcoder.focused_loop.identities import EXECUTION_AUTHORITY_SCHEMA_ID

AUTHORITY_DIGEST_FIELD = "authority_digest"
GRANTED_BY_NATIVE_CLIENT_CUSTOMER_ACTION = "native_client_customer_action"
ALLOWED_GRANTED_BY = (GRANTED_BY_NATIVE_CLIENT_CUSTOMER_ACTION,)
MAX_ATTEMPT_IDENTITY_BYTES = 128
MAX_LEDGER_ENTRIES = 1_024

AUTHORITY_FIELDS = (
    "schema_id",
    "plan_digest",
    "granted_by",
    "displayed_plan_digest",
    "attempt_identity",
    "expires_at",
    "single_use",
    AUTHORITY_DIGEST_FIELD,
)


def attempt_identity_text(value: object) -> str:
    """Validate one bounded attempt identity string."""
    return bounded_text(
        value,
        category="execution_authority_attempt_identity_invalid",
        max_bytes=MAX_ATTEMPT_IDENTITY_BYTES,
    )


def _normalize_authority_body(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_id") != EXECUTION_AUTHORITY_SCHEMA_ID:
        raise FocusedLoopError("execution_authority_schema_invalid")
    single_use = strict_bool(
        value.get("single_use"), category="execution_authority_not_single_use"
    )
    if single_use is not True:
        raise FocusedLoopError("execution_authority_not_single_use")
    return {
        "schema_id": EXECUTION_AUTHORITY_SCHEMA_ID,
        "plan_digest": digest_text(
            value.get("plan_digest"), category="execution_authority_plan_digest_invalid"
        ),
        "granted_by": enum_value(
            value.get("granted_by"),
            allowed=ALLOWED_GRANTED_BY,
            category="execution_authority_granted_by_unsupported",
        ),
        "displayed_plan_digest": digest_text(
            value.get("displayed_plan_digest"),
            category="execution_authority_displayed_plan_digest_invalid",
        ),
        "attempt_identity": attempt_identity_text(value.get("attempt_identity")),
        "expires_at": strict_float(
            value.get("expires_at"), category="execution_authority_expires_at_invalid"
        ),
        "single_use": True,
    }


def build_execution_authority(
    *,
    plan_digest: str,
    attempt_identity: str,
    expires_at: float,
    displayed_plan_digest: str | None = None,
    granted_by: str = GRANTED_BY_NATIVE_CLIENT_CUSTOMER_ACTION,
    single_use: bool = True,
) -> dict[str, Any]:
    """Return one self-digesting authority record bound to exactly one plan digest."""
    payload = {
        "schema_id": EXECUTION_AUTHORITY_SCHEMA_ID,
        "plan_digest": plan_digest,
        "granted_by": granted_by,
        "displayed_plan_digest": (
            plan_digest if displayed_plan_digest is None else displayed_plan_digest
        ),
        "attempt_identity": attempt_identity,
        "expires_at": expires_at,
        "single_use": single_use,
    }
    normalized = _normalize_authority_body(payload)
    normalized[AUTHORITY_DIGEST_FIELD] = digest_excluding(
        normalized, field=AUTHORITY_DIGEST_FIELD
    )
    return normalized


def validate_execution_authority(
    payload: Mapping[str, Any],
    *,
    plan_digest: str,
    now: float,
) -> dict[str, Any]:
    """Validate one authority against the exact plan digest it must carry.

    ``now`` is supplied explicitly so that expiry evaluation stays pure and testable.
    """
    strict = strict_mapping(
        payload, required=AUTHORITY_FIELDS, category="execution_authority_schema_invalid"
    )
    normalized = _normalize_authority_body(strict)
    expected_digest = digest_excluding(normalized, field=AUTHORITY_DIGEST_FIELD)
    if strict.get(AUTHORITY_DIGEST_FIELD) != expected_digest:
        raise FocusedLoopError("execution_authority_digest_mismatch")
    expected_plan = digest_text(
        plan_digest, category="execution_authority_plan_digest_invalid"
    )
    if normalized["plan_digest"] != expected_plan:
        raise FocusedLoopError("execution_authority_plan_digest_mismatch")
    if normalized["displayed_plan_digest"] != normalized["plan_digest"]:
        raise FocusedLoopError("execution_authority_displayed_plan_stale")
    observed_now = strict_float(now, category="execution_authority_expires_at_invalid")
    if observed_now >= normalized["expires_at"]:
        raise FocusedLoopError("execution_authority_expired")
    normalized[AUTHORITY_DIGEST_FIELD] = expected_digest
    return normalized


def consumed_identities(value: Iterable[str] | None) -> frozenset[str]:
    """Coerce an explicit iterable of consumed attempt identities into a frozen set."""
    if value is None:
        return frozenset()
    if isinstance(value, AttemptLedger):
        return value.consumed
    if isinstance(value, (str, bytes, bytearray)):
        raise FocusedLoopError("execution_attempt_ledger_invalid")
    identities = frozenset(attempt_identity_text(item) for item in value)
    if len(identities) > MAX_LEDGER_ENTRIES:
        raise FocusedLoopError("execution_attempt_ledger_overflow")
    return identities


def consume_attempt_identity(
    consumed: Iterable[str] | None, attempt_identity: str
) -> frozenset[str]:
    """Return the consumed set extended by ``attempt_identity``.

    Pure: the caller owns the resulting state. A second consumption of the same
    identity is refused rather than silently ignored.
    """
    current = consumed_identities(consumed)
    identity = attempt_identity_text(attempt_identity)
    if identity in current:
        raise FocusedLoopError("execution_attempt_identity_already_consumed")
    if len(current) >= MAX_LEDGER_ENTRIES:
        raise FocusedLoopError("execution_attempt_ledger_overflow")
    return current | {identity}


@dataclass(frozen=True)
class AttemptLedger:
    """Immutable in-memory record of attempt identities already spent.

    There is no module-level state: every transition returns a new ledger, so the
    caller must thread the ledger explicitly through the execution boundary.
    """

    consumed: frozenset[str] = frozenset()

    @classmethod
    def empty(cls) -> AttemptLedger:
        return cls(frozenset())

    @classmethod
    def of(cls, identities: Iterable[str] | None) -> AttemptLedger:
        return cls(consumed_identities(identities))

    def is_consumed(self, attempt_identity: str) -> bool:
        return attempt_identity_text(attempt_identity) in self.consumed

    def require_unconsumed(self, attempt_identity: str) -> str:
        identity = attempt_identity_text(attempt_identity)
        if identity in self.consumed:
            raise FocusedLoopError("execution_attempt_identity_already_consumed")
        return identity

    def consume(self, attempt_identity: str) -> AttemptLedger:
        return AttemptLedger(consume_attempt_identity(self.consumed, attempt_identity))


__all__ = [
    "AUTHORITY_DIGEST_FIELD",
    "AUTHORITY_FIELDS",
    "ALLOWED_GRANTED_BY",
    "AttemptLedger",
    "GRANTED_BY_NATIVE_CLIENT_CUSTOMER_ACTION",
    "attempt_identity_text",
    "build_execution_authority",
    "consume_attempt_identity",
    "consumed_identities",
    "validate_execution_authority",
]
