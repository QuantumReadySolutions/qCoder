"""One-time operator timing evidence for the private Current Loop stdio server."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile
import time
from typing import Any, Mapping


TIMING_EVIDENCE_SCHEMA_ID = "qcoder.current_loop.operator_stdio_timing.v1"
TIMING_EVIDENCE_FILENAME = "operator-stdio-timing.json"
MAX_TIMING_EVIDENCE_BYTES = 4_096
DEFAULT_MAXIMUM_AGE_SECONDS = 300.0
_TIMING_KEYS = {
    "schema_id",
    "schema_version",
    "server",
    "setup_binding_sha256",
    "session_binding_sha256",
    "receipt_id_sha256",
    "created_unix_ns",
    "operation_entry_offset_ns",
    "processing_complete_offset_ns",
    "result_return_offset_ns",
    "processing_ns",
    "return_ns",
    "total_ns",
    "retention",
    "audience",
    "customer_visible",
    "model_visible",
    "sensitive_payload_included",
}


class OperatorTimingEvidenceError(ValueError):
    """A bounded timing-evidence write or consumption failure."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _binding_digest(value: object, category: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise OperatorTimingEvidenceError(category)
    return sha256(value.encode("ascii")).hexdigest()


def _evidence_path(state_root: str | Path) -> Path:
    root = Path(state_root).expanduser().absolute()
    if root.is_symlink():
        raise OperatorTimingEvidenceError("operator_timing_state_root_symlink_rejected")
    if not root.is_dir():
        raise OperatorTimingEvidenceError("operator_timing_state_root_invalid")
    if os.name != "nt":
        root.chmod(0o700)
    return root / TIMING_EVIDENCE_FILENAME


def _atomic_write(path: Path, evidence: Mapping[str, Any]) -> None:
    if path.is_symlink():
        raise OperatorTimingEvidenceError("operator_timing_evidence_symlink_rejected")
    encoded = (json.dumps(dict(evidence), sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if len(encoded) > MAX_TIMING_EVIDENCE_BYTES:
        raise OperatorTimingEvidenceError("operator_timing_evidence_too_large")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
        if os.name != "nt":
            path.chmod(0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def record_stdio_operator_timing(
    *,
    state_root: str | Path,
    setup_generation: str,
    session_sha256: str,
    operation_entry_ns: int,
    processing_complete_ns: int,
    result_return_ns: int,
    wall_clock_ns: int | None = None,
) -> dict[str, Any]:
    """Replace the single bounded operator receipt after one stdio result is flushed."""

    if not (
        type(operation_entry_ns) is int
        and type(processing_complete_ns) is int
        and type(result_return_ns) is int
        and 0 <= operation_entry_ns <= processing_complete_ns <= result_return_ns
    ):
        raise OperatorTimingEvidenceError("operator_timing_boundaries_invalid")
    created = time.time_ns() if wall_clock_ns is None else wall_clock_ns
    if type(created) is not int or created <= 0:
        raise OperatorTimingEvidenceError("operator_timing_wall_clock_invalid")
    processing_ns = processing_complete_ns - operation_entry_ns
    return_ns = result_return_ns - processing_complete_ns
    evidence = {
        "schema_id": TIMING_EVIDENCE_SCHEMA_ID,
        "schema_version": 1,
        "server": "qcoder-current-loop",
        "setup_binding_sha256": _binding_digest(
            setup_generation, "operator_timing_setup_binding_invalid"
        ),
        "session_binding_sha256": _binding_digest(
            session_sha256, "operator_timing_session_binding_invalid"
        ),
        "receipt_id_sha256": sha256(secrets.token_bytes(32)).hexdigest(),
        "created_unix_ns": created,
        "operation_entry_offset_ns": 0,
        "processing_complete_offset_ns": processing_ns,
        "result_return_offset_ns": processing_ns + return_ns,
        "processing_ns": processing_ns,
        "return_ns": return_ns,
        "total_ns": processing_ns + return_ns,
        "retention": "consume_once_then_remove",
        "audience": "local_operator_only",
        "customer_visible": False,
        "model_visible": False,
        "sensitive_payload_included": False,
    }
    _atomic_write(_evidence_path(state_root), evidence)
    return dict(evidence)


def _read_evidence(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise OperatorTimingEvidenceError("operator_timing_evidence_not_found")
    if path.is_symlink():
        raise OperatorTimingEvidenceError("operator_timing_evidence_symlink_rejected")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise OperatorTimingEvidenceError("operator_timing_evidence_permissions_invalid")
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_TIMING_EVIDENCE_BYTES:
        raise OperatorTimingEvidenceError("operator_timing_evidence_size_invalid")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperatorTimingEvidenceError("operator_timing_evidence_invalid") from exc
    if not isinstance(value, dict) or set(value) != _TIMING_KEYS:
        raise OperatorTimingEvidenceError("operator_timing_evidence_shape_invalid")
    return value


def consume_stdio_operator_timing(
    *,
    state_root: str | Path,
    setup_generation: str,
    session_sha256: str,
    maximum_age_seconds: float = DEFAULT_MAXIMUM_AGE_SECONDS,
    wall_clock_ns: int | None = None,
) -> dict[str, Any]:
    """Validate, return, and remove one exact session-bound timing receipt."""

    if not 0.0 < float(maximum_age_seconds) <= 3_600.0:
        raise OperatorTimingEvidenceError("operator_timing_maximum_age_invalid")
    path = _evidence_path(state_root)
    evidence = _read_evidence(path)
    if evidence.get("setup_binding_sha256") != _binding_digest(
        setup_generation, "operator_timing_setup_binding_invalid"
    ):
        raise OperatorTimingEvidenceError("operator_timing_evidence_stale")
    if evidence.get("session_binding_sha256") != _binding_digest(
        session_sha256, "operator_timing_session_binding_invalid"
    ):
        raise OperatorTimingEvidenceError("operator_timing_evidence_cross_session")
    now = time.time_ns() if wall_clock_ns is None else wall_clock_ns
    created = evidence.get("created_unix_ns")
    if type(created) is not int or type(now) is not int:
        raise OperatorTimingEvidenceError("operator_timing_evidence_clock_invalid")
    age_ns = now - created
    if age_ns < 0 or age_ns > int(float(maximum_age_seconds) * 1_000_000_000):
        raise OperatorTimingEvidenceError("operator_timing_evidence_stale")
    for key in (
        "operation_entry_offset_ns",
        "processing_complete_offset_ns",
        "result_return_offset_ns",
        "processing_ns",
        "return_ns",
        "total_ns",
    ):
        if type(evidence.get(key)) is not int or evidence[key] < 0:
            raise OperatorTimingEvidenceError("operator_timing_evidence_numeric_invalid")
    if not (
        evidence["operation_entry_offset_ns"] == 0
        and evidence["processing_complete_offset_ns"] == evidence["processing_ns"]
        and evidence["result_return_offset_ns"] == evidence["total_ns"]
        and evidence["processing_ns"] + evidence["return_ns"] == evidence["total_ns"]
    ):
        raise OperatorTimingEvidenceError("operator_timing_evidence_relationship_invalid")
    if (
        evidence.get("schema_id") != TIMING_EVIDENCE_SCHEMA_ID
        or evidence.get("schema_version") != 1
        or evidence.get("server") != "qcoder-current-loop"
        or evidence.get("retention") != "consume_once_then_remove"
        or evidence.get("audience") != "local_operator_only"
        or evidence.get("customer_visible") is not False
        or evidence.get("model_visible") is not False
        or evidence.get("sensitive_payload_included") is not False
    ):
        raise OperatorTimingEvidenceError("operator_timing_evidence_contract_invalid")
    path.unlink()
    return dict(evidence)


def clear_stdio_operator_timing(*, state_root: str | Path) -> None:
    """Remove a stale local operator receipt without reading its contents."""

    if not Path(state_root).expanduser().absolute().exists():
        return
    path = _evidence_path(state_root)
    if path.is_symlink():
        raise OperatorTimingEvidenceError("operator_timing_evidence_symlink_rejected")
    path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consume one local qCoder stdio timing receipt.")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--setup-generation", required=True)
    parser.add_argument("--session-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        evidence = consume_stdio_operator_timing(
            state_root=args.state_root,
            setup_generation=args.setup_generation,
            session_sha256=args.session_sha256,
        )
    except OperatorTimingEvidenceError as exc:
        print(json.dumps({"ok": False, "category": exc.category}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "timing_evidence": evidence}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_MAXIMUM_AGE_SECONDS",
    "MAX_TIMING_EVIDENCE_BYTES",
    "TIMING_EVIDENCE_FILENAME",
    "TIMING_EVIDENCE_SCHEMA_ID",
    "OperatorTimingEvidenceError",
    "clear_stdio_operator_timing",
    "consume_stdio_operator_timing",
    "record_stdio_operator_timing",
]
