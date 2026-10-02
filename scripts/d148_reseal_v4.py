"""Exact v3 -> v4 campaign reseal, with no training, evaluation or tracker access.

Accept only committed v3 inputs and the reviewed runtime-only source correction.
Old checkpoints remain historical; production validation has no migration bypass.
"""
import argparse
import ast
import hashlib
from pathlib import Path
import subprocess
import tempfile

from qcoder.focused_loop.canonical import canonical_bytes, canonical_digest
from qcoder.ml_research import fixture, models, runtime
from qcoder.ml_research.contracts import read, seal, write_new

BASE = "3a54fc6502b183374853f59cfc3c6bd588c44202"
EXPECTED = {
    "candidate": "2b6a5e672af2f7d1312289cef02079e6962a15d708e6253e4e993e33fdd870db",
    "baseline": "821199f89772f3614462401a6ec0b8820c3c67cbaf175118662f98e62eba67ff",
}
PROVENANCE = {"digest", "scientific_identity", "scientific_runtime"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    args = parser.parse_args()
    assert not args.new.exists() and not args.proof.exists(), "fresh destinations required"
    def git_bytes(path):
        return subprocess.check_output(["git", "show", BASE + ":" + path], cwd=args.repository)
    source = Path(runtime.__file__).parent
    old_sources = {name: git_bytes("src/qcoder/ml_research/" + name) for name in runtime.CODE_FILES}
    for name, raw in old_sources.items():
        if name != "runtime.py":
            assert raw == (source / name).read_bytes(), name
    assert git_bytes("src/qcoder/focused_loop/canonical.py") == (source.parent / "focused_loop/canonical.py").read_bytes()
    # Compare full module AST after exactly three declared edits in this function.
    old_tree = ast.parse(old_sources["runtime.py"])
    for node in old_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "scientific_runtime":
            node.body.insert(0, ast.Expr(value=ast.Constant(value="Portable numerical contract; the full local platform belongs to runtime().")))
            for child in ast.walk(node):
                if isinstance(child, ast.Dict):
                    for i in range(len(child.keys) - 1, -1, -1):
                        key = child.keys[i]
                        if isinstance(key, ast.Constant) and key.value == "platform":
                            del child.keys[i]; del child.values[i]
                        elif isinstance(key, ast.Constant) and key.value == "schema":
                            assert child.values[i].value == "d148.scientific_runtime.v2"
                            child.values[i].value = "d148.scientific_runtime.v3"
    assert ast.dump(old_tree) == ast.dump(ast.parse((source / "runtime.py").read_text())), "unexpected runtime logic change"
    original_file = runtime.__file__
    with tempfile.TemporaryDirectory() as directory:
        for name, raw in old_sources.items():
            (Path(directory) / name).write_bytes(raw)
        try:
            runtime.__file__ = str(Path(directory) / "runtime.py")
            old_identity = runtime.scientific_identity()
        finally:
            runtime.__file__ = original_file
    current_profile = runtime.scientific_runtime()
    proof = {"schema": "d148.runtime_portability_reseal.v1", "basis_commit": BASE,
             "training_or_evaluation_performed": False,
             "only_runtime_schema_platform_and_docstring_changed": True,
             "unchanged_source_files": [n for n in old_sources if n != "runtime.py"],
             "old_scientific_identity": old_identity,
             "new_scientific_identity": runtime.scientific_identity(),
             "new_scientific_runtime": current_profile, "roles": {}, "preserved_fixture_bytes": {}}
    args.new.mkdir(parents=True)
    for name in ("fixture.json", "train.json", "validation.json", "test.json", "recipes.json"):
        raw = git_bytes("evidence/d148/frozen/" + name)
        (args.new / name).write_bytes(raw)
        proof["preserved_fixture_bytes"][name] = hashlib.sha256(raw).hexdigest()
    for role, expected in EXPECTED.items():
        old_path = args.repository / "evidence/d148/recut-v3/frozen" / (role + "-checkpoint.json")
        assert old_path.read_bytes() == git_bytes(str(old_path.relative_to(args.repository)))
        old = read(old_path)
        assert old["digest"] == expected and old["scientific_identity"] == old_identity
        old_profile = old["scientific_runtime"]
        assert old_profile["schema"] == "d148.scientific_runtime.v2"
        assert old_profile["platform"] == "Linux-5.15.167.4-microsoft-standard-WSL2-x86_64-with-glibc2.35"
        projected = seal({**{k: v for k, v in old_profile.items() if k not in {"digest", "schema", "platform"}}, "schema": "d148.scientific_runtime.v3"})
        assert projected == current_profile, "real scientific runtime incompatibility"
        new = seal({**{k: v for k, v in old.items() if k not in PROVENANCE},
                    "scientific_identity": runtime.scientific_identity(), "scientific_runtime": current_profile})
        models.validate_checkpoint(new, role, fixture.manifest(args.new))
        science = lambda record: {k: v for k, v in record.items() if k not in PROVENANCE}
        assert canonical_bytes(science(old)) == canonical_bytes(science(new))
        write_new(args.new / (role + "-checkpoint.json"), new)
        proof["roles"][role] = {"old_digest": old["digest"], "new_digest": new["digest"],
                               "old_file_sha256": hashlib.sha256(old_path.read_bytes()).hexdigest(),
                               "new_file_sha256": hashlib.sha256((args.new / (role + "-checkpoint.json")).read_bytes()).hexdigest(),
                               "all_nonprovenance_bytes_equal": True,
                               "nonprovenance_sha256_old_and_new": canonical_digest(science(new)),
                               "numeric_state_sha256_old_and_new": canonical_digest(new["state"]),
                               "complete_history_sha256_old_and_new": canonical_digest(new["selection_history"]),
                               "history_epochs": len(new["selection_history"]), "selected_epoch": new["epoch"],
                               "validation_bce": new["selection_history"][new["epoch"] - 1]["validation_bce"]}
        proof["old_scientific_runtime"] = old_profile
    write_new(args.proof, seal(proof))


if __name__ == "__main__":
    main()
