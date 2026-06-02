from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qcoder import __version__
from qcoder.pipelines.analyze import analyze_qasm_json
from qcoder.pro_preview.errors import ProPreviewManifestError

WORKFLOW_MANIFEST_SCHEMA_ID = "qcoder.pro_preview.workflow_manifest.v0"


def build_workflow_manifest(
    *,
    qasm: str | None = None,
    before_qasm: str | None = None,
    after_qasm: str | None = None,
    project_dir: str | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    mode = _resolve_mode(qasm=qasm, before_qasm=before_qasm, after_qasm=after_qasm)
    payload: dict[str, Any] = {
        "schema_id": WORKFLOW_MANIFEST_SCHEMA_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "client": {
            "package": "qcoder",
            "version": __version__,
        },
        "mode": mode,
        "workflow": _workflow_metadata(project_dir=project_dir, label=label),
        "boundary": {
            "dry_run": True,
            "upload_performed": False,
            "network_performed": False,
            "source_contents_included": False,
            "cards_local": False,
            "local_pro_analysis": False,
            "confidential_analysis_local": False,
        },
        "non_claims": [
            "not correctness proof",
            "not performance proof",
            "not prediction",
            "not quantum advantage evidence",
            "not service execution",
        ],
    }

    if mode == "single":
        assert qasm is not None
        payload["inputs"] = {
            "qasm": _qasm_manifest_entry(qasm),
        }
    else:
        assert before_qasm is not None
        assert after_qasm is not None
        payload["inputs"] = {
            "before_qasm": _qasm_manifest_entry(before_qasm),
            "after_qasm": _qasm_manifest_entry(after_qasm),
        }
    return payload


def write_workflow_manifest(payload: dict[str, Any], out_path: str) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _resolve_mode(*, qasm: str | None, before_qasm: str | None, after_qasm: str | None) -> str:
    has_single = qasm is not None
    has_before = before_qasm is not None
    has_after = after_qasm is not None
    has_pair = has_before or has_after
    if has_single and has_pair:
        raise ProPreviewManifestError("choose either --qasm or --before-qasm/--after-qasm")
    if has_single:
        return "single"
    if has_before and has_after:
        return "pair"
    if has_before or has_after:
        raise ProPreviewManifestError("pair mode requires both --before-qasm and --after-qasm")
    raise ProPreviewManifestError("dry-run manifest requires --qasm or --before-qasm/--after-qasm")


def _workflow_metadata(*, project_dir: str | None, label: str | None) -> dict[str, Any]:
    workflow: dict[str, Any] = {
        "label": label,
        "project_dir_supplied": bool(project_dir),
    }
    if project_dir:
        workflow["project_dir_name"] = Path(project_dir).name
    return workflow


def _qasm_manifest_entry(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    qasm_bytes = path.read_bytes()
    sha256 = hashlib.sha256(qasm_bytes).hexdigest()
    return {
        "supplied_path": str(path),
        "file_name": path.name,
        "bytes": len(qasm_bytes),
        "sha256": sha256,
        "local_analysis": analyze_qasm_json(str(path)),
    }
