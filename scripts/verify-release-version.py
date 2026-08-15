#!/usr/bin/env python3
"""Verify qCoder candidate source, documentation pins, and artifact versions."""

from __future__ import annotations

import argparse
import json
import re
import tarfile
import tomllib
import zipfile
from pathlib import Path

OLD_CANDIDATE_VERSION = "0.6.0a1"
RELEASE_METADATA_FILENAME = "release-version.json"
RELEASE_METADATA_SCHEMA = "qcoder.release_version_source.v1"
UNPUBLISHED_CANDIDATE = "unpublished_candidate"
SUPPORTED_POSTURES = frozenset({UNPUBLISHED_CANDIDATE})
PRIVATE_CANDIDATE_PATTERN = re.compile(
    r"^(?P<public_version>[0-9]+\.[0-9]+\.[0-9]+a[0-9]+)"
    r"\+wi[0-9]+\.[a-z0-9][a-z0-9.]*$"
)
PIN_PATTERN = re.compile(r"\bqcoder(?:\[[A-Za-z0-9_,.-]+\])?==([0-9A-Za-z.!+-]+)")
TEXT_SUFFIXES = {".js", ".json", ".md", ".mdx", ".mjs", ".toml", ".ts", ".tsx"}
IGNORED_PARTS = {".git", ".docusaurus", ".pytest_cache", "build", "dist", "node_modules"}
QCODER_ALPHA_VERSION_PATTERN = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)a"
    r"(?P<serial>0|[1-9][0-9]*)$"
)


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


def release_metadata(source_root: Path) -> dict[str, object]:
    path = source_root / RELEASE_METADATA_FILENAME
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema",
        "source_version",
        "source_posture",
        "current_public_version",
        "published",
        "publicly_installable",
        "intervening_unpublished_versions",
    }
    if set(data) != required:
        raise ValueError("release_metadata_fields_invalid")
    if data["schema"] != RELEASE_METADATA_SCHEMA:
        raise ValueError("release_metadata_schema_unsupported")
    for key in ("source_version", "source_posture", "current_public_version"):
        if not isinstance(data[key], str):
            raise ValueError(f"release_metadata_{key}_invalid")
    if not isinstance(data["published"], bool) or not isinstance(
        data["publicly_installable"], bool
    ):
        raise ValueError("release_metadata_publication_flags_invalid")
    intervening = data["intervening_unpublished_versions"]
    if not isinstance(intervening, list) or not all(
        isinstance(value, str) for value in intervening
    ):
        raise ValueError("release_metadata_intervening_versions_invalid")
    if len(intervening) != len(set(intervening)):
        raise ValueError("release_metadata_intervening_versions_duplicated")
    return data


def source_versions(source_root: Path) -> dict[str, str]:
    pyproject = tomllib.loads((source_root / "pyproject.toml").read_text(encoding="utf-8"))
    init_text = (source_root / "src/qcoder/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"$', init_text, re.MULTILINE)
    if match is None:
        raise ValueError("qcoder_dunder_version_missing")
    metadata = release_metadata(source_root)
    return {
        "pyproject": str(pyproject["project"]["version"]),
        "qcoder.__version__": match.group(1),
        "release_metadata": str(metadata["source_version"]),
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


def _qcoder_alpha_version(version: str) -> tuple[int, int, int, int]:
    private_candidate = PRIVATE_CANDIDATE_PATTERN.fullmatch(version)
    if private_candidate is not None:
        version = private_candidate.group("public_version")
    match = QCODER_ALPHA_VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f"unsupported_qcoder_release_line:{version}")
    return tuple(int(match.group(name)) for name in ("major", "minor", "patch", "serial"))


def _repository_pin_inventory(
    source_root: Path,
    raw_pins: dict[str, list[str]],
) -> dict[str, list[str]]:
    inventory: dict[str, list[str]] = {}
    source_root = source_root.resolve()
    for raw_path, versions in raw_pins.items():
        path = Path(raw_path).resolve()
        try:
            display_path = path.relative_to(source_root).as_posix()
        except ValueError:
            display_path = f"absolute:{path.as_posix()}"
        inventory[display_path] = list(versions)
    return dict(sorted(inventory.items()))


def _expected_intervening_alpha_versions(
    current_public_version: str,
    source_version: str,
) -> list[str]:
    public_identity = _qcoder_alpha_version(current_public_version)
    source_identity = _qcoder_alpha_version(source_version)
    if public_identity[:3] != source_identity[:3]:
        raise ValueError("candidate_and_public_release_line_mismatch")
    if source_identity <= public_identity:
        raise ValueError("candidate_not_newer_than_current_public_version")
    prefix = ".".join(str(part) for part in source_identity[:3])
    return [
        f"{prefix}a{serial}"
        for serial in range(public_identity[3] + 1, source_identity[3])
    ]


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
    expected = versions["pyproject"]
    if (wheel is None) != (sdist is None):
        raise ValueError("artifact_pair_incomplete")
    if wheel is not None and sdist is not None:
        versions["wheel"] = wheel_version(wheel)
        versions["sdist"] = sdist_version(sdist)
    local_match = PRIVATE_CANDIDATE_PATTERN.fullmatch(expected)
    source_posture = str(metadata["source_posture"])
    current_public_version = str(metadata["current_public_version"])
    pins = _repository_pin_inventory(
        source_root,
        customer_pin_versions([root.resolve() for root in customer_roots]),
    )
    mismatches = {source: value for source, value in versions.items() if value != expected}
    if expected == OLD_CANDIDATE_VERSION:
        raise ValueError("candidate_reuses_0.6.0a1")
    if mismatches:
        raise ValueError(f"authoritative_version_mismatch:{mismatches}")
    if source_posture not in SUPPORTED_POSTURES:
        raise ValueError(f"unsupported_release_posture:{source_posture}")
    if metadata["published"] is not False:
        raise ValueError("unpublished_candidate_marked_published")
    if metadata["publicly_installable"] is not False:
        raise ValueError("unpublished_candidate_marked_publicly_installable")
    if current_public_version == expected:
        raise ValueError("unpublished_candidate_equals_current_public_version")
    expected_intervening = _expected_intervening_alpha_versions(current_public_version, expected)
    declared_intervening = list(metadata["intervening_unpublished_versions"])
    if declared_intervening != expected_intervening:
        raise ValueError(
            "intervening_unpublished_versions_mismatch:"
            f"expected={expected_intervening}:declared={declared_intervening}"
        )
    candidate_pin_occurrences = [
        {"path": path, "version": version}
        for path, values in pins.items()
        for version in values
        if version == expected
    ]
    intervening_pin_occurrences = [
        {"path": path, "version": version}
        for path, values in pins.items()
        for version in values
        if version in declared_intervening
    ]
    if candidate_pin_occurrences:
        raise ValueError(f"unpublished_candidate_customer_pin:{candidate_pin_occurrences}")
    if intervening_pin_occurrences:
        raise ValueError(f"unpublished_intervening_customer_pin:{intervening_pin_occurrences}")
    pin_mismatches = {
        path: values
        for path, values in pins.items()
        if any(value != current_public_version for value in values)
    }
    if pin_mismatches:
        raise ValueError(f"customer_package_pin_mismatch:{pin_mismatches}")
    detected_pin_versions = sorted({version for values in pins.values() for version in values})
    return {
        "ok": True,
        "result": "pass",
        "version": expected,
        "source_version": expected,
        "source_posture": source_posture,
        "public_version": current_public_version,
        "current_public_version": current_public_version,
        "private_candidate_identity": local_match is not None,
        "authoritative_versions": versions,
        "customer_pin_files": sorted(pins),
        "customer_pins": pins,
        "detected_customer_pin_versions": detected_pin_versions,
        "candidate_pin_occurrences": [],
        "intervening_unpublished_pin_occurrences": [],
        "rejected_or_unpublished_pin_occurrences": [],
        "forbidden_customer_pin_versions": [*declared_intervening, expected],
        "artifact_versions_checked": wheel is not None,
        "old_candidate_identity_absent": True,
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
            source_root=args.source_root.resolve(),
            wheel=args.wheel.resolve() if args.wheel is not None else None,
            sdist=args.sdist.resolve() if args.sdist is not None else None,
            customer_roots=[root.resolve() for root in args.customer_root],
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "result": "fail", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
