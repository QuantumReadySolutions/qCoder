"""Native private-input/review adapter; no assistant-confirmation shortcut.

The exact local intent file is never transmitted as a filename or byte blob.
Only its validated typed representation is sent after an attended inspection.
"""

from __future__ import annotations

import getpass
import json
from pathlib import Path

from qcoder import protected_blueprint_contract as c
from qcoder.protected_decision_client import BlueprintClient, BlueprintHTTPTransport
from qcoder.protected_decision_local_authority import BlueprintReview
from qcoder.current_loop import CurrentLoopStore


def native_review(*, intent_path, endpoint, release, input_stream, output_stream):
    if not input_stream.isatty() or not output_stream.isatty():
        raise c.ContractError("customer_terminal_required")
    path = Path(intent_path)
    if path.is_symlink() or not path.is_file():
        raise c.ContractError("local_intent_file")
    store = CurrentLoopStore.for_workspace(Path.cwd())

    def current_state():
        if path.is_symlink():
            raise c.ContractError("local_intent_file")
        with path.open("rb") as handle:
            intent = c.decode(handle.read(c.MAX_BYTES + 1))
        # Current Loop data remains LOCAL and is not hashed into a wire field.
        # A concurrently created/changed/deleted loop invalidates review too.
        local_loop = store.read() if store.state_path.exists() else None
        return {
            "intent": c.validate_intent(intent),
            "deferred_decisions": intent["unresolved"],
            "current_loop": local_loop,
        }

    client = BlueprintClient(BlueprintHTTPTransport(endpoint), release=release)
    review = BlueprintReview(client, current_state=current_state)
    request = review.prepare(current_state()["intent"])
    output_stream.write(c.encode(request).decode("ascii") + "\n")
    output_stream.write(
        "Only this structured intent is sent; authentication is separate.\n"
        "Content is processed and discarded; non-content quota metadata may remain.\n"
        "Type SEND STRUCTURED INTENT to transmit, or stop.\n"
    )
    output_stream.flush()
    if input_stream.readline(64) != "SEND STRUCTURED INTENT\n":
        raise c.ContractError("transmission_not_confirmed")
    # Private input is from the controlling terminal, never argv/stdin piping/MCP.
    bearer = getpass.getpass("EXISTING_QCODER_BEARER (hidden): ")
    caller = getpass.getpass("EXISTING_CALLER_ID_TOKEN_IF_REQUIRED (hidden; empty otherwise): ")
    try:
        review.acquire(bearer=bearer, caller_token=caller)
    finally:
        bearer = caller = None  # Discard references; no guaranteed memory-erasure claim.
    result = review.confirm_native(input_stream, output_stream)
    output_stream.write(json.dumps(result, sort_keys=True) + "\n")
    return result
