"""Compatibility facade for historical public Blueprint imports.

The existing Apache-licensed baseline remains reachable for compatibility. The
future protected capability is separate and never falls back to that baseline.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from qcoder.protected_capability import (
    ProtectedCapabilityCategory,
    protected_capability_outcome,
)

_BASELINE = "qcoder.algorithm_blueprint_public_oss"


def protected_capability_state(
    category: str = ProtectedCapabilityCategory.UNAVAILABLE.value,
) -> dict[str, Any]:
    return protected_capability_outcome(category).as_dict()


def _baseline() -> Any:
    return import_module(_BASELINE)


def __getattr__(name: str) -> Any:
    return getattr(_baseline(), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_baseline())))


__all__ = sorted(name for name in dir(_baseline()) if not name.startswith("_"))
