"""Canonical serialization, digests, and strict value validation for the focused loop.

The canonical form is the frozen house convention already used by the current-loop
evidence modules: UTF-8 JSON with ``ensure_ascii=True``, ``sort_keys=True``, compact
``(",", ":")`` separators, and a SHA-256 hex digest. Non-finite floats, duplicate
object keys, and prose-wrapped payloads are rejected rather than repaired.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import math
from typing import Any

MAX_CANONICAL_BYTES = 256 * 1024
MAX_TEXT_BYTES = 1_024
MAX_LIST_ITEMS = 64
DIGEST_LENGTH = 64
_HEX = frozenset("0123456789abcdef")


class FocusedLoopError(ValueError):
    """Bounded, machine-readable failure for every focused-loop contract."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def canonical_bytes(value: object) -> bytes:
    """Return the canonical UTF-8 JSON encoding of ``value``."""
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FocusedLoopError("canonical_serialization_unsupported_value") from exc
    if len(encoded) > MAX_CANONICAL_BYTES:
        raise FocusedLoopError("canonical_serialization_too_large")
    return encoded


def canonical_digest(value: object) -> str:
    """Return the SHA-256 hex digest of the canonical encoding of ``value``."""
    return sha256(canonical_bytes(value)).hexdigest()


def digest_excluding(payload: Mapping[str, Any], *, field: str) -> str:
    """Digest ``payload`` with its own self-digest field removed."""
    if not isinstance(payload, Mapping):
        raise FocusedLoopError("canonical_payload_invalid")
    return canonical_digest({key: value for key, value in payload.items() if key != field})


def is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == DIGEST_LENGTH
        and all(character in _HEX for character in value)
    )


def digest_text(value: object, *, category: str) -> str:
    if not is_digest(value):
        raise FocusedLoopError(category)
    return str(value)


def strict_mapping(
    value: object,
    *,
    required: Sequence[str],
    optional: Sequence[str] = (),
    category: str,
) -> dict[str, Any]:
    """Validate exact field presence: every required key present, no unknown key."""
    if not isinstance(value, Mapping):
        raise FocusedLoopError(category)
    keys = set(value)
    if any(not isinstance(key, str) for key in keys):
        raise FocusedLoopError(category)
    if not keys.issuperset(required) or not keys.issubset(set(required) | set(optional)):
        raise FocusedLoopError(category)
    return dict(value)


def bounded_text(value: object, *, category: str, max_bytes: int = MAX_TEXT_BYTES) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or value != value.strip()
        or len(value.encode("utf-8")) > max_bytes
    ):
        raise FocusedLoopError(category)
    return value


def bounded_text_list(
    value: object,
    *,
    category: str,
    max_items: int = MAX_LIST_ITEMS,
) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise FocusedLoopError(category)
    if len(value) > max_items:
        raise FocusedLoopError(category)
    items = [bounded_text(item, category=category) for item in value]
    if len(items) != len(set(items)):
        raise FocusedLoopError(category)
    return items


def enum_value(value: object, *, allowed: Sequence[str], category: str) -> str:
    if not isinstance(value, str) or value not in set(allowed):
        raise FocusedLoopError(category)
    return value


def strict_bool(value: object, *, category: str) -> bool:
    if not isinstance(value, bool):
        raise FocusedLoopError(category)
    return value


def strict_int(
    value: object,
    *,
    category: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise FocusedLoopError(category)
    if minimum is not None and value < minimum:
        raise FocusedLoopError(category)
    if maximum is not None and value > maximum:
        raise FocusedLoopError(category)
    return value


def strict_float(
    value: object,
    *,
    category: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FocusedLoopError(category)
    number = float(value)
    if not math.isfinite(number):
        raise FocusedLoopError(category)
    if minimum is not None and number < minimum:
        raise FocusedLoopError(category)
    if maximum is not None and number > maximum:
        raise FocusedLoopError(category)
    return number


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FocusedLoopError("typed_payload_duplicate_key")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise FocusedLoopError("typed_payload_non_finite_number")


def strict_typed_object(text: object, *, category: str) -> dict[str, Any]:
    """Parse one exact typed JSON object from ``text``.

    This is the machine-control channel. The whole input must be a single JSON
    object. Prose before or after the object, duplicate keys, non-finite numbers,
    and non-object payloads are rejected. No substring or heuristic extraction is
    ever attempted.
    """
    if not isinstance(text, str) or not text or len(text.encode("utf-8")) > MAX_CANONICAL_BYTES:
        raise FocusedLoopError(category)
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except FocusedLoopError:
        raise
    except (TypeError, ValueError) as exc:
        raise FocusedLoopError(category) from exc
    if not isinstance(parsed, dict):
        raise FocusedLoopError(category)
    return parsed
