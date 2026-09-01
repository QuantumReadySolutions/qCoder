"""Consume-once operator ledger for private begin_current_loop attempts."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import tempfile
import time
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

ATTEMPT_LEDGER_SCHEMA_ID = "qcoder.current_loop.begin_attempt_ledger.v1"
ATTEMPT_SCHEMA_ID = "qcoder.current_loop.begin_attempt.v1"
ATTEMPT_LEDGER_FILENAME = "operator-begin-attempt-ledger-v1.json"
MAX_ATTEMPT_LEDGER_BYTES = 16_384
MAX_BEGIN_ATTEMPTS = 8
DEFAULT_MAXIMUM_AGE_SECONDS = 300.0
_STATUSES = {"accepted", "terminal_blocker", "terminal_rejected"}
_ATTEMPT_KEYS = {
    "schema_id",
    "schema_version",
    "server",
    "operation_name",
    "status",
    "category",
    "setup_binding_sha256",
    "session_binding_sha256",
    "attempt_id_sha256",
    "semantic_revision_sha256",
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


def _path(state_root: str | Path) -> Path:
    root = Path(state_root).expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise OperatorTimingEvidenceError("operator_attempt_ledger_state_root_invalid")
    if os.name != "nt":
        root.chmod(0o700)
    return root / ATTEMPT_LEDGER_FILENAME


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    encoded = (json.dumps(dict(value), sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(encoded) > MAX_ATTEMPT_LEDGER_BYTES:
        raise OperatorTimingEvidenceError("operator_attempt_ledger_too_large")
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


def _read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or (os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o600):
        raise OperatorTimingEvidenceError("operator_attempt_ledger_permissions_invalid")
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_ATTEMPT_LEDGER_BYTES:
        raise OperatorTimingEvidenceError("operator_attempt_ledger_size_invalid")
    try:
        value = json.loads(raw.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperatorTimingEvidenceError("operator_attempt_ledger_invalid") from exc
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_id",
            "schema_version",
            "setup_binding_sha256",
            "session_binding_sha256",
            "attempts",
        }
        or value.get("schema_id") != ATTEMPT_LEDGER_SCHEMA_ID
        or value.get("schema_version") != 1
        or not isinstance(value.get("attempts"), list)
        or len(value["attempts"]) > MAX_BEGIN_ATTEMPTS
    ):
        raise OperatorTimingEvidenceError("operator_attempt_ledger_shape_invalid")
    return value


def record_begin_attempt(
    *,
    state_root: str | Path,
    setup_generation: str,
    session_sha256: str,
    status: str,
    category: str,
    operation_entry_ns: int,
    processing_complete_ns: int,
    result_return_ns: int,
    semantic_revision_sha256: str | None = None,
    wall_clock_ns: int | None = None,
) -> dict[str, Any]:
    """Append one sanitized begin_current_loop attempt."""

    if status not in _STATUSES:
        raise OperatorTimingEvidenceError("operator_attempt_status_invalid")
    if (
        not isinstance(category, str)
        or not category
        or len(category) > 96
        or not category.replace("_", "").isalnum()
    ):
        raise OperatorTimingEvidenceError("operator_attempt_category_invalid")
    if not (
        type(operation_entry_ns) is int
        and type(processing_complete_ns) is int
        and type(result_return_ns) is int
        and 0 <= operation_entry_ns < processing_complete_ns <= result_return_ns
    ):
        raise OperatorTimingEvidenceError("operator_attempt_boundaries_invalid")
    if semantic_revision_sha256 is not None and (
        len(semantic_revision_sha256) != 64
        or any(character not in "0123456789abcdef" for character in semantic_revision_sha256)
    ):
        raise OperatorTimingEvidenceError("operator_attempt_semantic_revision_invalid")
    setup_digest = _binding_digest(setup_generation, "operator_attempt_setup_binding_invalid")
    session_digest = _binding_digest(session_sha256, "operator_attempt_session_binding_invalid")
    processing_ns = processing_complete_ns - operation_entry_ns
    return_ns = result_return_ns - processing_complete_ns
    attempt = {
        "schema_id": ATTEMPT_SCHEMA_ID,
        "schema_version": 1,
        "server": "qcoder-current-loop",
        "operation_name": "begin_current_loop",
        "status": status,
        "category": category,
        "setup_binding_sha256": setup_digest,
        "session_binding_sha256": session_digest,
        "attempt_id_sha256": sha256(secrets.token_bytes(32)).hexdigest(),
        "semantic_revision_sha256": semantic_revision_sha256,
        "created_unix_ns": time.time_ns() if wall_clock_ns is None else wall_clock_ns,
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
    path = _path(state_root)
    ledger = _read(path) or {
        "schema_id": ATTEMPT_LEDGER_SCHEMA_ID,
        "schema_version": 1,
        "setup_binding_sha256": setup_digest,
        "session_binding_sha256": session_digest,
        "attempts": [],
    }
    if ledger.get("setup_binding_sha256") != setup_digest:
        raise OperatorTimingEvidenceError("operator_attempt_ledger_stale")
    if ledger.get("session_binding_sha256") != session_digest:
        raise OperatorTimingEvidenceError("operator_attempt_ledger_cross_session")
    attempts = [dict(item) for item in ledger["attempts"] if isinstance(item, Mapping)]
    attempts.append(attempt)
    ledger["attempts"] = attempts[-MAX_BEGIN_ATTEMPTS:]
    _atomic_write(path, ledger)
    return dict(attempt)


def consume_begin_attempt_ledger(
    *,
    state_root: str | Path,
    setup_generation: str,
    session_sha256: str,
    maximum_age_seconds: float = DEFAULT_MAXIMUM_AGE_SECONDS,
    wall_clock_ns: int | None = None,
) -> dict[str, Any]:
    """Validate and consume the complete session-bound ledger once."""

    path = _path(state_root)
    ledger = _read(path)
    if ledger is None:
        raise OperatorTimingEvidenceError("operator_attempt_ledger_not_found")
    setup_digest = _binding_digest(setup_generation, "operator_attempt_setup_binding_invalid")
    session_digest = _binding_digest(session_sha256, "operator_attempt_session_binding_invalid")
    if ledger.get("setup_binding_sha256") != setup_digest:
        raise OperatorTimingEvidenceError("operator_attempt_ledger_stale")
    if ledger.get("session_binding_sha256") != session_digest:
        raise OperatorTimingEvidenceError("operator_attempt_ledger_cross_session")
    now = time.time_ns() if wall_clock_ns is None else wall_clock_ns
    attempts = ledger["attempts"]
    if not attempts:
        raise OperatorTimingEvidenceError("operator_attempt_ledger_not_found")
    for attempt in attempts:
        if not isinstance(attempt, dict) or set(attempt) != _ATTEMPT_KEYS:
            raise OperatorTimingEvidenceError("operator_attempt_shape_invalid")
        created = attempt.get("created_unix_ns")
        if (
            attempt.get("schema_id") != ATTEMPT_SCHEMA_ID
            or attempt.get("operation_name") != "begin_current_loop"
            or attempt.get("status") not in _STATUSES
            or not isinstance(created, int)
            or now - created < 0
            or now - created > int(maximum_age_seconds * 1_000_000_000)
            or not isinstance(attempt.get("processing_ns"), int)
            or attempt["processing_ns"] <= 0
            or not isinstance(attempt.get("return_ns"), int)
            or attempt["return_ns"] < 0
            or attempt.get("total_ns") != attempt["processing_ns"] + attempt["return_ns"]
            or attempt.get("customer_visible") is not False
            or attempt.get("model_visible") is not False
            or attempt.get("sensitive_payload_included") is not False
        ):
            raise OperatorTimingEvidenceError("operator_attempt_contract_invalid")
    path.unlink(missing_ok=True)
    return dict(ledger)


def clear_begin_attempt_ledger(*, state_root: str | Path) -> None:
    path = _path(state_root)
    if path.is_symlink():
        raise OperatorTimingEvidenceError("operator_attempt_ledger_symlink_rejected")
    path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consume one qCoder begin-attempt ledger.")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--setup-generation", required=True)
    parser.add_argument("--session-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        ledger = consume_begin_attempt_ledger(
            state_root=args.state_root,
            setup_generation=args.setup_generation,
            session_sha256=args.session_sha256,
        )
    except OperatorTimingEvidenceError as exc:
        print(json.dumps({"ok": False, "category": exc.category}, sort_keys=True))
        return 2
    print(json.dumps({"ok": True, "attempt_ledger": ledger}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ATTEMPT_LEDGER_FILENAME",
    "ATTEMPT_LEDGER_SCHEMA_ID",
    "DEFAULT_MAXIMUM_AGE_SECONDS",
    "MAX_ATTEMPT_LEDGER_BYTES",
    "MAX_BEGIN_ATTEMPTS",
    "OperatorTimingEvidenceError",
    "clear_begin_attempt_ledger",
    "consume_begin_attempt_ledger",
    "record_begin_attempt",
]
