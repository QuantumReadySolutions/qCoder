"""Policy-free compatibility facade for historical coordinator imports."""

from __future__ import annotations

import sys
from importlib import import_module
from typing import Any

from qcoder.protected_capability import (
    ProtectedCapabilityCategory,
    protected_capability_outcome,
)

_BASELINE = "qcoder.current_loop_coordinator_public_kernel"


def protected_capability_state(
    category: str = ProtectedCapabilityCategory.UNAVAILABLE.value,
) -> dict[str, Any]:
    return protected_capability_outcome(category).as_dict()


_module = import_module(_BASELINE)
_module.protected_capability_state = protected_capability_state
sys.modules[__name__] = _module
