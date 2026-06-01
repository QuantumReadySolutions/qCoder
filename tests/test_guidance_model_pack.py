"""Tests for bundled resource guidance model pack (shadow / metadata only)."""

from __future__ import annotations

import ast
import json
from copy import deepcopy
from importlib import resources
from pathlib import Path

import pytest

from qcoder.engines.guidance.model_pack import (
    ResourceGuidancePack,
    compute_pack_sha256,
    evaluate_resource_guidance_pack_shadow,
    load_resource_guidance_pack,
    validate_resource_guidance_pack,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_PACK_PATH = REPO_ROOT / "src/qcoder/model_packs/resource_guidance_local_v0.json"


def _read_bundled_dict() -> dict:
    return json.loads(BUNDLED_PACK_PATH.read_text(encoding="utf-8"))


def test_bundled_pack_file_exists():
    assert BUNDLED_PACK_PATH.is_file()


def test_loader_returns_pack():
    pack = load_resource_guidance_pack()
    assert pack is not None
    assert pack.model_pack_id == "resource_guidance_local_v0"
    assert pack.model_pack_version == "0.1.0-candidate"


def test_sha256_stable_nonempty():
    pack = load_resource_guidance_pack()
    assert pack is not None
    assert len(pack.sha256_hex) == 64
    raw = BUNDLED_PACK_PATH.read_bytes()
    assert compute_pack_sha256(raw) == pack.sha256_hex
    pack2 = load_resource_guidance_pack()
    assert pack2 is not None
    assert pack2.sha256_hex == pack.sha256_hex


def test_validator_accepts_bundled_pack():
    data = _read_bundled_dict()
    assert validate_resource_guidance_pack(data) == []


def test_validator_rejects_missing_required_fields():
    errs = validate_resource_guidance_pack({"model_pack_schema_version": "resource_guidance_pack.v0"})
    assert errs
    assert any("missing top-level key" in e for e in errs)


def test_validator_rejects_unsupported_schema_version():
    data = _read_bundled_dict()
    data["model_pack_schema_version"] = "resource_guidance_pack.v99"
    errs = validate_resource_guidance_pack(data)
    assert any("model_pack_schema_version" in e for e in errs)


def test_validator_rejects_trivial_n_qubits_catchall():
    data = _read_bundled_dict()
    data["rules"] = [
        {
            "rule_id": "bad_catchall",
            "conditions": [{"feature": "n_qubits", "op": ">=", "value": 0}],
            "output": {"mps_pressure": "high", "mps_ladder": "high"},
        }
    ]
    errs = validate_resource_guidance_pack(data)
    assert any("trivial catch-all" in e for e in errs)


def test_shadow_evaluation_matches_known_low_rule():
    pack = load_resource_guidance_pack()
    assert pack is not None
    fm = {
        "n_qubits": 4.0,
        "entangling_depth": 5.0,
        "cut_max": 4.0,
    }
    out = evaluate_resource_guidance_pack_shadow(fm, pack, feature_schema_version="0.4.0")
    assert out["matched_rule_id"] == "candidate_mps_low_structural_v0"
    assert out["suggested_mps_pressure"] == "low"
    assert out["suggested_mps_ladder"] == "low"
    assert out["suggested_starting_points"] == [16, 32]
    assert out["no_match_reason"] is None


def test_shadow_no_match_out_of_bounds_n_qubits():
    pack = load_resource_guidance_pack()
    assert pack is not None
    fm = {"n_qubits": 200.0, "entangling_depth": 5.0, "cut_max": 4.0}
    out = evaluate_resource_guidance_pack_shadow(fm, pack, feature_schema_version="0.4.0")
    assert out["matched_rule_id"] is None
    assert out["no_match_reason"] == "out_of_support_bounds"


def test_shadow_no_match_unsupported_feature_schema():
    pack = load_resource_guidance_pack()
    assert pack is not None
    fm = {"n_qubits": 4.0, "entangling_depth": 5.0, "cut_max": 4.0}
    out = evaluate_resource_guidance_pack_shadow(fm, pack, feature_schema_version="0.3.0")
    assert out["no_match_reason"] == "unsupported_feature_schema"


def test_model_pack_py_has_no_network_imports():
    mp_path = REPO_ROOT / "src/qcoder/engines/guidance/model_pack.py"
    tree = ast.parse(mp_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    forbidden = {"urllib", "urllib3", "requests", "http", "socket", "aiohttp", "httpx"}
    assert not (names & forbidden), f"unexpected imports: {names & forbidden}"


def test_package_data_includes_json():
    root = resources.files("qcoder.model_packs")
    assert root.joinpath("resource_guidance_local_v0.json").is_file()


def test_resource_guidance_pack_dataclass_frozen():
    d = _read_bundled_dict()
    p = ResourceGuidancePack(
        model_pack_id="x",
        model_pack_version="0",
        model_pack_schema_version="resource_guidance_pack.v0",
        sha256_hex="a" * 64,
        data=d,
    )
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        p.model_pack_id = "y"  # type: ignore[misc]
