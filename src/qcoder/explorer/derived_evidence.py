from __future__ import annotations

import hashlib
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Mapping

from qcoder.pipelines.context import build_preflight_context

REQUEST_SCHEMA_ID = "qcoder.explorer.custom_guided_evidence.request.v0"
MAX_REQUEST_BYTES = 256 * 1024

_FORBIDDEN_KEYS = {
    "authorization",
    "auth_header",
    "cookie",
    "cookies",
    "counts",
    "counts_json",
    "headers",
    "local_path",
    "notebook",
    "path",
    "prompt",
    "qasm",
    "qasm_path",
    "qasm_text",
    "raw_counts",
    "raw_qasm",
    "raw_source",
    "source",
    "source_path",
    "source_text",
    "token",
}

_SELECTED_FEATURE_KEYS = (
    "n_qubits",
    "n_cbits",
    "n_ops",
    "real_depth",
    "entangling_depth",
    "n_2q_gate_ops",
    "n_measure_ops",
    "n_param_ops",
    "span_avg",
    "span_max",
    "span_long_range_ratio",
    "cut_max",
    "cut_mean",
    "cut_entropy",
    "n_active_cuts",
    "ig_n_edges",
    "ig_edge_density",
    "ig_avg_degree",
    "ig_is_connected",
)


class ExplorerDerivedEvidenceRequestError(ValueError):
    """Raised when a local artifact cannot be converted to a safe Explorer request."""


def _qcoder_version() -> str:
    try:
        return version("qcoder")
    except PackageNotFoundError:
        return "unknown"


def _load_context_json(path: str) -> dict[str, Any]:
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExplorerDerivedEvidenceRequestError("context JSON is not valid JSON") from exc
    if not isinstance(loaded, dict):
        raise ExplorerDerivedEvidenceRequestError("context JSON must be a JSON object")
    return loaded


def _walk_forbidden(obj: Any, *, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(obj, Mapping):
        for raw_key, value in obj.items():
            key = str(raw_key)
            key_l = key.lower()
            child_path = f"{path}.{key}"
            if key_l in _FORBIDDEN_KEYS:
                hits.append(child_path)
            hits.extend(_walk_forbidden(value, path=child_path))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            hits.extend(_walk_forbidden(value, path=f"{path}[{index}]"))
    return hits


def _require_context_shape(context: Mapping[str, Any]) -> None:
    if context.get("artifact_type") != "qcoder.preflight_context":
        raise ExplorerDerivedEvidenceRequestError("context JSON must be a qCoder preflight context artifact")
    circuit = context.get("circuit")
    analysis = context.get("analysis")
    hashes = context.get("hashes")
    if not isinstance(circuit, Mapping) or not isinstance(analysis, Mapping) or not isinstance(hashes, Mapping):
        raise ExplorerDerivedEvidenceRequestError("context JSON is missing required circuit, analysis, or hashes blocks")
    source_format = str(circuit.get("source_format") or "").lower()
    if source_format == "qasm3":
        raise ExplorerDerivedEvidenceRequestError(
            "OpenQASM 3 is not supported for Explorer derived evidence yet; export OpenQASM 2."
        )
    if source_format and source_format != "qasm2":
        raise ExplorerDerivedEvidenceRequestError("Explorer derived evidence currently accepts OpenQASM 2 context only")


def _safe_scalar(value: Any) -> str | int | float | bool | None:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def _safe_circuit_summary(circuit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_format": _safe_scalar(circuit.get("source_format")),
        "n_qubits": _safe_scalar(circuit.get("n_qubits")),
        "n_cbits": _safe_scalar(circuit.get("n_cbits")),
        "n_ops": _safe_scalar(circuit.get("n_ops")),
    }


def _safe_hashes(hashes: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in ("qasm_sha256", "analysis_fingerprint"):
        value = hashes.get(key)
        if isinstance(value, str) and value:
            out[key] = value
    return out


def _safe_feature_map(feature_map: Mapping[str, Any]) -> dict[str, int | float | bool]:
    out: dict[str, int | float | bool] = {}
    for key in _SELECTED_FEATURE_KEYS:
        value = feature_map.get(key)
        if isinstance(value, (int, float, bool)):
            out[key] = value
    return out


def _safe_feature_definitions(definitions: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in _SELECTED_FEATURE_KEYS:
        value = definitions.get(key)
        if isinstance(value, str) and value:
            out[key] = value
    return out


def _safe_guidance(guidance: Any) -> dict[str, Any] | None:
    if not isinstance(guidance, Mapping):
        return None
    out: dict[str, Any] = {}
    shot = guidance.get("shot_guidance")
    if isinstance(shot, Mapping):
        out["shot_guidance"] = {
            "applicability": _safe_scalar(shot.get("applicability")),
            "starting_shots": [
                value for value in list(shot.get("starting_shots") or [])[:4] if isinstance(value, (int, float))
            ],
        }
    sim = guidance.get("simulation_guidance")
    if isinstance(sim, Mapping):
        mps = sim.get("mps_bond_dimension")
        out["simulation_guidance"] = {
            "statevector_scale": _safe_scalar((sim.get("statevector") or {}).get("scale"))
            if isinstance(sim.get("statevector"), Mapping)
            else None,
            "mps_pressure": _safe_scalar(mps.get("pressure")) if isinstance(mps, Mapping) else None,
            "mps_starting_points": [
                value for value in list(mps.get("starting_points") or [])[:4] if isinstance(value, (int, float))
            ]
            if isinstance(mps, Mapping)
            else [],
        }
    return out or None


def _safe_profiles(feature_profiles: Any) -> dict[str, Any] | None:
    if not isinstance(feature_profiles, Mapping):
        return None
    profiles = feature_profiles.get("profiles")
    if not isinstance(profiles, Mapping):
        return None
    out: dict[str, Any] = {}
    for key in (
        "size_profile",
        "sampling_profile",
        "entanglement_profile",
        "topology_profile",
        "locality_profile",
        "simulation_pressure_profile",
    ):
        profile = profiles.get(key)
        if not isinstance(profile, Mapping):
            continue
        safe_profile: dict[str, Any] = {}
        labels = profile.get("labels")
        if isinstance(labels, list):
            safe_profile["labels"] = [str(item) for item in labels[:6] if isinstance(item, (str, int, float, bool))]
        tiers = profile.get("tiers")
        if isinstance(tiers, Mapping):
            safe_profile["tiers"] = {
                str(tier_key): tier_value
                for tier_key, tier_value in tiers.items()
                if isinstance(tier_value, (str, int, float, bool))
            }
        if safe_profile:
            out[key] = safe_profile
    return out or None


def _build_request_from_context(context: Mapping[str, Any], *, input_kind: str) -> dict[str, Any]:
    _require_context_shape(context)
    forbidden_hits = [
        hit for hit in _walk_forbidden(context) if not hit.startswith("$.circuit.qasm_path")
    ]
    if forbidden_hits:
        raise ExplorerDerivedEvidenceRequestError(
            "context JSON contains fields that cannot be sent to Explorer Beta derived evidence"
        )

    circuit = context["circuit"]
    analysis = context["analysis"]
    hashes = context["hashes"]
    feature_map = analysis.get("feature_map")
    if not isinstance(feature_map, Mapping):
        raise ExplorerDerivedEvidenceRequestError("context JSON is missing analysis.feature_map")

    safe_analysis: dict[str, Any] = {
        "selected_feature_map": _safe_feature_map(feature_map),
        "feature_definitions": _safe_feature_definitions(
            analysis.get("feature_definitions") if isinstance(analysis.get("feature_definitions"), Mapping) else {}
        ),
    }
    guidance = _safe_guidance(analysis.get("guidance"))
    if guidance is not None:
        safe_analysis["guidance"] = guidance
    profiles = _safe_profiles(analysis.get("feature_profiles"))
    if profiles is not None:
        safe_analysis["feature_profiles"] = profiles

    request = {
        "schema_id": REQUEST_SCHEMA_ID,
        "client": {
            "name": "qcoder",
            "version": _qcoder_version(),
            "command_namespace": "qcoder student",
            "compatibility_namespace": True,
        },
        "input_summary": {
            "input_kind": input_kind,
            "source_format": circuit.get("source_format"),
            "derived_locally": True,
            "raw_artifact_uploaded": False,
        },
        "fingerprints": _safe_hashes(hashes),
        "circuit_summary": _safe_circuit_summary(circuit),
        "derived_analysis": safe_analysis,
        "privacy_boundary": {
            "raw_qasm_included": False,
            "raw_source_text_included": False,
            "local_paths_included": False,
            "operation_list_included": False,
            "raw_counts_included": False,
            "notebooks_included": False,
            "prompts_included": False,
            "tokens_or_headers_included": False,
            "client_environment_included": False,
        },
        "non_claims_requested": [
            "No runtime prediction.",
            "No hardware execution or backend ranking.",
            "No fidelity or correctness proof.",
            "No quantum advantage claim.",
            "No persistent history in v0.",
        ],
    }
    _assert_safe_request(request)
    return request


def _assert_safe_request(request: Mapping[str, Any]) -> None:
    forbidden_hits = _walk_forbidden(request)
    if forbidden_hits:
        raise ExplorerDerivedEvidenceRequestError("derived evidence request still contains forbidden raw fields")
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_REQUEST_BYTES:
        raise ExplorerDerivedEvidenceRequestError("derived evidence request exceeds 256 KB safety cap")


def build_derived_evidence_request_from_qasm(qasm_path: str) -> dict[str, Any]:
    try:
        context = build_preflight_context(qasm_path, include_guidance=True, include_profiles=True)
    except NotImplementedError as exc:
        message = str(exc)
        if "OpenQASM 3" in message:
            raise ExplorerDerivedEvidenceRequestError(
                "OpenQASM 3 is not supported for Explorer derived evidence yet; export OpenQASM 2."
            ) from exc
        raise
    return _build_request_from_context(context, input_kind="local_qasm2_analysis")


def build_derived_evidence_request_from_context_json(context_json_path: str) -> dict[str, Any]:
    context = _load_context_json(context_json_path)
    return _build_request_from_context(context, input_kind="preflight_context_json")


def request_fingerprint(request: Mapping[str, Any]) -> str:
    raw = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

