#!/usr/bin/env python3
"""Generate or verify the minimal deterministic D-136 first-value goldens."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from qcoder.review_before_generation import (
    build_first_value,
    canonical_first_value_delivery,
    canonical_json,
    review_revision,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "goldens"
BELL_REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a Φ+ Bell state. "
    "Before generating the code, help me review how you interpret my request and the important "
    "implementation choices."
)
GHZ_REQUEST = (
    "Use qCoder to help me create a Qiskit program that prepares and measures a three-qubit GHZ "
    "state. Before generating the code, help me review how you interpret my request and the "
    "important implementation choices."
)


def _content(*, ghz: bool = False, target: str | None = None) -> dict:
    if not ghz:
        value = json.loads(
            (ROOT / "src/qcoder/model_packs/wi0440_bell_review_before_generation_v1.json").read_text(
                encoding="utf-8"
            )
        )
        value["proposed_source_target"] = target
        return value
    return {
        "interpretation": (
            "Create a three-qubit GHZ Qiskit program and review its implementation plan before "
            "producing source."
        ),
        "implementation_recommendations": [
            {"label": "Framework", "value": "Use Qiskit QuantumCircuit."},
            {"label": "Registers", "value": "Use three qubits and three classical bits."},
            {
                "label": "Preparation",
                "value": "Apply H to q0, then CX from q0 to q1 and CX from q1 to q2.",
            },
            {
                "label": "Measurement",
                "value": "Measure all three qubits into matching classical bits.",
            },
        ],
        "output_artifact": "Readable Python source after confirmation",
        "limitations": ["The review does not claim hardware performance."],
        "blocking_question": None,
        "proposed_source_target": target,
    }


def _delivery(request: str, content: dict) -> dict:
    first = build_first_value(request, content)
    revision = review_revision(request, content)
    return canonical_first_value_delivery(first, review_revision_value=revision)


def _outputs() -> dict[str, str]:
    bell_inline = _delivery(BELL_REQUEST, _content())
    file_request = "Use qCoder to review the Qiskit Bell plan before generating source in bell.py."
    bell_file = _delivery(file_request, _content(target="bell.py"))
    ghz = _delivery(GHZ_REQUEST, _content(ghz=True))
    blocker_content = _content(ghz=True)
    blocker_content["blocking_question"] = "Which oracle behavior should the implementation use?"
    blocker = _delivery(
        "Use qCoder to review an underspecified Qiskit source plan before generation.",
        blocker_content,
    )
    values = {
        "wi0440_d136_bell_inline": bell_inline,
        "wi0440_d136_bell_workspace_file": bell_file,
        "wi0440_d136_ghz_inline": ghz,
        "wi0440_d136_bounded_blocker": blocker,
    }
    result: dict[str, str] = {}
    for stem, value in values.items():
        result[f"{stem}.json"] = canonical_json(value)
        result[f"{stem}.md"] = value["canonical_markdown"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    mismatches: list[str] = []
    for name, payload in _outputs().items():
        path = OUT / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != payload:
                mismatches.append(name)
        else:
            path.write_text(payload, encoding="utf-8")
    if mismatches:
        raise SystemExit("D-136 golden mismatch: " + ", ".join(mismatches))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
