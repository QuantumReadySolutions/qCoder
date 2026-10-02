"""Dedicated local MLflow, exact ID reads and science-independent delivery."""
from pathlib import Path
import re
from urllib.parse import unquote, urlparse

from .contracts import checked, locked, now, read, require, seal, write_new

PARAMS = ("role", "fixture_digest", "split_digest", "preprocessing_digest", "checkpoint_digest", "recipe_digest")


def destination(root):
    root = Path(root).resolve()
    return {"tracking_uri": "sqlite:///" + str(root / "tracking.sqlite"), "artifact_root": (root / "tracker-artifacts").as_uri()}


def client(root):
    # No ambient MLFLOW_TRACKING_URI, registry or remote artifact destination is used.
    from mlflow.tracking import MlflowClient
    return MlflowClient(tracking_uri=destination(root)["tracking_uri"])


def initialize(root):
    root = Path(root)
    c = client(root)
    dest = destination(root)
    experiment = c.create_experiment("D148-local-" + root.resolve().name, artifact_location=dest["artifact_root"])
    record = seal({"schema": "d148.tracker.v1", "destination": dest, "experiment_id": experiment})
    write_new(root / "tracker.json", record)
    return record


def configuration(root):
    config = read(Path(root) / "tracker.json")
    checked(config, "d148.tracker.v1", ["destination", "experiment_id"])
    require(config["destination"] == destination(root), "tracker_destination_changed")
    experiment = client(root).get_experiment(config["experiment_id"])
    require(experiment.artifact_location == config["destination"]["artifact_root"] and experiment.lifecycle_stage == "active", "experiment_destination")
    return config


def exact_run(root, run_id):
    require(isinstance(run_id, str) and re.fullmatch(r"[0-9a-f]{32}", run_id), "exact_run_id_required")
    config = configuration(root)
    run = client(root).get_run(run_id)
    require(run.info.experiment_id == config["experiment_id"] and run.info.lifecycle_stage == "active", "selected_experiment")
    uri = urlparse(run.info.artifact_uri)
    artifact_root = Path(root).resolve() / "tracker-artifacts"
    require(uri.scheme == "file" and not uri.netloc and not uri.query and not uri.fragment, "remote_artifacts_forbidden")
    path = Path(unquote(uri.path))
    expected = artifact_root / run_id / "artifacts"
    require(path == expected and path.resolve() == expected, "artifact_location_mismatch")
    # Tags/free text remain inert. Never fetch model/source/pickle artifacts.
    return run


def training_record(root, role):
    root = Path(root)
    checkpoint = read(root / f"{role}-checkpoint.json")
    recipes = read(root / "recipes.json")
    config = configuration(root)
    params = {"role": role, "fixture_digest": checkpoint["fixture_digest"], "split_digest": checkpoint["split_digest"], "preprocessing_digest": checkpoint["preprocessing_digest"], "checkpoint_digest": checkpoint["digest"], "recipe_digest": recipes["digest"]}
    # Reservation failure is preserved as unknown, never searched for or auto-recreated.
    write_new(root / f"{role}-tracking-entered.json", seal({"schema": "d148.tracking_entry.v1", "role": role, "time": now()}))
    c = client(root)
    run = c.create_run(config["experiment_id"], tags={"qcoder.kind": "training", "qcoder.provenance": "external_reported"})
    write_new(root / f"{role}-run.json", seal({"schema": "d148.training_run.v1", "run_id": run.info.run_id, "params": params}))
    exact_run(root, run.info.run_id)
    for key, value in params.items():
        c.log_param(run.info.run_id, key, value)
    c.log_dict(run.info.run_id, checkpoint, "checkpoint-provenance.json")
    c.set_terminated(run.info.run_id)
    return run.info.run_id


def selected(root, candidate_id, baseline_id):
    result = {}
    require(candidate_id != baseline_id, "distinct_training_runs")
    for role, run_id in (("candidate", candidate_id), ("baseline", baseline_id)):
        local = read(Path(root) / f"{role}-run.json")
        require(run_id == local["run_id"], "run_not_locally_verified")
        run = exact_run(root, run_id)
        require(run.info.status == "FINISHED", "training_not_finished")
        observed = {key: run.data.params.get(key) for key in PARAMS}
        require(observed == local["params"], "selected_record_tampered")
        checkpoint = read(Path(root) / f"{role}-checkpoint.json")
        require(observed["checkpoint_digest"] == checkpoint["digest"] and observed["fixture_digest"] == checkpoint["fixture_digest"] and observed["split_digest"] == checkpoint["split_digest"] and observed["preprocessing_digest"] == checkpoint["preprocessing_digest"], "selected_checkpoint_mismatch")
        result[role] = {"run_id": run_id, "external_reported": observed, "qcoder_verified_local_checkpoint_digest": checkpoint["digest"]}
    return result


def reserve_assessment(root):
    root = Path(root)
    config = configuration(root)
    write_new(root / "assessment-reservation-entered.json", seal({"schema": "d148.reservation_entry.v1", "time": now()}))
    run = client(root).create_run(config["experiment_id"], tags={"qcoder.kind": "assessment_pending"})
    write_new(root / "assessment-run.json", seal({"schema": "d148.assessment_run.v1", "run_id": run.info.run_id}))
    exact_run(root, run.info.run_id)
    return run.info.run_id


def assessment(root, plan, result):
    return seal({"schema": "d148.assessment.v1", "source_run_ids": {role: plan["selected"][role]["run_id"] for role in ("candidate", "baseline")}, "assessment_run_id": plan["assessment_run_id"], "job_id": plan["job_id"], "plan_digest": plan["digest"], "result_digest": result["digest"], "receipt_digest": result["receipt_digest"], "identities": plan["identities"], "metrics": result["metrics"], "accounting": result["accounting"], "evidence_conclusion": result["evidence_conclusion"], "next_action": result["next_action"], "rationale": "Predeclared accuracy >=26/40 and baseline advantage <=4/40; descriptive comparison only.", "limitations": ["40 held-out examples", "one fixed recipe per model", "no advantage, generalization or QPU claim", "no automatic refinement"], "evaluation_time": result["evaluation_time"], "tracker_write_time": now(), "provenance": {"qcoder_established": ["metrics", "conclusion", "next_action", "local_identities", "accounting"], "external_reported": ["MLflow source params"], "assistant_inference": [], "not_established": ["quantum advantage", "population performance", "refinement outcome"]}})


def delivery_fields(value):
    metrics = {"candidate_accuracy": value["metrics"]["candidate"]["accuracy"], "baseline_accuracy": value["metrics"]["baseline"]["accuracy"], "accuracy_delta": value["metrics"]["delta"]}
    params = {"job_id": value["job_id"], "plan_digest": value["plan_digest"], "result_digest": value["result_digest"], "candidate_run_id": value["source_run_ids"]["candidate"], "baseline_run_id": value["source_run_ids"]["baseline"], "assessment_digest": value["digest"], "schema": value["schema"], "evidence_conclusion": value["evidence_conclusion"], "next_action": value["next_action"]}
    return metrics, params


def readback(root, value):
    checked(value, "d148.assessment.v1")
    run = exact_run(root, value["assessment_run_id"])
    metrics, params = delivery_fields(value)
    require(all(run.data.params.get(k) == v for k, v in params.items()), "assessment_params_mismatch")
    require(all(run.data.metrics.get(k) == v for k, v in metrics.items()), "assessment_metrics_mismatch")
    # Real MLflow path, preceded by exact local URI validation. JSON only.
    downloaded = client(root).download_artifacts(run.info.run_id, "qcoder-assessment.json")
    observed = read(downloaded)
    require(observed == value, "assessment_artifact_mismatch")
    return seal({"schema": "d148.readback.v1", "assessment_run_id": run.info.run_id, "assessment_digest": value["digest"], "result_digest": value["result_digest"], "verified_at": now(), "projection": observed})


def deliver(root):
    from .job import verify_completed
    root = Path(root)
    with locked(root):
        plan, result = verify_completed(root)
        path = root / "assessment.json"
        if not path.exists():
            write_new(path, assessment(root, plan, result))
        value = read(path)
        require(value["result_digest"] == result["digest"] and value["plan_digest"] == plan["digest"], "delivery_result_mismatch")
        c = client(root)
        run_id = value["assessment_run_id"]
        run = exact_run(root, run_id)
        metrics, params = delivery_fields(value)
        require(all(k not in run.data.params or run.data.params[k] == v for k, v in params.items()), "assessment_conflicting_params")
        require(all(k not in run.data.metrics or run.data.metrics[k] == v for k, v in metrics.items()), "assessment_conflicting_metrics")
        existing = c.list_artifacts(run_id)
        if any(item.path == "qcoder-assessment.json" for item in existing):
            artifact = read(c.download_artifacts(run_id, "qcoder-assessment.json"))
            require(artifact == value, "assessment_conflicting_artifact")
        for key, v in params.items():
            if key not in run.data.params:
                c.log_param(run_id, key, v)
        for key, v in metrics.items():
            if key not in run.data.metrics:
                c.log_metric(run_id, key, v)
        if not any(item.path == "qcoder-assessment.json" for item in existing):
            # log_dict adds whitespace, so write our canonical bytes under the fixed name.
            local = root / "qcoder-assessment.json"
            if not local.exists():
                write_new(local, value)
            require(read(local) == value, "delivery_artifact_changed")
            c.log_artifact(run_id, str(local))
        c.set_terminated(run_id)
        verified = readback(root, value)
        if not (root / "readback.json").exists():
            write_new(root / "readback.json", verified)
        return verified
