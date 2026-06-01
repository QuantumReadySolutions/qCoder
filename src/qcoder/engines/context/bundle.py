from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qcoder.engines.feature_extraction.features.glossary_v0 import (
    STRUCTURAL_SUMMARY_FEATURES,
    full_feature_definitions,
    selected_feature_definitions,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def qasm_sha256(path: str) -> str:
    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest()


def context_bundle_basis(analysis: dict[str, Any]) -> str:
    """Human-readable bundle basis from which optional blocks are included."""
    has_g = "guidance" in analysis
    has_p = "feature_profiles" in analysis
    if has_g and has_p:
        return "deterministic_analysis_plus_guidance_and_profiles"
    if has_g:
        return "deterministic_analysis_plus_guidance"
    if has_p:
        return "deterministic_analysis_plus_profiles"
    return "deterministic_analysis"


def analysis_fingerprint(analysis: dict[str, Any]) -> str:
    canonical = {
        "features": analysis.get("features", {}),
        "feature_map": analysis.get("feature_map", {}),
    }
    if "feature_profiles" in analysis:
        canonical["feature_profiles"] = analysis.get("feature_profiles", {})
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_context_bundle(
    *,
    qasm_path: str,
    analysis: dict[str, Any],
    qcoder_version: str,
    generated_utc: str | None = None,
    include_full_features: bool = False,
) -> dict[str, Any]:
    circuit = {
        "qasm_path": analysis.get("qasm_path", qasm_path),
        "circuit_id": analysis.get("circuit_id"),
        "circuit_name": analysis.get("circuit_name"),
        "source_format": analysis.get("source_format"),
        "n_qubits": analysis.get("n_qubits"),
        "n_cbits": analysis.get("n_cbits"),
        "n_ops": analysis.get("n_ops"),
    }
    defs = full_feature_definitions() if include_full_features else selected_feature_definitions(STRUCTURAL_SUMMARY_FEATURES)
    defs_scope = "full" if include_full_features else "selected"
    analysis_block: dict[str, Any] = {
        "features": analysis.get("features", {}),
        "feature_map": analysis.get("feature_map", {}),
        "feature_definitions": defs,
        "feature_definitions_scope": defs_scope,
    }
    if "guidance" in analysis:
        analysis_block["guidance"] = analysis["guidance"]
    if "feature_profiles" in analysis:
        analysis_block["feature_profiles"] = analysis["feature_profiles"]

    llm_limits = [
        "Do not interpret this artifact as simulator or hardware execution evidence.",
        "Guidance is heuristic and non-guaranteed when present.",
    ]
    if "feature_profiles" in analysis:
        llm_limits.append(
            "Feature profiles are deterministic structural taxonomy, not execution evidence."
        )

    return {
        "context_bundle_schema_version": "0.1",
        "artifact_type": "qcoder.preflight_context",
        "basis": context_bundle_basis(analysis),
        "generated_utc": generated_utc or utc_now_iso(),
        "qcoder_version": qcoder_version,
        "circuit": circuit,
        "hashes": {
            "qasm_sha256": qasm_sha256(qasm_path),
            "analysis_fingerprint": analysis_fingerprint(analysis),
        },
        "analysis": analysis_block,
        "assumptions": [
            "No backend execution was performed.",
            "This artifact is deterministic context, not execution results.",
        ],
        "llm_use": {
            "intended_use": "Attach or paste this artifact for AI-assisted circuit planning.",
            "limits": llm_limits,
        },
    }

