"""Public wire vocabulary and strict codec, not recommendation policy.

No free-form customer text is accepted. The vocabulary states available public
choices; the private service alone decides which, if any, to recommend.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

REQUEST = "qcoder.protected.blueprint_decision_request.v1"
RESPONSE = "qcoder.protected.blueprint_decision_response.v1"
MAX_BYTES, MAX_DEPTH, MAX_CONTAINER = 16384, 8, 32
ROUTE = "/v1/blueprint/decision-recommendation"
AUTHORITY = "proposal_only_no_write_no_run"
PRIVACY = {"structured_intent_only": True, "process_and_discard": True}
SCALARS = {
    "objective": {"entanglement", "search", "optimization", "unspecified"},
    "problem_size": {"small_demonstration", "customer_defined", "unspecified"},
    "framework": {"qiskit", "cirq", "unspecified"},
    "measurement": {"computational_basis", "expectation", "unspecified"},
}
SETS = {
    "constraints": {"no_generation", "no_execution", "no_backend_selection", "portable"},
    "non_goals": {"hardware_execution", "performance_claim", "source_generation"},
    "unresolved": set(SCALARS),
}
CHOICES = {
    "framework": {"qiskit", "cirq"},
    "formulation": {"state_preparation", "amplitude_amplification", "variational"},
    "measurement": {"computational_basis", "expectation"},
}
BASES = {"explicit_intent", "compatible_structure", "insufficient_intent"}
LIMITATIONS = {"no_performance_claim", "no_execution_selection", "customer_model_required"}
OUTCOMES = {"completed", "unavailable", "unauthorized", "expired", "quota_limited", "unsupported"}
REQUEST_KEYS = {
    "schema",
    "version",
    "nonce",
    "revision",
    "expires_at",
    "intent",
    "privacy",
    "request_digest",
}
RESPONSE_KEYS = {
    "schema",
    "version",
    "nonce",
    "revision",
    "expires_at",
    "request_digest",
    "release",
    "outcome",
    "proposal",
    "response_digest",
}
PROPOSAL_KEYS = {"authority", "groups", "limitations", "unresolved", "semantic_digest"}
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
NONCE = re.compile(r"[A-Za-z0-9_-]{22,64}\Z")
RELEASE = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}\Z")


class ContractError(ValueError):
    """Only static, non-content categories cross this boundary."""


def fail(category):
    raise ContractError(category) from None


def bounded(value, depth=0):
    if depth > MAX_DEPTH:
        fail("depth")
    if type(value) is dict:
        if len(value) > MAX_CONTAINER:
            fail("container")
        for k, v in value.items():
            if type(k) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", k):
                fail("key")
            bounded(v, depth + 1)
    elif type(value) is list:
        if len(value) > MAX_CONTAINER:
            fail("container")
        for v in value:
            bounded(v, depth + 1)
    elif type(value) is str:
        if len(value.encode("utf-8")) > 512:
            fail("scalar")
    elif value is not None and type(value) not in (bool, int):
        fail("type")


def encode(value):
    try:
        bounded(value)
        raw = json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("ascii")
    except ContractError:
        raise
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        fail("encoding")
    if len(raw) > MAX_BYTES:
        fail("size")
    return raw


def decode(raw):
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        fail("size")

    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                fail("duplicate_key")
            result[k] = v
        return result

    try:
        obj = json.loads(
            raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=lambda _: fail("nonfinite")
        )
    except ContractError:
        raise
    except (ValueError, UnicodeError, json.JSONDecodeError, RecursionError):
        fail("json")
    if type(obj) is not dict:
        fail("shape")
    if encode(obj) != raw:
        fail("canonical_encoding")
    return obj


def digest(obj, omit):
    return hashlib.sha256(encode({k: v for k, v in obj.items() if k != omit})).hexdigest()


def exact(obj, keys):
    if type(obj) is not dict or set(obj) != keys:
        fail("keys")


def enum(value, allowed):
    if type(value) is not str or value not in allowed:
        fail("vocabulary")


def enum_set(value, allowed, maximum=8):
    if type(value) is not list or len(value) > maximum:
        fail("list")
    for item in value:
        enum(item, allowed)
    if sorted(set(value)) != value:
        fail("ordered_set")


def timestamp(value):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        fail("expiry_shape")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail("expiry_shape")


def now_utc():
    return datetime.now(timezone.utc)


def validate_intent(intent):
    exact(intent, set(SCALARS) | set(SETS))
    for field, values in SCALARS.items():
        enum(intent[field], values)
    for field, values in SETS.items():
        enum_set(intent[field], values)
    return decode(encode(intent))


def validate_request(obj, now):
    exact(obj, REQUEST_KEYS)
    if obj["schema"] != REQUEST or type(obj["version"]) is not int or obj["version"] != 1:
        fail("version")
    if type(obj["nonce"]) is not str or not NONCE.fullmatch(obj["nonce"]):
        fail("nonce")
    if type(obj["revision"]) is not int or not 1 <= obj["revision"] <= 5:
        fail("revision")
    expiry = timestamp(obj["expires_at"])
    if not now < expiry <= now + timedelta(minutes=5):
        fail("expiry")
    if encode(obj["privacy"]) != encode(PRIVACY):
        fail("privacy")
    validate_intent(obj["intent"])
    if obj["request_digest"] != digest(obj, "request_digest"):
        fail("request_digest")
    return decode(encode(obj))


def make_request(intent, nonce, revision, now):
    obj = {
        "schema": REQUEST,
        "version": 1,
        "nonce": nonce,
        "revision": revision,
        "expires_at": (now + timedelta(minutes=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "intent": validate_intent(intent),
        "privacy": dict(PRIVACY),
        "request_digest": "",
    }
    obj["request_digest"] = digest(obj, "request_digest")
    return validate_request(obj, now)


def validate_proposal(obj):
    exact(obj, PROPOSAL_KEYS)
    if obj["authority"] != AUTHORITY:
        fail("authority")
    groups = obj["groups"]
    if type(groups) is not list or not 1 <= len(groups) <= 3:
        fail("groups")
    ids = []
    for group in groups:
        exact(group, {"id", "recommended", "alternatives", "basis", "unresolved"})
        enum(group["id"], CHOICES)
        ids.append(group["id"])
        choice = group["recommended"]
        if choice is not None:
            enum(choice, CHOICES[group["id"]])
        enum_set(group["alternatives"], CHOICES[group["id"]], maximum=2)
        enum(group["basis"], BASES)
        if type(group["unresolved"]) is not bool or group["unresolved"] != (choice is None):
            fail("unresolved")
        if choice in group["alternatives"] or (choice is None) != (
            group["basis"] == "insufficient_intent"
        ):
            fail("consistency")
    if len(set(ids)) != len(ids):
        fail("duplicate_group")
    enum_set(obj["limitations"], LIMITATIONS)
    if not {"no_execution_selection", "no_performance_claim"} <= set(obj["limitations"]):
        fail("limitations")
    enum_set(obj["unresolved"], SCALARS)
    if obj["semantic_digest"] != digest(obj, "semantic_digest"):
        fail("semantic_digest")
    return decode(encode(obj))


def validate_response(obj, request, release, now):
    exact(obj, RESPONSE_KEYS)
    if obj["schema"] != RESPONSE or type(obj["version"]) is not int or obj["version"] != 1:
        fail("version")
    if type(release) is not str or not RELEASE.fullmatch(release) or obj["release"] != release:
        fail("release")
    validate_request(request, now)
    for field in ("nonce", "revision", "request_digest", "expires_at"):
        if type(obj[field]) is not type(request[field]) or obj[field] != request[field]:
            fail("response_binding")
    enum(obj["outcome"], OUTCOMES)
    if obj["outcome"] == "completed":
        validate_proposal(obj["proposal"])
    elif obj["proposal"] is not None:
        fail("noncompleted_proposal")
    if obj["response_digest"] != digest(obj, "response_digest"):
        fail("response_digest")
    return decode(encode(obj))
