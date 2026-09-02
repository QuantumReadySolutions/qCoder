"""Versioned flat public motif baseline for account-free evidence facts."""

from __future__ import annotations

import hashlib
import json

PUBLIC_MOTIF_ALLOWLIST_SCHEMA_ID = "qcoder.public.flat_motif_allowlist.v1"
PUBLIC_MOTIF_ALLOWLIST_V1 = (
    "qiskit.circuit.construction",
    "qiskit.parameter.use",
    "qiskit.measurement.mapping",
    "qiskit.controlled.operations",
    "qiskit.result.processing",
    "grover.oracle.structure",
    "grover.diffusion.amplification",
    "grover.iteration.structure",
    "qaoa.cost.layer",
    "qaoa.mixer.layer",
    "qaoa.repetition.layer",
    "qaoa.parameterized.layer",
)


def public_motif_allowlist_v1() -> dict[str, object]:
    """Return the exact flat identifier baseline without hierarchy or scores."""
    return {
        "schema_id": PUBLIC_MOTIF_ALLOWLIST_SCHEMA_ID,
        "motifs": list(PUBLIC_MOTIF_ALLOWLIST_V1),
    }


def public_motif_allowlist_sha256() -> str:
    payload = json.dumps(
        public_motif_allowlist_v1(),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
