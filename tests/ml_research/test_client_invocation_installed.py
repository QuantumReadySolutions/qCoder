"""Real installed dev8 context subprocess through the external client runtime."""
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest
from test_d148 import prepared
from test_client_context import complete, snapshot, assert_safe
from qcoder.ml_research import tracker

CLIENT=Path(os.environ.get('D148_CLIENT_SOURCE',Path(__file__).resolve().parents[2]/'conference/d148-client'))


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
    monkeypatch.setattr(r,'WORKSPACE',workspace)
    monkeypatch.setattr(r,'PYTHON',Path(sys.executable))
    monkeypatch.setattr(r,'CONFIG_HOME',tmp_path/'fixture-home')
    monkeypatch.setattr(r,'ENTERPRISE',tmp_path/'fixture-enterprise')
    monkeypatch.chdir(root)
    names={'qcoder-context':'qcoder-context','.cursor/hooks.json':'hooks.json',
           r.RULE:'binding.mdc','.d148/package.json':'package.json',
           '.d148/runtime.py':'runtime.py','.d148/guard':'guard'}
    for dest,src in names.items():(root/dest).write_bytes((CLIENT/src).read_bytes())
    (root/'qcoder-context').chmod(0o700)
    (root/'.d148/guard').chmod(0o700)
    receipt={'root':str(root),'workspace':str(workspace),'python':str(r.PYTHON),
             'python_resolved':str(r.PYTHON.resolve()),'python_sha256':r.digest(r.PYTHON.read_bytes()),
             'host_id':r.host_id(),'cursor_version':'test-only',
             'files':{n:r.digest((root/n).read_bytes()) for n in names},
             'instruction_inventory':r.instruction_inventory(root)}
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
