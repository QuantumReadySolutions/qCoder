from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys
import zipfile


def main() -> None:
    workspace = Path(sys.argv[1]).resolve()
    safe_return = workspace / "safe-return"
    records = sorted(path for path in safe_return.glob("*.json") if path.name != "manifest.json")
    manifest = {
        "schema_id": "qcoder.wi0435.natural_cursor_safe_return_manifest.v4",
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
    manifest_path = safe_return / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    archive = workspace.parent / "qcoder-wi0435-natural-cursor-safe-return-v4.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(safe_return.glob("*.json")):
            bundle.write(path, arcname=path.name)
    print(archive)
    print(f"bytes={archive.stat().st_size}")
    print(f"sha256={sha256(archive.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
