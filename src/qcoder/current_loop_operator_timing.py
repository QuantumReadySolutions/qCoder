"""Consume-once operator timing for accepted private Current Loop operations."""

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

TIMING_EVIDENCE_SCHEMA_ID = "qcoder.current_loop.operator_stdio_timing.v2"
TIMING_EVIDENCE_FILENAME = "operator-stdio-timing-v2.json"
MAX_TIMING_EVIDENCE_BYTES = 16_384
MAX_TIMING_RECEIPTS = 8
DEFAULT_MAXIMUM_AGE_SECONDS = 300.0
_OPERATIONS = {"begin_current_loop", "complete_current_step"}
_RECEIPT_KEYS = {
    "schema_id",
    "schema_version",
    "server",
    "operation_name",
    "setup_binding_sha256",
    "session_binding_sha256",
    "receipt_id_sha256",
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
        raise OperatorTimingEvidenceError("operator_timing_state_root_invalid")
    if os.name != "nt":
        root.chmod(0o700)
    return root / TIMING_EVIDENCE_FILENAME


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    encoded = (json.dumps(dict(value), sort_keys=True, separators=(",", ":")) + "\n").encode()
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


def _read_store(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_symlink() or (os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != 0o600):
        raise OperatorTimingEvidenceError("operator_timing_evidence_permissions_invalid")
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_TIMING_EVIDENCE_BYTES:
        raise OperatorTimingEvidenceError("operator_timing_evidence_size_invalid")
    try:
        value = json.loads(raw.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperatorTimingEvidenceError("operator_timing_evidence_invalid") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_id", "schema_version", "receipts"}
        or value.get("schema_id") != "qcoder.current_loop.operator_stdio_timing_store.v2"
        or value.get("schema_version") != 2
        or not isinstance(value.get("receipts"), list)
        or len(value["receipts"]) > MAX_TIMING_RECEIPTS
    ):
        raise OperatorTimingEvidenceError("operator_timing_evidence_store_invalid")
    return [dict(item) for item in value["receipts"] if isinstance(item, Mapping)]


def _write_store(path: Path, receipts: list[dict[str, Any]]) -> None:
    if receipts:
        _atomic_write(
            path,
            {
                "schema_id": "qcoder.current_loop.operator_stdio_timing_store.v2",
                "schema_version": 2,
                "receipts": receipts[-MAX_TIMING_RECEIPTS:],
            },
        )
    else:
        path.unlink(missing_ok=True)


def record_stdio_operator_timing(
    *,
    state_root: str | Path,
    setup_generation: str,
    session_sha256: str,
    operation_name: str,
    operation_entry_ns: int,
    processing_complete_ns: int,
    result_return_ns: int,
    semantic_revision_sha256: str | None = None,
    wall_clock_ns: int | None = None,
) -> dict[str, Any]:
    """Append one accepted-operation receipt; discovery can never replace it."""

    if operation_name not in _OPERATIONS:
        raise OperatorTimingEvidenceError("operator_timing_operation_invalid")
    if not (
        type(operation_entry_ns) is int
        and type(processing_complete_ns) is int
        and type(result_return_ns) is int
        and 0 <= operation_entry_ns < processing_complete_ns <= result_return_ns
    ):
        raise OperatorTimingEvidenceError("operator_timing_boundaries_invalid")
    if semantic_revision_sha256 is not None and (
        len(semantic_revision_sha256) != 64
        or any(character not in "0123456789abcdef" for character in semantic_revision_sha256)
    ):
        raise OperatorTimingEvidenceError("operator_timing_semantic_revision_invalid")
    created = time.time_ns() if wall_clock_ns is None else wall_clock_ns
    processing_ns = processing_complete_ns - operation_entry_ns
    return_ns = result_return_ns - processing_complete_ns
    receipt = {
        "schema_id": TIMING_EVIDENCE_SCHEMA_ID,
        "schema_version": 2,
        "server": "qcoder-current-loop",
        "operation_name": operation_name,
        "setup_binding_sha256": _binding_digest(
            setup_generation, "operator_timing_setup_binding_invalid"
        ),
        "session_binding_sha256": _binding_digest(
            session_sha256, "operator_timing_session_binding_invalid"
        ),
        "receipt_id_sha256": sha256(secrets.token_bytes(32)).hexdigest(),
        "semantic_revision_sha256": semantic_revision_sha256,
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
    path = _path(state_root)
    receipts = _read_store(path)
    receipts.append(receipt)
    _write_store(path, receipts)
    return dict(receipt)


def consume_stdio_operator_timing(
    *,
    state_root: str | Path,
    setup_generation: str,
    session_sha256: str,
    operation_name: str | None = None,
    receipt_id_sha256: str | None = None,
    maximum_age_seconds: float = DEFAULT_MAXIMUM_AGE_SECONDS,
    wall_clock_ns: int | None = None,
) -> dict[str, Any]:
    """Consume exactly one matching, session-bound accepted-operation receipt."""

    if operation_name is not None and operation_name not in _OPERATIONS:
        raise OperatorTimingEvidenceError("operator_timing_operation_invalid")
    path = _path(state_root)
    receipts = _read_store(path)
    if not receipts:
        raise OperatorTimingEvidenceError("operator_timing_evidence_not_found")
    matches = [
        (index, receipt)
        for index, receipt in enumerate(receipts)
        if (operation_name is None or receipt.get("operation_name") == operation_name)
        and (receipt_id_sha256 is None or receipt.get("receipt_id_sha256") == receipt_id_sha256)
    ]
    if not matches:
        raise OperatorTimingEvidenceError("operator_timing_evidence_not_found")
    index, evidence = matches[0]
    if set(evidence) != _RECEIPT_KEYS:
        raise OperatorTimingEvidenceError("operator_timing_evidence_shape_invalid")
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
    if (
        not isinstance(created, int)
        or now - created < 0
        or now - created > int(maximum_age_seconds * 1_000_000_000)
    ):
        raise OperatorTimingEvidenceError("operator_timing_evidence_stale")
    if (
        evidence.get("schema_id") != TIMING_EVIDENCE_SCHEMA_ID
        or evidence.get("schema_version") != 2
        or evidence.get("operation_name") not in _OPERATIONS
        or not isinstance(evidence.get("processing_ns"), int)
        or evidence["processing_ns"] <= 0
        or not isinstance(evidence.get("return_ns"), int)
        or evidence["return_ns"] < 0
        or evidence.get("total_ns") != evidence["processing_ns"] + evidence["return_ns"]
        or evidence.get("retention") != "consume_once_then_remove"
        or evidence.get("audience") != "local_operator_only"
        or evidence.get("customer_visible") is not False
        or evidence.get("model_visible") is not False
        or evidence.get("sensitive_payload_included") is not False
    ):
        raise OperatorTimingEvidenceError("operator_timing_evidence_contract_invalid")
    del receipts[index]
    _write_store(path, receipts)
    return dict(evidence)


def clear_stdio_operator_timing(*, state_root: str | Path) -> None:
    path = _path(state_root)
    if path.is_symlink():
        raise OperatorTimingEvidenceError("operator_timing_evidence_symlink_rejected")
    path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consume one qCoder operation timing receipt.")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--setup-generation", required=True)
    parser.add_argument("--session-sha256", required=True)
    parser.add_argument("--operation")
    args = parser.parse_args(argv)
    try:
        evidence = consume_stdio_operator_timing(
            state_root=args.state_root,
            setup_generation=args.setup_generation,
            session_sha256=args.session_sha256,
            operation_name=args.operation,
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
