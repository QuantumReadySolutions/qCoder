#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qcoder.review_before_generation import (  # noqa: E402
    build_first_value,
    canonical_json,
    render_first_value_markdown,
)


REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a Φ+ Bell state. "
    "Before generating the code, help me review how you interpret my request and the important "
    "implementation choices."
)
PROPOSAL = ROOT / "src/qcoder/model_packs/wi0440_bell_review_before_generation_v1.json"
MATRIX = ROOT / "src/qcoder/model_packs/wi0440_review_before_generation_class_matrix_v1.json"
GOLDEN_DIR = ROOT / "tests/fixtures/wi0440_review_before_generation_v1/goldens"


def expected() -> dict[Path, bytes]:
    proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    first_value = build_first_value(REQUEST, proposal)
    profile = json.loads(MATRIX.read_text(encoding="utf-8"))["profiles"]["GHZ"]
    ghz_request = (
        "Use qCoder to review a concrete GHZ Qiskit construction before generating source."
    )
    ghz_proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    ghz_proposal["customer_constraints"] = []
    ghz_proposal["recommended_interpretation"] = profile["recommended_interpretation"]
    ghz_proposal["implementation_recommendations"] = [
        "Use Qiskit QuantumCircuit.",
        profile["quantum_scope"],
        profile["construction"],
        profile["measurement_mapping"],
        profile["output_structure"],
    ]
    ghz_proposal["output_artifact"] = profile["intended_artifact"]
    for index, key in ((1, "construction"), (2, "measurement_mapping"), (3, "output_structure")):
        ghz_proposal["material_choices"][index]["recommendation"] = profile[key]
    ghz_first_value = build_first_value(ghz_request, ghz_proposal)
    return {
        GOLDEN_DIR / "bell-first-value.json": canonical_json(first_value).encode("utf-8"),
        GOLDEN_DIR / "bell-first-value.md": render_first_value_markdown(first_value).encode(
            "utf-8"
        ),
        GOLDEN_DIR / "ghz-first-value.json": canonical_json(ghz_first_value).encode("utf-8"),
        GOLDEN_DIR / "ghz-first-value.md": render_first_value_markdown(ghz_first_value).encode(
            "utf-8"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or verify WI-0440 Bell goldens.")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = expected()
    if args.check:
        mismatches = [
            str(path.relative_to(ROOT))
            for path, data in outputs.items()
            if not path.is_file() or path.read_bytes() != data
        ]
        if mismatches:
            raise SystemExit("golden_mismatch:" + ",".join(mismatches))
        print(json.dumps({"goldens": len(outputs), "ok": True}, sort_keys=True))
        return 0
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for path, data in outputs.items():
        path.write_bytes(data)
    print(json.dumps({"goldens": len(outputs), "ok": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
