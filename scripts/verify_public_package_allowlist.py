#!/usr/bin/env python3
"""Verify the WI-0441 exact public package boundary.

The checks are deliberately independent of setuptools discovery.  A source tree
must pass before a build, and an archive must expose exactly the public payload
described by ``packaging/public-package-allowlist-v1.json``.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import stat
import tarfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = ROOT / "packaging/public-package-allowlist-v1.json"
ARCHIVE_SUFFIXES = (
    ".zip",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".whl",
)
FORBIDDEN_NAME_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "docs/private-notes",
    "docs/roadmap",
    "node_modules",
}


class BoundaryError(ValueError):
    """A source or archive member crossed the exact public boundary."""


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def load_allowlist(path: Path = ALLOWLIST_PATH) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_member_name(raw: str) -> str:
    if not raw or "\\" in raw or "\x00" in raw:
        raise BoundaryError(f"unsafe member name: {raw!r}")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BoundaryError(f"unsafe member path: {raw!r}")
    normalized = path.as_posix()
    lowered = normalized.casefold()
    if any(part in lowered for part in FORBIDDEN_NAME_PARTS):
        raise BoundaryError(f"forbidden member class: {raw!r}")
    if lowered.endswith(ARCHIVE_SUFFIXES):
        raise BoundaryError(f"nested/archive member: {raw!r}")
    if lowered.endswith((".map", ".pyc", ".pyo", ".egg-link")):
        raise BoundaryError(f"generated/editable member: {raw!r}")
    if PurePosixPath(lowered).name in {"setup.py", "setup.cfg"}:
        raise BoundaryError(f"unapproved build hook: {raw!r}")
    return normalized


def validate_member_names(names: list[str]) -> list[str]:
    normalized = [_safe_member_name(name) for name in names]
    if len(normalized) != len(set(normalized)):
        raise BoundaryError("duplicate archive member")
    casefolded = [name.casefold() for name in normalized]
    if len(casefolded) != len(set(casefolded)):
        raise BoundaryError("case-folding collision")
    skeletons = [unicodedata.normalize("NFKC", name).casefold() for name in normalized]
    if len(skeletons) != len(set(skeletons)):
        raise BoundaryError("Unicode-normalization collision")
    return normalized


def expected_source_payload(data: dict[str, object]) -> set[str]:
    return set(data["allowed_python_sources"]) | set(data["allowed_package_data_filenames"])


def verify_source_tree(
    root: Path = ROOT, data: dict[str, object] | None = None
) -> dict[str, object]:
    data = data or load_allowlist(root / "packaging/public-package-allowlist-v1.json")
    expected = expected_source_payload(data)
    actual: set[str] = set()
    source_root = root / "src" / "qcoder"
    for path in source_root.rglob("*"):
        if path.is_symlink():
            raise BoundaryError(f"symlink rejected: {path.relative_to(root).as_posix()}")
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode) or path.stat().st_nlink != 1:
            raise BoundaryError(f"non-regular or hard-linked source: {rel}")
        actual.add(_safe_member_name(rel))
    validate_member_names(sorted(actual))
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        raise BoundaryError(f"source allowlist mismatch missing={missing} unexpected={unexpected}")
    for name in data["allowed_sdist_root_files"]:
        path = root / str(name)
        if not path.is_file() or path.is_symlink():
            raise BoundaryError(f"missing/unsafe root member: {name}")
    manifest = []
    for rel in sorted(expected):
        payload = (root / rel).read_bytes()
        manifest.append(
            {"path": rel, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        )
    result = {
        "schema_id": "qcoder.packaging.public_source_manifest.v1",
        "members": manifest,
        "member_count": len(manifest),
        "canonical_sha256": hashlib.sha256(canonical_json(manifest)).hexdigest(),
    }
    return result


def _expected_installed_payload(data: dict[str, object]) -> set[str]:
    return {name.removeprefix("src/") for name in expected_source_payload(data)}


def verify_wheel(path: Path, data: dict[str, object] | None = None) -> dict[str, object]:
    data = data or load_allowlist()
    expected = _expected_installed_payload(data)
    with zipfile.ZipFile(path) as archive:
        names = validate_member_names(
            [item.filename for item in archive.infolist() if not item.is_dir()]
        )
        payload = {name for name in names if name.startswith("qcoder/")}
        if payload != expected:
            raise BoundaryError(
                f"wheel payload mismatch missing={sorted(expected - payload)} unexpected={sorted(payload - expected)}"
            )
        for item in archive.infolist():
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise BoundaryError(f"wheel symlink rejected: {item.filename}")
        record_name = next((name for name in names if name.endswith(".dist-info/RECORD")), None)
        if record_name is None:
            raise BoundaryError("wheel RECORD missing")
        rows = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
        record_paths = {row[0] for row in rows}
        if record_paths != set(names):
            raise BoundaryError("wheel RECORD member set mismatch")
        for member, digest, size in rows:
            if member == record_name:
                if digest or size:
                    raise BoundaryError("RECORD self-row must omit digest and size")
                continue
            raw = archive.read(member)
            expected_digest = (
                "sha256="
                + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()
            )
            if digest != expected_digest or size != str(len(raw)):
                raise BoundaryError(f"RECORD integrity failure: {member}")
    return {"path": path.name, "payload_count": len(payload), "record": "PASS"}


def verify_sdist(
    path: Path,
    data: dict[str, object] | None = None,
    *,
    allow_setuptools_intermediate: bool = False,
) -> dict[str, object]:
    data = data or load_allowlist()
    expected_source = expected_source_payload(data)
    expected_roots = set(data["allowed_sdist_root_files"])
    with tarfile.open(path, "r:*") as archive:
        files = []
        for item in archive.getmembers():
            if item.issym() or item.islnk() or item.isdev() or item.isfifo():
                raise BoundaryError(f"unsafe sdist member type: {item.name}")
            if item.isfile():
                files.append(item.name)
        generated_setup = [name for name in files if PurePosixPath(name).name == "setup.cfg"]
        if allow_setuptools_intermediate:
            if len(generated_setup) != 1:
                raise BoundaryError("setuptools intermediate setup.cfg missing or duplicated")
            setup_payload = archive.extractfile(generated_setup[0])
            if (
                setup_payload is None
                or setup_payload.read() != b"[egg_info]\ntag_build = \ntag_date = 0\n\n"
            ):
                raise BoundaryError("setuptools intermediate setup.cfg content mismatch")
            files.remove(generated_setup[0])
        names = validate_member_names(files)
        roots = {PurePosixPath(name).parts[0] for name in names}
        if len(roots) != 1:
            raise BoundaryError("sdist must have one archive root")
        prefix = next(iter(roots)) + "/"
        stripped = {name.removeprefix(prefix) for name in names}
        source_payload = {
            name for name in stripped if name.startswith("src/qcoder/") and ".egg-info/" not in name
        }
        if source_payload != expected_source:
            raise BoundaryError(
                "sdist source mismatch "
                f"missing={sorted(expected_source - source_payload)} unexpected={sorted(source_payload - expected_source)}"
            )
        allowed_metadata = {
            "PKG-INFO",
            "src/qcoder.egg-info/PKG-INFO",
            "src/qcoder.egg-info/SOURCES.txt",
            "src/qcoder.egg-info/dependency_links.txt",
            "src/qcoder.egg-info/entry_points.txt",
            "src/qcoder.egg-info/requires.txt",
            "src/qcoder.egg-info/top_level.txt",
        }
        unexpected = stripped - expected_source - expected_roots - allowed_metadata
        if unexpected:
            raise BoundaryError(f"unexpected sdist members: {sorted(unexpected)}")
    return {"path": path.name, "payload_count": len(source_payload), "inventory": "PASS"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--sdist", type=Path)
    args = parser.parse_args()
    data = load_allowlist(args.root / "packaging/public-package-allowlist-v1.json")
    result: dict[str, object] = {"source": verify_source_tree(args.root, data)}
    if args.wheel:
        result["wheel"] = verify_wheel(args.wheel, data)
    if args.sdist:
        result["sdist"] = verify_sdist(args.sdist, data)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
