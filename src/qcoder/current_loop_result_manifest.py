"""Strict, local result-manifest validation for bounded Current Loop evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from hashlib import sha256
import json
from typing import Any

from qcoder.engines.review.counts_v0 import normalize_counts_v0


STRICT_RESULT_MANIFEST_SCHEMA_ID = "qcoder.current_loop.strict_result_manifest.v1"
STRICT_RESULT_MANIFEST_SCHEMA_VERSION = 1
RESULT_LINEAGE_STATUSES = ("exact", "unknown")
MAX_WARNINGS = 32
MAX_TEXT_BYTES = 1_024


class StrictResultManifestError(ValueError):
    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _canonical_digest(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _bounded_text(value: object, *, category: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        raise StrictResultManifestError(category)
    return value


def _bounded_text_list(value: object, *, category: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise StrictResultManifestError(category)
    if len(value) > MAX_WARNINGS:
        raise StrictResultManifestError(category)
    return [_bounded_text(item, category=category) for item in value]


def _lineage(
    value: object,
    *,
    artifact_revisions: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("status") not in RESULT_LINEAGE_STATUSES:
        raise StrictResultManifestError("result_manifest_circuit_lineage_invalid")
    status = str(value["status"])
    if status == "unknown":
        if value.get("artifact_revision_id") is not None or value.get("content_digest") is not None:
            raise StrictResultManifestError("result_manifest_unknown_lineage_claim_invalid")
        return {
            "status": "unknown",
            "artifact_revision_id": None,
            "content_digest": None,
            "limitation": "The exact producing circuit is not supplied and is not inferred.",
        }
    revision_id = value.get("artifact_revision_id")
    digest = value.get("content_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise StrictResultManifestError("result_manifest_exact_lineage_binding_invalid")
    if revision_id is None:
        matches = [
            (candidate_id, candidate)
            for candidate_id, candidate in artifact_revisions.items()
            if isinstance(candidate, Mapping)
            and candidate.get("logical_role") in {"circuit_qasm", "framework_circuit"}
            and candidate.get("content_digest") == digest
        ]
        if len(matches) != 1:
            raise StrictResultManifestError("result_manifest_exact_lineage_binding_invalid")
        revision_id, revision = matches[0]
    else:
        revision = artifact_revisions.get(revision_id)
    if (
        not isinstance(revision, Mapping)
        or revision.get("logical_role") not in {"circuit_qasm", "framework_circuit"}
        or revision.get("content_digest") != digest
    ):
        raise StrictResultManifestError("result_manifest_false_circuit_lineage")
    source_revision_id = value.get("source_artifact_revision_id")
    source_digest = value.get("source_content_digest")
    if source_digest is not None:
        if not isinstance(source_digest, str) or len(source_digest) != 64:
            raise StrictResultManifestError("result_manifest_source_lineage_binding_invalid")
        if source_revision_id is None:
            source_matches = [
                (candidate_id, candidate)
                for candidate_id, candidate in artifact_revisions.items()
                if isinstance(candidate, Mapping)
                and candidate.get("logical_role") == "source"
                and candidate.get("content_digest") == source_digest
            ]
            if len(source_matches) != 1:
                raise StrictResultManifestError("result_manifest_source_lineage_binding_invalid")
            source_revision_id, source_revision = source_matches[0]
        else:
            source_revision = artifact_revisions.get(source_revision_id)
        if (
            not isinstance(source_revision_id, str)
            or not isinstance(source_revision, Mapping)
            or source_revision.get("logical_role") != "source"
            or source_revision.get("content_digest") != source_digest
        ):
            raise StrictResultManifestError("result_manifest_false_source_lineage")
    elif source_revision_id is not None:
        raise StrictResultManifestError("result_manifest_source_lineage_binding_invalid")
    return {
        "status": "exact",
        "artifact_revision_id": revision_id,
        "content_digest": digest,
        "source_artifact_revision_id": source_revision_id,
        "source_content_digest": source_digest,
        "limitation": None,
    }


def normalize_strict_result_manifest(
    value: Mapping[str, Any],
    *,
    artifact_revisions: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one strict result manifestation without executing or discovering."""

    if (
        value.get("schema_id") != STRICT_RESULT_MANIFEST_SCHEMA_ID
        or value.get("schema_version") != STRICT_RESULT_MANIFEST_SCHEMA_VERSION
        or value.get("manifestation") != "exact_result"
    ):
        raise StrictResultManifestError("result_manifest_schema_invalid")
    counts_value = value.get("counts")
    if not isinstance(counts_value, Mapping) or not counts_value:
        raise StrictResultManifestError("result_manifest_counts_invalid")
    requested = value.get("requested_shots")
    observed = value.get("observed_shots")
    if requested is not None and (not isinstance(requested, int) or requested < 1):
        raise StrictResultManifestError("result_manifest_requested_shots_invalid")
    if not isinstance(observed, int) or observed < 1:
        raise StrictResultManifestError("result_manifest_observed_shots_invalid")
    try:
        normalized_counts = normalize_counts_v0(
            {"schema": "qcoder.counts.v0", "counts": dict(counts_value), "shots_total": observed}
        )["counts"]
    except (TypeError, ValueError) as exc:
        raise StrictResultManifestError("result_manifest_counts_invalid") from exc
    if sum(normalized_counts.values()) != observed:
        raise StrictResultManifestError("result_manifest_observed_shots_contradiction")
    lineage = _lineage(value.get("circuit_lineage"), artifact_revisions=artifact_revisions)
    configuration = value.get("execution_configuration")
    if not isinstance(configuration, Mapping) or configuration.get("status") not in {
        "exact",
        "unknown",
    }:
        raise StrictResultManifestError("result_manifest_execution_configuration_invalid")
    if configuration["status"] == "exact":
        reference = _bounded_text(
            configuration.get("reference"),
            category="result_manifest_execution_configuration_invalid",
        )
        settings = configuration.get("settings")
        if not isinstance(settings, Mapping):
            raise StrictResultManifestError("result_manifest_execution_configuration_invalid")
        computed = _canonical_digest(dict(settings))
        if configuration.get("digest") != computed:
            raise StrictResultManifestError(
                "result_manifest_execution_configuration_digest_invalid"
            )
        normalized_configuration = {
            "status": "exact",
            "reference": reference,
            "digest": computed,
            "settings": deepcopy(dict(settings)),
        }
    else:
        normalized_configuration = {
            "status": "unknown",
            "reference": None,
            "digest": None,
            "settings": {},
        }
    producer = value.get("producer")
    if not isinstance(producer, Mapping):
        raise StrictResultManifestError("result_manifest_producer_invalid")
    normalized_producer = {
        "kind": _bounded_text(producer.get("kind"), category="result_manifest_producer_invalid"),
        "capture_method": _bounded_text(
            producer.get("capture_method"), category="result_manifest_producer_invalid"
        ),
        "identity": (
            _bounded_text(producer["identity"], category="result_manifest_producer_invalid")
            if producer.get("identity") is not None
            else None
        ),
    }
    ordering = value.get("bit_register_ordering")
    if not isinstance(ordering, Mapping) or ordering.get("status") not in {"known", "unknown"}:
        raise StrictResultManifestError("result_manifest_bit_ordering_invalid")
    normalized_ordering = {
        "status": ordering["status"],
        "convention": (
            _bounded_text(
                ordering.get("convention"), category="result_manifest_bit_ordering_invalid"
            )
            if ordering["status"] == "known"
            else None
        ),
    }
    execution_attempt_id = _bounded_text(
        value.get("execution_attempt_id"), category="result_manifest_execution_attempt_invalid"
    )
    warnings = _bounded_text_list(
        value.get("warnings", []), category="result_manifest_warning_invalid"
    )
    limitations = _bounded_text_list(
        value.get("limitations", []), category="result_manifest_limitation_invalid"
    )
    non_claims = _bounded_text_list(
        value.get("non_claims", []), category="result_manifest_non_claim_invalid"
    )
    explicit_missingness = _bounded_text_list(
        value.get("explicit_missingness", []),
        category="result_manifest_explicit_missingness_invalid",
    )
    if lineage["limitation"] is not None and lineage["limitation"] not in limitations:
        if len(limitations) >= MAX_WARNINGS:
            raise StrictResultManifestError("result_manifest_limitation_invalid")
        limitations.append(str(lineage["limitation"]))
    normalized = {
        "schema_id": STRICT_RESULT_MANIFEST_SCHEMA_ID,
        "schema_version": STRICT_RESULT_MANIFEST_SCHEMA_VERSION,
        "manifestation": "exact_result",
        "counts": dict(sorted(normalized_counts.items())),
        "requested_shots": requested,
        "observed_shots": observed,
        "circuit_lineage": lineage,
        "execution_configuration": normalized_configuration,
        "execution_attempt_id": execution_attempt_id,
        "producer": normalized_producer,
        "bit_register_ordering": normalized_ordering,
        "warnings": warnings,
        "explicit_missingness": sorted(set(explicit_missingness)),
        "limitations": limitations,
        "non_claims": non_claims,
        "raw_terminal_or_chat_evidence_used": False,
        "workspace_or_filename_lineage_inferred": False,
    }
    normalized["manifest_digest"] = _canonical_digest(normalized)
    return normalized


def result_manifest_contract_snapshot() -> dict[str, Any]:
    payload = {
        "schema_id": STRICT_RESULT_MANIFEST_SCHEMA_ID,
        "schema_version": STRICT_RESULT_MANIFEST_SCHEMA_VERSION,
        "strict_top_level_envelope_required": True,
        "arbitrary_top_level_json_rejected": True,
        "exact_or_unknown_circuit_lineage": True,
        "false_lineage_rejected": True,
        "chat_or_terminal_history_permitted": False,
        "filename_or_adjacency_inference_permitted": False,
        "native_execution_owned_by_qcoder": False,
    }
    payload["contract_digest"] = _canonical_digest(payload)
    return payload
