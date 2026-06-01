"""
Lightweight adjoint/mirror eligibility for OpenQASM 2.

Detects unitary eligibility (no measure/reset; conservative) and attempts
to generate mirror QASM via existing inversion utilities. Does not modify
the 48-feature vector; for metadata only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .mirror_build import UnsupportedQasm, build_mirror_qasm

_RE_MEASURE = re.compile(r"^\s*measure\s+", re.I)
_RE_RESET = re.compile(r"^\s*reset\s+", re.I)
_RE_IF = re.compile(r"^\s*if\s*\(", re.I)
_RE_OPENQASM = re.compile(r"^\s*openqasm\s+", re.I)
_RE_INCLUDE = re.compile(r'^\s*include\s+"[^"]+"\s*;\s*$', re.I)
_RE_QREG = re.compile(r"^\s*qreg\s+[A-Za-z_]\w*\s*\[\s*\d+\s*\]\s*;\s*$", re.I)
_RE_CREG = re.compile(r"^\s*creg\s+[A-Za-z_]\w*\s*\[\s*\d+\s*\]\s*;\s*$", re.I)
_RE_BARRIER = re.compile(r"^\s*barrier\s+", re.I)
_RE_OP = re.compile(r"^\s*[A-Za-z_]\w*\s*(\([^)]*\))?\s+.+;\s*$")


@dataclass(frozen=True)
class AdjointEligibility:
    adjoint_supported: bool
    adjoint_reason: str
    mirror_qasm: Optional[str] = None

    def to_metadata_dict(self, *, include_mirror_qasm: bool = False) -> dict:
        out = {
            "adjoint_supported": self.adjoint_supported,
            "adjoint_reason": self.adjoint_reason,
        }
        if include_mirror_qasm and self.mirror_qasm is not None:
            out["mirror_qasm"] = self.mirror_qasm
        return out


def classify_mirror_eligibility(qasm_text: str) -> tuple[str, str]:
    """
    Return (classification, reason) where classification is one of:
      - ok
      - non_unitary
      - parse_error
    Policy:
      - allow terminal measurement block
      - non_unitary on reset
      - non_unitary on measurements before terminal block
      - non_unitary on classical conditional execution (if (...))
    """
    saw_terminal_measure = False

    for line in qasm_text.splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        # Remove trailing inline comments for simple statement checks.
        if "//" in s:
            s = s.split("//", 1)[0].strip()
            if not s:
                continue

        if _RE_RESET.match(s):
            return "non_unitary", "circuit contains reset (not unitary)"
        if _RE_IF.match(s):
            return "non_unitary", "circuit contains classical conditional execution"
        if _RE_MEASURE.match(s):
            saw_terminal_measure = True
            continue

        # Non-measurement statement after measure => mid-circuit measurement.
        if saw_terminal_measure:
            return "non_unitary", "circuit has measurement before terminal measurement block"

        if (
            _RE_OPENQASM.match(s)
            or _RE_INCLUDE.match(s)
            or _RE_QREG.match(s)
            or _RE_CREG.match(s)
            or _RE_BARRIER.match(s)
            or _RE_OP.match(s)
        ):
            continue

        return "parse_error", f"unrecognized statement: {s[:80]}"

    return "ok", ""


def check_adjoint_eligibility(
    qasm_text: str,
    *,
    drop_barriers: bool = True,
    include_mirror_qasm: bool = True,
) -> AdjointEligibility:
    """
    Check whether the circuit is eligible for mirror/adjoint (unitary) and
    attempt to generate mirror QASM.

    Returns AdjointEligibility with adjoint_supported, adjoint_reason, and
    optionally mirror_qasm text. Unitary eligibility is conservative:
    presence of measure or reset lines makes the circuit non-unitary.
    """
    cls, reason = classify_mirror_eligibility(qasm_text)
    if cls != "ok":
        return AdjointEligibility(
            adjoint_supported=False,
            adjoint_reason=reason or cls,
            mirror_qasm=None,
        )
    try:
        mirror_qasm, _ = build_mirror_qasm(qasm_text, drop_barriers=drop_barriers)
        return AdjointEligibility(
            adjoint_supported=True,
            adjoint_reason="",
            mirror_qasm=mirror_qasm if include_mirror_qasm else None,
        )
    except UnsupportedQasm as e:
        return AdjointEligibility(
            adjoint_supported=False,
            adjoint_reason=str(e),
            mirror_qasm=None,
        )
