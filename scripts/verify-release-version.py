#!/usr/bin/env python3
"""Verify one immutable qCoder release unit has a single version identity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import tarfile
import tomllib
import zipfile


OLD_CANDIDATE_VERSION = "0.6.0a1"
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
        metadata = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise ValueError("wheel_metadata_inventory_invalid")
        return _metadata_version(archive.read(metadata[0]).decode("utf-8"))


def sdist_version(path: Path) -> str:
    with tarfile.open(path, "r:gz") as archive:
        metadata = [
            member
            for member in archive.getmembers()
            if member.isfile() and member.name.count("/") == 1 and member.name.endswith("/PKG-INFO")
        ]
        if len(metadata) != 1:
            raise ValueError("sdist_metadata_inventory_invalid")
        handle = archive.extractfile(metadata[0])
        if handle is None:
            raise ValueError("sdist_metadata_unreadable")
        return _metadata_version(handle.read().decode("utf-8"))


def source_versions(source_root: Path) -> dict[str, str]:
    pyproject = tomllib.loads((source_root / "pyproject.toml").read_text(encoding="utf-8"))
    init_text = (source_root / "src/qcoder/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"$', init_text, re.MULTILINE)
    if match is None:
        raise ValueError("qcoder_dunder_version_missing")
    return {
        "pyproject": str(pyproject["project"]["version"]),
        "qcoder.__version__": match.group(1),
    }


def customer_pin_versions(roots: list[Path]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if (
                not path.is_file()
                or path.suffix not in TEXT_SUFFIXES
                or any(part in IGNORED_PARTS for part in path.parts)
            ):
                continue
            versions = PIN_PATTERN.findall(path.read_text(encoding="utf-8"))
            if versions:
                found[str(path)] = versions
    return found


def verify_release_version(
    *,
    source_root: Path,
    wheel: Path,
    sdist: Path,
    customer_roots: list[Path],
) -> dict[str, object]:
    versions = source_versions(source_root)
    versions["wheel"] = wheel_version(wheel)
    versions["sdist"] = sdist_version(sdist)
    expected = versions["pyproject"]
    release_line = expected.rsplit("a", 1)[0]
    pins = {
        path: [version for version in values if version.startswith(release_line)]
        for path, values in customer_pin_versions(customer_roots).items()
    }
    pins = {path: values for path, values in pins.items() if values}
    mismatches = {source: value for source, value in versions.items() if value != expected}
    pin_mismatches = {
        path: values for path, values in pins.items() if any(value != expected for value in values)
    }
    if expected == OLD_CANDIDATE_VERSION:
        raise ValueError("candidate_reuses_0.6.0a1")
    if mismatches:
        raise ValueError(f"authoritative_version_mismatch:{mismatches}")
    if not pins:
        raise ValueError("customer_package_pin_missing")
    if pin_mismatches:
        raise ValueError(f"customer_package_pin_mismatch:{pin_mismatches}")
    return {
        "ok": True,
        "version": expected,
        "authoritative_versions": versions,
        "customer_pin_files": sorted(pins),
        "old_candidate_identity_absent": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--customer-root", type=Path, action="append", required=True)
    args = parser.parse_args()
    result = verify_release_version(
        source_root=args.source_root.resolve(),
        wheel=args.wheel.resolve(),
        sdist=args.sdist.resolve(),
        customer_roots=[root.resolve() for root in args.customer_root],
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
