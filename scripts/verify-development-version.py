#!/usr/bin/env python3
from __future__ import annotations

import json
from packaging.version import Version
from pathlib import Path
import re

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


EXPECTED_SCHEMA = "qcoder.private_development_version.v1"
EXPECTED_VERSION = "0.6.0a24.post0.dev2+openqasm3.local.evidence.v1"
EXPECTED_PREDECESSOR = "0.6.0a24.post0.dev1+deterministic.evidence.usability.pack.v1"
EXPECTED_BASIS = "0.6.0a24"
EXPECTED_WORK_IDENTITY = "QCODER_OSS_OPENQASM3_AND_LOCAL_EVIDENCE_HARDENING_MARATHON_V1"


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
    return {
        "ok": True,
        "version": EXPECTED_VERSION,
        "basis_version": EXPECTED_BASIS,
        "public_release_record_unchanged": True,
        "publication_permitted": False,
        "pep440_ordering_after_basis": True,
        "pep440_ordering_after_private_predecessor": True,
        "development_release": True,
        "public_successor_selected": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(Path(__file__).resolve().parents[1]), sort_keys=True))
