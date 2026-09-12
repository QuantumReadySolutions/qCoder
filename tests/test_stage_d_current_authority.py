"""Current canonical local authority, not a parallel recommendation-test field."""

import copy
import io
from pathlib import Path
import subprocess
import types

import pytest

from qcoder import protected_blueprint_contract as c
from qcoder.protected_blueprint_native import current_blueprint_authority, read_typed_intent
from qcoder.protected_decision_client import BlueprintClient
from qcoder.protected_decision_local_authority import BlueprintReview
from qcoder.current_loop import save_exact_canonical_artifact
from qcoder.blueprint_decisions_public_oss import build_decision_records, pack_decision_record_set
from qcoder.algorithm_blueprint_public_oss import with_artifact_digest
from tests.test_current_loop_continuity_v1 import _activate, _blueprint, LINEAGE
from tests.test_stage_d_public_boundary import NOW, RELEASE, intent, response


def bound_authority(tmp_path, disposition):
    store, _ = _activate(tmp_path)
    artifact = _blueprint()
    rows = build_decision_records(
        profile_id="generic_qiskit",
        current_lineage_reference=LINEAGE,
        parent_artifact_references=[{"artifact_ref": "session-artifact-" + "a" * 16}],
        dispositions={"generic_qiskit.measurement_mapping": disposition},
    )
    artifact["blueprint_decision_records"] = pack_decision_record_set(
        profile_id="generic_qiskit", decision_records=rows
    )
    artifact = with_artifact_digest(artifact)
    path = store.workspace_root / "canonical-blueprint.json"
    save_exact_canonical_artifact(
        store=store,
        role="working_blueprint",
        artifact=artifact,
        destination=path,
        expected_revision=store.read()["state_revision"],
    )
    return store, path


def recommended_response(request):
    value = response(request)
    group = value["proposal"]["groups"][0]
    group.update(
        id="measurement", recommended="expectation", unresolved=False, basis="compatible_structure"
    )
    value["proposal"]["semantic_digest"] = c.digest(value["proposal"], "semantic_digest")
    value["response_digest"] = c.digest(value, "response_digest")
    return value


@pytest.mark.parametrize(
    "disposition,category",
    [
        ({"user_disposition": "left_unresolved"}, "local_deferral"),
        (
            {
                "user_disposition": "selected_choice",
                "resolution_state": "resolved",
                "selected_value": "computational_basis",
            },
            "local_choice_conflict",
        ),
    ],
)
def test_actual_canonical_decision_rejects_old_acceptance(tmp_path, disposition, category):
    store, path = bound_authority(tmp_path, disposition)
    state_before, artifact_before = store.state_path.read_bytes(), path.read_bytes()
    state = {"intent": intent(), "authority": current_blueprint_authority(store)}
    request = c.make_request(intent(), "n" * 32, 1, NOW)
    value = recommended_response(request)
    # Exact previously delivered consumer demonstrates the ignored authority.
    root = Path(__file__).parents[1]
    old_source = subprocess.check_output(
        [
            "git",
            "show",
            "faf29f772abe6dd2de531318ef5bf08371b0a945:src/qcoder/protected_decision_local_authority.py",
        ],
        cwd=root,
    )
    old = types.ModuleType("stage_d_prior_review")
    exec(compile(old_source, "pinned-prior-review", "exec"), old.__dict__)
    for cls, rejects in ((old.BlueprintReview, False), (BlueprintReview, True)):
        review = cls(
            BlueprintClient(None, release=RELEASE), current_state=lambda: state, clock=lambda: NOW
        )
        review._state, review._request = copy.deepcopy(state), request
        if rejects:
            with pytest.raises(c.ContractError, match=category):
                review._validate_current(value)
        else:
            review._validate_current(value)
    assert store.state_path.read_bytes() == state_before
    assert path.read_bytes() == artifact_before


def test_actual_artifact_modification_and_unsupported_choice_are_not_normalized(tmp_path):
    store, path = bound_authority(
        tmp_path,
        {
            "user_disposition": "selected_choice",
            "selected_value": "SENSITIVE_UNSUPPORTED",
            "resolution_state": "resolved",
        },
    )
    with pytest.raises(c.ContractError, match="^local_authority_not_representable$"):
        current_blueprint_authority(store)
    path.write_bytes(b"{}")
    from qcoder.current_loop import CurrentLoopError

    with pytest.raises(CurrentLoopError):
        current_blueprint_authority(store)


def test_intent_snapshot_race_stops_before_acquisition():
    prior = intent()
    changed = {**prior, "framework": "cirq"}
    review = BlueprintReview(
        BlueprintClient(None, release=RELEASE),
        current_state=lambda: {"intent": changed},
        clock=lambda: NOW,
    )
    with pytest.raises(c.ContractError, match="local_state_changed"):
        review.prepare(prior)


@pytest.mark.parametrize("boundary", ["before_transmission", "after_transport", "confirmation"])
def test_canonical_authority_change_at_real_review_boundaries(tmp_path, boundary):
    store, path = bound_authority(tmp_path, {"user_disposition": "left_unresolved"})

    def state():
        return {"intent": intent(), "authority": current_blueprint_authority(store)}

    class Transport:
        def exchange(self, request, **kwargs):
            value = response(request)
            if boundary == "after_transport":
                path.write_bytes(b"{}")
            return value

    review = BlueprintReview(
        BlueprintClient(Transport(), release=RELEASE, clock=lambda: NOW),
        current_state=state,
        clock=lambda: NOW,
    )
    review.prepare(intent())
    # This producer-neutral response respects the original measurement deferral.
    # Modifying the actual canonical file invalidates the digest-bound authority;
    # no parallel mutable test authority field supplies the change.
    from qcoder.current_loop import CurrentLoopError

    class Terminal(io.StringIO):
        def isatty(self):
            return True

        def readline(self, *args):
            path.write_bytes(b"{}")
            return "CONFIRM " + review._response["response_digest"] + "\n"

    with pytest.raises(CurrentLoopError):
        if boundary == "before_transmission":
            path.write_bytes(b"{}")
            review.check_before_transmission()
        elif boundary == "after_transport":
            review.acquire(bearer="synthetic")
        else:
            review.acquire(bearer="synthetic")
            review.confirm_native(Terminal(), Terminal())


def test_native_typed_form_has_no_json_construction_or_free_text():
    chosen = read_typed_intent(
        io.StringIO("entanglement\nsmall_demonstration\nqiskit\nunspecified\nno_execution\n\n\n"),
        io.StringIO(),
    )
    assert chosen["objective"] == "entanglement" and chosen["constraints"] == ["no_execution"]
    with pytest.raises(c.ContractError, match="intent_selection_invalid"):
        read_typed_intent(io.StringIO("SENSITIVE/path.py\n"), io.StringIO())
