#!/usr/bin/env python3
"""Verify the fail-closed qCoder 0.6.0a24 release identity and lineage."""

from __future__ import annotations

import argparse
import hashlib
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
EXPECTED_VERSION = "0.6.0a24"
PUBLIC_PREDECESSOR = {
    "version": "0.6.0a22",
    "source_commit": "eafc00fd9ebd99f0fa485261f388612278407092",
    "source_tree": "778d081437a005d1437de58bd84a08ade86c3131",
    "state": "published_terminal_immutable",
    "relationship_to_source": "behavior_changing",
}
LINEAGE_PREDECESSOR = {
    "version": "0.6.0a23",
    "source_commit": "9c984936ab0067d2109eb24b9b1ea072b09b686d",
    "source_tree": "ea21765a855ed03642e729b10453bdfc17b8d27e",
    "state": "consumed_terminal_unpublished_do_not_publish",
    "relationship_to_source": "behavior_changing",
}
PRODUCT_CORRECTION_BASIS = {
    "source_commit": "75babdcc27f894094f776bc9e3d1382ab9e1496f",
    "source_tree": "6887f0fbdf27cfce7c2316f2eed336f663ac2bf2",
    "state": "private_unfrozen_a24_truthful_connection_state_product_basis_not_publishable",
    "relationship_to_source": "behavior_preserving_except_release_identity_release_truth_mechanically_resulting_package_metadata_and_release_only_verification",
}
INTERVENING: list[dict[str, str]] = []

RELATIONSHIP_PRODUCT_BLOCK = """qCoder 0.6.0a24 is a behavior-changing pre-release successor to public qCoder 0.6.0a22. Public
qCoder 0.6.0a22 is its customer upgrade predecessor. Frozen qCoder 0.6.0a23 at commit
`9c984936ab0067d2109eb24b9b1ea072b09b686d` is the implementation lineage predecessor; a23 is
unpublished, consumed, terminal, do-not-publish evidence and is not a customer release.

The a24 product correction basis is commit `75babdcc27f894094f776bc9e3d1382ab9e1496f`,
tree `6887f0fbdf27cfce7c2316f2eed336f663ac2bf2`. That exact basis → a24 relationship
preserves runtime implementation and product behavior except for release identity, release-truth
documentation, mechanically resulting package metadata, and release-only verification. The public
a22 → a24 and terminal a23 → a24 relationships are behavior-changing.

Relative to a23, qCoder 0.6.0a24 corrects the customer-visible distinction between a configured
client workspace and a connected client. Managed setup now reports `qCoder configured`. A bounded
verification command reports `qCoder connected` only after an actual client initializes both
canonical MCP servers, discovers exactly twelve public tools plus two private operations, and
completes a successful read-only qCoder request. Direct server smoke is only a credential and
server-readiness preflight. Evidence Review, Algorithm Blueprint, Current Loop, Binding MCP v12,
Current Step Contract v11, request semantics v5, and state schema v16 are preserved. The umbrella
connected-assistant contract advances from binding v47 / schema 46 to binding v48 / schema 47."""

HISTORICAL_STATUS_BLOCK = """Plain 0.6.0a19 remains intentionally reserved and has no accepted frozen or public candidate.
Plain 0.6.0a20 and plain 0.6.0a21 are immutable, unpublished, technically qualified,
publication-truth-rejected, terminal, do-not-publish candidates. They are retained evidence, not
customer releases or upgrade predecessors, and must not be repaired, rebuilt, replaced, tagged,
published, or selected again.

Frozen qCoder 0.6.0a23 is the sole implementation lineage predecessor for a24. It must not be
published, repaired, rebuilt, replaced, tagged, or treated as a customer release."""

UPGRADE_BLOCK = """Install qCoder 0.6.0a24 for a new installation or before starting a new Current Loop. If qCoder
0.6.0a22 already has an active Current Loop, upgrade only at a clean Current Loop boundary:
before a new loop begins or after the current loop has reached a truthful terminal boundary.

Do not upgrade while any binding v45 / Current Step Contract v11 step, completion, continuation
capsule, pending receipt, or recovery action remains outstanding. Finish the outstanding step on
qCoder 0.6.0a22, or explicitly abandon it and restart the work under qCoder 0.6.0a24 at a clean
boundary.

qCoder does not support or claim mid-step migration from binding v45 / Current Step Contract v11
to binding v48 / Current Step Contract v11. A v45/v11 operation receipt, authority grant,
completion input, continuation capsule, or pending step must not be reused or reinterpreted under
v48/v11. Project evidence history may remain; this boundary applies to the active step."""

NONCLAIM_BLOCK = """This release makes no latency, speed, p95, responsiveness, overhead, quiet-operation, or
consistency guarantee; does not establish universal framework neutrality, general framework
qualification, or general PennyLane qualification; and does not activate Tested, First-class,
Client Compatibility, CL-023, named-client support, website, or marketing claims. Publication,
deployment, qualification evidence, public applicability, and support claims remain separate
lifecycle and product decisions."""

CHANGELOG_BLOCK = """Public upgrade predecessor: qCoder 0.6.0a22. The a22 → a24 relationship is behavior-changing.

Implementation lineage predecessor: frozen terminal unpublished qCoder 0.6.0a23 at commit
`9c984936ab0067d2109eb24b9b1ea072b09b686d`. The a23 → a24 relationship is
behavior-changing. The a23 artifacts are consumed, terminal, do-not-publish evidence and are not
a customer upgrade predecessor.

Product correction basis: commit `75babdcc27f894094f776bc9e3d1382ab9e1496f`. That exact
product basis → a24 relationship preserves runtime implementation and product behavior except
for release identity, release-truth documentation, mechanically resulting package metadata, and
release-only verification."""

ACTIVE_BLOCKS = (RELATIONSHIP_PRODUCT_BLOCK, HISTORICAL_STATUS_BLOCK, UPGRADE_BLOCK, NONCLAIM_BLOCK)
RELEASE_NOTE_REQUIRED_CLAUSES = (
    "qCoder 0.6.0a24 is a behavior-changing pre-release successor to public qCoder 0.6.0a22",
    "a23 is unpublished, consumed, terminal, do-not-publish evidence and is not a customer release",
    "75babdcc27f894094f776bc9e3d1382ab9e1496f",
    "6887f0fbdf27cfce7c2316f2eed336f663ac2bf2",
    "That exact basis → a24 relationship preserves runtime implementation and product behavior except for release identity",
    "Managed setup now reports `qCoder configured`",
    "A bounded verification command reports `qCoder connected` only after an actual client initializes both canonical MCP servers",
    "both canonical MCP servers initialized",
    "exactly twelve public tools and two private Current Loop operations were discovered",
    "one public read-only qCoder request completed successfully with canonical process-and-discard retention",
    "Connection does not create a client qualification or support claim",
    "binding v47 / schema 46 to binding v48 / schema 47",
    "Evidence Review, Algorithm Blueprint, Current Loop",
    "only at a clean Current Loop boundary",
    "does not activate Tested, First-class, Client Compatibility, CL-023, named-client support, website, or marketing claims",
)
A22_RELEASE_NOTE_SHA256 = "6d9b26a650f4260cd314ee9b98cd86906c575edbdfd0636add1b36ba9540548e"
A23_RELEASE_NOTE_SHA256 = "c763fa12dc955e9471b893f7b99c3330a4d6288c0663fde65662811950b21946"
PIN_PATTERN = re.compile(r"\bqcoder(?:\[[A-Za-z0-9_,.-]+\])?==([0-9A-Za-z.!+-]+)")
TEXT_SUFFIXES = {".js", ".json", ".md", ".mdx", ".mjs", ".toml", ".ts", ".tsx"}
IGNORED_PARTS = {".git", ".docusaurus", ".pytest_cache", "build", "dist", "node_modules"}


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _metadata_version(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("Version: "):
            return line.removeprefix("Version: ").strip()
    raise ValueError("distribution_metadata_version_missing")


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
            raise ValueError(f"release_truth_block_missing:{surface}")
    forbidden = (
        "behavior-preserving pre-release successor to public qCoder 0.6.0a22",
        "behavior-preserving successor to qCoder 0.6.0a23",
        "qCoder 0.6.0a23 is a customer upgrade predecessor",
        "direct server smoke test establishes client connection",
        "private candidate was public",
        "private candidate is a customer upgrade predecessor",
        "mid-step migration is supported",
        "receipt reuse is supported",
    )
    if any(item in normalized for item in forbidden):
        raise ValueError(f"release_truth_contradiction:{surface}")


def _validate_changelog(text: str) -> None:
    if "## 0.6.0a24" not in text or _normalized(CHANGELOG_BLOCK) not in _normalized(text):
        raise ValueError("release_truth_changelog_block_missing")


def _validate_release_note(text: str, surface: str) -> None:
    normalized = _normalized(text)
    for clause in RELEASE_NOTE_REQUIRED_CLAUSES:
        if _normalized(clause) not in normalized:
            raise ValueError(f"release_truth_note_clause_missing:{surface}")
    _validate_active_surface(
        "\n\n".join(ACTIVE_BLOCKS),
        surface,
    )


def publication_truth(
    source_root: Path, wheel: Path | None = None, sdist: Path | None = None
) -> dict[str, object]:
    readme = (source_root / "README.md").read_text(encoding="utf-8")
    note_path = source_root / "docs/releases/0.6.0a24.md"
    note = note_path.read_text(encoding="utf-8")
    _validate_active_surface(readme, "README.md")
    _validate_release_note(note, str(note_path.relative_to(source_root)))
    _validate_changelog((source_root / "CHANGELOG.md").read_text(encoding="utf-8"))
    historical = source_root / "docs/releases/0.6.0a22.md"
    if hashlib.sha256(historical.read_bytes()).hexdigest() != A22_RELEASE_NOTE_SHA256:
        raise ValueError("historical_a22_release_note_changed")
    terminal_a23 = source_root / "docs/releases/0.6.0a23.md"
    if hashlib.sha256(terminal_a23.read_bytes()).hexdigest() != A23_RELEASE_NOTE_SHA256:
        raise ValueError("terminal_a23_release_note_changed")
    policy = _normalized(
        (source_root / "docs/release-version-policy.md").read_text(encoding="utf-8")
    )
    for clause in (
        "public upgrade predecessor and the implementation-lineage predecessor as distinct relationships",
        "A generic predecessor field, conflation, reversal, or substitution of these relationships fails closed",
        "never become customer upgrade predecessors",
    ):
        if clause not in policy:
            raise ValueError("release_truth_policy_incomplete")
    artifacts = False
    if (wheel is None) != (sdist is None):
        raise ValueError("artifact_pair_incomplete")
    if wheel is not None and sdist is not None:
        _validate_active_surface(_wheel_metadata(wheel), "wheel METADATA")
        _validate_active_surface(_sdist_pkg_info(sdist), "sdist PKG-INFO")
        artifacts = True
    return {
        "source_surfaces_checked": 6,
        "artifact_surfaces_checked": 2 if artifacts else 0,
        "exact_active_blocks": len(ACTIVE_BLOCKS),
        "historical_a22_note_immutable": True,
        "terminal_a23_note_immutable": True,
        "relationships_distinct": True,
    }


def release_metadata(source_root: Path) -> dict[str, object]:
    data = json.loads((source_root / RELEASE_METADATA_FILENAME).read_text(encoding="utf-8"))
    required = {
        "schema",
        "source_version",
        "release_identity_kind",
        "publication_state_authority",
        "public_upgrade_predecessor",
        "implementation_lineage_predecessor",
        "product_correction_basis",
        "intervening_nonpublic_versions",
    }
    if set(data) != required:
        raise ValueError("release_metadata_fields_invalid")
    expected = {
        "schema": RELEASE_METADATA_SCHEMA,
        "source_version": EXPECTED_VERSION,
        "release_identity_kind": "prerelease_successor",
        "publication_state_authority": "external_release_control",
        "public_upgrade_predecessor": PUBLIC_PREDECESSOR,
        "implementation_lineage_predecessor": LINEAGE_PREDECESSOR,
        "product_correction_basis": PRODUCT_CORRECTION_BASIS,
        "intervening_nonpublic_versions": INTERVENING,
    }
    for key, value in expected.items():
        if data[key] != value:
            raise ValueError(f"release_metadata_{key}_invalid")
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
        (source_root / "src/qcoder/__init__.py").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if match is None:
        raise ValueError("qcoder_dunder_version_missing")
    return {
        "pyproject": str(pyproject["project"]["version"]),
        "qcoder.__version__": match.group(1),
        "release_metadata": str(release_metadata(source_root)["source_version"]),
    }


def customer_pin_versions(roots: list[Path]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
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
        versions.update(
            {
                "wheel": _metadata_version(_wheel_metadata(wheel)),
                "sdist": _metadata_version(_sdist_pkg_info(sdist)),
            }
        )
    if any(value != EXPECTED_VERSION for value in versions.values()):
        raise ValueError(f"authoritative_version_mismatch:{versions}")
    pins = customer_pin_versions([root.resolve() for root in customer_roots])
    allowed = {PUBLIC_PREDECESSOR["version"], EXPECTED_VERSION}
    bad = {
        path: values
        for path, values in pins.items()
        if any(value not in allowed for value in values)
    }
    if bad:
        raise ValueError(f"customer_package_pin_mismatch:{bad}")
    truth = publication_truth(source_root, wheel, sdist)
    return {
        "ok": True,
        "result": "pass",
        "version": EXPECTED_VERSION,
        "release_identity_kind": metadata["release_identity_kind"],
        "publication_state_authority": metadata["publication_state_authority"],
        "public_upgrade_predecessor": metadata["public_upgrade_predecessor"],
        "implementation_lineage_predecessor": metadata["implementation_lineage_predecessor"],
        "product_correction_basis": metadata["product_correction_basis"],
        "intervening_nonpublic_versions": metadata["intervening_nonpublic_versions"],
        "authoritative_versions": versions,
        "customer_pins": pins,
        "artifact_versions_checked": wheel is not None,
        "relationships_distinct": True,
        "release_truth": truth,
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
