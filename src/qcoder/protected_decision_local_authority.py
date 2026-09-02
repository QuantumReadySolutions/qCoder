"""Pure public confirmation binding for an inert protected proposal."""

from __future__ import annotations

import hmac
from typing import Any, Mapping

from qcoder.protected_decision_validation import validate_proposal


def inert_proposal_projection(
    proposal: Mapping[str, Any], *, semantic_revision_digest: str
) -> dict[str, Any]:
    normalized = validate_proposal(proposal)
    return {
        "proposal": normalized,
        "proposal_digest": normalized["proposal_digest"],
        "semantic_revision_digest": semantic_revision_digest,
        "display_required_before_confirmation": True,
        "local_authority_granted": False,
        "local_effect_performed": False,
        "execution_authorized": False,
        "write_authorized": False,
        "continuation_authorized": False,
    }


def confirm_inert_proposal(
    projection: Mapping[str, Any],
    *,
    displayed_proposal_digest: str,
    displayed_semantic_revision_digest: str,
) -> dict[str, Any]:
    proposal = projection.get("proposal")
    if not isinstance(proposal, Mapping):
        raise ValueError("protected_confirmation_proposal_missing")
    normalized = validate_proposal(proposal)
    if not hmac.compare_digest(normalized["proposal_digest"], displayed_proposal_digest):
        raise ValueError("protected_confirmation_proposal_stale")
    revision = projection.get("semantic_revision_digest")
    if not isinstance(revision, str) or not hmac.compare_digest(
        revision, displayed_semantic_revision_digest
    ):
        raise ValueError("protected_confirmation_revision_stale")
    return {
        "confirmed_proposal_digest": displayed_proposal_digest,
        "confirmed_semantic_revision_digest": displayed_semantic_revision_digest,
        "customer_confirmation_exact": True,
        "protected_proposal_authority": "confirmed_for_local_evaluation_only",
        "execution_authorized": False,
        "write_authorized": False,
        "continuation_authorized": False,
    }
