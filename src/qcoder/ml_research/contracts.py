"""Strict JSON, durable records, exact identities and independent metric protocol."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import fcntl
import math
import os
import stat
import time

from qcoder.focused_loop.canonical import canonical_bytes, canonical_digest, strict_typed_object


class Refusal(ValueError):
    """A fail-closed research boundary."""


def require(condition, reason):
    if not condition:
        raise Refusal(reason)


def seal(body):
    require(isinstance(body, dict) and "digest" not in body, "seal_body")
    return dict(body, digest=canonical_digest(body))


def checked(value, schema=None, fields=None):
    require(isinstance(value, dict), "record_type")
    require(value.get("digest") == canonical_digest({k: v for k, v in value.items() if k != "digest"}), "record_digest")
    if schema:
        require(value.get("schema") == schema, "record_schema")
    if fields is not None:
        require(set(value) == set(fields) | {"schema", "digest"}, "record_fields")
    return value


def read(path):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 262144, "unsafe_record")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(262145)
        value = strict_typed_object(raw.decode(), category="invalid_json")
        require(raw == canonical_bytes(value), "noncanonical_record")
        return checked(value)
    finally:
        os.close(fd)


def write_new(path, value):
    """Exclusive creation plus file and directory fsync; never overwrite evidence."""
    path = Path(path)
    raw = canonical_bytes(checked(value))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


@contextmanager
def locked(root):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), "unsafe_workspace")
    fd = os.open(root / "research.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        require(os.fstat(fd).st_nlink == 1, "unsafe_lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def file_digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def metric(labels, predictions):
    require(len(labels) == len(predictions) == 40, "heldout_count")
    require(all(type(v) is int and v in (0, 1) for v in labels + predictions), "binary_values")
    correct = sum(a == b for a, b in zip(labels, predictions))
    return {"correct": correct, "count": 40, "accuracy": correct / 40}


def reference_metric(labels, predictions):
    """Independent confusion-matrix oracle, without using metric's equality sum."""
    matrix = [[0, 0], [0, 0]]
    for truth, prediction in zip(labels, predictions, strict=True):
        matrix[truth][prediction] += 1
    return (matrix[0][0] + matrix[1][1]) / sum(map(sum, matrix))


def conclusion(candidate, baseline, compatible=True):
    if not compatible:
        return {"evidence_conclusion": "comparison_not_established", "evaluation_state": "comparison_incomplete", "next_action": "repair_comparison_evidence"}
    supported = candidate["correct"] >= 26 and baseline["correct"] - candidate["correct"] <= 4
    return {"evidence_conclusion": "bounded_refinement_candidate" if supported else "bounded_refinement_not_supported", "evaluation_state": "evaluation_complete", "next_action": "consider_one_predeclared_quantum_refinement" if supported else "stop_or_reframe_quantum_candidate"}


def numeric(value, shape):
    if not shape:
        require(type(value) in (int, float) and math.isfinite(value), "finite_numeric_required")
    else:
        require(isinstance(value, list) and len(value) == shape[0], "numeric_shape")
        for item in value:
            numeric(item, shape[1:])
    return value


def now():
    return time.time()
