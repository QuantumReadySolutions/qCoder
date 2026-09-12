"""Pure public confirmation binding for an inert protected proposal."""

from __future__ import annotations

import hmac
from typing import Any, Mapping

from qcoder.protected_decision_validation import validate_proposal
from qcoder import protected_blueprint_contract as blueprint
import copy
import secrets
import threading


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
    # Historical foundation callers supplied two strings, not a customer action.
    # Keep import compatibility and stale diagnostics, but never attest consent.
    raise ValueError("protected_customer_action_required")


class BlueprintReview:
    """Ephemeral native-client review; no write/run/retention authority.

    State is read from the actual local consumer at every boundary, not accepted
    as confirmation arguments. Closing/restarting loses review eligibility.
    Native confirmation is a terminal customer action, never an MCP/service flag.
    """

    def __init__(self, client, *, current_state, clock=blueprint.now_utc):
        self.client, self.current_state, self.clock = client, current_state, clock
        self._lock = threading.Lock()
        self._display = None
        self._used = False

    def prepare(self, intent):
        with self._lock:
            self._state = copy.deepcopy(self.current_state())
            if self._state.get("intent", intent) != intent:
                raise blueprint.ContractError("local_state_changed")
            self._request = blueprint.make_request(
                intent, secrets.token_urlsafe(24), 1, self.clock()
            )
            self._display, self._used = None, False
            return copy.deepcopy(self._request)

    def check_before_transmission(self):
        if self.current_state() != self._state:
            raise blueprint.ContractError("local_state_changed")
        blueprint.validate_request(self._request, self.clock())

    def acquire(self, *, bearer, caller_token=""):
        with self._lock:
            if self.current_state() != self._state or self._used or self._display is not None:
                raise blueprint.ContractError("local_state_changed")
            response = self.client.recommend(
                self._request, bearer=bearer, caller_token=caller_token
            )
            self._validate_current(response)
            if response["outcome"] != "completed":
                raise blueprint.ContractError(response["outcome"])
            self._response = copy.deepcopy(response)
            self._display = blueprint.encode(response)
            return self._display.decode("ascii")

    def _validate_current(self, response):
        if self.current_state() != self._state:
            raise blueprint.ContractError("local_state_changed")
        blueprint.validate_response(response, self._request, self.client.release, self.clock())
        # Deferrals are local ceilings, never service-granted authority.
        deferred = set(self._state.get("deferred_decisions", []))
        authority = self._state.get("authority", {})
        deferred.update(authority.get("deferred", []))
        unresolved = set(self._request["intent"]["unresolved"])
        deferred |= unresolved & {"framework", "measurement"}
        if unresolved & {"objective", "problem_size"}:
            deferred.add("formulation")
        for group in (response.get("proposal") or {}).get("groups", []):
            if group["id"] in deferred and group["recommended"] is not None:
                raise blueprint.ContractError("local_deferral")
            required = authority.get("required", {}).get(group["id"])
            if required is not None and group["recommended"] not in (None, required):
                raise blueprint.ContractError("local_choice_conflict")
            explicit = self._request["intent"].get(group["id"])
            if (
                explicit
                and explicit != "unspecified"
                and group["recommended"] not in (None, explicit)
            ):
                raise blueprint.ContractError("explicit_intent_conflict")

    def confirm_native(self, input_stream, output_stream):
        with self._lock:
            if not input_stream.isatty() or not output_stream.isatty():
                raise blueprint.ContractError("customer_terminal_required")
            if self._display is None or self._used:
                raise blueprint.ContractError("display_required_or_consumed")
            self._validate_current(self._response)
            if blueprint.encode(self._response) != self._display:
                raise blueprint.ContractError("display_modified")
            # Re-display the exact validated envelope at the confirmation surface.
            output_stream.write(self._display.decode("ascii") + "\n")
            for group in self._response["proposal"]["groups"]:
                output_stream.write(
                    group["id"].capitalize()
                    + ": "
                    + (group["recommended"] or "unresolved")
                    + "; alternatives (unranked): "
                    + (", ".join(group["alternatives"]) or "none")
                    + "; basis: "
                    + group["basis"]
                    + "\n"
                )
            output_stream.write(
                "Limitations: " + ", ".join(self._response["proposal"]["limitations"]) + "\n"
            )
            output_stream.write(
                "Unresolved: "
                + (", ".join(self._response["proposal"]["unresolved"]) or "none")
                + "\n"
            )
            marker = "CONFIRM " + self._response["response_digest"]
            output_stream.write("For local evaluation only, type " + marker + "\n")
            output_stream.flush()
            answer = input_stream.readline(128)
            self._validate_current(self._response)
            if answer != marker + "\n":
                raise blueprint.ContractError("customer_confirmation_required")
            self._used = True
            return {
                "customer_confirmation_exact": True,
                "confirmed_response_digest": self._response["response_digest"],
                "authority": "confirmed_for_local_evaluation_only",
                "write_authorized": False,
                "execution_authorized": False,
                "retention_authorized": False,
                "evidence_acceptance_authorized": False,
                "selection_authorized": False,
                "continuation_authorized": False,
            }
