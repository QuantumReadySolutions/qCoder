from __future__ import annotations

# Backwards-compatible shim.
# Prefer: from qcoder.core.run_config import RunConfig
from qcoder.core.run_config import (
    CPU_ALIASES,
    GPU_ALIASES,
    SINGLE_ALIASES,
    DOUBLE_ALIASES,
    RunConfig,
    normalize_backend,
    normalize_precision,
)

# Older code referred to Context; keep it as an alias.
Context = RunConfig
