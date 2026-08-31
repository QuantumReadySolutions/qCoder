"""Package-owned bounded tokenizer/parser for a static OpenQASM 3.0 subset.

This module deliberately does not execute, import, resolve includes, evaluate
runtime state, or repair source.  It extracts qualified static evidence from
one explicitly selected byte sequence.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import re
from typing import Any, Iterable, Sequence

from .ir import CircuitIR, Operation, QRegDecl
from .openqasm3_static_evidence import (
    LANGUAGE_BUILTINS,
    NON_CLAIMS,
    OPENQASM3_PARSER_ID,
    OPENQASM3_STANDARD_GATE_VOCABULARY_ID,
    OPENQASM3_STATIC_EVIDENCE_SCHEMA_ID,
    STANDARD_GATES,
    validate_openqasm3_static_evidence,
)


MAX_SOURCE_BYTES = 100_000
MAX_TOKENS = 40_000
MAX_STATEMENTS = 12_000
MAX_DECLARATIONS = 1_000
MAX_OPERATIONS = 10_000
MAX_NESTING_DEPTH = 32
MAX_EXPRESSION_DEPTH = 32
MAX_CUSTOM_GATES = 256
MAX_MODIFIER_DEPTH = 8
MAX_BROADCAST_EXPANSION = 4_096
MAX_RECOVERY_EVENTS = 128
MAX_DIAGNOSTICS = 512
MAX_LEDGER_ENTRIES = 12_000

PARSER_LIMITS = {
    "source_bytes": MAX_SOURCE_BYTES,
    "tokens": MAX_TOKENS,
    "statements": MAX_STATEMENTS,
    "declarations": MAX_DECLARATIONS,
    "operations": MAX_OPERATIONS,
    "nesting_depth": MAX_NESTING_DEPTH,
    "expression_depth": MAX_EXPRESSION_DEPTH,
    "custom_gates": MAX_CUSTOM_GATES,
    "modifier_depth": MAX_MODIFIER_DEPTH,
    "broadcast_expansion": MAX_BROADCAST_EXPANSION,
    "recovery_events": MAX_RECOVERY_EVENTS,
    "diagnostics": MAX_DIAGNOSTICS,
    "construct_ledger_entries": MAX_LEDGER_ENTRIES,
}

_IDENTIFIER_RE = re.compile(r"(?:[A-Za-z_][A-Za-z0-9_]*|[πτℇ])")
_NUMBER_RE = re.compile(
    r"(?:"
    r"0[xX][0-9A-Fa-f](?:_?[0-9A-Fa-f])*|"
    r"0[oO][0-7](?:_?[0-7])*|"
    r"0[bB][01](?:_?[01])*|"
    r"(?:[0-9](?:_?[0-9])*)?\.(?:[0-9](?:_?[0-9])*)(?:[eE][+-]?[0-9](?:_?[0-9])*)?|"
    r"[0-9](?:_?[0-9])*(?:[eE][+-]?[0-9](?:_?[0-9])*)?"
    r")"
)
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")

_RECOGNIZED_UNSUPPORTED = {
    "qreg": "compatibility_quantum_declaration",
    "creg": "compatibility_classical_declaration",
    "int": "typed_classical_computation",
    "uint": "typed_classical_computation",
    "float": "typed_classical_computation",
    "angle": "typed_classical_computation",
    "bool": "typed_classical_computation",
    "complex": "typed_classical_computation",
    "const": "typed_classical_computation",
    "array": "array",
    "let": "alias",
    "input": "input_declaration",
    "output": "output_declaration",
    "if": "control_flow_if",
    "else": "control_flow_else",
    "for": "control_flow_for",
    "while": "control_flow_while",
    "switch": "control_flow_switch",
    "break": "control_flow_break",
    "continue": "control_flow_continue",
    "end": "control_flow_end",
    "def": "subroutine",
    "return": "return",
    "extern": "extern",
    "delay": "timing_delay",
    "box": "timing_box",
    "duration": "duration",
    "stretch": "stretch",
    "durationof": "durationof",
    "cal": "calibration",
    "defcal": "calibration",
    "defcalgrammar": "calibration_grammar",
    "pragma": "pragma",
    "nop": "later_version_construct",
}
_BLOCK_FAMILIES = {"if", "else", "for", "while", "switch", "def", "box", "cal", "defcal"}
_EXPRESSION_NAMES = {"pi", "tau", "euler", "π", "τ", "ℇ"}


class OpenQASM3ParseError(ValueError):
    """Bounded parser failure category with no raw input in its message."""


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    line: int
    column: int
    end_line: int
    end_column: int


@dataclass(frozen=True)
class OpenQASM3ParseResult:
    sidecar: dict[str, Any]
    circuit_ir: CircuitIR | None


@dataclass
class _CustomGate:
    name: str
    parameter_names: tuple[str, ...]
    qubit_names: tuple[str, ...]
    support: str
    construct_id: str
    body_call_names: list[str]


@dataclass(frozen=True)
class _Expression:
    canonical: str
    integer_value: int | None
    supported: bool


def _advance_position(value: str, line: int, column: int) -> tuple[int, int]:
    for character in value:
        if character == "\n":
            line += 1
            column = 1
        else:
            column += 1
    return line, column


def _tokenize(text: str) -> tuple[list[Token], int]:
    tokens: list[Token] = []
    position = 0
    line = 1
    column = 1
    maximum_nesting = 0
    nesting = 0
    length = len(text)
    while position < length:
        character = text[position]
        if character.isspace():
            start = position
            while position < length and text[position].isspace():
                position += 1
            line, column = _advance_position(text[start:position], line, column)
            continue
        if text.startswith("//", position):
            end = text.find("\n", position + 2)
            if end < 0:
                end = length
            line, column = _advance_position(text[position:end], line, column)
            position = end
            continue
        if text.startswith("/*", position):
            end = text.find("*/", position + 2)
            if end < 0:
                raise OpenQASM3ParseError("unterminated_block_comment")
            end += 2
            line, column = _advance_position(text[position:end], line, column)
            position = end
            continue
        start_line, start_column = line, column
        if character == '"':
            end = position + 1
            escaped = False
            while end < length:
                current = text[end]
                if current == "\n":
                    raise OpenQASM3ParseError("unterminated_string")
                if current == '"' and not escaped:
                    end += 1
                    break
                escaped = current == "\\" and not escaped
                if current != "\\":
                    escaped = False
                end += 1
            else:
                raise OpenQASM3ParseError("unterminated_string")
            value = text[position:end]
            line, column = _advance_position(value, line, column)
            tokens.append(Token("string", value, start_line, start_column, line, column))
            position = end
        elif match := _IDENTIFIER_RE.match(text, position):
            value = match.group(0)
            position = match.end()
            column += len(value)
            tokens.append(Token("identifier", value, start_line, start_column, line, column))
        elif match := _NUMBER_RE.match(text, position):
            value = match.group(0)
            position = match.end()
            column += len(value)
            tokens.append(Token("number", value, start_line, start_column, line, column))
        elif (
            text.startswith("->", position)
            or text.startswith("**", position)
            or text.startswith("++", position)
        ):
            value = text[position : position + 2]
            position += 2
            column += 2
            tokens.append(Token("symbol", value, start_line, start_column, line, column))
        elif character in ";,[](){}@=:+-*/$!<>|&%^~":
            position += 1
            column += 1
            tokens.append(Token("symbol", character, start_line, start_column, line, column))
            if character in "([{":
                nesting += 1
                maximum_nesting = max(maximum_nesting, nesting)
            elif character in ")]}" and nesting:
                nesting -= 1
        else:
            raise OpenQASM3ParseError("unrecognized_character")
        if len(tokens) > MAX_TOKENS:
            raise OpenQASM3ParseError("token_limit_exceeded")
    return tokens, maximum_nesting


def _span(tokens: Sequence[Token]) -> dict[str, int]:
    if not tokens:
        return {"start_line": 1, "start_column": 1, "end_line": 1, "end_column": 1}
    return {
        "start_line": tokens[0].line,
        "start_column": tokens[0].column,
        "end_line": tokens[-1].end_line,
        "end_column": tokens[-1].end_column,
    }


def _split_top_level(tokens: Sequence[Token], separator: str = ",") -> list[list[Token]]:
    rows: list[list[Token]] = [[]]
    depth = 0
    for token in tokens:
        if token.value in {"(", "[", "{"}:
            depth += 1
        elif token.value in {
            ")",
            "]",
            "}",
        }:
            depth -= 1
        if token.value == separator and depth == 0:
            rows.append([])
        else:
            rows[-1].append(token)
    return rows


def _canonical_expression(node: ast.AST) -> str:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return repr(node.value)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operator = "+" if isinstance(node.op, ast.UAdd) else "-"
        return f"({operator}{_canonical_expression(node.operand)})"
    if isinstance(node, ast.BinOp) and isinstance(
        node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
    ):
        operator = {
            ast.Add: "+",
            ast.Sub: "-",
            ast.Mult: "*",
            ast.Div: "/",
            ast.Pow: "**",
        }[type(node.op)]
        return f"({_canonical_expression(node.left)}{operator}{_canonical_expression(node.right)})"
    raise OpenQASM3ParseError("unsupported_expression")


def _expression_depth(node: ast.AST) -> int:
    children = list(ast.iter_child_nodes(node))
    return 1 + (max((_expression_depth(child) for child in children), default=0))


def _fraction_value(node: ast.AST, allowed_names: set[str]) -> Fraction | None:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ):
        return Fraction(node.value)
    if isinstance(node, ast.Name) and node.id in allowed_names:
        return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _fraction_value(node.operand, allowed_names)
        if value is None:
            return None
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left = _fraction_value(node.left, allowed_names)
        right = _fraction_value(node.right, allowed_names)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise OpenQASM3ParseError("division_by_zero")
            return left / right
        if isinstance(node.op, ast.Pow):
            if right.denominator != 1 or abs(right.numerator) > 1024:
                raise OpenQASM3ParseError("unsupported_expression")
            if left == 0 and right < 0:
                raise OpenQASM3ParseError("division_by_zero")
            return left**right.numerator
    return None


def _parse_expression(tokens: Sequence[Token], *, formal_names: Iterable[str] = ()) -> _Expression:
    if not tokens:
        return _Expression("", None, False)
    source = "".join(token.value for token in tokens)
    source = source.replace("π", "pi").replace("τ", "tau").replace("ℇ", "euler")
    allowed_names = set(formal_names) | _EXPRESSION_NAMES
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, ValueError):
        return _Expression("", None, False)
    if _expression_depth(tree) > MAX_EXPRESSION_DEPTH:
        return _Expression("", None, False)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in allowed_names:
            return _Expression("", None, False)
        if isinstance(node, ast.Constant) and (
            not isinstance(node.value, (int, float)) or isinstance(node.value, bool)
        ):
            return _Expression("", None, False)
        if isinstance(
            node,
            (
                ast.Expression,
                ast.Load,
                ast.Constant,
                ast.Name,
                ast.UnaryOp,
                ast.UAdd,
                ast.USub,
                ast.BinOp,
                ast.Add,
                ast.Sub,
                ast.Mult,
                ast.Div,
                ast.Pow,
            ),
        ):
            continue
        return _Expression("", None, False)
    try:
        canonical = _canonical_expression(tree.body)
        value = _fraction_value(tree.body, allowed_names)
    except OpenQASM3ParseError:
        return _Expression("", None, False)
    integer_value = int(value) if value is not None and value.denominator == 1 else None
    return _Expression(canonical, integer_value, True)


def _parse_integer(token: Token) -> int | None:
    if token.kind != "number" or any(mark in token.value.casefold() for mark in (".", "e")):
        return None
    try:
        return int(token.value.replace("_", ""), 0 if token.value.startswith("0") else 10)
    except ValueError:
        return None


class _Parser:
    def __init__(self, raw: bytes, text: str, artifact_label: str):
        self.raw = raw
        self.text = text
        self.artifact_label = artifact_label
        self.tokens: list[Token] = []
        self.position = 0
        self.maximum_nesting = 0
        self.declared_version: str | None = None
        self.constructs: list[dict[str, Any]] = []
        self.unsupported_regions: list[dict[str, Any]] = []
        self.recoveries: list[dict[str, Any]] = []
        self.diagnostics: list[dict[str, Any]] = []
        self.includes: list[dict[str, Any]] = []
        self.quantum_declarations: list[dict[str, Any]] = []
        self.classical_declarations: list[dict[str, Any]] = []
        self.quantum: dict[str, tuple[int, int]] = {}
        self.classical: dict[str, tuple[int, int]] = {}
        self.operations: list[Operation] = []
        self.measurements: list[dict[str, Any]] = []
        self.modifier_chains: list[dict[str, Any]] = []
        self.custom_gate_rows: list[dict[str, Any]] = []
        self.custom_gates: dict[str, _CustomGate] = {}
        self.standard_gates_active = False
        self.statement_count = 0
        self.maximum_broadcast = 0
        self.fatal_error: dict[str, Any] | None = None

    def _token_span(self) -> dict[str, int]:
        if self.tokens:
            return _span(self.tokens[max(0, min(self.position, len(self.tokens) - 1)) :][:1])
        return _span(())

    def _diagnostic(
        self,
        category: str,
        message: str,
        tokens: Sequence[Token],
        *,
        construct_id: str | None = None,
        severity: str = "limitation",
    ) -> None:
        if len(self.diagnostics) >= MAX_DIAGNOSTICS:
            self._fatal("parser_limit_exceeded", "The diagnostic limit was exceeded.", tokens)
            return
        self.diagnostics.append(
            {
                "category": category,
                "severity": severity,
                "construct_id": construct_id,
                "span": _span(tokens),
                "message": message,
            }
        )

    def _fatal(self, category: str, message: str, tokens: Sequence[Token]) -> None:
        if self.fatal_error is None:
            self.fatal_error = {"category": category, "message": message, "span": _span(tokens)}

    def _add_construct(
        self,
        *,
        family: str,
        name: str,
        classification: str,
        tokens: Sequence[Token],
        established: Sequence[str],
        unavailable: Sequence[str] = (),
        effects: Sequence[str] = (),
        category: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        construct_id = f"construct-{len(self.constructs) + 1:04d}"
        row = {
            "construct_id": construct_id,
            "family": family,
            "name": name,
            "classification": classification,
            "span": _span(tokens),
            "established": list(established),
            "unavailable": list(unavailable),
            "dependent_fact_effects": list(effects),
        }
        self.constructs.append(row)
        if len(self.constructs) > MAX_LEDGER_ENTRIES:
            self._fatal("parser_limit_exceeded", "The construct-ledger limit was exceeded.", tokens)
        if classification in {
            "partially_supported",
            "recognized_but_unsupported",
            "unrecognized",
        }:
            diagnostic_category = category or (
                "unrecognized_construct"
                if classification == "unrecognized"
                else "unsupported_construct"
            )
            limitation = message or "The construct is outside the bounded supported subset."
            self.unsupported_regions.append(
                {
                    "construct_id": construct_id,
                    "classification": classification,
                    "category": diagnostic_category,
                    "span": _span(tokens),
                    "limitation": limitation,
                }
            )
            self._diagnostic(diagnostic_category, limitation, tokens, construct_id=construct_id)
        elif classification == "malformed":
            self.recoveries.append(
                {
                    "construct_id": construct_id,
                    "category": "malformed_syntax",
                    "span": _span(tokens),
                    "boundary_reliable": True,
                    "source_repaired": False,
                }
            )
            self._diagnostic(
                "malformed_syntax",
                message or "One bounded statement was malformed and was not repaired.",
                tokens,
                construct_id=construct_id,
                severity="error",
            )
            if len(self.recoveries) > MAX_RECOVERY_EVENTS:
                self._fatal(
                    "parser_limit_exceeded", "The recovery-event limit was exceeded.", tokens
                )
        return row

    def _consume_statement(self) -> list[Token] | None:
        start = self.position
        paren = 0
        bracket = 0
        brace = 0
        while self.position < len(self.tokens):
            token = self.tokens[self.position]
            if token.value == "(":
                paren += 1
            elif token.value == ")":
                paren -= 1
            elif token.value == "[":
                bracket += 1
            elif token.value == "]":
                bracket -= 1
            elif token.value == "{":
                brace += 1
            elif token.value == "}":
                if brace == 0:
                    return None
                brace -= 1
            self.position += 1
            if token.value == ";" and paren == 0 and bracket == 0 and brace == 0:
                self.statement_count += 1
                if self.statement_count > MAX_STATEMENTS:
                    self._fatal(
                        "parser_limit_exceeded", "The statement limit was exceeded.", [token]
                    )
                return self.tokens[start : self.position]
        return None

    def _consume_block(self) -> list[Token] | None:
        start = self.position
        brace = next(
            (index for index in range(start, len(self.tokens)) if self.tokens[index].value == "{"),
            None,
        )
        semicolon = next(
            (index for index in range(start, len(self.tokens)) if self.tokens[index].value == ";"),
            None,
        )
        if brace is None or (semicolon is not None and semicolon < brace):
            return self._consume_statement()
        depth = 0
        for index in range(brace, len(self.tokens)):
            token = self.tokens[index]
            if token.value == "{":
                depth += 1
            elif token.value == "}":
                depth -= 1
                if depth == 0:
                    self.position = index + 1
                    if self.position < len(self.tokens) and self.tokens[self.position].value == ";":
                        self.position += 1
                    self.statement_count += 1
                    return self.tokens[start : self.position]
        return None

    def _parse_header(self) -> None:
        if not self.tokens:
            self._fatal("missing_header", "An operative OPENQASM declaration is required.", ())
            return
        first = self.tokens[0]
        if first.value != "OPENQASM":
            category = (
                "invalid_header" if first.value.casefold() == "openqasm" else "missing_header"
            )
            self._fatal(category, "The operative OpenQASM version declaration is invalid.", [first])
            return
        if len(self.tokens) < 3 or self.tokens[2].value != ";":
            self._fatal(
                "invalid_header",
                "The operative OpenQASM version declaration is malformed.",
                self.tokens[:3],
            )
            return
        version = self.tokens[1].value
        if self.tokens[1].kind != "number" or not _VERSION_RE.fullmatch(version):
            self._fatal(
                "invalid_header",
                "The operative OpenQASM version declaration is malformed.",
                self.tokens[:3],
            )
            return
        if version not in {"3", "3.0"}:
            self._fatal(
                "unsupported_openqasm_version",
                "This bounded parser supports only declared OpenQASM 3.0.",
                self.tokens[:3],
            )
            return
        self.declared_version = "3.0"
        self.position = 3
        self.statement_count = 1
        for token in self.tokens[3:]:
            if token.value.casefold() == "openqasm":
                category = "invalid_header" if token.value != "OPENQASM" else "malformed_syntax"
                self._fatal(
                    category,
                    "A duplicate or misplaced OpenQASM declaration is not accepted.",
                    [token],
                )
                return

    def _declaration(
        self,
        tokens: Sequence[Token],
        *,
        kind: str,
        allow_measurement: bool = True,
    ) -> None:
        core = list(tokens[:-1])
        equals = next((i for i, token in enumerate(core) if token.value == "="), None)
        left = core if equals is None else core[:equals]
        right = [] if equals is None else core[equals + 1 :]
        size = 1
        name_index = 1
        if len(left) >= 5 and left[1].value == "[" and left[3].value == "]":
            parsed_size = _parse_integer(left[2])
            if parsed_size is None or parsed_size <= 0:
                self._recover_malformed(
                    tokens, f"{kind}_declaration", "The declaration size is invalid."
                )
                return
            size = parsed_size
            name_index = 4
        if len(left) != name_index + 1 or left[name_index].kind != "identifier":
            self._recover_malformed(
                tokens, f"{kind}_declaration", "The declaration shape is invalid."
            )
            return
        name = left[name_index].value
        if name in self.quantum or name in self.classical or name in self.custom_gates:
            row = self._add_construct(
                family=f"{kind}_declaration",
                name=name,
                classification="malformed",
                tokens=tokens,
                established=("The declaration boundary and duplicate name were identified.",),
                unavailable=("A new register was not established.",),
                effects=("Declaration-derived width is not complete.",),
                message="A duplicate declaration was rejected.",
            )
            self.diagnostics[-1]["category"] = "duplicate_declaration"
            self.diagnostics[-1]["message"] = "A duplicate declaration was rejected."
            return
        total_declarations = len(self.quantum_declarations) + len(self.classical_declarations)
        if total_declarations >= MAX_DECLARATIONS:
            self._fatal("parser_limit_exceeded", "The declaration limit was exceeded.", tokens)
            return
        target = self.quantum if kind == "qubit" else self.classical
        rows = self.quantum_declarations if kind == "qubit" else self.classical_declarations
        base = sum(row["size"] for row in rows)
        target[name] = (size, base)
        row = self._add_construct(
            family=f"{kind}_declaration",
            name=name,
            classification="supported",
            tokens=tokens,
            established=(f"A {kind} declaration with static size {size} was established.",),
        )
        rows.append(
            {"name": name, "size": size, "base": base, "support": "supported", "span": row["span"]}
        )
        if right:
            if kind == "bit" and allow_measurement and right[0].value == "measure":
                self._measurement(
                    tokens,
                    right,
                    form="declaration",
                    destination_tokens=[left[name_index]],
                    existing_construct=row,
                )
            else:
                row["classification"] = "recognized_but_unsupported"
                row["unavailable"] = [
                    "General classical initialization semantics were not interpreted."
                ]
                row["dependent_fact_effects"] = ["Classical-value facts are not established."]
                self.unsupported_regions.append(
                    {
                        "construct_id": row["construct_id"],
                        "classification": row["classification"],
                        "category": "unsupported_construct",
                        "span": row["span"],
                        "limitation": "Only bit initialization by a supported measurement is supported.",
                    }
                )
                self._diagnostic(
                    "unsupported_construct",
                    "Only bit initialization by a supported measurement is supported.",
                    tokens,
                    construct_id=row["construct_id"],
                )

    def _recover_malformed(self, tokens: Sequence[Token], family: str, message: str) -> None:
        self._add_construct(
            family=family,
            name=tokens[0].value if tokens else "unknown",
            classification="malformed",
            tokens=tokens,
            established=("The statement boundary and construct family were identified.",),
            unavailable=("The malformed occurrence was not semantically interpreted.",),
            effects=("Dependent facts are downgraded or withheld.",),
            message=message,
        )

    def _resolve_reference(
        self,
        tokens: Sequence[Token],
        *,
        classical: bool = False,
        formal_qubits: set[str] | None = None,
    ) -> tuple[list[int], str | None]:
        if not tokens:
            return [], "invalid_register_reference"
        if tokens[0].value == "$":
            return [], "unsupported_construct"
        if tokens[0].kind != "identifier":
            return [], "invalid_register_reference"
        name = tokens[0].value
        if formal_qubits is not None:
            if len(tokens) == 1 and name in formal_qubits:
                return [-1], None
            return [], "invalid_register_reference"
        registers = self.classical if classical else self.quantum
        if name not in registers:
            return [], "invalid_register_reference"
        size, base = registers[name]
        if len(tokens) == 1:
            return list(range(base, base + size)), None
        if len(tokens) == 4 and tokens[1].value == "[" and tokens[3].value == "]":
            index = _parse_integer(tokens[2])
            if index is None:
                return [], "unsupported_construct"
            if index < 0 or index >= size:
                return [], "index_out_of_range"
            return [base + index], None
        return [], "unsupported_construct"

    def _measurement(
        self,
        tokens: Sequence[Token],
        expression_tokens: Sequence[Token],
        *,
        form: str,
        destination_tokens: Sequence[Token] = (),
        existing_construct: dict[str, Any] | None = None,
    ) -> None:
        expression = list(expression_tokens)
        source_tokens: list[Token]
        destination = list(destination_tokens)
        if form in {"declaration", "assignment"}:
            if not expression or expression[0].value != "measure":
                return
            source_tokens = expression[1:]
        elif form == "arrow":
            arrow = next((i for i, token in enumerate(expression) if token.value == "->"), -1)
            if arrow < 1:
                self._recover_malformed(
                    tokens, "measurement", "The measurement arrow form is malformed."
                )
                return
            source_tokens = expression[1:arrow]
            destination = expression[arrow + 1 :]
        else:
            source_tokens = expression[1:]
        qtargets, qerror = self._resolve_reference(source_tokens)
        ctargets: list[int] = []
        cerror = None
        if destination:
            ctargets, cerror = self._resolve_reference(destination, classical=True)
        valid = (
            qerror is None
            and cerror is None
            and (not destination or len(qtargets) == len(ctargets))
        )
        if existing_construct is None:
            row = self._add_construct(
                family="measurement",
                name="measure",
                classification="supported" if valid else "partially_supported",
                tokens=tokens,
                established=("The measurement form and bounded source span were identified.",),
                unavailable=()
                if valid
                else ("The complete measurement mapping was not established.",),
                effects=() if valid else ("Measurement count and mapping are not complete.",),
                category=qerror or cerror or "unsupported_construct",
                message=(
                    None
                    if valid
                    else "The measurement reference or register widths are unsupported."
                ),
            )
        else:
            row = existing_construct
            if not valid:
                row["classification"] = "partially_supported"
                row["unavailable"] = ["The complete measurement mapping was not established."]
                row["dependent_fact_effects"] = ["Measurement count and mapping are not complete."]
                self.unsupported_regions.append(
                    {
                        "construct_id": row["construct_id"],
                        "classification": "partially_supported",
                        "category": qerror or cerror or "unsupported_construct",
                        "span": row["span"],
                        "limitation": "The measurement reference or register widths are unsupported.",
                    }
                )
                self._diagnostic(
                    qerror or cerror or "unsupported_construct",
                    "The measurement reference or register widths are unsupported.",
                    tokens,
                    construct_id=row["construct_id"],
                )
        self.measurements.append(
            {
                "construct_id": row["construct_id"],
                "form": form,
                "quantum_targets": qtargets,
                "classical_targets": ctargets,
                "exactness": "exact" if valid else "partial",
                "span": row["span"],
            }
        )
        if valid:
            for offset, qubit in enumerate(qtargets):
                self.operations.append(
                    Operation(
                        name="measure",
                        qubits=(qubit,),
                        params=(),
                        line_index=tokens[0].line - 1,
                        op_index=len(self.operations),
                        is_measure=True,
                    )
                )

    def _parse_modifiers(
        self, tokens: Sequence[Token], formal_parameters: set[str]
    ) -> tuple[list[dict[str, Any]], int, int, bool]:
        modifiers: list[dict[str, Any]] = []
        position = 0
        controls = 0
        valid = True
        while position < len(tokens):
            at = next((i for i in range(position, len(tokens)) if tokens[i].value == "@"), None)
            if at is None:
                break
            part = tokens[position:at]
            if not part or part[0].kind != "identifier":
                valid = False
                break
            name = part[0].value
            argument_tokens: Sequence[Token] = ()
            if len(part) > 1:
                if len(part) < 4 or part[1].value != "(" or part[-1].value != ")":
                    valid = False
                else:
                    argument_tokens = part[2:-1]
            expression = (
                _parse_expression(argument_tokens, formal_names=formal_parameters)
                if argument_tokens
                else None
            )
            support = "supported"
            if name not in {"inv", "ctrl", "negctrl", "pow"}:
                support = "recognized_but_unsupported"
                valid = False
            elif name == "inv" and argument_tokens:
                support = "recognized_but_unsupported"
                valid = False
            elif name in {"ctrl", "negctrl"}:
                count = (
                    1 if not argument_tokens else (expression.integer_value if expression else None)
                )
                if count is None or count <= 0:
                    support = "recognized_but_unsupported"
                    valid = False
                else:
                    controls += count
            elif name == "pow" and (not expression or not expression.supported):
                support = "recognized_but_unsupported"
                valid = False
            modifiers.append(
                {
                    "name": name if name in {"inv", "ctrl", "negctrl", "pow"} else "pow",
                    "argument": expression.canonical
                    if expression and expression.supported
                    else None,
                    "support": support,
                }
            )
            position = at + 1
            if len(modifiers) > MAX_MODIFIER_DEPTH:
                return modifiers, position, controls, False
        return modifiers, position, controls, valid

    def _gate_call(
        self,
        tokens: Sequence[Token],
        *,
        formal_qubits: set[str] | None = None,
        formal_parameters: set[str] | None = None,
        current_gate: str | None = None,
        emit_operation: bool = True,
    ) -> tuple[str, str]:
        core = list(tokens[:-1]) if tokens and tokens[-1].value == ";" else list(tokens)
        parameter_names = formal_parameters or set()
        modifiers, position, controls, modifiers_valid = self._parse_modifiers(
            core, parameter_names
        )
        if position >= len(core) or core[position].kind != "identifier":
            self._recover_malformed(tokens, "quantum_operation", "The operation name is malformed.")
            return "malformed", ""
        name = core[position].value
        position += 1
        parameters: list[_Expression] = []
        if position < len(core) and core[position].value == "(":
            depth = 0
            close = None
            for index in range(position, len(core)):
                if core[index].value == "(":
                    depth += 1
                elif core[index].value == ")":
                    depth -= 1
                    if depth == 0:
                        close = index
                        break
            if close is None:
                self._recover_malformed(
                    tokens, "quantum_operation", "The parameter list is malformed."
                )
                return "malformed", name
            groups = _split_top_level(core[position + 1 : close])
            if groups == [[]]:
                groups = []
            parameters = [
                _parse_expression(group, formal_names=parameter_names) for group in groups
            ]
            position = close + 1
        operands = _split_top_level(core[position:])
        if operands == [[]]:
            operands = []
        signature: tuple[int, int] | None = None
        custom = False
        declared_support = "supported"
        if name in LANGUAGE_BUILTINS:
            signature = LANGUAGE_BUILTINS[name]
        elif self.standard_gates_active and name in STANDARD_GATES:
            signature = STANDARD_GATES[name]
        elif name in self.custom_gates:
            definition = self.custom_gates[name]
            signature = (len(definition.parameter_names), len(definition.qubit_names))
            custom = True
            declared_support = definition.support
        classification = "supported"
        category = None
        limitation = None
        if name == current_gate:
            classification = "recognized_but_unsupported"
            category = "unsupported_construct"
            limitation = "Recursive custom-gate calls are recognized but unsupported."
        elif signature is None:
            classification = "unrecognized"
            category = "unrecognized_construct"
            limitation = (
                "The gate name is not a built-in, active standard gate, or valid prior custom gate."
            )
        elif declared_support != "supported":
            classification = "partially_supported"
            category = "unsupported_construct"
            limitation = "The referenced custom-gate declaration is not fully supported."
        elif not modifiers_valid:
            classification = "partially_supported"
            category = "unsupported_modifier"
            limitation = "The complete modifier chain is not supported."
        elif len(modifiers) > MAX_MODIFIER_DEPTH:
            classification = "partially_supported"
            category = "parser_limit_exceeded"
            limitation = "The modifier-depth limit was exceeded."
        elif any(not expression.supported for expression in parameters):
            classification = "partially_supported"
            category = "unsupported_expression"
            limitation = "At least one parameter expression is outside the bounded subset."
        elif len(parameters) != signature[0] or len(operands) != signature[1] + controls:
            classification = "partially_supported"
            category = "unsupported_construct"
            limitation = (
                "The exact parameter or target arity does not match the operation signature."
            )
        resolved: list[list[int]] = []
        reference_error: str | None = None
        if classification == "supported" and signature is not None:
            for operand in operands:
                indexes, error = self._resolve_reference(operand, formal_qubits=formal_qubits)
                if error:
                    reference_error = error
                    break
                resolved.append(indexes)
            if reference_error:
                classification = (
                    "recognized_but_unsupported"
                    if reference_error == "unsupported_construct"
                    else "partially_supported"
                )
                category = reference_error
                limitation = "At least one operation target is not statically resolvable."
        expansion = 1
        expanded_targets: list[tuple[int, ...]] = []
        if classification == "supported" and formal_qubits is None:
            widths = [len(indexes) for indexes in resolved]
            expansion = max(widths, default=1)
            if any(width not in {1, expansion} for width in widths):
                classification = "partially_supported"
                category = "unsupported_construct"
                limitation = "Register broadcasting requires mechanically known equal widths."
            elif expansion > MAX_BROADCAST_EXPANSION:
                self._fatal(
                    "parser_limit_exceeded", "The broadcast-expansion limit was exceeded.", tokens
                )
                classification = "partially_supported"
                category = "parser_limit_exceeded"
                limitation = "The broadcast-expansion limit was exceeded."
            else:
                self.maximum_broadcast = max(self.maximum_broadcast, expansion)
                expanded_targets = [
                    tuple(
                        indexes[0] if len(indexes) == 1 else indexes[offset] for indexes in resolved
                    )
                    for offset in range(expansion)
                ]
        row = self._add_construct(
            family="custom_gate_call" if custom else "quantum_operation",
            name=name,
            classification=classification,
            tokens=tokens,
            established=(
                "The operation identity, source span, explicit parameter forms, and explicit target forms were identified.",
            ),
            unavailable=()
            if classification == "supported"
            else (
                "Complete operation semantics and every dependent structural fact were not established.",
            ),
            effects=()
            if classification == "supported"
            else ("Operation count, depth, interactions, and gate statistics are qualified.",),
            category=category,
            message=limitation,
        )
        if modifiers:
            self.modifier_chains.append(
                {"construct_id": row["construct_id"], "modifiers": modifiers}
            )
        if classification == "supported" and emit_operation and formal_qubits is None:
            if len(self.operations) + len(expanded_targets) > MAX_OPERATIONS:
                self._fatal("parser_limit_exceeded", "The operation limit was exceeded.", tokens)
            else:
                for targets in expanded_targets:
                    self.operations.append(
                        Operation(
                            name=name,
                            qubits=targets,
                            params=tuple(expression.canonical for expression in parameters),
                            line_index=tokens[0].line - 1,
                            op_index=len(self.operations),
                            is_custom=custom,
                        )
                    )
        return classification, name

    def _custom_gate(self, tokens: Sequence[Token]) -> None:
        try:
            open_brace = next(i for i, token in enumerate(tokens) if token.value == "{")
            close_brace = (
                len(tokens)
                - 1
                - next(i for i, token in enumerate(reversed(tokens)) if token.value == "}")
            )
        except StopIteration:
            self._fatal("malformed_syntax", "The custom-gate body boundary is malformed.", tokens)
            return
        header = list(tokens[:open_brace])
        body = list(tokens[open_brace + 1 : close_brace])
        if len(header) < 3 or header[0].value != "gate" or header[1].kind != "identifier":
            self._recover_malformed(
                tokens, "custom_gate_declaration", "The custom-gate declaration is malformed."
            )
            return
        name = header[1].value
        if (
            name in self.quantum
            or name in self.classical
            or name in self.custom_gates
            or name in LANGUAGE_BUILTINS
            or name in STANDARD_GATES
        ):
            self._recover_malformed(
                tokens, "custom_gate_declaration", "The custom-gate name is duplicate or reserved."
            )
            return
        position = 2
        formal_parameters: list[str] = []
        if position < len(header) and header[position].value == "(":
            close = next(
                (i for i in range(position + 1, len(header)) if header[i].value == ")"), None
            )
            if close is None:
                self._recover_malformed(
                    tokens,
                    "custom_gate_declaration",
                    "The custom-gate parameter list is malformed.",
                )
                return
            groups = _split_top_level(header[position + 1 : close])
            if groups != [[]]:
                if any(len(group) != 1 or group[0].kind != "identifier" for group in groups):
                    self._recover_malformed(
                        tokens,
                        "custom_gate_declaration",
                        "Custom-gate formal parameters are invalid.",
                    )
                    return
                formal_parameters = [group[0].value for group in groups]
            position = close + 1
        groups = _split_top_level(header[position:])
        if not groups or any(len(group) != 1 or group[0].kind != "identifier" for group in groups):
            self._recover_malformed(
                tokens, "custom_gate_declaration", "Custom-gate formal qubits are invalid."
            )
            return
        formal_qubits = [group[0].value for group in groups]
        if (
            len(set(formal_parameters)) != len(formal_parameters)
            or len(set(formal_qubits)) != len(formal_qubits)
            or set(formal_parameters) & set(formal_qubits)
        ):
            self._recover_malformed(
                tokens, "custom_gate_declaration", "Custom-gate formal identifiers must be unique."
            )
            return
        if len(self.custom_gates) >= MAX_CUSTOM_GATES:
            self._fatal(
                "parser_limit_exceeded", "The custom-gate definition limit was exceeded.", tokens
            )
            return
        declaration = self._add_construct(
            family="custom_gate_declaration",
            name=name,
            classification="supported",
            tokens=tokens,
            established=("The custom-gate identity and exact formal arities were established.",),
        )
        gate = _CustomGate(
            name=name,
            parameter_names=tuple(formal_parameters),
            qubit_names=tuple(formal_qubits),
            support="supported",
            construct_id=declaration["construct_id"],
            body_call_names=[],
        )
        self.custom_gates[name] = gate
        body_statements: list[list[Token]] = []
        start = 0
        depth = 0
        for index, token in enumerate(body):
            if token.value in {"(", "["}:
                depth += 1
            elif token.value in {
                ")",
                "]",
            }:
                depth -= 1
            elif token.value in {"{", "}"}:
                gate.support = "recognized_but_unsupported"
            if token.value == ";" and depth == 0:
                body_statements.append(body[start : index + 1])
                start = index + 1
        if body[start:]:
            gate.support = "recognized_but_unsupported"
        for statement in body_statements:
            first = statement[0].value if statement else ""
            if first in _RECOGNIZED_UNSUPPORTED or first in {
                "include",
                "measure",
                "reset",
                "barrier",
            }:
                self._add_construct(
                    family="custom_gate_body_unsupported",
                    name=first,
                    classification="recognized_but_unsupported",
                    tokens=statement,
                    established=("The custom-gate body construct family was identified.",),
                    unavailable=("The body construct semantics were not interpreted.",),
                    effects=("The custom-gate declaration and calls remain opaque.",),
                    message="Only supported gate calls are permitted in a supported custom-gate body.",
                )
                gate.support = "recognized_but_unsupported"
                continue
            classification, call_name = self._gate_call(
                statement,
                formal_qubits=set(formal_qubits),
                formal_parameters=set(formal_parameters),
                current_gate=name,
                emit_operation=False,
            )
            gate.body_call_names.append(call_name)
            if classification != "supported":
                gate.support = "recognized_but_unsupported"
        if gate.support != "supported":
            declaration["classification"] = "partially_supported"
            declaration["unavailable"] = [
                "The complete custom-gate body contribution was not established."
            ]
            declaration["dependent_fact_effects"] = [
                "Calls to this gate cannot establish complete depth or internal interactions."
            ]
            self.unsupported_regions.append(
                {
                    "construct_id": declaration["construct_id"],
                    "classification": "partially_supported",
                    "category": "unsupported_construct",
                    "span": declaration["span"],
                    "limitation": "The custom-gate body contains recursion, a forward reference, or unsupported behavior.",
                }
            )
            self._diagnostic(
                "unsupported_construct",
                "The custom-gate body contains recursion, a forward reference, or unsupported behavior.",
                tokens,
                construct_id=declaration["construct_id"],
            )
        self.custom_gate_rows.append(
            {
                "name": name,
                "parameter_arity": len(formal_parameters),
                "qubit_arity": len(formal_qubits),
                "declaration_construct_id": declaration["construct_id"],
                "support": gate.support,
                "body_call_names": gate.body_call_names,
            }
        )

    def _simple_operation(self, tokens: Sequence[Token], family: str) -> None:
        core = list(tokens[1:-1])
        groups = _split_top_level(core)
        resolved: list[int] = []
        error = None
        for group in groups:
            indexes, reference_error = self._resolve_reference(group)
            if reference_error:
                error = reference_error
                break
            resolved.extend(indexes)
        valid = bool(groups) and error is None
        classification = (
            "supported"
            if valid
            else "recognized_but_unsupported"
            if error == "unsupported_construct"
            else "partially_supported"
        )
        row = self._add_construct(
            family=family,
            name=tokens[0].value,
            classification=classification,
            tokens=tokens,
            established=("The operation family and explicit target forms were identified.",),
            unavailable=()
            if valid
            else ("The complete statically resolvable target set was not established.",),
            effects=() if valid else ("Operation count, depth, and interactions are qualified.",),
            category=error,
            message=None if valid else "At least one target is not statically resolvable.",
        )
        if valid:
            target_groups = (
                [(qubit,) for qubit in resolved] if family == "reset" else [tuple(resolved)]
            )
            for target_group in target_groups:
                self.operations.append(
                    Operation(
                        name=tokens[0].value,
                        qubits=target_group,
                        params=(),
                        line_index=tokens[0].line - 1,
                        op_index=len(self.operations),
                        is_barrier=family == "barrier",
                        is_reset=family == "reset",
                    )
                )
        del row

    def _unsupported(self, tokens: Sequence[Token], family: str) -> None:
        self._add_construct(
            family=family,
            name=tokens[0].value if tokens else family,
            classification="recognized_but_unsupported",
            tokens=tokens,
            established=("The construct family, presence, and source span were identified.",),
            unavailable=("The construct semantics and body effects were not interpreted.",),
            effects=("Every potentially affected structural fact is qualified or withheld.",),
            category="unsupported_construct",
            message="The construct is recognized but outside the bounded static subset.",
        )

    def _parse_statement(self, tokens: Sequence[Token]) -> None:
        if not tokens:
            return
        first = tokens[0].value
        if first == "include":
            valid_shape = len(tokens) == 3 and tokens[1].kind == "string"
            target = tokens[1].value[1:-1] if valid_shape else "invalid_include"
            supported = valid_shape and target == "stdgates.inc"
            row = self._add_construct(
                family="include",
                name=target,
                classification="supported" if supported else "recognized_but_unsupported",
                tokens=tokens,
                established=("The include target and global source span were identified.",),
                unavailable=()
                if supported
                else ("The include contents and imported meanings were not inspected.",),
                effects=()
                if supported
                else ("Operations relying on the include are not established as standard gates.",),
                category="unsupported_include",
                message=None
                if supported
                else "Only the exact package-owned stdgates.inc vocabulary is supported.",
            )
            self.includes.append(
                {
                    "target": target,
                    "support": row["classification"],
                    "span": row["span"],
                    "opened": False,
                }
            )
            if supported:
                self.standard_gates_active = True
            return
        if first in {"qubit", "bit"}:
            self._declaration(tokens, kind=first)
            return
        if first == "measure":
            form = "arrow" if any(token.value == "->" for token in tokens) else "unassigned"
            self._measurement(tokens, tokens[:-1], form=form)
            return
        if len(tokens) > 3 and tokens[1].value == "=" and tokens[2].value == "measure":
            self._measurement(
                tokens,
                tokens[2:-1],
                form="assignment",
                destination_tokens=tokens[:1],
            )
            return
        if first in {"reset", "barrier"}:
            self._simple_operation(tokens, first)
            return
        if first in _RECOGNIZED_UNSUPPORTED:
            self._unsupported(tokens, _RECOGNIZED_UNSUPPORTED[first])
            return
        if first == "@":
            self._unsupported(tokens, "annotation")
            return
        if first == "$":
            self._unsupported(tokens, "physical_qubit")
            return
        if any(token.value in {"=", "++"} for token in tokens):
            self._unsupported(tokens, "general_assignment_or_concatenation")
            return
        self._gate_call(tokens)

    def parse(self) -> OpenQASM3ParseResult:
        if len(self.raw) > MAX_SOURCE_BYTES:
            self._fatal(
                "input_size_exceeded",
                "The selected source exceeds the bounded 100000-byte limit.",
                (),
            )
            return self._result()
        try:
            self.tokens, self.maximum_nesting = _tokenize(self.text)
        except OpenQASM3ParseError as exc:
            category = "parser_limit_exceeded" if "limit" in str(exc) else "malformed_syntax"
            self._fatal(category, "Lexical structure is not safely bounded.", ())
            return self._result()
        if self.maximum_nesting > MAX_NESTING_DEPTH:
            self._fatal(
                "parser_limit_exceeded",
                "The scope or expression nesting limit was exceeded.",
                self.tokens,
            )
            return self._result()
        self._parse_header()
        while self.fatal_error is None and self.position < len(self.tokens):
            token = self.tokens[self.position]
            if token.value == "gate":
                statement = self._consume_block()
                if statement is None:
                    self._fatal(
                        "malformed_syntax", "A custom-gate body boundary is incomplete.", [token]
                    )
                    break
                self._custom_gate(statement)
            elif token.value in _BLOCK_FAMILIES:
                statement = self._consume_block()
                if statement is None:
                    self._fatal(
                        "malformed_syntax", "An unsupported block boundary is incomplete.", [token]
                    )
                    break
                self._unsupported(statement, _RECOGNIZED_UNSUPPORTED[token.value])
            elif token.value == "}":
                self._fatal("malformed_syntax", "A scope-closing brace is misplaced.", [token])
                break
            else:
                statement = self._consume_statement()
                if statement is None:
                    self._fatal(
                        "malformed_syntax",
                        "A statement boundary is not mechanically complete.",
                        self.tokens[self.position :],
                    )
                    break
                self._parse_statement(statement)
        return self._result()

    def _derived(self, file_status: str) -> dict[str, Any]:
        fatal = file_status == "fatal"
        partial = file_status == "partial"
        quantum_width = sum(row["size"] for row in self.quantum_declarations)
        classical_width = sum(row["size"] for row in self.classical_declarations)
        known_operations = len(self.operations)
        known_measurements = sum(1 for operation in self.operations if operation.is_measure)
        uncertain_execution = any(
            row["classification"] != "supported"
            and row["family"]
            not in {"include", "input_declaration", "output_declaration", "pragma", "annotation"}
            for row in self.constructs
        )
        custom_calls = any(operation.is_custom for operation in self.operations)
        count_exactness = (
            "not_established" if fatal else "lower_bound" if uncertain_execution else "exact"
        )
        width_uncertain = any(
            row["classification"] != "supported"
            and row["family"]
            in {
                "qubit_declaration",
                "bit_declaration",
                "compatibility_quantum_declaration",
                "compatibility_classical_declaration",
                "input_declaration",
                "output_declaration",
            }
            for row in self.constructs
        )
        width_exactness = "not_established" if fatal else "partial" if width_uncertain else "exact"
        depth_value: int | None = None
        if not fatal and not partial and not custom_calls:
            frontier = [0] * quantum_width
            depth_value = 0
            for operation in self.operations:
                if not operation.qubits:
                    continue
                level = max((frontier[index] for index in operation.qubits), default=0) + 1
                for index in operation.qubits:
                    frontier[index] = level
                depth_value = max(depth_value, level)
        edges = sorted(
            {
                (min(left, right), max(left, right))
                for operation in self.operations
                if not operation.is_custom
                for offset, left in enumerate(operation.qubits)
                for right in operation.qubits[offset + 1 :]
                if left != right
            }
        )
        counts = dict(sorted(Counter(operation.name for operation in self.operations).items()))
        return {
            "quantum_width": {
                "value": None if fatal else quantum_width,
                "exactness": width_exactness,
            },
            "classical_width": {
                "value": None if fatal else classical_width,
                "exactness": width_exactness,
            },
            "operation_count": {
                "value": None if fatal else known_operations,
                "exactness": count_exactness,
            },
            "measurement_count": {
                "value": None if fatal else known_measurements,
                "exactness": count_exactness,
            },
            "depth": {
                "value": depth_value,
                "exactness": "exact" if depth_value is not None else "not_established",
            },
            "interaction_graph": {
                "value": [list(edge) for edge in edges],
                "exactness": "not_established"
                if fatal
                else "partial"
                if partial or custom_calls
                else "exact",
            },
            "gate_statistics": {
                "value": counts,
                "exactness": "not_established" if fatal else "partial" if partial else "exact",
            },
        }

    def _limit_rows(self) -> dict[str, dict[str, Any]]:
        observed = {
            "source_bytes": len(self.raw),
            "tokens": len(self.tokens),
            "statements": self.statement_count,
            "declarations": len(self.quantum_declarations) + len(self.classical_declarations),
            "operations": len(self.operations),
            "nesting_depth": self.maximum_nesting,
            "expression_depth": min(self.maximum_nesting, MAX_EXPRESSION_DEPTH),
            "custom_gates": len(self.custom_gates),
            "modifier_depth": max(
                (len(row["modifiers"]) for row in self.modifier_chains), default=0
            ),
            "broadcast_expansion": self.maximum_broadcast,
            "recovery_events": len(self.recoveries),
            "diagnostics": len(self.diagnostics),
            "construct_ledger_entries": len(self.constructs),
        }
        return {
            name: {
                "maximum": maximum,
                "observed": observed[name],
                "status": "within_limit" if observed[name] <= maximum else "exceeded",
            }
            for name, maximum in PARSER_LIMITS.items()
        }

    def _ir(self, file_status: str) -> CircuitIR | None:
        if file_status != "supported":
            return None
        return CircuitIR(
            n_qubits=sum(row["size"] for row in self.quantum_declarations),
            n_cbits=sum(row["size"] for row in self.classical_declarations),
            operations=tuple(self.operations),
            qasm_format="qasm3",
            qregs=tuple(
                QRegDecl(name=row["name"], size=row["size"], base=row["base"])
                for row in self.quantum_declarations
            ),
        )

    def _ir_projection(self, ir: CircuitIR | None) -> dict[str, Any] | None:
        if ir is None:
            return None
        return {
            "source_format": ir.source_format,
            "n_qubits": ir.n_qubits,
            "n_cbits": ir.n_cbits,
            "qregs": [{"name": row.name, "size": row.size, "base": row.base} for row in ir.qregs],
            "operations": [
                {
                    "name": row.name,
                    "qubits": list(row.qubits),
                    "params": list(row.params),
                    "is_measure": row.is_measure,
                    "is_barrier": row.is_barrier,
                    "is_reset": row.is_reset,
                    "is_custom": row.is_custom,
                }
                for row in ir.operations
            ],
            "complete": True,
        }

    def _result(self) -> OpenQASM3ParseResult:
        if self.fatal_error is not None:
            file_status = "fatal"
        elif any(row["classification"] != "supported" for row in self.constructs):
            file_status = "partial"
        else:
            file_status = "supported"
        ir = self._ir(file_status)
        limitations = [
            "Only the D-118 bounded static OpenQASM 3.0 subset is interpreted.",
            "Unsupported, unrecognized, and recovered-malformed regions qualify or withhold dependent facts.",
            "Custom-gate bodies are preserved structurally and are not recursively expanded.",
        ]
        if file_status == "partial":
            limitations.append(
                "The selected file is partial evidence and is not a complete CircuitIR projection."
            )
        if file_status == "fatal":
            limitations.append(
                "Fatal structural uncertainty prevents a complete circuit projection."
            )
        sidecar = {
            "schema_id": OPENQASM3_STATIC_EVIDENCE_SCHEMA_ID,
            "schema_version": 1,
            "parser_identity": OPENQASM3_PARSER_ID,
            "standard_gate_vocabulary_identity": OPENQASM3_STANDARD_GATE_VOCABULARY_ID,
            "declared_language_version": self.declared_version,
            "source_sha256": hashlib.sha256(self.raw).hexdigest(),
            "selection_provenance": "explicit_file_argument",
            "artifact_label": self.artifact_label,
            "file_status": file_status,
            "fatal_error": self.fatal_error,
            "quantum_declarations": self.quantum_declarations,
            "classical_declarations": self.classical_declarations,
            "include_ledger": self.includes,
            "construct_ledger": self.constructs,
            "unsupported_region_ledger": self.unsupported_regions,
            "recovery_ledger": self.recoveries,
            "modifier_chains": self.modifier_chains,
            "custom_gates": self.custom_gate_rows,
            "measurements": self.measurements,
            "diagnostics": self.diagnostics,
            "derived_facts": self._derived(file_status),
            "parser_limits": self._limit_rows(),
            "circuit_ir": self._ir_projection(ir),
            "limitations": limitations,
            "non_claims": list(NON_CLAIMS),
            "raw_source_included": False,
            "source_or_circuit_executed": False,
            "repository_scanned": False,
            "network_accessed": False,
            "motif_evidence_emitted": False,
            "intent_inferred": False,
        }
        validate_openqasm3_static_evidence(sidecar)
        return OpenQASM3ParseResult(sidecar=sidecar, circuit_ir=ir)


def parse_openqasm3_bytes(
    raw: bytes, *, artifact_label: str = "selected.qasm3"
) -> OpenQASM3ParseResult:
    """Parse one explicitly supplied byte sequence with strict UTF-8 handling."""

    if not isinstance(raw, bytes):
        raise TypeError("openqasm3_source_bytes_required")
    if "/" in artifact_label or "\\" in artifact_label or not artifact_label:
        raise OpenQASM3ParseError("unsafe_path")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        parser = _Parser(raw, "", artifact_label)
        parser._fatal("invalid_encoding", "The selected source is not valid UTF-8.", ())
        return parser._result()
    return _Parser(raw, text, artifact_label).parse()


def parse_openqasm3_text(
    text: str, *, artifact_label: str = "selected.qasm3"
) -> OpenQASM3ParseResult:
    """Parse one in-memory source string using its deterministic UTF-8 bytes."""

    if not isinstance(text, str):
        raise TypeError("openqasm3_source_text_required")
    return parse_openqasm3_bytes(text.encode("utf-8"), artifact_label=artifact_label)
