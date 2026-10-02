"""Portability/currentness matrix on synthetic records; no canonical science."""
import pytest

from qcoder.ml_research import fixture, job, models, runtime
from qcoder.ml_research.contracts import Refusal, read, seal
from test_d148 import prepared


@pytest.fixture
def checkpoint():
    # Validation is numeric JSON only; no training or inference is needed here.
    f = {"digest": "f" * 64, "split_digest": "a" * 64,
         "preprocessing": {"digest": "b" * 64}}
    record = seal({"schema": "d148.checkpoint.v2", "role": "baseline",
                   "scientific_identity": runtime.scientific_identity(),
                   "scientific_runtime": runtime.scientific_runtime(),
                   "architecture": models.ARCHITECTURES["baseline"],
                   "recipe": models.RECIPES["baseline"], "fixture_digest": f["digest"],
                   "split_digest": f["split_digest"], "preprocessing_digest": f["preprocessing"]["digest"],
                   "epoch": 1, "selection_partitions": ["train", "validation"],
                   "heldout_evaluations_before_freeze": 0,
                   "selection_history": [{"epoch": i, "train_bce": 1.0, "validation_bce": 1.0} for i in range(1, 81)],
                   "state": {"0.weight": [[0.0, 0.0]] * 4, "0.bias": [0.0] * 4,
                             "2.weight": [[0.0] * 4], "2.bias": [0.0]}})
    models.validate_checkpoint(record, "baseline", f)
    return record, f


def test_wsl_kernel_only_is_portable_but_execution_is_exact(checkpoint, monkeypatch):
    record, f = checkpoint
    profiles = []
    for kernel in ("5.15.167.4", "6.18.33.2"):
        platform = f"Linux-{kernel}-microsoft-standard-WSL2-x86_64-with-glibc2.35"
        monkeypatch.setattr(runtime.platform, "platform", lambda: platform)
        models.validate_checkpoint(record, "baseline", f)
        assert runtime.scientific_runtime() == record["scientific_runtime"]
        profiles.append(runtime.runtime())
        assert profiles[-1]["platform"] == platform
    assert profiles[0]["digest"] != profiles[1]["digest"]


@pytest.mark.parametrize("attribute,value", [("python_version", "3.12.10"), ("machine", "aarch64")])
def test_python_and_architecture_still_invalidate(checkpoint, monkeypatch, attribute, value):
    record, f = checkpoint
    monkeypatch.setattr(runtime.platform, attribute, lambda: value)
    with pytest.raises(Refusal, match="checkpoint_code_runtime"):
        models.validate_checkpoint(record, "baseline", f)


@pytest.mark.parametrize("name", ["numpy", "autoray"])
def test_root_and_transitive_scientific_versions_still_invalidate(checkpoint, monkeypatch, name):
    record, f = checkpoint
    assert name in record["scientific_runtime"]["dependencies"]
    original = runtime.version
    monkeypatch.setattr(runtime, "version", lambda n: "999.0" if n == name else original(n))
    with pytest.raises(Refusal, match="scientific_runtime_unqualified|checkpoint_code_runtime"):
        models.validate_checkpoint(record, "baseline", f)


@pytest.mark.parametrize("field,value", [("implementation", "pypy"), ("device", "cuda"),
                                         ("dtype", "float32"), ("torch_threads", 2),
                                         ("deterministic_algorithms", False)])
def test_numerical_contract_mismatch_still_invalidates(checkpoint, monkeypatch, field, value):
    record, f = checkpoint
    profile = runtime.scientific_runtime()
    changed = seal({**{k: v for k, v in profile.items() if k != "digest"}, field: value})
    monkeypatch.setattr(runtime, "scientific_runtime", lambda: changed)
    with pytest.raises(Refusal, match="checkpoint_code_runtime"):
        models.validate_checkpoint(record, "baseline", f)


def test_old_runtime_schema_is_not_silently_accepted(checkpoint):
    record, f = checkpoint
    profile = seal({**{k: v for k, v in record["scientific_runtime"].items() if k != "digest"},
                    "schema": "d148.scientific_runtime.v2", "platform": runtime.platform.platform()})
    stale = seal({**{k: v for k, v in record.items() if k != "digest"}, "scientific_runtime": profile})
    with pytest.raises(Refusal, match="checkpoint_code_runtime"):
        models.validate_checkpoint(stale, "baseline", f)


def test_kernel_change_stales_execution_plan_before_authority(prepared, monkeypatch):
    root, plan = prepared
    actual = runtime.platform.platform()
    assert plan["identities"]["runtime"]["platform"] == actual
    assert job.current(root) == plan
    monkeypatch.setattr(runtime.platform, "platform", lambda: actual + "-different-kernel")
    for role in ("candidate", "baseline"):
        models.validate_checkpoint(read(root / (role + "-checkpoint.json")), role, fixture.manifest(root))
    with pytest.raises(Refusal, match="inputs_or_runtime_stale"):
        job.current(root)
    with pytest.raises(Refusal, match="inputs_or_runtime_stale"):
        job.run(root)
    assert not (root / "approval.json").exists()
    assert not (root / "entered.json").exists()
