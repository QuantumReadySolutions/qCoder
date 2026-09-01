#!/usr/bin/env python3
from __future__ import annotations

from hashlib import sha256
import json
from packaging.version import Version
from pathlib import Path
import re
import sys

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


EXPECTED_SCHEMA = "qcoder.private_development_version.v1"
EXPECTED_VERSION = "0.6.0a24.post0.dev6+review.before.generation.v4"
EXPECTED_PREDECESSOR = "0.6.0a24.post0.dev5+review.before.generation.v3"
EXPECTED_BASIS = "0.6.0a24"
EXPECTED_WORK_IDENTITY = "WI0440_REVIEW_BEFORE_GENERATION_CONVERGENT_FIRST_VALUE_V1"
EXPECTED_BINDING = "qcoder.connected_assistant.client_binding.v56"
EXPECTED_BINDING_SCHEMA = 55
EXPECTED_DESCRIPTOR_BYTES = 238_216
EXPECTED_DESCRIPTOR_SHA256 = "df61ba96f2bf440f019261d7b38961c7d3b5cdb87f8607082b1688b2190db5ce"


def verify(root: Path) -> dict[str, object]:
    development = json.loads((root / "development-version.json").read_text(encoding="utf-8"))
    release = json.loads((root / "release-version.json").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    initializer = (root / "src/qcoder/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', initializer, re.MULTILINE)
    required = {
        "basis_commit",
        "basis_tree",
        "basis_version",
        "binding",
        "binding_descriptor_canonical_bytes",
        "binding_descriptor_canonical_sha256",
        "binding_descriptor_coordinator_prefix",
        "binding_schema",
        "identity_kind",
        "publication_permitted",
        "public_release_record_preserved_in",
        "public_successor_selected",
        "schema_id",
        "version",
        "work_identity",
    }
    if set(development) != required or development.get("schema_id") != EXPECTED_SCHEMA:
        raise ValueError("development_version_schema_invalid")
    if development.get("version") != EXPECTED_VERSION:
        raise ValueError("development_version_identity_invalid")
    if (
        pyproject["project"]["version"] != EXPECTED_VERSION
        or match is None
        or match.group(1) != EXPECTED_VERSION
    ):
        raise ValueError("development_version_sources_diverge")
    if development.get("basis_version") != EXPECTED_BASIS:
        raise ValueError("development_version_basis_invalid")
    if release.get("source_version") != EXPECTED_BASIS:
        raise ValueError("public_release_record_changed")
    if development.get("work_identity") != EXPECTED_WORK_IDENTITY:
        raise ValueError("development_work_identity_invalid")
    if (
        development.get("binding") != EXPECTED_BINDING
        or development.get("binding_schema") != EXPECTED_BINDING_SCHEMA
        or development.get("binding_descriptor_coordinator_prefix") != ["qcoder"]
    ):
        raise ValueError("development_binding_identity_invalid")
    if development.get("identity_kind") != "private_unfrozen_development_successor":
        raise ValueError("development_identity_kind_invalid")
    if development.get("publication_permitted") is not False:
        raise ValueError("development_publication_must_be_prohibited")
    if development.get("public_successor_selected") is not False:
        raise ValueError("development_public_successor_must_remain_unselected")
    candidate = Version(EXPECTED_VERSION)
    predecessor = Version(EXPECTED_PREDECESSOR)
    basis = Version(EXPECTED_BASIS)
    if candidate <= basis or candidate <= predecessor or not candidate.is_devrelease:
        raise ValueError("development_version_pep440_ordering_invalid")
    if candidate.release != basis.release or candidate.pre != basis.pre:
        raise ValueError("development_public_successor_selected")
    sys.path.insert(0, str(root / "src"))
    from qcoder.context_bridge_mcp import build_client_binding_descriptor

    descriptor = build_client_binding_descriptor(coordinator_prefix=["qcoder"])[
        "client_binding_contract"
    ]
    canonical_descriptor = json.dumps(
        descriptor,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    descriptor_digest = sha256(canonical_descriptor).hexdigest()
    if (
        descriptor.get("contract_id") != EXPECTED_BINDING
        or descriptor.get("schema_version") != EXPECTED_BINDING_SCHEMA
        or len(canonical_descriptor) != EXPECTED_DESCRIPTOR_BYTES
        or descriptor_digest != EXPECTED_DESCRIPTOR_SHA256
        or development.get("binding_descriptor_canonical_bytes") != EXPECTED_DESCRIPTOR_BYTES
        or development.get("binding_descriptor_canonical_sha256") != EXPECTED_DESCRIPTOR_SHA256
    ):
        raise ValueError("development_binding_descriptor_identity_invalid")
    return {
        "ok": True,
        "version": EXPECTED_VERSION,
        "basis_version": EXPECTED_BASIS,
        "binding": EXPECTED_BINDING,
        "binding_schema": EXPECTED_BINDING_SCHEMA,
        "binding_descriptor_canonical_bytes": EXPECTED_DESCRIPTOR_BYTES,
        "binding_descriptor_canonical_sha256": EXPECTED_DESCRIPTOR_SHA256,
        "public_release_record_unchanged": True,
        "publication_permitted": False,
        "pep440_ordering_after_basis": True,
        "pep440_ordering_after_private_predecessor": True,
        "development_release": True,
        "public_successor_selected": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(Path(__file__).resolve().parents[1]), sort_keys=True))
