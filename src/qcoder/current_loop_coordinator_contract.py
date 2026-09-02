"""Directional public construction seam for the local Current Loop kernel."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_IMPLEMENTATION = "qcoder.current_loop_coordinator_public_kernel"


class CurrentLoopCoordinator:
    """Compatibility constructor without a static authority-to-policy import."""

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        implementation = import_module(_IMPLEMENTATION).CurrentLoopCoordinator
        return implementation(*args, **kwargs)


def coordinator_contract_snapshot() -> dict[str, Any]:
    return import_module(_IMPLEMENTATION).coordinator_contract_snapshot()
