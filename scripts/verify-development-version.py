#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import re

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


EXPECTED_SCHEMA = "qcoder.private_development_version.v1"
EXPECTED_BASIS = "0.6.0a22"


def verify(root: Path) -> dict[str, object]:
    development = json.loads((root / "development-version.json").read_text(encoding="utf-8"))
    release = json.loads((root / "release-version.json").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    initializer = (root / "src/qcoder/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', initializer, re.MULTILINE)
    if development.get("schema_id") != EXPECTED_SCHEMA:
        raise ValueError("development_version_schema_invalid")
    version = development.get("version")
    if not isinstance(version, str) or "+wi0440.natural.first.value.v1" not in version:
        raise ValueError("development_version_identity_invalid")
    if pyproject["project"]["version"] != version or match is None or match.group(1) != version:
        raise ValueError("development_version_sources_diverge")
    if development.get("basis_version") != EXPECTED_BASIS:
        raise ValueError("development_version_basis_invalid")
    if release.get("source_version") != EXPECTED_BASIS:
        raise ValueError("public_release_record_changed")
    if development.get("publication_permitted") is not False:
        raise ValueError("development_publication_must_be_prohibited")
    if development.get("public_successor_selected") is not False:
        raise ValueError("public_successor_must_remain_unselected")
    return {
        "ok": True,
        "version": version,
        "basis_version": EXPECTED_BASIS,
        "public_release_record_unchanged": True,
        "publication_permitted": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(Path(__file__).resolve().parents[1]), sort_keys=True))
