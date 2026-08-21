from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import stat


QISKIT_VERSION = "2.5.2"
QISKIT_AER_VERSION = "0.17.2"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _versions() -> dict[str, str]:
    versions = {
        "python": platform.python_version(),
        "qiskit": importlib.metadata.version("qiskit"),
        "qiskit_aer": importlib.metadata.version("qiskit-aer"),
    }
    if versions["qiskit"] != QISKIT_VERSION or versions["qiskit_aer"] != QISKIT_AER_VERSION:
        raise SystemExit("Prepared external execution runtime version mismatch.")
    return versions


def _bell_from_qasm(path: Path):
    from qiskit import qasm2

    circuit = qasm2.loads(path.read_text(encoding="utf-8"))
    if circuit.num_clbits == 0:
        circuit.measure_all()
    elif not any(instruction.operation.name == "measure" for instruction in circuit.data):
        circuit.measure(range(circuit.num_qubits), range(circuit.num_clbits))
    return circuit


def _sample(circuit, *, shots: int) -> tuple[dict[str, int], str]:
    from qiskit import transpile
    from qiskit_aer import AerSimulator

    backend = AerSimulator()
    compiled = transpile(circuit, backend)
    job = backend.run(compiled, shots=shots)
    counts = {str(key): int(value) for key, value in job.result().get_counts().items()}
    if sum(counts.values()) != shots:
        raise SystemExit("Prepared sampler returned a contradictory shot total.")
    return counts, "qiskit_aer.AerSimulator"


def _manifest(
    *,
    counts: dict[str, int],
    shots: int,
    attempt_id: str,
    versions: dict[str, str],
    backend: str,
    circuit_lineage_status: str,
    qasm_input_sha256: str | None,
) -> dict[str, object]:
    settings = {
        "backend": backend,
        "interface": "qiskit_backend_run",
        "qiskit": versions["qiskit"],
        "qiskit_aer": versions["qiskit_aer"],
        "shots": shots,
    }
    if qasm_input_sha256 is not None:
        settings["qasm_input_sha256"] = qasm_input_sha256
    return {
        "schema_id": "qcoder.current_loop.strict_result_manifest.v3",
        "schema_version": 3,
        "manifestation": "exact_result",
        "counts": dict(sorted(counts.items())),
        "requested_shots": shots,
        "observed_shots": shots,
        "circuit_lineage": {"status": circuit_lineage_status},
        "source_lineage": {"status": "not_supplied"},
        "execution_configuration": {
            "status": "exact",
            "reference": "prepared-workspace-qiskit-aer",
            "settings": settings,
        },
        "execution_method": {
            "kind": "sampled_shots",
            "interface": "qiskit_backend_run",
            "backend_or_sampler": backend,
        },
        "execution_observation": {
            "status": "client_reported_completed",
            "external_execution_attempt_count": 1,
            "dependency_installation_performed": False,
            "environment_mutated": False,
            "qcoder_independently_verified_execution": False,
        },
        "execution_attempt_id": attempt_id,
        "producer_provenance": {
            "kind": "native_client_external_execution",
            "method": "qiskit_aer_backend_run",
            "identity": f"qiskit-aer-{versions['qiskit_aer']}",
        },
        "capture_provenance": {
            "kind": "native_client_execution_capture",
            "method": "backend_result_get_counts_to_exact_manifest",
            "identity": "prepared-workspace-sampler-helper-v1",
        },
        "bit_register_ordering": {
            "status": "known",
            "convention": "qiskit_little_endian",
            "endianness": "little",
            "bit_order": ["c[1]", "c[0]"],
            "register_order": ["c"],
        },
        "warnings": [],
        "explicit_missingness": (
            ["circuit_lineage", "source_lineage", "provider_job_identity"]
            if circuit_lineage_status == "unknown"
            else ["provider_job_identity", "host_environment_beyond_pins"]
        ),
        "limitations": (
            ["The exact producing circuit is unknown and is not inferred."]
            if circuit_lineage_status == "unknown"
            else ["Execution completion and provenance are reported by the native client."]
        ),
        "non_claims": [
            "qCoder did not execute customer code.",
            "qCoder did not independently verify that the external execution occurred.",
            "No QPU or provider submission is claimed.",
        ],
        "raw_terminal_or_chat_evidence_used": False,
        "workspace_or_filename_lineage_inferred": False,
    }


def preflight(identity_path: Path, unknown_result_path: Path) -> None:
    from qiskit import QuantumCircuit

    versions = _versions()
    circuit = QuantumCircuit(2, 2)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.measure([0, 1], [0, 1])
    counts, backend = _sample(circuit, shots=32)
    if not set(counts).issubset({"00", "11"}):
        raise SystemExit("Prepared Bell sampler preflight produced an unexpected outcome.")
    identity = {
        "schema_id": "qcoder.wi0435.prepared_external_runtime.v1",
        "versions": versions,
        "backend_or_sampler": backend,
        "interface": "qiskit_backend_run",
        "preflight": {
            "status": "pass",
            "external_execution_count": 1,
            "shots": 32,
            "outcome_labels": sorted(counts),
            "counts_digest": sha256(canonical_bytes(counts)).hexdigest(),
        },
        "natural_campaign_execution_count": 0,
        "dependency_installation_during_natural_campaign_permitted": False,
        "environment_mutation_during_natural_campaign_permitted": False,
        "qcoder_executed_preflight": False,
    }
    identity_path.write_bytes(canonical_bytes(identity) + b"\n")
    os.chmod(identity_path, stat.S_IRUSR | stat.S_IWUSR)
    unknown_manifest = _manifest(
        counts=counts,
        shots=32,
        attempt_id="prepared-runtime-preflight-unknown-lineage-v4",
        versions=versions,
        backend=backend,
        circuit_lineage_status="unknown",
        qasm_input_sha256=None,
    )
    unknown_result_path.write_bytes(canonical_bytes(unknown_manifest) + b"\n")
    os.chmod(unknown_result_path, stat.S_IRUSR | stat.S_IWUSR)


def run(qasm_path: Path, result_path: Path, *, shots: int, attempt_id: str) -> None:
    if shots < 1 or not attempt_id or len(attempt_id.encode("utf-8")) > 1_024:
        raise SystemExit("Bounded execution arguments are invalid.")
    qasm_path = qasm_path.absolute()
    result_path = result_path.absolute()
    if not qasm_path.is_file() or qasm_path.is_symlink():
        raise SystemExit("The exact QASM input is unavailable.")
    if result_path.exists() or result_path.is_symlink():
        raise SystemExit("The exact result target already exists; no execution occurred.")
    versions = _versions()
    circuit = _bell_from_qasm(qasm_path)
    counts, backend = _sample(circuit, shots=shots)
    manifest = _manifest(
        counts=counts,
        shots=shots,
        attempt_id=attempt_id,
        versions=versions,
        backend=backend,
        circuit_lineage_status="current_step_contract",
        qasm_input_sha256=sha256(qasm_path.read_bytes()).hexdigest(),
    )
    result_path.write_bytes(canonical_bytes(manifest) + b"\n")
    os.chmod(result_path, stat.S_IRUSR | stat.S_IWUSR)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)
    check = subparsers.add_parser("preflight")
    check.add_argument("--identity", type=Path, required=True)
    check.add_argument("--unknown-result", type=Path, required=True)
    execute = subparsers.add_parser("run")
    execute.add_argument("--qasm", type=Path, required=True)
    execute.add_argument("--result", type=Path, required=True)
    execute.add_argument("--shots", type=int, required=True)
    execute.add_argument("--attempt-id", required=True)
    args = parser.parse_args()
    if args.operation == "preflight":
        preflight(args.identity.absolute(), args.unknown_result.absolute())
        return
    run(args.qasm, args.result, shots=args.shots, attempt_id=args.attempt_id)


if __name__ == "__main__":
    main()
