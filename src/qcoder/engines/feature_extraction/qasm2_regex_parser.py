from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .ir import CircuitIR, Operation, QRegDecl


_RE_QREG = re.compile(r"^\s*qreg\s+([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*;\s*$")
_RE_CREG = re.compile(r"^\s*creg\s+([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*;\s*$")
_RE_OPENQASM2 = re.compile(r"^\s*OPENQASM\s+2(\.\d+)?\s*;\s*$", re.IGNORECASE)
_RE_OPENQASM3 = re.compile(r"^\s*OPENQASM\s+3(\.\d+)?\s*;\s*$", re.IGNORECASE)
_RE_INCLUDE = re.compile(r'^\s*include\s+"[^"]+"\s*;\s*$', re.IGNORECASE)

# op forms: name(params?) q[i],q[j];
_RE_OP = re.compile(
    r"^\s*([A-Za-z_]\w*)\s*(\([^)]*\))?\s+(.+?)\s*;\s*$"
)

# qubit ref: q[12]
_RE_QREF = re.compile(r"([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]")


@dataclass(frozen=True)
class _Regs:
    qreg_base: dict[str, int]
    qreg_size: dict[str, int]
    qreg_order: tuple[str, ...]
    n_qubits: int
    n_cbits: int


def _strip_inline_comment(line: str) -> str:
    # QASM2 line comments start with //
    idx = line.find("//")
    return line[:idx] if idx >= 0 else line


def _detect_format(lines: list[str]) -> str:
    for raw in lines:
        s = raw.strip()
        if not s or s.startswith("//"):
            continue
        if _RE_OPENQASM3.match(s):
            return "qasm3"
        if _RE_OPENQASM2.match(s):
            return "qasm2"
        break
    return "unknown"


def _build_regs(lines: list[str]) -> _Regs:
    qreg_base: dict[str, int] = {}
    qreg_size: dict[str, int] = {}
    qreg_order: list[str] = []
    n_qubits = 0
    n_cbits = 0

    for raw in lines:
        s = raw.strip()
        if not s:
            continue

        m = _RE_QREG.match(s)
        if m:
            name = m.group(1)
            size = int(m.group(2))
            if name not in qreg_base:
                qreg_base[name] = n_qubits
                qreg_size[name] = size
                qreg_order.append(name)
                n_qubits += size
            continue

        m = _RE_CREG.match(s)
        if m:
            size = int(m.group(2))
            n_cbits += size
            continue

    return _Regs(
        qreg_base=qreg_base,
        qreg_size=qreg_size,
        qreg_order=tuple(qreg_order),
        n_qubits=n_qubits,
        n_cbits=n_cbits,
    )


def _flatten_qubits(arg_str: str, regs: _Regs) -> tuple[int, ...]:
    # find all qref occurrences in the operand string
    out: list[int] = []
    for reg_name, idx_str in _RE_QREF.findall(arg_str):
        if reg_name not in regs.qreg_base:
            continue
        idx = int(idx_str)
        size = regs.qreg_size[reg_name]
        if 0 <= idx < size:
            out.append(regs.qreg_base[reg_name] + idx)
    return tuple(out)


def _parse_qasm2_lines(lines: list[str]) -> CircuitIR:
    fmt = _detect_format(lines)
    regs = _build_regs(lines)

    ops: list[Operation] = []
    op_index = 0

    for line_index, s in enumerate(lines):
        if not s:
            continue
        if _RE_OPENQASM2.match(s) or _RE_OPENQASM3.match(s) or _RE_INCLUDE.match(s):
            continue
        if _RE_QREG.match(s) or _RE_CREG.match(s):
            continue

        # recognize common non-gate statements
        low = s.lower()
        if low.startswith("barrier"):
            qubits = _flatten_qubits(s, regs)
            ops.append(Operation("barrier", qubits, (), line_index, op_index, is_barrier=True))
            op_index += 1
            continue
        if low.startswith("reset"):
            qubits = _flatten_qubits(s, regs)
            ops.append(Operation("reset", qubits, (), line_index, op_index, is_reset=True))
            op_index += 1
            continue
        if low.startswith("measure"):
            qubits = _flatten_qubits(s, regs)
            ops.append(Operation("measure", qubits, (), line_index, op_index, is_measure=True))
            op_index += 1
            continue

        m = _RE_OP.match(s)
        if not m:
            # unknown construct; count as a custom op with no qubits
            ops.append(Operation("custom", (), (), line_index, op_index, is_custom=True))
            op_index += 1
            continue

        name = m.group(1)
        params_raw = (m.group(2) or "").strip()
        operands = (m.group(3) or "").strip()

        params: tuple[str, ...] = ()
        if params_raw.startswith("(") and params_raw.endswith(")"):
            inside = params_raw[1:-1].strip()
            if inside:
                params = tuple(x.strip() for x in inside.split(",") if x.strip())

        qubits = _flatten_qubits(operands, regs)

        is_custom = False
        if not name or (not qubits and name not in {"id"}):
            is_custom = True
            name = "custom"

        ops.append(Operation(name=name.lower(), qubits=qubits, params=params, line_index=line_index, op_index=op_index, is_custom=is_custom))
        op_index += 1

    qregs = tuple(
        QRegDecl(name=name, size=regs.qreg_size[name], base=regs.qreg_base[name]) for name in regs.qreg_order
    )
    return CircuitIR(
        n_qubits=regs.n_qubits,
        n_cbits=regs.n_cbits,
        operations=tuple(ops),
        qasm_format=fmt,
        qregs=qregs,
    )


def parse_qasm2_text(qasm_text: str, *, source_label: str | None = None) -> CircuitIR:
    """
    Parse OpenQASM 2 source from a string. Same IR as parse_qasm2_file for identical content.

    Does not raise for OpenQASM 3 headers; consumers that need rejection should use
    parse_circuit_file() or check ir.qasm_format.

    source_label: optional provenance string for future diagnostics (unused today).
    """
    _ = source_label  # reserved for error-context diagnostics
    raw_lines = qasm_text.splitlines()
    lines: list[str] = []
    for raw in raw_lines:
        stripped = _strip_inline_comment(raw).strip()
        lines.append(stripped)
    return _parse_qasm2_lines(lines)


def parse_qasm2_file(path: str) -> CircuitIR:
    p = Path(path)
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    return parse_qasm2_text(text)
