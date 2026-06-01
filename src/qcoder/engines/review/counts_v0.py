from __future__ import annotations

from typing import Any


def _to_int_count(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("count values must be numeric integers, not booleans")
    if isinstance(value, int):
        out = value
    elif isinstance(value, float) and value.is_integer():
        out = int(value)
    elif isinstance(value, str) and value.isdigit():
        out = int(value)
    else:
        raise ValueError(f"invalid count value: {value!r}")
    if out < 0:
        raise ValueError(f"count must be non-negative: {value!r}")
    return out


def _validate_bitstring_key(key: str) -> str:
    if not isinstance(key, str):
        raise ValueError("bitstring keys must be strings")
    k = key.replace(" ", "").strip()
    if not k:
        raise ValueError("bitstring key cannot be empty")
    if any(ch not in {"0", "1"} for ch in k):
        raise ValueError(f"bitstring key must contain only 0/1: {key!r}")
    return k


def normalize_counts_v0(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("counts payload must be a JSON object")
    schema = payload.get("schema")
    if schema not in {None, "qcoder.counts.v0"}:
        raise ValueError(f"unsupported counts schema: {schema!r}")
    counts_raw = payload.get("counts")
    if not isinstance(counts_raw, dict) or not counts_raw:
        raise ValueError("counts must be a non-empty object")

    counts: dict[str, int] = {}
    widths: set[int] = set()
    for key, value in counts_raw.items():
        k = _validate_bitstring_key(key)
        c = _to_int_count(value)
        counts[k] = counts.get(k, 0) + c
        widths.add(len(k))

    shots_total = payload.get("shots_total")
    if shots_total is None:
        shots = int(sum(counts.values()))
    else:
        shots = _to_int_count(shots_total)

    classical_width_expected = payload.get("classical_width_expected")
    if classical_width_expected is not None:
        classical_width_expected = _to_int_count(classical_width_expected)

    notes = payload.get("notes") or []
    if not isinstance(notes, list):
        raise ValueError("notes must be a list when provided")
    notes_out = [str(x) for x in notes]

    return {
        "schema": "qcoder.counts.v0",
        "counts": dict(sorted(counts.items(), key=lambda kv: kv[0])),
        "shots_total": shots,
        "classical_width_expected": classical_width_expected,
        "notes": notes_out,
    }

