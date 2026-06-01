"""Local resource guidance JSON pack: load, validate, and shadow evaluation (stdlib only, no network)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from typing import Any, Mapping

PACK_RESOURCE = "resource_guidance_local_v0.json"
PACK_PACKAGE = "qcoder.model_packs"

ALLOWED_OPS = frozenset({"<", "<=", "==", ">=", ">"})
REQUIRED_NON_CLAIMS = frozenset(
    {
        "not_optimality_proof",
        "not_fidelity_proof",
        "not_hardware_correctness_proof",
        "not_runtime_guarantee",
        "not_backend_ranking",
        "not_causal_savings",
    }
)
EXPECTED_OUTPUT_MAPPING = {
    "mps_pressure": "simulation_guidance.mps_bond_dimension.pressure",
    "mps_ladder": "simulation_guidance.mps_bond_dimension.starting_points",
}
REQUIRED_TOP_LEVEL = (
    "model_pack_schema_version",
    "model_pack_id",
    "model_pack_version",
    "target_feature_schema_versions",
    "targets",
    "rule_evaluation",
    "condition_logic",
    "no_match_behavior",
    "training_data",
    "features",
    "support_bounds",
    "outputs",
    "output_mapping",
    "rules",
    "fallback",
    "non_claims",
)
EXPECTED_FEATURES = frozenset(
    {
        "n_qubits",
        "n_cbits",
        "n_measure_ops",
        "n_2q_gate_ops",
        "n_param_ops",
        "real_depth",
        "entangling_depth",
        "n_entangling_layers",
        "cut_max",
        "cut_mean",
        "cut_entropy",
        "n_active_cuts",
        "span_avg",
        "span_max",
        "span_long_range_ratio",
        "ig_edge_density",
        "ig_avg_degree",
        "ig_is_connected",
    }
)


@dataclass(frozen=True)
class ResourceGuidancePack:
    """Validated resource guidance pack (shadow / metadata only in v0)."""

    model_pack_id: str
    model_pack_version: str
    model_pack_schema_version: str
    sha256_hex: str
    data: dict[str, Any]


def compute_pack_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _feat(feature_map: Mapping[str, Any], key: str) -> float:
    value = feature_map.get(key, 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _float(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _condition_matches(feature_map: Mapping[str, Any], cond: Mapping[str, Any]) -> bool:
    feat = cond.get("feature")
    op = cond.get("op")
    val = cond.get("value")
    if feat not in EXPECTED_FEATURES or op not in ALLOWED_OPS:
        return False
    lhs = _feat(feature_map, str(feat))
    rhs = _float(val)
    if rhs is None:
        return False
    if op == "<":
        return lhs < rhs
    if op == "<=":
        return lhs <= rhs
    if op == "==":
        return lhs == rhs
    if op == ">=":
        return lhs >= rhs
    if op == ">":
        return lhs > rhs
    return False


def _trivial_catchall(cond: Mapping[str, Any], *, n_qubits_min: float) -> bool:
    feat = cond.get("feature")
    op = cond.get("op")
    rhs = _float(cond.get("value"))
    if rhs is None or feat not in EXPECTED_FEATURES or op not in ALLOWED_OPS:
        return False
    if feat == "n_qubits" and op == ">=":
        if rhs <= 0:
            return True
        if rhs <= n_qubits_min:
            return True
    if op == ">=" and rhs <= 0:
        return True
    return False


def validate_resource_guidance_pack(data: Mapping[str, Any]) -> list[str]:
    """Return a list of validation errors; empty means the pack is acceptable."""
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["root must be a JSON object"]

    for key in REQUIRED_TOP_LEVEL:
        if key not in data:
            errors.append(f"missing top-level key: {key}")

    if data.get("model_pack_schema_version") != "resource_guidance_pack.v0":
        errors.append("model_pack_schema_version must be resource_guidance_pack.v0")

    targets = data.get("targets")
    if targets != ["mps_pressure", "mps_bond_ladder"]:
        errors.append("targets must be exactly ['mps_pressure', 'mps_bond_ladder']")

    if data.get("rule_evaluation") != "first_match":
        errors.append("rule_evaluation must be 'first_match'")

    if data.get("condition_logic") != "all":
        errors.append("condition_logic must be 'all'")

    if data.get("no_match_behavior") != "fallback_deterministic":
        errors.append("no_match_behavior must be 'fallback_deterministic'")

    om = data.get("output_mapping")
    if om != EXPECTED_OUTPUT_MAPPING:
        errors.append("output_mapping must match expected public guidance paths")

    nc = data.get("non_claims", [])
    if not isinstance(nc, list) or frozenset(nc) != REQUIRED_NON_CLAIMS or len(nc) != len(REQUIRED_NON_CLAIMS):
        errors.append("non_claims must contain exactly the required non-claim keys")

    feats = data.get("features", [])
    if not isinstance(feats, list) or frozenset(feats) != EXPECTED_FEATURES or len(feats) != len(EXPECTED_FEATURES):
        errors.append("features must be the expected unique structural set (18 names)")

    sb = data.get("support_bounds", {})
    nqb = sb.get("n_qubits", {}) if isinstance(sb, dict) else {}
    n_min = _float(nqb.get("min")) if isinstance(nqb, dict) else None
    n_max = _float(nqb.get("max")) if isinstance(nqb, dict) else None
    if n_min is None or n_max is None:
        errors.append("support_bounds.n_qubits must include numeric min and max")
        n_qubits_min = 1.0
    else:
        n_qubits_min = float(n_min)

    ladders = data.get("outputs", {}).get("mps_ladders", {}) if isinstance(data.get("outputs"), dict) else {}
    if not isinstance(ladders, dict):
        errors.append("outputs.mps_ladders must be an object")
    else:
        for label in ("low", "medium", "high"):
            if label not in ladders or not isinstance(ladders[label], list):
                errors.append(f"outputs.mps_ladders.{label} must be a non-empty array")

    ladder_keys = frozenset(ladders.keys()) if isinstance(ladders, dict) else frozenset()

    rules = data.get("rules", [])
    if not isinstance(rules, list) or len(rules) < 1:
        errors.append("rules must be a non-empty array")
        return errors

    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"rules[{i}] must be an object")
            continue
        for rk in ("rule_id", "conditions", "output"):
            if rk not in rule:
                errors.append(f"rules[{i}] missing {rk}")
        conds = rule.get("conditions", [])
        if isinstance(conds, list) and len(conds) == 1 and isinstance(conds[0], dict):
            if _trivial_catchall(conds[0], n_qubits_min=n_qubits_min):
                errors.append(
                    f"rules[{i}] is a trivial catch-all (forbidden for public guidance packs); "
                    "use no_match_behavior fallback instead"
                )
        out = rule.get("output", {})
        if isinstance(out, dict):
            if out.get("mps_pressure") not in ladder_keys:
                errors.append(f"rules[{i}].output.mps_pressure must be a ladder label")
            if out.get("mps_ladder") not in ladder_keys:
                errors.append(f"rules[{i}].output.mps_ladder must be a ladder label")
        if not isinstance(conds, list) or not conds:
            errors.append(f"rules[{i}].conditions must be a non-empty array")
            continue
        for j, c in enumerate(conds):
            if not isinstance(c, dict):
                errors.append(f"rules[{i}].conditions[{j}] must be an object")
                continue
            if c.get("op") not in ALLOWED_OPS:
                errors.append(f"rules[{i}].conditions[{j}].op is not an allowed op")
            if c.get("feature") not in EXPECTED_FEATURES:
                errors.append(f"rules[{i}].conditions[{j}].feature is not a known feature")

    return errors


def load_resource_guidance_pack() -> ResourceGuidancePack | None:
    """Load the bundled resource guidance pack from package data, or None if missing/invalid."""
    try:
        root = resources.files(PACK_PACKAGE)
        path = root.joinpath(PACK_RESOURCE)
        raw = path.read_bytes()
    except (OSError, FileNotFoundError, TypeError, ValueError):
        return None

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if validate_resource_guidance_pack(data):
        return None

    if not isinstance(data, dict):
        return None

    digest = compute_pack_sha256(raw)
    return ResourceGuidancePack(
        model_pack_id=str(data.get("model_pack_id", "")),
        model_pack_version=str(data.get("model_pack_version", "")),
        model_pack_schema_version=str(data.get("model_pack_schema_version", "")),
        sha256_hex=digest,
        data=dict(data),
    )


def evaluate_resource_guidance_pack_shadow(
    features: Mapping[str, Any],
    pack: ResourceGuidancePack,
    *,
    feature_schema_version: str,
) -> dict[str, Any]:
    """
    First-match shadow evaluation: suggest pack ladder/pressure without applying to public guidance.

    Out-of-support ``n_qubits`` or unsupported feature schema version yields no match
    (caller should keep deterministic guidance).
    """
    tvers = pack.data.get("target_feature_schema_versions", [])
    if not isinstance(tvers, list) or feature_schema_version not in tvers:
        return {
            "matched_rule_id": None,
            "suggested_mps_pressure": None,
            "suggested_mps_ladder": None,
            "suggested_starting_points": None,
            "no_match_reason": "unsupported_feature_schema",
        }

    sb = pack.data.get("support_bounds", {})
    nqb = sb.get("n_qubits", {}) if isinstance(sb, dict) else {}
    n_min = _float(nqb.get("min")) if isinstance(nqb, dict) else None
    n_max = _float(nqb.get("max")) if isinstance(nqb, dict) else None
    nq = _feat(features, "n_qubits")
    if n_min is not None and nq < n_min:
        return {
            "matched_rule_id": None,
            "suggested_mps_pressure": None,
            "suggested_mps_ladder": None,
            "suggested_starting_points": None,
            "no_match_reason": "out_of_support_bounds",
        }
    if n_max is not None and nq > n_max:
        return {
            "matched_rule_id": None,
            "suggested_mps_pressure": None,
            "suggested_mps_ladder": None,
            "suggested_starting_points": None,
            "no_match_reason": "out_of_support_bounds",
        }

    rules = pack.data.get("rules", [])
    ladders = pack.data.get("outputs", {}).get("mps_ladders", {})
    if not isinstance(rules, list) or not isinstance(ladders, dict):
        return {
            "matched_rule_id": None,
            "suggested_mps_pressure": None,
            "suggested_mps_ladder": None,
            "suggested_starting_points": None,
            "no_match_reason": "invalid_pack_shape",
        }

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        conds = rule.get("conditions", [])
        if not isinstance(conds, list) or not conds:
            continue
        if not all(isinstance(c, dict) and _condition_matches(features, c) for c in conds):
            continue
        out = rule.get("output", {})
        if not isinstance(out, dict):
            continue
        ladder_key = out.get("mps_ladder")
        sp = ladders.get(ladder_key) if isinstance(ladder_key, str) else None
        if not isinstance(sp, list):
            sp = None
        return {
            "matched_rule_id": rule.get("rule_id"),
            "suggested_mps_pressure": out.get("mps_pressure"),
            "suggested_mps_ladder": ladder_key,
            "suggested_starting_points": list(sp) if sp is not None else None,
            "no_match_reason": None,
        }

    return {
        "matched_rule_id": None,
        "suggested_mps_pressure": None,
        "suggested_mps_ladder": None,
        "suggested_starting_points": None,
        "no_match_reason": "no_matching_rule",
    }
