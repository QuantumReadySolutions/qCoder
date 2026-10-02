"""Read-only offline Carbon update checks. No tracker, training, or job imports."""
import argparse
import hashlib
from importlib.metadata import distributions
import json
from pathlib import Path
import zipfile

import qcoder
from qcoder.ml_research import fixture, models, runtime
from qcoder.ml_research.contracts import read

VERSION = "0.6.0a24.post0.dev7+iqt.d148.runtime.v4"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True,
                        help="existing dev6 frozen fixture directory (read only)")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    for line in (bundle / "SHA256SUMS").read_text().splitlines():
        expected, name = line.split("  ", 1)
        path = (bundle / name).resolve()
        assert path.is_relative_to(bundle)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, name
    proof = read(bundle / "reseal-proof.json")
    for name, expected in proof["preserved_fixture_bytes"].items():
        assert hashlib.sha256((args.frozen / name).read_bytes()).hexdigest() == expected, name
    expected_dependencies = {}
    for line in (bundle / "dependencies.lock.txt").read_text().splitlines():
        if line and not line.startswith("#"):
            name, version = line.split("==")
            expected_dependencies[name.lower().replace("_", "-")] = version
    observed = {d.metadata["Name"].lower().replace("_", "-"): d.version for d in distributions()
                if d.metadata["Name"].lower() != "qcoder"}
    assert len(expected_dependencies) == 99 and observed == expected_dependencies, "dependency lock mismatch"
    assert "site-packages" in str(Path(qcoder.__file__).resolve()), "installed package required"
    if args.preflight:
        assert qcoder.__version__ == "0.6.0a24.post0.dev6+iqt.d148.human.v3"
        old = runtime.scientific_runtime()
        from qcoder.ml_research.contracts import seal
        projected = seal({**{k: v for k, v in old.items() if k not in {"digest", "schema", "platform"}},
                          "schema": "d148.scientific_runtime.v3"})
        assert projected == proof["new_scientific_runtime"], "scientific incompatibility"
    else:
        assert qcoder.__version__ == VERSION
        assert runtime.scientific_runtime() == proof["new_scientific_runtime"]
        with zipfile.ZipFile(bundle / ("qcoder-" + VERSION + "-py3-none-any.whl")) as wheel:
            site = Path(qcoder.__file__).parent.parent
            payload = [n for n in wheel.namelist() if n.startswith("qcoder/") and not n.endswith("/")]
            assert len(payload) == 156
            for name in payload:
                assert (site / name).read_bytes() == wheel.read(name), name
        for role in ("candidate", "baseline"):
            record = read(bundle / "frozen" / (role + "-checkpoint.json"))
            assert record["digest"] == proof["roles"][role]["new_digest"]
            models.validate_checkpoint(record, role, fixture.manifest(args.frozen))
    print(json.dumps({"status": "preflight_pass" if args.preflight else "installed_update_pass",
                      "qcoder": qcoder.__version__, "origin": qcoder.__file__,
                      "dependencies_exact": 99, "actual_execution_runtime": runtime.runtime(),
                      "scientific_runtime": runtime.scientific_runtime(),
                      "new_canonical_science": 0, "tracker_access": False}, indent=2))


if __name__ == "__main__":
    main()
