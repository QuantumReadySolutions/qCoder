"""Native private-input/review adapter; no assistant-confirmation shortcut.

The exact local intent file is never transmitted as a filename or byte blob.
Only its validated typed representation is sent after an attended inspection.
"""

from __future__ import annotations

import getpass
import json
import os
import warnings
from pathlib import Path

from qcoder import protected_blueprint_contract as c
from qcoder.protected_decision_client import (
    BlueprintClient,
    BlueprintHTTPTransport,
    require_native_blueprint_destination,
)
from qcoder.protected_decision_local_authority import BlueprintReview
from qcoder.current_loop import (
    CurrentLoopError,
    CurrentLoopStore,
    _read_saved_artifact,
    decision_inventory_binding,
)
from qcoder.blueprint_decisions_public_oss import catalog_entries, unpack_decision_record_set


def read_private_from_tty(prompt: str, *, optional: bool = False) -> str:
    """Approved controlling-TTY/getpass mechanism, without echo/stdin fallback.

    A supplied stream's isatty flag is not this check. Warning promotion happens
    before getpass's fallback reader. getpass restores terminal modes on normal,
    EOF and interrupt exits; inability to establish/restore them rejects the call.
    """
    if os.name != "posix":
        raise c.ContractError("private_input_unavailable")
    try:
        flags = os.O_RDWR | os.O_NOCTTY | os.O_CLOEXEC | os.O_NOFOLLOW
        descriptor = os.open("/dev/tty", flags)
        try:
            if not os.isatty(descriptor):
                raise OSError
        finally:
            os.close(descriptor)
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass(prompt)
    except (OSError, EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        raise c.ContractError("private_input_unavailable") from None
    if (not value and not optional) or len(value) > 8192 or value != value.strip():
        raise c.ContractError("private_input_invalid")
    return value


def current_blueprint_authority(store):
    """Resolve only current, digest-bound local artifacts; nothing here is sent.

    Do not infer broad choices from free text or strip a decision ID suffix.
    Public catalog field relationships select the relevant decision records.
    Unsupported explicit values remain unsupported, never silently overridden.
    """
    if not store.state_path.exists():
        return {"loop": None, "artifact": None, "deferred": [], "required": {}}
    state = store.read()
    saved = state.get("saved_artifacts", {})
    descriptor = saved.get("evolved_blueprint") or saved.get("working_blueprint")
    result = {"loop": state, "artifact": None, "deferred": [], "required": {}}
    if descriptor is None:
        # No canonical decision has been committed at this point; retain state
        # currentness, not an invented governing blueprint or inferred prompt.
        return result
    artifact = _read_saved_artifact(descriptor)
    binding = decision_inventory_binding(artifact)
    records = (
        unpack_decision_record_set(artifact["blueprint_decision_records"])
        if "blueprint_decision_records" in artifact
        else artifact["decision_records"]
    )
    definitions = {r["profile_decision_id"]: r for r in catalog_entries(binding["profile_id"])}
    fields = {
        "measurement_plan": "measurement",
        "framework_requirement": "framework",
        "normalized_goal": "formulation",
        "optimization_problem": "formulation",
        "objective": "formulation",
        "search_space_meaning": "formulation",
    }
    deferred, required = set(), {}
    for record in records:
        groups = {
            fields[f]
            for f in definitions[record["profile_decision_id"]]["blueprint_fields"]
            if f in fields
        }
        if groups and record["resolution_state"] == "conflicting":
            raise c.ContractError("local_authority_conflict")
        for group in groups:
            if record["user_disposition"] in {
                "left_unresolved",
                "deferred_to_source_evidence",
                "deferred_to_later_evidence",
            }:
                deferred.add(group)
            if record["user_disposition"] == "selected_choice":
                value = record.get("selected_value")
                if type(value) is not str or value not in c.CHOICES[group]:
                    raise c.ContractError("local_authority_not_representable")
                if group in required and required[group] != value:
                    raise c.ContractError("local_authority_conflict")
                required[group] = value
    if set(required) & deferred:
        raise c.ContractError("local_authority_conflict")
    result.update(artifact=artifact, deferred=sorted(deferred), required=required)
    return result


def read_typed_intent(input_stream, output_stream):
    """Native finite form; no hand-written JSON or free-text interpretation."""
    intent = {}
    for field, values in c.SCALARS.items():
        output_stream.write(field + " [" + ", ".join(sorted(values)) + "]: ")
        output_stream.flush()
        value = input_stream.readline(128)
        if not value.endswith("\n") or value[:-1] not in values:
            raise c.ContractError("intent_selection_invalid")
        intent[field] = value[:-1]
    for field, values in c.SETS.items():
        output_stream.write(
            field + " [comma-separated from " + ", ".join(sorted(values)) + "; empty allowed]: "
        )
        output_stream.flush()
        value = input_stream.readline(512)
        if not value.endswith("\n"):
            raise c.ContractError("intent_selection_invalid")
        intent[field] = [] if value == "\n" else sorted(value[:-1].split(","))
    return c.validate_intent(intent)


def native_review(*, intent_path, endpoint, release, input_stream, output_stream):
    require_native_blueprint_destination(endpoint, release)
    if not input_stream.isatty() or not output_stream.isatty():
        raise c.ContractError("customer_terminal_required")
    path = Path(intent_path) if intent_path is not None else None
    if path is not None and (path.is_symlink() or not path.is_file()):
        raise c.ContractError("local_intent_file")
    store = CurrentLoopStore.for_workspace(Path.cwd())
    try:
        before_form = current_blueprint_authority(store)
    except CurrentLoopError:
        raise c.ContractError("local_state_invalid") from None
    form_intent = read_typed_intent(input_stream, output_stream) if path is None else None

    def current_state():
        if path is not None and path.is_symlink():
            raise c.ContractError("local_intent_file")
        if path is not None:
            with path.open("rb") as handle:
                intent = c.decode(handle.read(c.MAX_BYTES + 1))
        else:
            intent = form_intent
        # Current Loop data remains LOCAL and is not hashed into a wire field.
        # A concurrently created/changed/deleted loop invalidates review too.
        try:
            authority = current_blueprint_authority(store)
        except CurrentLoopError:
            raise c.ContractError("local_state_invalid") from None
        return {
            "intent": c.validate_intent(intent),
            "deferred_decisions": intent["unresolved"],
            "current_loop": authority["loop"],
            "authority": authority,
        }

    client = BlueprintClient(BlueprintHTTPTransport(endpoint), release=release)
    review = BlueprintReview(client, current_state=current_state)
    initial = current_state()
    if initial["authority"] != before_form:
        raise c.ContractError("local_state_changed")
    request = review.prepare(initial["intent"])
    output_stream.write(c.encode(request).decode("ascii") + "\n")
    output_stream.write(
        "Only this structured intent is sent; authentication is separate.\n"
        "Content is processed and discarded; non-content quota metadata may remain.\n"
        "Type SEND STRUCTURED INTENT to transmit, or stop.\n"
    )
    output_stream.flush()
    if input_stream.readline(64) != "SEND STRUCTURED INTENT\n":
        raise c.ContractError("transmission_not_confirmed")
    review.check_before_transmission()
    # Private input is from the controlling terminal, never argv/stdin piping/MCP.
    bearer = caller = None
    try:
        bearer = read_private_from_tty("EXISTING_QCODER_BEARER (hidden): ")
        caller = read_private_from_tty(
            "EXISTING_CALLER_ID_TOKEN_IF_REQUIRED (hidden; empty otherwise): ", optional=True
        )
        review.acquire(bearer=bearer, caller_token=caller)
    finally:
        bearer = caller = None  # Discard references; no guaranteed memory-erasure claim.
    result = review.confirm_native(input_stream, output_stream)
    output_stream.write(json.dumps(result, sort_keys=True) + "\n")
    return result
