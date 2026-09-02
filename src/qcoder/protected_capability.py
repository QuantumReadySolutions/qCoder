"""Public, policy-free protected capability outcome vocabulary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

PROTECTED_CAPABILITY_SCHEMA_ID = "qcoder.protected_capability.outcome.v1"


class ProtectedCapabilityCategory(StrEnum):
    """Closed public result categories; none grants local authority."""

    COMPLETED = "protected_capability_completed"
    UNAVAILABLE = "protected_capability_unavailable"
    UNAUTHORIZED = "protected_capability_unauthorized"
    EXPIRED = "protected_capability_expired"
    QUOTA_LIMITED = "protected_capability_quota_limited"
    UNSUPPORTED_CONTRACT = "protected_capability_unsupported_contract"


@dataclass(frozen=True)
class ProtectedCapabilityOutcome:
    schema_id: str
    category: str
    local_authority_granted: bool
    local_effect_performed: bool
    historical_policy_fallback: bool
    retry_performed: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def protected_capability_outcome(
    category: ProtectedCapabilityCategory | str,
) -> ProtectedCapabilityOutcome:
    normalized = ProtectedCapabilityCategory(category)
    return ProtectedCapabilityOutcome(
        schema_id=PROTECTED_CAPABILITY_SCHEMA_ID,
        category=normalized.value,
        local_authority_granted=False,
        local_effect_performed=False,
        historical_policy_fallback=False,
        retry_performed=False,
    )


def protected_capability_unavailable() -> ProtectedCapabilityOutcome:
    """Normal Stage B outcome: no service behavior exists yet."""

    return protected_capability_outcome(ProtectedCapabilityCategory.UNAVAILABLE)
