#!/usr/bin/env python3
"""Regenerate or verify deterministic D-118 OpenQASM 3 golden outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qcoder.engines.feature_extraction.openqasm3_bounded_parser import (  # noqa: E402
    parse_openqasm3_bytes,
)
from qcoder.engines.feature_extraction.openqasm3_static_evidence import (  # noqa: E402
    canonical_openqasm3_json,
    render_openqasm3_static_evidence_markdown,
)
from qcoder.engines.review.local_evidence import (  # noqa: E402
    build_local_evidence_review,
    build_share_safe_local_evidence_review,
)
from qcoder.engines.review.local_evidence_markdown import (  # noqa: E402
    render_local_evidence_markdown,
)
from qcoder.evidence_usability import build_evidence_usability_pack, canonical_json  # noqa: E402


CORPUS = ROOT / "tests" / "fixtures" / "openqasm3_v1"
CORPUS_GOLDENS = CORPUS / "goldens"
EXAMPLE = ROOT / "examples" / "openqasm3_static_evidence"
EXAMPLE_EXPECTED = EXAMPLE / "expected"


def _outputs() -> dict[Path, bytes]:
    outputs: dict[Path, bytes] = {}
    representatives = {
        "supported": CORPUS / "supported" / "bell.qasm3",
        "partial": CORPUS / "partial" / "control_flow.qasm3",
        "recognized-unsupported": CORPUS / "recognized" / "timing_calibration_extensions.qasm3",
        "recoverable-malformed": CORPUS / "partial" / "recoverable_malformed.qasm3",
    }
    for label, source in representatives.items():
        sidecar = parse_openqasm3_bytes(source.read_bytes(), artifact_label=source.name).sidecar
        outputs[CORPUS_GOLDENS / f"{label}-sidecar.json"] = canonical_openqasm3_json(
            sidecar
        ).encode()
        outputs[CORPUS_GOLDENS / f"{label}-sidecar.md"] = render_openqasm3_static_evidence_markdown(
            sidecar
        ).encode()

    selected = EXAMPLE / "bell.qasm3"
    paths = [str(selected)]
    local = build_local_evidence_review(paths)
    share_safe = build_share_safe_local_evidence_review(local, paths)
    outputs[EXAMPLE_EXPECTED / "local-evidence.share-safe.json"] = (
        json.dumps(share_safe, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    outputs[EXAMPLE_EXPECTED / "local-evidence.share-safe.md"] = render_local_evidence_markdown(
        share_safe
    ).encode()
    for stem, (payload, markdown) in build_evidence_usability_pack(paths=paths).items():
        outputs[EXAMPLE_EXPECTED / f"{stem}.json"] = canonical_json(payload).encode()
        outputs[EXAMPLE_EXPECTED / f"{stem}.md"] = markdown.encode()
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mismatches = []
    for path, expected in _outputs().items():
        if args.check:
            if not path.is_file() or path.read_bytes() != expected:
                mismatches.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(expected)
    if mismatches:
        print("OpenQASM 3 golden mismatch: " + ", ".join(mismatches), file=sys.stderr)
        return 1
    print("OpenQASM 3 goldens PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
