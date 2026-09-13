"""Purpose-limited privacy projections for focused-loop records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from qcoder.focused_loop.canonical import FocusedLoopError, digest_excluding, enum_value

PROJECTION_ID = "qcoder.focused_loop.privacy_projection.v1"
PROJECTION_DIGEST_FIELD = "projection_digest"

DESTINATION_LOCAL_DETERMINISTIC = "local_deterministic"
DESTINATION_DEVELOPER = "developer"
DESTINATION_MODEL_DECISION_CONTEXT = "model_decision_context"
DESTINATION_PROTECTED_SERVICE = "protected_service"

DESTINATIONS = (
    DESTINATION_LOCAL_DETERMINISTIC,
    DESTINATION_DEVELOPER,
    DESTINATION_MODEL_DECISION_CONTEXT,
    DESTINATION_PROTECTED_SERVICE,
)

#: Destinations that are neither the local deterministic engine nor the local developer.
#: Every prohibited field class is withheld from these.
RESTRICTED_DESTINATIONS = (
    DESTINATION_MODEL_DECISION_CONTEXT,
    DESTINATION_PROTECTED_SERVICE,
)

#: The single explicit prohibited-key rule. Field class -> exact key names (casefolded)
#: that carry that class of information anywhere in a record tree.
PROHIBITED_FIELD_CLASSES: Mapping[str, tuple[str, ...]] = {
    "credential": (
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    ),
    "filesystem_path": (
        "artifact_path",
        "file_path",
        "output_directory",
        "path",
        "source_path",
        "working_directory",
    ),
    "machine_identity": (
        "home_directory",
        "host",
        "hostname",
        "machine_id",
        "user",
        "username",
    ),
    "raw_counts": (
        "counts",
        "memory",
        "raw_counts",
        "shot_records",
    ),
    "raw_customer_source": (
        "customer_source",
        "program_source",
        "source_text",
    ),
    "raw_qasm": (
        "circuit_qasm",
        "qasm",
        "qasm_text",
    ),
    "raw_resource_detail": (
        "available_floor_bytes",
        "reserve_bytes",
        "total_memory_bytes",
    ),
}

#: Credentials are never permitted at any destination, including the local engine.
UNIVERSALLY_PROHIBITED_CLASSES = ("credential",)

#: Classes withheld from the local developer surface. Raw QASM, counts and paths stay
#: available there because that surface exists to debug local evidence.
DEVELOPER_PROHIBITED_CLASSES = ("credential", "machine_identity")

#: Every class is withheld from the model and protected-service surfaces. The derived
#: ``safe_envelope_bytes`` and its coarse band survive; raw total/available/reserve do not.
RESTRICTED_PROHIBITED_CLASSES = tuple(sorted(PROHIBITED_FIELD_CLASSES))

PROHIBITED_CLASSES_BY_DESTINATION: Mapping[str, tuple[str, ...]] = {
    DESTINATION_LOCAL_DETERMINISTIC: UNIVERSALLY_PROHIBITED_CLASSES,
    DESTINATION_DEVELOPER: DEVELOPER_PROHIBITED_CLASSES,
    DESTINATION_MODEL_DECISION_CONTEXT: RESTRICTED_PROHIBITED_CLASSES,
    DESTINATION_PROTECTED_SERVICE: RESTRICTED_PROHIBITED_CLASSES,
}

#: Derived resource fields that remain safe for every destination.
PERMITTED_RESOURCE_FIELDS = ("safe_envelope_bytes", "safe_envelope_band")

MAX_PROJECTION_DEPTH = 8


def prohibited_keys_for(destination: str) -> frozenset[str]:
    """Return every casefolded key name withheld from ``destination``."""
    target = enum_value(
        destination, allowed=DESTINATIONS, category="privacy_destination_unsupported"
    )
    return frozenset(
        key
        for field_class in PROHIBITED_CLASSES_BY_DESTINATION[target]
        for key in PROHIBITED_FIELD_CLASSES[field_class]
    )


def _project_value(value: Any, *, withheld: frozenset[str], depth: int, found: set[str]) -> Any:
    if depth > MAX_PROJECTION_DEPTH:
        raise FocusedLoopError("privacy_projection_depth_exceeded")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise FocusedLoopError("privacy_record_invalid")
            if key.casefold() in withheld:
                found.add(key)
                continue
            result[key] = _project_value(
                item, withheld=withheld, depth=depth + 1, found=found
            )
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _project_value(item, withheld=withheld, depth=depth + 1, found=found)
            for item in value
        ]
    if isinstance(value, (bytes, bytearray)):
        raise FocusedLoopError("privacy_unprojectable_value")
    return value


def project_record(record: Mapping[str, Any], *, destination: str) -> dict[str, Any]:
    """Return the purpose-limited projection of ``record`` for ``destination``.

    Prohibited fields are omitted, never redacted in place and never summarized into a
    value that reconstructs them. The projection carries the source record digest so it
    stays traceable, and its own digest over the projected content.
    """
    target = enum_value(
        destination, allowed=DESTINATIONS, category="privacy_destination_unsupported"
    )
    if not isinstance(record, Mapping) or not record:
        raise FocusedLoopError("privacy_record_invalid")
    withheld = prohibited_keys_for(target)
    found: set[str] = set()
    projected = _project_value(dict(record), withheld=withheld, depth=0, found=found)
    if not isinstance(projected, dict):
        raise FocusedLoopError("privacy_record_invalid")
    projected.pop("record_digest", None)
    payload: dict[str, Any] = {
        "privacy_projection_id": PROJECTION_ID,
        "privacy_destination": target,
        "source_schema_id": record.get("schema_id"),
        "source_record_digest": record.get("record_digest"),
        "fields_withheld": sorted(found),
        "field_classes_withheld": list(PROHIBITED_CLASSES_BY_DESTINATION[target]),
        **projected,
    }
    leaked = sorted(key for key in collect_keys(payload) if key.casefold() in withheld)
    if leaked:
        raise FocusedLoopError("privacy_projection_leak_detected")
    payload[PROJECTION_DIGEST_FIELD] = digest_excluding(payload, field=PROJECTION_DIGEST_FIELD)
    return payload


def collect_keys(value: Any, *, depth: int = 0) -> set[str]:
    """Return every mapping key appearing anywhere in ``value``."""
    if depth > MAX_PROJECTION_DEPTH:
        raise FocusedLoopError("privacy_projection_depth_exceeded")
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            keys.add(str(key))
            keys |= collect_keys(item, depth=depth + 1)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            keys |= collect_keys(item, depth=depth + 1)
    return keys


def assert_no_prohibited_keys(value: Any, *, destination: str) -> None:
    """Raise when ``value`` carries any key prohibited at ``destination``."""
    withheld = prohibited_keys_for(destination)
    if any(key.casefold() in withheld for key in collect_keys(value)):
        raise FocusedLoopError("privacy_projection_leak_detected")
