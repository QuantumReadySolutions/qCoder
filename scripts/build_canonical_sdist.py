#!/usr/bin/env python3
"""Normalize one validated setuptools sdist into canonical public bytes."""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import io
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
VERIFY_SPEC = importlib.util.spec_from_file_location(
    "verify_public_package_allowlist",
    ROOT / "scripts" / "verify_public_package_allowlist.py",
)
assert VERIFY_SPEC and VERIFY_SPEC.loader
VERIFY = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY)


def canonicalize(source: Path, destination: Path, *, epoch: int) -> None:
    """Validate payload membership, then write deterministic gzip/tar metadata."""
    VERIFY.verify_sdist(source, allow_setuptools_intermediate=True)
    with tarfile.open(source, "r:*") as archive:
        source_members = {item.name: item for item in archive.getmembers()}
        names = VERIFY.validate_member_names(
            [
                item.name
                for item in source_members.values()
                if item.isfile() and PurePosixPath(item.name).name != "setup.cfg"
            ]
        )
        roots = {PurePosixPath(name).parts[0] for name in names}
        if len(roots) != 1:
            raise VERIFY.BoundaryError("canonical sdist requires one root")
        root = next(iter(roots))
        files: dict[str, bytes] = {}
        for name in names:
            handle = archive.extractfile(source_members[name])
            if handle is None:
                raise VERIFY.BoundaryError(f"sdist member unreadable: {name}")
            files[name] = handle.read()

    directories = {root}
    for name in files:
        parent = PurePosixPath(name).parent
        while parent.as_posix() not in {".", ""}:
            directories.add(parent.as_posix())
            parent = parent.parent

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as output:
                for name in sorted(directories):
                    item = tarfile.TarInfo(name)
                    item.type = tarfile.DIRTYPE
                    item.mode = 0o755
                    item.uid = item.gid = 0
                    item.uname = item.gname = ""
                    item.mtime = epoch
                    output.addfile(item)
                for name in sorted(files):
                    payload = files[name]
                    item = tarfile.TarInfo(name)
                    item.mode = 0o644
                    item.uid = item.gid = 0
                    item.uname = item.gname = ""
                    item.mtime = epoch
                    item.size = len(payload)
                    output.addfile(item, io.BytesIO(payload))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--epoch", type=int, required=True)
    args = parser.parse_args()
    canonicalize(args.source, args.destination, epoch=args.epoch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
