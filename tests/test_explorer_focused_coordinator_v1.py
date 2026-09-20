"""Conference Explorer composition: deterministic negatives and bounded real Aer proof."""

import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest
from qcoder.explorer import focused_loop_coordinator as c
from qcoder.focused_loop import fixtures as fx
from qcoder.focused_loop.canonical import FocusedLoopError, canonical_bytes
from qcoder.executors.aer_stabilizer_v1 import BackendSample, CooperativeCancellation


def workspace(tmp_path, parameters=fx.PRIMARY_FAMILY_PARAMETERS):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "input.qasm").write_text(fx.render_fixture_qasm(parameters))
    return tmp_path


def prepared(tmp_path, parameters=fx.PRIMARY_FAMILY_PARAMETERS):
    workspace(tmp_path, parameters)
    return c.prepare(tmp_path, parameters.fixture_id, "input.qasm")


def digest(s):
    return s["prepared"]["plan"]["plan_digest"]


def fake(request):
    return BackendSample(
        {"0" * 12: 598}, "aer_simulator_stabilizer", "qiskit_aer.AerSimulator.run", c.VERSIONS
    )


def cli(root, *args):
    # Works unchanged when copied into the external installed harness.
    return subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "qcoder",
            "explorer",
            "focused",
            *args,
            "--workspace",
            str(root),
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )


@pytest.mark.parametrize("parameters", [fx.PRIMARY_FAMILY_PARAMETERS, fx.HELDOUT_FAMILY_PARAMETERS])
def test_prepare_general_family(tmp_path, parameters):
    s = prepared(tmp_path, parameters)
    assert s["status"] == "awaiting_authority" and s["dispatch_count"] == 0
    assert s["authority"] is None and s["outcome"] is None
    p = s["prepared"]
    assert p["material"]["chi_required_claim"]["chi_required"] == 32768
    assert (
        p["evaluations"][c.identities.METHOD_MPS_EXACT]["rejection_reason"]
        == "resource_lower_bound_exceeded"
    )
    assert (
        p["evaluations"][c.identities.METHOD_MPS_APPROXIMATE]["rejection_reason"]
        == "exactness_policy_conflict"
    )
    assert all(p["evaluations"]["stabilizer"]["gates"].values())
    assert p["plan"]["settings"]["shots"] == 598
    with pytest.raises(FocusedLoopError, match="already_exists"):
        c.prepare(tmp_path, parameters.fixture_id, "input.qasm")


@pytest.mark.parametrize("confirmation", [None, "", "0" * 64])
def test_confirmation_refuses_without_dispatch(tmp_path, confirmation):
    s = prepared(tmp_path)
    with pytest.raises(FocusedLoopError, match="confirmation_required"):
        c.run(
            tmp_path,
            confirmation,
            _executor_options={"backend_factory": lambda r: pytest.fail("dispatch")},
        )
    assert c.status(tmp_path) == s


def test_stale_circuit_exact_bytes(tmp_path):
    s = prepared(tmp_path)
    (tmp_path / "input.qasm").write_bytes(
        fx.render_fixture_qasm(fx.PRIMARY_FAMILY_PARAMETERS).replace("\n", "\r\n").encode()
    )
    with pytest.raises(FocusedLoopError, match="binding_stale"):
        c.run(tmp_path, digest(s))
    assert c.status(tmp_path)["dispatch_count"] == 0


@pytest.mark.parametrize("mutation", ["digest", "malformed", "resealed_plan", "unknown_field"])
def test_tampered_state(tmp_path, mutation):
    s = prepared(tmp_path)
    path = tmp_path / ".qcoder/focused-loop-v1/session.json"
    if mutation == "digest":
        s["session_digest"] = "0" * 64
    if mutation == "resealed_plan":
        s["prepared"]["plan"]["settings"]["shots"] = 599
        s["session_digest"] = c.digest_excluding(s, field="session_digest")
    if mutation == "unknown_field":
        s["extra"] = True
        s["session_digest"] = c.digest_excluding(s, field="session_digest")
    path.write_text("{" if mutation == "malformed" else json.dumps(s))
    with pytest.raises(FocusedLoopError):
        c.run(tmp_path, digest(s))


def test_completed_fake_join_analysis_repeat(tmp_path):
    s = prepared(tmp_path)
    done = c.run(tmp_path, digest(s), _executor_options={"backend_factory": fake})
    assert done["status"] == "completed", done
    assert done["dispatch_count"] == 1
    assert canonical_bytes(c.status(tmp_path)) == canonical_bytes(done)
    o = done["outcome"]
    assert not o["joined_attempt"]["deviation"]["detected"]
    assert o["receipt"]["result_manifest_digest"] == o["manifest"]["manifest_digest"]
    assert o["receipt"]["plan_match_verified_in_process"] is True
    assert (
        o["manifest"]["execution_observation"]["qcoder_independently_verified_execution"] is False
    )
    assert o["analysis"]["shots_evaluated"] == o["analysis"]["satisfying_shots"] == 598
    assert o["analysis"]["interval"]["lower"] == 0.9950029413057535
    assert o["next_action"]["action"] == "stop_goal_met"
    assert c.repeat(tmp_path)["new_execution_attempts_required"] == 0
    with pytest.raises(FocusedLoopError, match="already_entered"):
        c.run(tmp_path, digest(s))


def test_unknown_crash_never_retries(tmp_path):
    s = prepared(tmp_path)

    def crash(request):
        # The fsynced boundary exists before the backend is reachable.
        persisted = json.loads((tmp_path / ".qcoder/focused-loop-v1/session.json").read_text())
        assert persisted["status"] == c.UNKNOWN
        assert persisted["authority"]["plan_digest"] == digest(s)
        raise SystemExit(99)

    with pytest.raises(SystemExit):
        c.run(tmp_path, digest(s), _executor_options={"backend_factory": crash})
    assert c.status(tmp_path)["status"] == c.UNKNOWN
    assert c.status(tmp_path)["dispatch_count"] is None
    r = cli(tmp_path, "run", "--confirm-plan-digest", digest(s))
    assert r.returncode == 2 and "already_entered" in r.stdout


@pytest.mark.parametrize("failure", ["cancel", "timeout", "backend", "predicate"])
def test_contained_failures_no_more_shots(tmp_path, failure):
    s = prepared(tmp_path)
    options = {"backend_factory": fake}
    if failure == "cancel":
        options["cancellation"] = CooperativeCancellation(requested=True)
    if failure == "timeout":
        options["clock"] = iter([0.0, 61.0]).__next__
    if failure == "backend":

        def broken(r):
            raise RuntimeError("contained")

        options["backend_factory"] = broken
    if failure == "predicate":
        options["backend_factory"] = lambda r: BackendSample(
            {"0" * 11 + "1": 598},
            "aer_simulator_stabilizer",
            "qiskit_aer.AerSimulator.run",
            c.VERSIONS,
        )
    done = c.run(tmp_path, digest(s), _executor_options=options)
    assert done["dispatch_count"] == (0 if failure == "cancel" else 1)
    if failure == "predicate":
        assert done["status"] == "completed"
        assert done["outcome"]["analysis"]["satisfying_shots"] == 0
        assert done["outcome"]["next_action"]["action"] != "continue_sampling"
    else:
        assert done["status"] == "failed"
    with pytest.raises(FocusedLoopError, match="already_entered"):
        c.run(tmp_path, digest(s))


def test_explain_readonly_truthful(tmp_path):
    prepared(tmp_path)
    before = (tmp_path / ".qcoder/focused-loop-v1/session.json").read_bytes()
    texts = {t: c.explain(tmp_path, t)["text"] for t in c.TOPICS}
    assert "declared synthetic 36 GiB" in texts["mps"]
    assert "not a complete Aer peak-memory" in texts["mps"]
    assert "exact_required" in texts["mps"]
    assert "597" in texts["shots"] and "0.9950029413057535" in texts["shots"]
    assert "not state or process fidelity" in texts["result"]
    assert "No remote/QPU/paid" in texts["limits"]
    assert before == (tmp_path / ".qcoder/focused-loop-v1/session.json").read_bytes()
    assert c.status(tmp_path)["dispatch_count"] == 0


def test_no_other_state_access_or_mutation(tmp_path, monkeypatch):
    workspace(tmp_path)
    marker = tmp_path / ".qcoder/current-loop/do-not-read"
    marker.parent.mkdir(parents=True)
    marker.write_text("sentinel")
    opened = []
    # Audit observes actual file opens, including os.open with dir_fd, without routing imports.
    original = os.open

    def guard(path, *args, **kwargs):
        assert "current-loop" not in str(path)
        opened.append(str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", guard)
    s = c.prepare(tmp_path, fx.PRIMARY_FAMILY_PARAMETERS.fixture_id, "input.qasm")
    c.run(tmp_path, digest(s), _executor_options={"backend_factory": fake})
    c.repeat(tmp_path)
    for topic in c.TOPICS:
        c.explain(tmp_path, topic)
    assert marker.read_text() == "sentinel"
    assert not any("current-loop" in p for p in opened)


def test_state_symlink_refused(tmp_path):
    workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".qcoder").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        c.prepare(tmp_path, fx.PRIMARY_FAMILY_PARAMETERS.fixture_id, "input.qasm")
    assert not list(outside.iterdir())


def test_mcp_inventory_unchanged():
    from qcoder.context_bridge_mcp import tool_descriptors
    from qcoder.current_loop_binding_mcp import binding_tool_descriptors

    assert len(tool_descriptors()) == 12
    assert {x["name"] for x in binding_tool_descriptors()} == {
        "begin_current_loop",
        "complete_current_step",
    }


def test_composition_import_boundary():
    source = Path(c.__file__).read_text()
    tree = ast.parse(source)
    imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imports |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert {m for m in imports if m.startswith("qcoder.current_loop")} == {
        "qcoder.current_loop_result_manifest"
    }
    allowed_roots = {
        "__future__",
        "argparse",
        "contextlib",
        "fcntl",
        "hashlib",
        "importlib",
        "json",
        "os",
        "pathlib",
        "stat",
        "time",
        "uuid",
        "sys",
        "qcoder",
    }
    assert {m.split(".")[0] for m in imports} <= allowed_roots
    assert all(
        m.startswith(
            ("qcoder.focused_loop", "qcoder.executors", "qcoder.current_loop_result_manifest")
        )
        for m in imports
        if m.startswith("qcoder.")
    )
    assert ".qcoder/current-loop" not in source
    p = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import sys; import qcoder.explorer.focused_loop_coordinator; print([m for m in sys.modules if m.startswith('qcoder.current_loop')])",
        ],
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0
    assert p.stdout.strip() == "['qcoder.current_loop_result_manifest']"


def test_student_alias_has_no_focused_command(tmp_path):
    p = subprocess.run(
        [sys.executable, "-B", "-m", "qcoder", "student", "focused", "--help"],
        capture_output=True,
        text=True,
    )
    assert p.returncode != 0


def test_real_aer_canonical_separate_process_repeat(tmp_path, monkeypatch):
    s = prepared(tmp_path)
    source = {
        str(p): sha256(p.read_bytes()).hexdigest()
        for root in (Path(fx.__file__).parent, Path(c.__file__).parent)
        for p in root.glob("*.py")
    }
    environment = dict(os.environ)
    qasm = (tmp_path / "input.qasm").read_bytes()

    def deny(*args, **kwargs):
        raise AssertionError("network forbidden")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    done = c.run(tmp_path, digest(s))
    assert done["status"] == "completed", done
    assert done["dispatch_count"] == 1
    assert done["outcome"]["analysis"]["satisfying_shots"] == 598
    before = (tmp_path / ".qcoder/focused-loop-v1/session.json").read_bytes()
    p = cli(tmp_path, "repeat")
    assert p.returncode == 0, p.stderr + p.stdout
    reused = json.loads(p.stdout)
    assert (
        reused["action"] == "reuse_existing_result"
        and reused["new_execution_attempts_required"] == 0
    )
    assert reused["dispatch_count"] == 1
    assert before == (tmp_path / ".qcoder/focused-loop-v1/session.json").read_bytes()
    assert qasm == (tmp_path / "input.qasm").read_bytes()
    assert dict(os.environ) == environment
    assert source == {path: sha256(Path(path).read_bytes()).hexdigest() for path in source}


def test_runtime_drift_refuses_before_authority(tmp_path, monkeypatch):
    s = prepared(tmp_path)
    monkeypatch.setattr(c, "version", lambda name: "wrong")
    with pytest.raises(FocusedLoopError, match="runtime_unqualified"):
        c.run(tmp_path, digest(s))
    assert c.status(tmp_path) == s


def test_process_death_durable_boundary_and_lock_release(tmp_path):
    s = prepared(tmp_path)
    script = """import os, sys
from qcoder.explorer import focused_loop_coordinator as c
def crash(request): os._exit(91)
c.run(sys.argv[1],sys.argv[2],_executor_options={'backend_factory':crash})
"""
    proc = subprocess.run(
        [sys.executable, "-B", "-c", script, str(tmp_path), digest(s)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 91, proc.stderr
    r = cli(tmp_path, "status")
    assert r.returncode == 0
    assert json.loads(r.stdout)["status"] == c.UNKNOWN
    r = cli(tmp_path, "run", "--confirm-plan-digest", digest(s))
    assert r.returncode == 2 and "already_entered" in r.stdout


def test_concurrent_run_is_excluded(tmp_path):
    s = prepared(tmp_path)
    # Hold the exact same process lock while a separate CLI process requests execution.
    with c._store(tmp_path, exclusive=True):
        r = cli(tmp_path, "run", "--confirm-plan-digest", digest(s))
        assert r.returncode == 2 and "focused_session_busy" in r.stdout
    assert c.status(tmp_path) == s


def test_json_missing_argument_refusal(tmp_path):
    p = subprocess.run(
        [sys.executable, "-B", "-m", "qcoder", "explorer", "focused", "prepare", "--json"],
        capture_output=True,
        text=True,
    )
    assert p.returncode == 2 and json.loads(p.stdout)["category"] == "focused_arguments_invalid"


def test_equivalent_repeat_checks_current_bytes(tmp_path):
    s = prepared(tmp_path)
    c.run(tmp_path, digest(s), _executor_options={"backend_factory": fake})
    (tmp_path / "input.qasm").write_text("changed")
    with pytest.raises(FocusedLoopError, match="binding_stale"):
        c.repeat(tmp_path)
    assert c.status(tmp_path)["dispatch_count"] == 1
