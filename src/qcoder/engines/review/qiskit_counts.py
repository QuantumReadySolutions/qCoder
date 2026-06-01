from __future__ import annotations

from typing import Any

from .counts_v0 import normalize_counts_v0


def normalize_qiskit_counts_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("qiskit_counts payload must be a JSON object")

    if "counts" in payload and isinstance(payload.get("counts"), dict):
        counts_obj = payload["counts"]
    else:
        counts_obj = payload

    wrapped = {
        "schema": "qcoder.counts.v0",
        "counts": counts_obj,
        "shots_total": payload.get("shots_total"),
        "classical_width_expected": payload.get("classical_width_expected"),
        "notes": payload.get("notes") or [],
    }
    return normalize_counts_v0(wrapped)

