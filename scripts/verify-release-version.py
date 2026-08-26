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
RELATIONSHIP_PRODUCT_BLOCK = """qCoder 0.6.0a22 is a behavior-changing pre-release successor to public qCoder 0.6.0a18. Its
runtime implementation and product behavior are preserved from the immutable, unpublished qCoder
0.6.0a21 candidate, except for release identity, publication-truth documentation, mechanically
resulting package metadata, and release-only verification. qCoder 0.6.0a21 was never public and
is not a customer upgrade predecessor.

The public upgrade relationship is qCoder 0.6.0a18 → qCoder 0.6.0a22. The implementation lineage
relationship is qCoder 0.6.0a21 → qCoder 0.6.0a22. These relationships are distinct and must not
be conflated.

Relative to public qCoder 0.6.0a18, qCoder 0.6.0a22 changes the Current Loop contract from binding
v44 / Current Step Contract v10 to binding v45 / Current Step Contract v11 and uses one contract-
selected terminal-closure route for routine source work. When an exact native-edit integration is
configured, a successful native edit drives qCoder’s independent validation, single registration,
receipt, and source-stage stop without a redundant completion call or another interpretation of
qCoder procedure. Hook-absent clients retain the fail-closed typed-completion route. The a18 →
a22 upgrade is not behavior-preserving and is not a supported mid-step migration."""
HISTORICAL_STATUS_BLOCK = """Plain 0.6.0a19 remains intentionally reserved and has no accepted frozen or public candidate.
Plain 0.6.0a20 and plain 0.6.0a21 are immutable, unpublished, technically qualified,
publication-truth-rejected, terminal, do-not-publish candidates. They are retained evidence, not
customer releases or upgrade predecessors, and must not be repaired, rebuilt, replaced, tagged,
published, or selected again."""
UPGRADE_BLOCK = """Install qCoder 0.6.0a22 for a new installation or before starting a new Current Loop. If qCoder
0.6.0a18 already has an active Current Loop, upgrade only at a clean Current Loop boundary:
before a new loop begins or after the current loop has reached a truthful terminal boundary.

Do not upgrade while any binding v44 / Current Step Contract v10 step, completion, continuation
capsule, pending receipt, or recovery action remains outstanding. Finish the outstanding step on
qCoder 0.6.0a18, or explicitly abandon it and restart the work under qCoder 0.6.0a22 at a clean
boundary.

qCoder does not support or claim mid-step migration from binding v44 / Current Step Contract v10
to binding v45 / Current Step Contract v11. A v44/v10 operation receipt, authority grant,
completion input, continuation capsule, or pending step must not be reused or reinterpreted under
v45/v11. Project evidence history may remain; this boundary applies to the active step."""
NONCLAIM_BLOCK = """This release makes no latency, speed, p95, responsiveness, overhead, quiet-operation, or
consistency guarantee; does not establish universal framework neutrality, general framework
qualification, or general PennyLane qualification; and does not activate Tested, First-class,
Client Compatibility, CL-023, named-client support, website, or marketing claims. Publication,
deployment, qualification evidence, public applicability, and support claims remain separate
lifecycle and product decisions."""
CHANGELOG_BLOCK = """Public upgrade predecessor: qCoder 0.6.0a18. The a18 → a22 relationship is behavior-changing.

Implementation lineage predecessor: immutable unpublished qCoder 0.6.0a21. The a21 → a22
relationship preserves runtime implementation and product behavior except for release identity,
publication-truth documentation, mechanically resulting package metadata, and release-only
verification.

Plain 0.6.0a19 remains intentionally reserved. Plain 0.6.0a20 and plain 0.6.0a21 remain immutable,
unpublished, technically qualified, publication-truth-rejected, terminal, and do-not-publish.

Existing installations upgrade only at the clean Current Loop boundary stated in the a22 release
note and package long description. Mid-step v44/v10 → v45/v11 migration and receipt reuse are not
supported claims."""
A21_HISTORICAL_CORRECTION = """**Historical do-not-publish candidate.** qCoder 0.6.0a21 is immutable, unpublished, technically
qualified, rejected for publication truth, terminal, and must not be published. Its source and
distribution bytes remain historical evidence and must not be repaired, rebuilt, replaced,
tagged, published, or selected again.

qCoder 0.6.0a21 preserved the runtime implementation and product behavior of the immutable,
unpublished qCoder 0.6.0a20 candidate. It would have been a behavior-changing pre-release
successor to public qCoder 0.6.0a18, but it was never published. Its release note incorrectly
described behavior preservation as relative to public a18; that publication-truth defect consumed
the a21 identity. Public upgrade lineage and implementation lineage are distinct."""
ACTIVE_BLOCKS = (
    RELATIONSHIP_PRODUCT_BLOCK,
    HISTORICAL_STATUS_BLOCK,
    UPGRADE_BLOCK,
    NONCLAIM_BLOCK,
)
DEFECTIVE_RELATIONSHIP = "behavior-preserving pre-release successor to public qCoder 0.6.0a18"
PIN_PATTERN = re.compile(r"\bqcoder(?:\[[A-Za-z0-9_,.-]+\])?==([0-9A-Za-z.!+-]+)")
TEXT_SUFFIXES = {".js", ".json", ".md", ".mdx", ".mjs", ".toml", ".ts", ".tsx"}
IGNORED_PARTS = {".git", ".docusaurus", ".pytest_cache", "build", "dist", "node_modules"}


def _metadata_version(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("Version: "):
            return line.removeprefix("Version: ").strip()
    raise ValueError("distribution_metadata_version_missing")


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _wheel_metadata(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise ValueError("wheel_metadata_inventory_invalid")
        return archive.read(names[0]).decode()


def _sdist_pkg_info(path: Path) -> str:
    with tarfile.open(path, "r:gz") as archive:
        members = [
            member
            for member in archive.getmembers()
            if member.isfile() and member.name.count("/") == 1 and member.name.endswith("/PKG-INFO")
        ]
        if len(members) != 1:
            raise ValueError("sdist_metadata_inventory_invalid")
        handle = archive.extractfile(members[0])
        if handle is None:
            raise ValueError("sdist_metadata_unreadable")
        return handle.read().decode()


def _validate_active_surface(text: str, surface: str) -> None:
    normalized = _normalized(text)
    for block in ACTIVE_BLOCKS:
        if _normalized(block) not in normalized:
            raise ValueError(f"publication_truth_block_missing:{surface}")
    forbidden = (
        DEFECTIVE_RELATIONSHIP,
        "qCoder 0.6.0a21 was public",
        "qCoder 0.6.0a21 is a customer upgrade predecessor",
        "mid-step migration is supported",
        "receipt reuse is supported",
        "qCoder 0.6.0a22 is unpublished",
        "qCoder 0.6.0a22 is pending publication",
        "qCoder 0.6.0a22 is not current",
    )
    if any(item in normalized for item in forbidden):
        raise ValueError(f"publication_truth_contradiction:{surface}")


def _validate_changelog(text: str) -> None:
    normalized = _normalized(text)
    if _normalized(CHANGELOG_BLOCK) not in normalized:
        raise ValueError("publication_truth_changelog_block_missing")
    if "## 0.6.0a21 (unpublished terminal candidate; do not publish)" not in text:
        raise ValueError("publication_truth_a21_changelog_heading_invalid")


def _validate_a21_history(text: str) -> None:
    normalized = _normalized(text)
    expected = _normalized(f"# qCoder 0.6.0a21\n\n{A21_HISTORICAL_CORRECTION}")
    if not normalized.startswith(expected):
        raise ValueError("publication_truth_a21_historical_correction_invalid")
    if DEFECTIVE_RELATIONSHIP in normalized:
        raise ValueError("publication_truth_a21_defect_retained")


def publication_truth(
    source_root: Path, wheel: Path | None = None, sdist: Path | None = None
) -> dict[str, object]:
    readme = (source_root / "README.md").read_text(encoding="utf-8")
    note = (source_root / "docs/releases/0.6.0a22.md").read_text(encoding="utf-8")
    _validate_active_surface(readme, "README.md")
    _validate_active_surface(note, "docs/releases/0.6.0a22.md")
    _validate_changelog((source_root / "CHANGELOG.md").read_text(encoding="utf-8"))
    _validate_a21_history((source_root / "docs/releases/0.6.0a21.md").read_text(encoding="utf-8"))
    policy = _normalized(
        (source_root / "docs/release-version-policy.md").read_text(encoding="utf-8")
    )
    for clause in (
        "public upgrade predecessor and the implementation-lineage predecessor as distinct relationships",
        "A generic predecessor field, conflation, reversal, or substitution of these relationships fails closed",
        "never become customer upgrade predecessors",
    ):
        if clause not in policy:
            raise ValueError("publication_truth_policy_incomplete")
    artifacts = False
    if (wheel is None) != (sdist is None):
        raise ValueError("artifact_pair_incomplete")
    if wheel is not None and sdist is not None:
        _validate_active_surface(_wheel_metadata(wheel), "wheel METADATA")
        _validate_active_surface(_sdist_pkg_info(sdist), "sdist PKG-INFO")
        artifacts = True
    return {
        "source_surfaces_checked": 5,
        "artifact_surfaces_checked": 2 if artifacts else 0,
        "exact_active_blocks": len(ACTIVE_BLOCKS),
        "relationships_distinct": True,
    }


def wheel_version(path: Path) -> str:
    return _metadata_version(_wheel_metadata(path))


def sdist_version(path: Path) -> str:
    return _metadata_version(_sdist_pkg_info(path))


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
    truth = publication_truth(source_root, wheel, sdist)
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
        "publication_truth": truth,
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
