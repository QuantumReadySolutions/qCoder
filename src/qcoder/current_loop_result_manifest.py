"""Strict, bounded result-manifest validation for Current Loop evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import math
from typing import Any

from qcoder.engines.review.counts_v0 import normalize_counts_v0


STRICT_RESULT_MANIFEST_SCHEMA_ID = "qcoder.current_loop.strict_result_manifest.v3"
STRICT_RESULT_MANIFEST_SCHEMA_VERSION = 3
RESULT_LINEAGE_STATUSES = ("exact", "current_step_contract", "unknown")
SOURCE_LINEAGE_STATUSES = ("exact", "unknown", "not_supplied")
MAX_OUTCOMES = 1_024
MAX_LIST_ITEMS = 32
MAX_TEXT_BYTES = 1_024
MAX_SETTINGS_BYTES = 8_192
MAX_ORDERING_ITEMS = 4_096
_FORBIDDEN_SETTING_KEYS = frozenset(
    {"authorization", "credential", "password", "raw_result", "secret", "token"}
)


class StrictResultManifestError(ValueError):
    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def _canonical_digest(value: object) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _is_digest(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _bounded_text(value: object, *, category: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or len(value.encode("utf-8")) > MAX_TEXT_BYTES
    ):
        raise StrictResultManifestError(category)
    return value


def _bounded_text_list(value: object, *, category: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise StrictResultManifestError(category)
    if len(value) > MAX_LIST_ITEMS:
        raise StrictResultManifestError(category)
    result = [_bounded_text(item, category=category) for item in value]
    if len(result) != len(set(result)):
        raise StrictResultManifestError(category)
    return result


def _safe_setting(value: object, *, depth: int = 0) -> object:
    if depth > 4:
        raise StrictResultManifestError("result_manifest_configuration_depth_invalid")
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise StrictResultManifestError("result_manifest_configuration_number_invalid")
        return value
    if isinstance(value, str):
        return _bounded_text(value, category="result_manifest_configuration_text_invalid")
    if isinstance(value, Mapping):
        if len(value) > 32:
            raise StrictResultManifestError("result_manifest_configuration_object_too_large")
        result: dict[str, object] = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            name = str(key)
            if (
                not name
                or len(name.encode("utf-8")) > 80
                or name.casefold() in _FORBIDDEN_SETTING_KEYS
            ):
                raise StrictResultManifestError("result_manifest_configuration_key_invalid")
            result[name] = _safe_setting(item, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if len(value) > 32:
            raise StrictResultManifestError("result_manifest_configuration_array_too_large")
        return [_safe_setting(item, depth=depth + 1) for item in value]
    raise StrictResultManifestError("result_manifest_configuration_type_invalid")


def _revision(
    *,
    revision_id: object,
    digest: object,
    artifact_revisions: Mapping[str, Any],
    permitted_roles: set[str],
    invalid_category: str,
    false_category: str,
) -> tuple[str, Mapping[str, Any]]:
    if not isinstance(revision_id, str) or not _is_digest(digest):
        raise StrictResultManifestError(invalid_category)
    revision = artifact_revisions.get(revision_id)
    if (
        not isinstance(revision, Mapping)
        or revision.get("logical_role") not in permitted_roles
        or revision.get("content_digest") != digest
    ):
        raise StrictResultManifestError(false_category)
    return revision_id, revision


def _normalize_circuit_lineage(
    value: object,
    *,
    artifact_revisions: Mapping[str, Any],
    expected_circuit_lineage: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], Mapping[str, Any] | None]:
    if not isinstance(value, Mapping) or value.get("status") not in RESULT_LINEAGE_STATUSES:
        raise StrictResultManifestError("result_manifest_circuit_lineage_invalid")
    status = str(value["status"])
    unexpected = set(value).difference({"status", "artifact_revision_id", "content_digest"})
    if unexpected:
        raise StrictResultManifestError("result_manifest_circuit_lineage_invalid")
    if status == "unknown":
        if value.get("artifact_revision_id") is not None or value.get("content_digest") is not None:
            raise StrictResultManifestError("result_manifest_unknown_lineage_claim_invalid")
        return (
            {
                "status": "unknown",
                "artifact_revision_id": None,
                "content_digest": None,
                "limitation": "The exact producing circuit is not supplied and is not inferred.",
            },
            None,
        )
    if status == "current_step_contract":
        if value.get("artifact_revision_id") is not None or value.get("content_digest") is not None:
            raise StrictResultManifestError("result_manifest_contract_lineage_claim_invalid")
        if not isinstance(expected_circuit_lineage, Mapping):
            raise StrictResultManifestError("result_manifest_expected_circuit_unavailable")
        revision_id = expected_circuit_lineage.get("artifact_revision_id")
        digest = expected_circuit_lineage.get("content_digest")
    else:
        revision_id = value.get("artifact_revision_id")
        digest = value.get("content_digest")
    exact_id, revision = _revision(
        revision_id=revision_id,
        digest=digest,
        artifact_revisions=artifact_revisions,
        permitted_roles={"circuit_qasm", "framework_circuit"},
        invalid_category="result_manifest_exact_lineage_binding_invalid",
        false_category="result_manifest_false_circuit_lineage",
    )
    if isinstance(expected_circuit_lineage, Mapping) and (
        expected_circuit_lineage.get("artifact_revision_id") != exact_id
        or expected_circuit_lineage.get("content_digest") != digest
    ):
        raise StrictResultManifestError("result_manifest_circuit_not_current_step_input")
    return (
        {
            "status": "exact",
            "artifact_revision_id": exact_id,
            "content_digest": digest,
            "binding_source": (
                "current_step_contract"
                if status == "current_step_contract"
                else "explicit_manifest"
            ),
            "limitation": None,
        },
        revision,
    )


def _normalize_source_lineage(
    value: object,
    *,
    artifact_revisions: Mapping[str, Any],
    circuit_revision: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if value is None:
        value = {"status": "not_supplied"}
    if not isinstance(value, Mapping) or value.get("status") not in SOURCE_LINEAGE_STATUSES:
        raise StrictResultManifestError("result_manifest_source_lineage_invalid")
    status = str(value["status"])
    if set(value).difference({"status", "artifact_revision_id", "content_digest"}):
        raise StrictResultManifestError("result_manifest_source_lineage_invalid")
    if status != "exact":
        if value.get("artifact_revision_id") is not None or value.get("content_digest") is not None:
            raise StrictResultManifestError("result_manifest_source_lineage_invalid")
        return {
            "status": status,
            "artifact_revision_id": None,
            "content_digest": None,
            "limitation": (
                "Source lineage is explicitly unknown."
                if status == "unknown"
                else "Source lineage was not supplied by the result producer."
            ),
        }
    source_id, _source_revision = _revision(
        revision_id=value.get("artifact_revision_id"),
        digest=value.get("content_digest"),
        artifact_revisions=artifact_revisions,
        permitted_roles={"source"},
        invalid_category="result_manifest_source_lineage_binding_invalid",
        false_category="result_manifest_false_source_lineage",
    )
    circuit_source = (
        circuit_revision.get("causal_lineage", {}).get("source")
        if isinstance(circuit_revision, Mapping)
        else None
    )
    if (
        not isinstance(circuit_source, Mapping)
        or circuit_source.get("status") != "exact"
        or circuit_source.get("artifact_revision_id") != source_id
        or circuit_source.get("content_digest") != value.get("content_digest")
    ):
        raise StrictResultManifestError("result_manifest_false_source_to_circuit_lineage")
    return {
        "status": "exact",
        "artifact_revision_id": source_id,
        "content_digest": value.get("content_digest"),
        "limitation": None,
    }


def _normalize_configuration(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("status") not in {"exact", "unknown"}:
        raise StrictResultManifestError("result_manifest_execution_configuration_invalid")
    if set(value).difference({"status", "reference", "digest", "settings"}):
        raise StrictResultManifestError("result_manifest_execution_configuration_invalid")
    if value["status"] == "unknown":
        if any(value.get(key) not in (None, {}) for key in ("reference", "digest", "settings")):
            raise StrictResultManifestError("result_manifest_execution_configuration_invalid")
        return {"status": "unknown", "reference": None, "digest": None, "settings": {}}
    reference = _bounded_text(
        value.get("reference"), category="result_manifest_execution_configuration_invalid"
    )
    settings = _safe_setting(value.get("settings"))
    if not isinstance(settings, Mapping) or len(_canonical_bytes(settings)) > MAX_SETTINGS_BYTES:
        raise StrictResultManifestError("result_manifest_execution_configuration_invalid")
    digest = _canonical_digest(settings)
    if value.get("digest") is not None and value.get("digest") != digest:
        raise StrictResultManifestError("result_manifest_execution_configuration_digest_invalid")
    return {"status": "exact", "reference": reference, "digest": digest, "settings": settings}


def _normalize_provenance(value: object, *, category: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value).difference({"kind", "method", "identity"}):
        raise StrictResultManifestError(category)
    return {
        "kind": _bounded_text(value.get("kind"), category=category),
        "method": _bounded_text(value.get("method"), category=category),
        "identity": (
            _bounded_text(value.get("identity"), category=category)
            if value.get("identity") is not None
            else None
        ),
    }


def _normalize_execution_method(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value).difference(
        {"kind", "interface", "backend_or_sampler"}
    ):
        raise StrictResultManifestError("result_manifest_execution_method_invalid")
    kind = value.get("kind")
    if kind not in {
        "sampled_shots",
        "analytic_probabilities",
        "deterministic_construction",
        "unknown",
    }:
        raise StrictResultManifestError("result_manifest_execution_method_invalid")
    interface = _bounded_text(
        value.get("interface"), category="result_manifest_execution_method_invalid"
    )
    backend = value.get("backend_or_sampler")
    if backend is not None:
        backend = _bounded_text(backend, category="result_manifest_execution_method_invalid")
    if kind == "sampled_shots" and backend is None:
        raise StrictResultManifestError("result_manifest_sampled_backend_missing")
    return {
        "kind": kind,
        "interface": interface,
        "backend_or_sampler": backend,
    }


def _normalize_execution_observation(value: object) -> dict[str, Any]:
    fields = {
        "status",
        "external_execution_attempt_count",
        "dependency_installation_performed",
        "environment_mutated",
        "qcoder_independently_verified_execution",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise StrictResultManifestError("result_manifest_execution_observation_invalid")
    if value.get("status") != "client_reported_completed":
        raise StrictResultManifestError("result_manifest_execution_observation_invalid")
    attempts = value.get("external_execution_attempt_count")
    if attempts != 1 or isinstance(attempts, bool):
        raise StrictResultManifestError("result_manifest_external_execution_attempt_count_invalid")
    if value.get("dependency_installation_performed") is not False:
        raise StrictResultManifestError(
            "result_manifest_dependency_installation_outside_current_step"
        )
    if value.get("environment_mutated") is not False:
        raise StrictResultManifestError("result_manifest_environment_mutation_outside_current_step")
    if value.get("qcoder_independently_verified_execution") is not False:
        raise StrictResultManifestError(
            "result_manifest_qcoder_execution_verification_claim_invalid"
        )
    return {
        "status": "client_reported_completed",
        "external_execution_attempt_count": 1,
        "dependency_installation_performed": False,
        "environment_mutated": False,
        "qcoder_independently_verified_execution": False,
    }


def _ordering_items(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise StrictResultManifestError("result_manifest_bit_ordering_invalid")
    if len(value) > MAX_ORDERING_ITEMS:
        raise StrictResultManifestError("result_manifest_bit_ordering_invalid")
    result = [
        _bounded_text(item, category="result_manifest_bit_ordering_invalid") for item in value
    ]
    if len(result) != len(set(result)):
        raise StrictResultManifestError("result_manifest_bit_ordering_contradictory")
    return result


def _normalize_ordering(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("status") not in {"known", "unknown"}:
        raise StrictResultManifestError("result_manifest_bit_ordering_invalid")
    if set(value).difference({"status", "convention", "endianness", "bit_order", "register_order"}):
        raise StrictResultManifestError("result_manifest_bit_ordering_invalid")
    if value["status"] == "unknown":
        if any(
            value.get(key) not in (None, [])
            for key in ("convention", "endianness", "bit_order", "register_order")
        ):
            raise StrictResultManifestError("result_manifest_bit_ordering_contradictory")
        return {
            "status": "unknown",
            "convention": None,
            "endianness": None,
            "bit_order": [],
            "register_order": [],
        }
    convention = _bounded_text(
        value.get("convention"), category="result_manifest_bit_ordering_invalid"
    )
    endianness = value.get("endianness")
    if endianness not in {"little", "big", "explicit"}:
        raise StrictResultManifestError("result_manifest_bit_ordering_invalid")
    bit_order = _ordering_items(value.get("bit_order", []))
    register_order = _ordering_items(value.get("register_order", []))
    if convention == "qiskit_little_endian" and endianness != "little":
        raise StrictResultManifestError("result_manifest_bit_ordering_contradictory")
    if endianness == "explicit" and not bit_order:
        raise StrictResultManifestError("result_manifest_bit_ordering_contradictory")
    return {
        "status": "known",
        "convention": convention,
        "endianness": endianness,
        "bit_order": bit_order,
        "register_order": register_order,
    }


def normalize_strict_result_manifest(
    value: Mapping[str, Any],
    *,
    artifact_revisions: Mapping[str, Any],
    expected_circuit_lineage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one explicit result manifestation without execution or discovery."""

    if (
        not isinstance(value, Mapping)
        or value.get("schema_id") != STRICT_RESULT_MANIFEST_SCHEMA_ID
        or value.get("schema_version") != STRICT_RESULT_MANIFEST_SCHEMA_VERSION
        or value.get("manifestation") != "exact_result"
    ):
        raise StrictResultManifestError("result_manifest_schema_invalid")
    if len(_canonical_bytes(value)) > 256 * 1024:
        raise StrictResultManifestError("result_manifest_too_large")
    allowed = {
        "schema_id",
        "schema_version",
        "manifestation",
        "counts",
        "requested_shots",
        "observed_shots",
        "circuit_lineage",
        "source_lineage",
        "execution_configuration",
        "execution_method",
        "execution_observation",
        "execution_attempt_id",
        "producer_provenance",
        "capture_provenance",
        "bit_register_ordering",
        "warnings",
        "explicit_missingness",
        "limitations",
        "non_claims",
        "raw_terminal_or_chat_evidence_used",
        "workspace_or_filename_lineage_inferred",
    }
    if set(value).difference(allowed):
        raise StrictResultManifestError("result_manifest_field_unsupported")
    if value.get("raw_terminal_or_chat_evidence_used") not in (None, False):
        raise StrictResultManifestError("result_manifest_reconstructive_evidence_prohibited")
    if value.get("workspace_or_filename_lineage_inferred") not in (None, False):
        raise StrictResultManifestError("result_manifest_inferred_lineage_prohibited")
    counts_value = value.get("counts")
    if (
        not isinstance(counts_value, Mapping)
        or not counts_value
        or len(counts_value) > MAX_OUTCOMES
        or any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0
            for count in counts_value.values()
        )
    ):
        raise StrictResultManifestError("result_manifest_counts_invalid")
    requested = value.get("requested_shots")
    observed = value.get("observed_shots")
    if requested is not None and (
        not isinstance(requested, int) or isinstance(requested, bool) or requested < 1
    ):
        raise StrictResultManifestError("result_manifest_requested_shots_invalid")
    if not isinstance(observed, int) or isinstance(observed, bool) or observed < 1:
        raise StrictResultManifestError("result_manifest_observed_shots_invalid")
    try:
        normalized_counts = normalize_counts_v0(
            {"schema": "qcoder.counts.v0", "counts": dict(counts_value), "shots_total": observed}
        )["counts"]
    except (TypeError, ValueError) as exc:
        raise StrictResultManifestError("result_manifest_counts_invalid") from exc
    if sum(normalized_counts.values()) != observed:
        raise StrictResultManifestError("result_manifest_observed_shots_contradiction")
    if requested is not None and requested != observed:
        raise StrictResultManifestError("result_manifest_requested_shots_contradiction")
    circuit_lineage, circuit_revision = _normalize_circuit_lineage(
        value.get("circuit_lineage"),
        artifact_revisions=artifact_revisions,
        expected_circuit_lineage=expected_circuit_lineage,
    )
    source_lineage = _normalize_source_lineage(
        value.get("source_lineage"),
        artifact_revisions=artifact_revisions,
        circuit_revision=circuit_revision,
    )
    execution_configuration = _normalize_configuration(value.get("execution_configuration"))
    execution_method = _normalize_execution_method(value.get("execution_method"))
    execution_observation = _normalize_execution_observation(value.get("execution_observation"))
    producer_provenance = _normalize_provenance(
        value.get("producer_provenance"), category="result_manifest_producer_invalid"
    )
    capture_provenance = _normalize_provenance(
        value.get("capture_provenance"), category="result_manifest_capture_invalid"
    )
    exact_circuit_claimed = circuit_lineage.get("status") == "exact"
    if execution_method["kind"] in {
        "analytic_probabilities",
        "deterministic_construction",
    }:
        raise StrictResultManifestError(
            "result_manifest_non_sampled_method_presented_as_sampled_shots"
        )
    contradictory_provenance_kinds = {
        "analytic_derivation",
        "deterministic_construction",
        "hard_coded_counts",
    }
    if execution_method["kind"] == "sampled_shots" and (
        producer_provenance["kind"] in contradictory_provenance_kinds
        or capture_provenance["kind"] in contradictory_provenance_kinds
    ):
        raise StrictResultManifestError("result_manifest_execution_provenance_contradiction")
    if exact_circuit_claimed and execution_method["kind"] != "sampled_shots":
        raise StrictResultManifestError("result_manifest_sampled_execution_method_required")
    if exact_circuit_claimed and execution_configuration["status"] != "exact":
        raise StrictResultManifestError("result_manifest_exact_execution_configuration_required")
    warnings = _bounded_text_list(
        value.get("warnings", []), category="result_manifest_warning_invalid"
    )
    limitations = _bounded_text_list(
        value.get("limitations", []), category="result_manifest_limitation_invalid"
    )
    for lineage in (circuit_lineage, source_lineage):
        limitation = lineage.get("limitation")
        if limitation is not None and limitation not in limitations:
            if len(limitations) >= MAX_LIST_ITEMS:
                raise StrictResultManifestError("result_manifest_limitation_invalid")
            limitations.append(str(limitation))
    normalized = {
        "schema_id": STRICT_RESULT_MANIFEST_SCHEMA_ID,
        "schema_version": STRICT_RESULT_MANIFEST_SCHEMA_VERSION,
        "manifestation": "exact_result",
        "counts": dict(sorted(normalized_counts.items())),
        "requested_shots": requested,
        "observed_shots": observed,
        "circuit_lineage": circuit_lineage,
        "source_lineage": source_lineage,
        "execution_configuration": execution_configuration,
        "execution_method": execution_method,
        "execution_observation": execution_observation,
        "execution_attempt_id": _bounded_text(
            value.get("execution_attempt_id"),
            category="result_manifest_execution_attempt_invalid",
        ),
        "producer_provenance": producer_provenance,
        "capture_provenance": capture_provenance,
        "bit_register_ordering": _normalize_ordering(value.get("bit_register_ordering")),
        "warnings": warnings,
        "explicit_missingness": _bounded_text_list(
            value.get("explicit_missingness", []),
            category="result_manifest_explicit_missingness_invalid",
        ),
        "limitations": limitations,
        "non_claims": _bounded_text_list(
            value.get("non_claims", []), category="result_manifest_non_claim_invalid"
        ),
        "raw_terminal_or_chat_evidence_used": False,
        "workspace_or_filename_lineage_inferred": False,
    }
    if exact_circuit_claimed and normalized["bit_register_ordering"]["status"] != "known":
        raise StrictResultManifestError("result_manifest_known_bit_ordering_required")
    normalized["outcome_digest"] = _canonical_digest(
        {
            "counts": normalized["counts"],
            "requested_shots": requested,
            "observed_shots": observed,
        }
    )
    normalized["manifest_digest"] = _canonical_digest(normalized)
    return normalized


def result_manifest_contract_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": STRICT_RESULT_MANIFEST_SCHEMA_ID,
        "schema_version": STRICT_RESULT_MANIFEST_SCHEMA_VERSION,
        "strict_top_level_envelope_required": True,
        "arbitrary_top_level_json_rejected": True,
        "exact_contract_bound_or_unknown_circuit_lineage": True,
        "optional_exact_unknown_or_unsupplied_source_lineage": True,
        "attempt_identity_required": True,
        "producer_and_capture_provenance_distinct": True,
        "sampled_execution_method_explicit": True,
        "client_reported_execution_observation_required": True,
        "dependency_installation_or_environment_mutation_permitted": False,
        "exact_current_circuit_requires_exact_configuration_and_known_ordering": True,
        "false_or_contradictory_lineage_rejected": True,
        "contradictory_shots_or_ordering_rejected": True,
        "chat_or_terminal_history_permitted": False,
        "filename_or_adjacency_inference_permitted": False,
        "native_execution_owned_by_qcoder": False,
        "maximum_manifest_bytes": 256 * 1024,
        "minimal_happy_path": {
            "schema_id": STRICT_RESULT_MANIFEST_SCHEMA_ID,
            "schema_version": STRICT_RESULT_MANIFEST_SCHEMA_VERSION,
            "manifestation": "exact_result",
            "counts": {"<bitstring>": "<nonnegative integer>"},
            "requested_shots": "<positive integer or null>",
            "observed_shots": "<positive integer equal to counts sum>",
            "circuit_lineage": {"status": "current_step_contract"},
            "source_lineage": {"status": "not_supplied"},
            "execution_configuration": {
                "status": "exact",
                "reference": "<bounded client configuration reference>",
                "settings": {
                    "backend": "<client-reported backend or sampler>",
                    "shots": "<same positive integer as requested_shots>",
                },
            },
            "execution_method": {
                "kind": "sampled_shots",
                "interface": "<client-reported method>",
                "backend_or_sampler": "<client-reported backend or sampler>",
            },
            "execution_observation": {
                "status": "client_reported_completed",
                "external_execution_attempt_count": 1,
                "dependency_installation_performed": False,
                "environment_mutated": False,
                "qcoder_independently_verified_execution": False,
            },
            "execution_attempt_id": "<client execution attempt identity>",
            "producer_provenance": {"kind": "<producer>", "method": "<execution method>"},
            "capture_provenance": {"kind": "<capture source>", "method": "<capture method>"},
            "bit_register_ordering": {
                "status": "known",
                "convention": "<bounded ordering convention>",
                "endianness": "little|big|explicit",
                "bit_order": ["<exact bit labels>"],
                "register_order": ["<exact register labels>"],
            },
            "warnings": [],
            "explicit_missingness": [],
            "limitations": [],
            "non_claims": ["qCoder did not execute customer code."],
        },
    }
    payload["contract_digest"] = _canonical_digest(payload)
    return payload


__all__ = [
    "STRICT_RESULT_MANIFEST_SCHEMA_ID",
    "STRICT_RESULT_MANIFEST_SCHEMA_VERSION",
    "StrictResultManifestError",
    "normalize_strict_result_manifest",
    "result_manifest_contract_snapshot",
]
