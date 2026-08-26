#!/usr/bin/env python3
"""Verify qCoder release identity and distinct predecessor relationships fail closed."""

from __future__ import annotations

import argparse
import json
import re
import tarfile
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 release tooling
    import tomli as tomllib

RELEASE_METADATA_FILENAME = "release-version.json"
RELEASE_METADATA_SCHEMA = "qcoder.release_version_source.v3"
EXPECTED_VERSION = "0.6.0a22"
PUBLIC_PREDECESSOR = {
    "version": "0.6.0a18",
    "source_commit": "2150a0f9953102f23801410d7251a64f3c01f5ea",
    "source_tree": "fd4c9021ea11258e2aa913d0518cacf7232e13b8",
    "state": "published_terminal_immutable",
    "relationship_to_source": "behavior_changing",
}
LINEAGE_PREDECESSOR = {
    "version": "0.6.0a21",
    "source_commit": "79fb41e447dea52be448447b7212214b5b9004f3",
    "source_tree": "b16da2374717d3a37bb3310462d086c74d83f264",
    "state": "frozen_unpublished_technically_qualified_publication_truth_rejected_terminal",
    "relationship_to_source": "behavior_preserving_except_release_identity_publication_truth_and_release_tooling",
}
INTERVENING = [
    {"version": "0.6.0a19", "state": "intentionally_reserved_unselected_no_accepted_candidate"},
    {
        "version": "0.6.0a20",
        "state": "frozen_unpublished_technically_qualified_publication_truth_rejected_terminal",
    },
    {
        "version": "0.6.0a21",
        "state": "frozen_unpublished_technically_qualified_publication_truth_rejected_terminal",
    },
]
PIN_PATTERN = re.compile(r"\bqcoder(?:\[[A-Za-z0-9_,.-]+\])?==([0-9A-Za-z.!+-]+)")
TEXT_SUFFIXES = {".js", ".json", ".md", ".mdx", ".mjs", ".toml", ".ts", ".tsx"}
IGNORED_PARTS = {".git", ".docusaurus", ".pytest_cache", "build", "dist", "node_modules"}


def _metadata_version(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("Version: "):
            return line.removeprefix("Version: ").strip()
    raise ValueError("distribution_metadata_version_missing")


def wheel_version(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ValueError("wheel_metadata_inventory_invalid")
        return _metadata_version(archive.read(names[0]).decode())


def sdist_version(path: Path) -> str:
    with tarfile.open(path, "r:gz") as archive:
        members = [
            m
            for m in archive.getmembers()
            if m.isfile() and m.name.count("/") == 1 and m.name.endswith("/PKG-INFO")
        ]
        if len(members) != 1:
            raise ValueError("sdist_metadata_inventory_invalid")
        handle = archive.extractfile(members[0])
        if handle is None:
            raise ValueError("sdist_metadata_unreadable")
        return _metadata_version(handle.read().decode())


def release_metadata(source_root: Path) -> dict[str, object]:
    data = json.loads((source_root / RELEASE_METADATA_FILENAME).read_text(encoding="utf-8"))
    required = {
        "schema",
        "source_version",
        "release_identity_kind",
        "publication_state_authority",
        "public_upgrade_predecessor",
        "implementation_lineage_predecessor",
        "intervening_nonpublic_versions",
    }
    if set(data) != required:
        raise ValueError("release_metadata_fields_invalid")
    if data["schema"] != RELEASE_METADATA_SCHEMA:
        raise ValueError("release_metadata_schema_unsupported")
    if data["source_version"] != EXPECTED_VERSION:
        raise ValueError("release_metadata_source_version_invalid")
    if data["release_identity_kind"] != "prerelease_successor":
        raise ValueError("release_metadata_identity_kind_unsupported")
    if data["publication_state_authority"] != "external_release_control":
        raise ValueError("release_metadata_publication_authority_invalid")
    if data["public_upgrade_predecessor"] != PUBLIC_PREDECESSOR:
        raise ValueError("public_upgrade_predecessor_invalid")
    if data["implementation_lineage_predecessor"] != LINEAGE_PREDECESSOR:
        raise ValueError("implementation_lineage_predecessor_invalid")
    if data["intervening_nonpublic_versions"] != INTERVENING:
        raise ValueError("intervening_nonpublic_versions_invalid")
    if (
        data["public_upgrade_predecessor"]["version"]
        == data["implementation_lineage_predecessor"]["version"]
    ):
        raise ValueError("predecessor_relationships_conflated")
    return data


def source_versions(source_root: Path) -> dict[str, str]:
    pyproject = tomllib.loads((source_root / "pyproject.toml").read_text(encoding="utf-8"))
    match = re.search(
        r'^__version__\s*=\s*"([^"]+)"$',
        (source_root / "src/qcoder/__init__.py").read_text(),
        re.MULTILINE,
    )
    if match is None:
        raise ValueError("qcoder_dunder_version_missing")
    metadata = release_metadata(source_root)
    return {
        "pyproject": str(pyproject["project"]["version"]),
        "qcoder.__version__": match.group(1),
        "release_metadata": str(metadata["source_version"]),
    }


def customer_pin_versions(roots: list[Path]) -> dict[str, list[str]]:
    found = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if (
                path.is_file()
                and path.suffix in TEXT_SUFFIXES
                and not any(part in IGNORED_PARTS for part in path.parts)
            ):
                versions = PIN_PATTERN.findall(path.read_text(encoding="utf-8"))
                if versions:
                    found[str(path)] = versions
    return found


def verify_release_version(
    *,
    source_root: Path,
    wheel: Path | None = None,
    sdist: Path | None = None,
    customer_roots: list[Path],
) -> dict[str, object]:
    source_root = source_root.resolve()
    metadata = release_metadata(source_root)
    versions = source_versions(source_root)
    if (wheel is None) != (sdist is None):
        raise ValueError("artifact_pair_incomplete")
    if wheel is not None and sdist is not None:
        versions.update({"wheel": wheel_version(wheel), "sdist": sdist_version(sdist)})
    if any(value != EXPECTED_VERSION for value in versions.values()):
        raise ValueError(f"authoritative_version_mismatch:{versions}")
    pins = customer_pin_versions([root.resolve() for root in customer_roots])
    allowed = PUBLIC_PREDECESSOR["version"]
    bad = {
        path: values for path, values in pins.items() if any(value != allowed for value in values)
    }
    if bad:
        raise ValueError(f"customer_package_pin_mismatch:{bad}")
    return {
        "ok": True,
        "result": "pass",
        "version": EXPECTED_VERSION,
        "source_version": EXPECTED_VERSION,
        "release_identity_kind": metadata["release_identity_kind"],
        "publication_state_authority": metadata["publication_state_authority"],
        "public_upgrade_predecessor": metadata["public_upgrade_predecessor"],
        "implementation_lineage_predecessor": metadata["implementation_lineage_predecessor"],
        "intervening_nonpublic_versions": metadata["intervening_nonpublic_versions"],
        "authoritative_versions": versions,
        "customer_pins": pins,
        "artifact_versions_checked": wheel is not None,
        "relationships_distinct": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--sdist", type=Path)
    parser.add_argument("--customer-root", type=Path, action="append", required=True)
    args = parser.parse_args()
    try:
        result = verify_release_version(
            source_root=args.source_root,
            wheel=args.wheel,
            sdist=args.sdist,
            customer_roots=args.customer_root,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "result": "fail", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
