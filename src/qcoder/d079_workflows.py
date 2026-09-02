"""Policy-free compatibility facade for historical workflow imports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from qcoder.protected_capability import (
    ProtectedCapabilityCategory,
    protected_capability_outcome,
)

_BASELINE = "qcoder.d079_workflows_public_oss"


def protected_capability_state(
    category: str = ProtectedCapabilityCategory.UNAVAILABLE.value,
) -> dict[str, Any]:
    return protected_capability_outcome(category).as_dict()


def _baseline() -> Any:
    return import_module(_BASELINE)


def __getattr__(name: str) -> Any:
    return getattr(_baseline(), name)


__all__ = sorted(name for name in dir(_baseline()) if not name.startswith("_"))
