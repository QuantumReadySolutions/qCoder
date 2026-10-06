"""Real installed dev8 context subprocess through the external client runtime."""
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest
from test_d148 import prepared as prepared_fixture
from test_client_context import complete, snapshot, assert_safe
from qcoder.ml_research import tracker

CLIENT=Path(os.environ.get('D148_CLIENT_SOURCE',Path(__file__).resolve().parents[2]/'conference/d148-client'))


@pytest.fixture
def prepared(tmp_path):
    workspace = tmp_path/'carbon-canonical-v4'
    workspace.mkdir()
    return prepared_fixture.__wrapped__(workspace)


@pytest.mark.parametrize('state',['prepared','completed'])
def test_external_runtime_real_installed_context(prepared,monkeypatch,capsys,tmp_path,state):
    workspace,plan=prepared
    if state=='completed':
        complete(workspace,plan)
        tracker.deliver(workspace)
    spec=importlib.util.spec_from_file_location('external_runtime',CLIENT/'runtime.py')
    r=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    root=tmp_path/'dedicated-client'
    (root/'.cursor/rules').mkdir(parents=True)
    (root/'.d148').mkdir()
    monkeypatch.setattr(r,'ROOT',root)
    monkeypatch.setattr(r,'BASE',root.parent)
    monkeypatch.setattr(r,'WORKSPACE',workspace)
    monkeypatch.setattr(r,'PYTHON',Path(sys.executable))
    monkeypatch.setattr(r,'CONFIG_HOME',tmp_path/'fixture-home')
    monkeypatch.setattr(r,'ENTERPRISE',tmp_path/'fixture-enterprise')
    monkeypatch.chdir(root)
    names={'qcoder-context':'qcoder-context','.cursor/hooks.json':'hooks.json',
           r.RULE:'binding.mdc','.d148/package.json':'package.json',
           '.d148/runtime.py':'runtime.py','.d148/guard':'guard',
           '.cursorignore':'cursorignore'}
    for dest,src in names.items():(root/dest).write_bytes((CLIENT/src).read_bytes())
    (root/'qcoder-context').chmod(0o700)
    (root/'.d148/guard').chmod(0o700)
    receipt={'root':str(root),'workspace':str(workspace),'python':str(r.PYTHON),
             'python_resolved':str(r.PYTHON.resolve()),'python_sha256':r.digest(r.PYTHON.read_bytes()),
             'host_id':r.host_id(),'schema':'d148.client_binding.v5',
             'files':{n:r.digest((root/n).read_bytes()) for n in names}}
    (root/'.d148/installed.json').write_text(json.dumps(receipt))
    # Client folder has its own operational audit; snapshot scientific files
    # separately so that only actual research/tracker mutations would fail.
    before={k:v for k,v in snapshot(workspace).items() if not k.startswith('dedicated-client/')}
    assert r.context()==0
    value=json.loads(capsys.readouterr().out)
    assert_safe(value,workspace)
    assert value['lifecycle_state']==('completed_delivered_verified_readback' if state=='completed' else 'prepared_awaiting_user_authority')
    if state=='completed':
        assert value['science_state']=='completed' and value['readback_verified']
        assert 'pending' not in json.dumps(value)
        assert value['qcoder_established']['result_digest']
    assert {k:v for k,v in snapshot(workspace).items() if not k.startswith('dedicated-client/')}==before
    audit=json.loads((root/'.d148/events.jsonl').read_text())
    assert audit['context_ns']>0 and audit['new_scientific_jobs']==0

    # Full fresh successor lifecycle uses the same synthetic state through the
    # unchanged installed dev8. Carbon pins stay unchanged in the actual source;
    # this disposable payload pins this test's already-completed IDs instead.
    if state == 'completed':
        import shutil
        payload = tmp_path/'client-payload'
        shutil.copytree(CLIENT, payload)
        expected = json.loads((payload/'carbon-context.json').read_text())
        expected['identities'] = {key: value['qcoder_established'][key] for key in expected['identities']}
        (payload/'carbon-context.json').write_text(json.dumps(expected))
        manifest = {n:r.digest((payload/n).read_bytes()) for n in (
            'runtime.py', 'setup.py', 'guard', 'qcoder-context', 'binding.mdc', 'hooks.json',
            'cursorignore', 'package.json', 'control_fixture.py', 'CARBON-INSTALL.txt',
            'acceptance-template.json', 'carbon-context.json')}
        (payload/'payload.json').write_text(json.dumps(manifest))
        sums = {**manifest, 'payload.json': r.digest((payload/'payload.json').read_bytes())}
        (payload/'SHA256SUMS').write_text(''.join(sha+'  '+name+'\n' for name,sha in sorted(sums.items())))
        spec = importlib.util.spec_from_file_location('installed_successor_setup', payload/'setup.py')
        operator = importlib.util.module_from_spec(spec); spec.loader.exec_module(operator)
        live = operator.runtime
        monkeypatch.setattr(live, 'BASE', tmp_path)
        monkeypatch.setattr(live, 'ROOT', tmp_path/'client-v5')
        monkeypatch.setattr(live, 'WORKSPACE', workspace)
        monkeypatch.setattr(live, 'PYTHON', Path(sys.executable))
        monkeypatch.chdir(tmp_path)
        old = tmp_path/'client-v4'
        old.mkdir(); (old/'historical.txt').write_text('historical client-v4')
        preserved_old = snapshot(old)
        before = snapshot(workspace)
        assert operator.install()['disk_binding'] == 'verified'
        monkeypatch.chdir(live.ROOT)
        direct = live.subprocess.run([str(live.ROOT/'qcoder-context')], cwd=live.ROOT,
            capture_output=True, timeout=90)
        assert direct.returncode == 0 and not direct.stderr
        projected = json.loads(direct.stdout)
        def scientific_view(projection):
            v = json.loads(json.dumps(projection))
            v.pop('digest')
            for key in ('readback_digest', 'readback_verified_at'):
                v['qcoder_established'].pop(key)
            return v
        # Every context call performs a fresh MLflow read; only the read-back
        # attestation digest/time changes, never scientific content/identities.
        assert scientific_view(projected) == scientific_view(value)
        assert operator.doctor_real()['completed_context']['job_id'] == value['qcoder_established']['job_id']
        report = operator.doctor()
        assert report['status'] == 'D148_CARBON_READY_FOR_CURSOR'
        assert report['completed_context']['result_digest'] == value['qcoder_established']['result_digest']
        normal = Path(json.loads((payload/'carbon-doctor.json').read_text())['fixture_root'])
        assert not list((normal/'.d148').glob('attachment-*.json'))
        assert not list((normal.parent/'carbon-canonical-v4').iterdir())
        assert snapshot(workspace) == before
        standalone = tmp_path/'standalone-doctor'
        shutil.copytree(payload, standalone)
        generator = operator.module('proof_generator', payload/'control_fixture.py')
        (standalone/'runtime.py').write_text(generator.render_runtime(tmp_path, Path(sys.executable)))
        manifest = {name: r.digest((standalone/name).read_bytes()) for name in manifest}
        (standalone/'payload.json').write_text(json.dumps(manifest))
        sums = {**manifest, 'payload.json': r.digest((standalone/'payload.json').read_bytes())}
        (standalone/'SHA256SUMS').write_text(''.join(sha+'  '+name+'\n' for name,sha in sorted(sums.items())))
        # The actual operator command, in its configured test-owned environment.
        command = [sys.executable, '-I', '-B', str(standalone/'setup.py'), 'doctor']
        command_result = live.subprocess.run(command, cwd=standalone, capture_output=True, timeout=90)
        assert command_result.returncode == 0 and not command_result.stderr
        command_value = json.loads(command_result.stdout)
        assert command_value['status'] == 'D148_CARBON_READY_FOR_CURSOR'
        assert str(workspace).encode() not in command_result.stdout
        assert str(tmp_path).encode() not in command_result.stdout
        assert command_value['completed_context']['job_id'] == expected['identities']['job_id']
        assert snapshot(workspace) == before
        if os.environ.get('D148_PROOF_EVIDENCE'):
            proof = {'scope': 'fresh_installed_dev8_synthetic_completed_context_not_Carbon',
                'doctor_command': command, 'doctor_result': command_value,
                'direct_successor_scientific_projection_identical': True,
                'volatile_readback_fields': ['digest', 'readback_digest', 'readback_verified_at'],
                'science_files_before': before, 'science_files_after': snapshot(workspace),
                'client_v4_before': preserved_old, 'client_v4_after': snapshot(old),
                'new_canonical_science': 0, 'approval_created_by_context': False, 'plan_mutated_by_context': False}
            Path(os.environ['D148_PROOF_EVIDENCE']).write_text(json.dumps(proof, indent=2)+'\n')
        (live.ROOT/'unrelated.txt').write_text('keep this unrelated material')
        assert operator.remove()['removed_managed_binding']
        assert (live.ROOT/'unrelated.txt').read_text() == 'keep this unrelated material'
        assert snapshot(old) == preserved_old
        assert snapshot(workspace) == before
