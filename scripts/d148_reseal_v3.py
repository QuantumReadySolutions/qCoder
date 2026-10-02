"""One-time bounded v2 -> v3 provenance reseal. Never trains or evaluates a model.

Only the two exact previously frozen fixture-owned JSON checkpoints are accepted.
This is campaign preparation evidence, not a production checkpoint import API.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from qcoder.focused_loop.canonical import canonical_bytes, canonical_digest
from qcoder.ml_research import fixture, models, runtime
from qcoder.ml_research.contracts import read, seal, write_new

BASE = "dca2a276b8b2510b064c0f1d0548201f22d7e82a"
EXPECTED = {
    "candidate": "457897807be1bd9197fc54db66c3488af21cc765e84b5236624b3dd798b070e3",
    "baseline": "9ced20ed5f0919d2a674b7934ecd89d66c720968c91d345d6fd5a7410bf56657",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    args = parser.parse_args()
    assert not args.new.exists(), "fresh destination required"
    source = Path(runtime.__file__).parent
    def git_bytes(relative):
        return subprocess.check_output(["git", "show", BASE + ":" + relative], cwd=args.repository)
    old_sources = {name: git_bytes("src/qcoder/ml_research/" + name) for name in runtime.CODE_FILES}
    old_code = seal({"schema": "d148.code.v1", "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in old_sources.items()}, "canonical_primitive": hashlib.sha256(git_bytes("src/qcoder/focused_loop/canonical.py")).hexdigest()})
    assert old_code["canonical_primitive"] == runtime.code_identity()["canonical_primitive"]
    unchanged = ("__init__.py", "contracts.py", "fixture.py", "training.py")
    for name in unchanged:
        assert old_sources[name] == (source / name).read_bytes(), name
    # Compare the entire models syntax after ONLY explicitly declared metadata
    # renamings. Architecture, initialization, state reconstruction, recipes,
    # numeric validation and selection logic must remain exactly identical.
    mapped = old_sources["models.py"].decode()
    for before, after in (
        ("code_identity", "scientific_identity"), ("training_code", "scientific_identity"),
        ("training_runtime", "scientific_runtime"), ("runtime()", "scientific_runtime()"),
        ("import scientific_identity, runtime", "import scientific_identity, scientific_runtime"),
        ("d148.checkpoint.v1", "d148.checkpoint.v2"),
    ):
        mapped = mapped.replace(before, after)
    syntax = lambda text: ast.dump(ast.parse(text), include_attributes=False)
    assert syntax(mapped) == syntax((source / "models.py").read_text()), "scientific model logic changed"
    scientific_profile = runtime.scientific_runtime()
    current_full_profile = runtime.runtime()
    records = {}
    for role, expected in EXPECTED.items():
        old = read(args.old / (role + "-checkpoint.json"))
        assert old["digest"] == expected and old["training_code"] == old_code
        assert old["training_runtime"] == current_full_profile, "legacy scientific environment changed"
        for key, value in scientific_profile.items():
            if key in ("schema", "digest"):
                continue
            if key in ("dependencies", "versions"):
                assert all(old["training_runtime"][key].get(name, old["training_runtime"]["dependencies"].get(name)) == version for name, version in value.items())
            else:
                assert old["training_runtime"][key] == value
        new = seal({**{key: value for key, value in old.items() if key not in ("schema", "digest", "training_code", "training_runtime")},
                    "schema": "d148.checkpoint.v2",
                    "scientific_identity": runtime.scientific_identity(),
                    "scientific_runtime": scientific_profile})
        models.validate_checkpoint(new, role, fixture.manifest(args.old))
        old_science = {key: value for key, value in old.items() if key not in ("schema", "digest", "training_code", "training_runtime")}
        new_science = {key: value for key, value in new.items() if key not in ("schema", "digest", "scientific_identity", "scientific_runtime")}
        assert canonical_bytes(old_science) == canonical_bytes(new_science)
        records[role] = (old, new)
    for name in ("approval.json", "entered.json", "receipt.json", "result.json"):
        assert not (args.old / name).exists()
    args.new.mkdir(parents=True)
    preserved = {}
    for name in ("fixture.json", "train.json", "validation.json", "test.json", "recipes.json"):
        shutil.copyfile(args.old / name, args.new / name)
        assert (args.old / name).read_bytes() == (args.new / name).read_bytes()
        preserved[name] = hashlib.sha256((args.new / name).read_bytes()).hexdigest()
    proof = {"schema": "d148.provenance_reseal.v3", "basis_commit": BASE, "training_or_evaluation_performed": False,
             "unchanged_source_files": list(unchanged), "model_AST_equal_after_metadata_renamings_only": True,
             "legacy_code_digest": old_code["digest"], "scientific_identity": runtime.scientific_identity(),
             "scientific_runtime": scientific_profile, "preserved_fixture_bytes": preserved, "roles": {}}
    for role, (old, new) in records.items():
        write_new(args.new / (role + "-checkpoint.json"), new)
        proof["roles"][role] = {"old_digest": old["digest"], "new_digest": new["digest"], "all_nonprovenance_bytes_equal": True,
                               "numeric_state_sha256_old_and_new": canonical_digest(new["state"]),
                               "complete_history_sha256_old_and_new": canonical_digest(new["selection_history"]),
                               "history_epochs": len(new["selection_history"]), "selected_epoch": new["epoch"],
                               "validation_bce": new["selection_history"][new["epoch"] - 1]["validation_bce"],
                               "recipe": new["recipe"]}
    write_new(args.proof, seal(proof))


if __name__ == "__main__":
    main()
