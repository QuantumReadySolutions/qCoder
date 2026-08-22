from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile


def main() -> None:
    workspace = Path(sys.argv[1]).resolve()
    operator_run_dir = Path(sys.argv[2]).resolve()
    if (
        workspace == operator_run_dir
        or workspace in operator_run_dir.parents
        or operator_run_dir in workspace.parents
    ):
        raise SystemExit("Operator run directory must be outside the Cursor workspace.")
    records = sorted(
        path for path in operator_run_dir.glob("*.json") if path.name != "manifest.json"
    )
    manifest = {
        "schema_id": "qcoder.wi0435.natural_cursor_safe_return_manifest.v6",
        "records": [
            {
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
            for path in records
        ],
        "excluded": [
            "credentials",
            "Cursor logs",
            "raw qCoder state",
            "source, circuit, and result contents",
            "project MCP configuration",
            "absolute workspace paths",
        ],
    }
    manifest_path = operator_run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    archive = operator_run_dir.parent / "qcoder-wi0435-natural-cursor-safe-return-v6.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(operator_run_dir.glob("*.json")):
            bundle.write(path, arcname=path.name)
    print(archive)
    print(f"bytes={archive.stat().st_size}")
    print(f"sha256={sha256(archive.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
