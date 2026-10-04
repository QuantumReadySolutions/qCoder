"""Client correction proof uses only temporary files and synthetic operations."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

CLIENT = Path(__file__).resolve().parents[1]/'client'
if not CLIENT.exists():
    CLIENT = Path(__file__).resolve().parents[2]/'conference/d148-client'
spec = importlib.util.spec_from_file_location('client_setup', CLIENT/'setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
r = setup.runtime


@pytest.fixture
def installed(tmp_path, monkeypatch):
    base = tmp_path/'successor'
    root = base/'client-v4'
    workspace = base/'carbon-canonical-v4'
    root.mkdir(parents=True)
    workspace.mkdir()
    (workspace/'scientific-sentinel').write_text('must never be read or changed by setup')
    monkeypatch.setattr(r, 'BASE', base)
    monkeypatch.setattr(r, 'ROOT', root)
    monkeypatch.setattr(r, 'WORKSPACE', workspace)
    monkeypatch.setattr(r, 'PYTHON', Path(sys.executable))
    monkeypatch.setattr(r, 'CONFIG_HOME', tmp_path/'home')
    monkeypatch.setattr(r, 'ENTERPRISE', tmp_path/'enterprise')
    monkeypatch.setattr(r, 'host_id', lambda: 'fixture-host')
    monkeypatch.chdir(root)
    # Test the installer with a tiny identity-covered installed-package fixture.
    payload = tmp_path/'payload'
    payload.mkdir()
    for p in CLIENT.iterdir():
        if p.is_file(): (payload/p.name).write_bytes(p.read_bytes())
    package = tmp_path/'site-packages/qcoder'
    package.mkdir(parents=True)
    (package/'__init__.py').write_text('# synthetic identity-covered package\n')
    (payload/'package.json').write_text(json.dumps({'qcoder/__init__.py':r.digest((package/'__init__.py').read_bytes())}))
    monkeypatch.setattr(setup, 'HERE', payload)
    monkeypatch.setattr(r.importlib.metadata, 'distribution', lambda _: SimpleNamespace(version=r.VERSION, locate_file=lambda name: package.parent/name))
    monkeypatch.setattr(r.importlib.metadata, 'version', lambda _:r.VERSION)
    manifest = {p.name:r.digest(p.read_bytes()) for p in payload.iterdir() if p.is_file() and p.name != 'payload.json'}
    (payload/'payload.json').write_text(json.dumps(manifest))
    # A real legacy D148 binding is replaced, not appended.
    (root/'.cursor/rules').mkdir(parents=True)
    (root/'.cursor/rules/old.mdc').write_text('D-148 legacy binding\n')
    (root/'qcoder-context').write_text('# old wrapper\n')
    before = snapshot(root)
    result = setup.install('fixture-1')
    assert result['active_attachment'] == 'unobserved'
    return root, before


def snapshot(root):
    return {p.relative_to(root).as_posix():(p.read_bytes(),p.stat().st_mode & 0o777)
            for p in root.rglob('*') if p.is_file()}


def event(name='preToolUse', **extra):
    return {'hook_event_name':name, 'workspace_roots':[str(r.ROOT)],
            'cursor_version':'fixture-1', 'conversation_id':'fixture-session',
            'generation_id':'fixture-turn', 'cwd':str(r.ROOT),
            'tool_name':'Shell', 'tool_input':{'command':r.ACTION}, **extra}


def attach():
    ev = event('beforeSubmitPrompt', attachments=[{'type':'rule','file_path':str(r.ROOT/r.RULE)}])
    assert r.decide(ev, 'beforeSubmitPrompt', r.verify())


def test_install_verify_rollback_preserves_scope(installed):
    root, before = installed
    preserved = snapshot(r.WORKSPACE)
    receipt = r.verify()
    assert Path(receipt['backup']).parent == r.BASE/'client-binding-backups'
    assert not (root/'.cursor/rules/old.mdc').exists()
    assert setup.verify()['active_attachment'] == 'unobserved'
    setup.rollback()
    assert snapshot(root) == before
    assert snapshot(r.WORKSPACE) == preserved


@pytest.mark.parametrize('change',['wrong_root','launcher_missing','rule_stale','extra_rule','inherited_rule','host','python','package','symlink'])
def test_binding_refuses_without_discovery(installed, monkeypatch, change):
    root,_ = installed
    if change == 'wrong_root': monkeypatch.chdir(root.parent)
    if change == 'launcher_missing': (root/'qcoder-context').unlink()
    if change == 'rule_stale': (root/r.RULE).write_text('D148 stale')
    if change == 'extra_rule': (root/'.cursor/rules/conflict.mdc').write_text('conflict')
    if change == 'inherited_rule': (root.parent/'AGENTS.md').write_text('conflict')
    if change == 'host': monkeypatch.setattr(r,'host_id',lambda:'other-host')
    if change == 'python': monkeypatch.setattr(r,'PYTHON',Path('/wrong/python'))
    if change == 'package':
        p = Path(r.importlib.metadata.distribution('qcoder').locate_file('qcoder/__init__.py'))
        p.write_text('tampered')
    if change == 'symlink':
        (root/'qcoder-context').unlink()
        (root/'qcoder-context').symlink_to('/never-follow-this')
    with pytest.raises((r.Refused,OSError,KeyError)): r.verify()


def test_exact_action_needs_active_attachment(installed):
    with pytest.raises(OSError): r.decide(event(), 'preToolUse', r.verify())
    attach()
    assert r.decide(event(), 'preToolUse', r.verify())
    assert r.decide(event(tool_input={'command':r.ACTION,'cwd':str(r.ROOT),'timeout':120000}), 'preToolUse', r.verify())
    assert r.decide(event('beforeShellExecution',command=r.ACTION), 'beforeShellExecution',r.verify())
    with pytest.raises(r.Refused):
        r.decide(event(generation_id='new-turn'), 'preToolUse',r.verify())


@pytest.mark.parametrize('command', ['pwd','ls','which python','python -m qcoder','cat /private/SECRET',
 './qcoder-context x','./qcoder-context; pwd','./qcoder-context && pwd','./qcoder-context\npwd',
 '$(pwd)/qcoder-context','env ./qcoder-context','./qcoder-context | cat','./qcoder-context > out',
 '(./qcoder-context)',' ./qcoder-context','./qcoder-context &','./qcoder-context || true',
 'bash ./qcoder-context','/different/qcoder-context','./qcoder-context\x00'])
def test_shell_variants_denied(installed,command):
    attach()
    assert not r.decide(event(tool_input={'command':command}),'preToolUse',r.verify())
    assert not r.decide(event('beforeShellExecution',command=command),'beforeShellExecution',r.verify())


@pytest.mark.parametrize('tool',['Read','Grep','Glob','LS','SemanticSearch','Task','Write','Delete','WebFetch','MCP:any','unknown'])
def test_every_other_tool_is_denied(installed,tool):
    attach()
    assert not r.decide(event(tool_name=tool, tool_input={'path':'/private/SECRET'}),'preToolUse',r.verify())


@pytest.mark.parametrize('name',['beforeReadFile','beforeMCPExecution','subagentStart','beforeTabFileRead'])
def test_secondary_controls_deny(installed,name):
    attach()
    assert not r.decide(event(name),name,r.verify())


@pytest.mark.parametrize('overrides',[{'workspace_roots':[]},{'workspace_roots':['/wrong']},
 {'workspace_roots':['/one','/two']},{'cursor_version':'new-version'},
 {'tool_input':{'command':r.ACTION,'working_directory':'/wrong'}},
 {'tool_input':{'command':r.ACTION,'cwd':'/wrong'}},
 {'tool_input':{'command':r.ACTION,'executable':'/arbitrary/python'}},
 {'tool_input':{'command':r.ACTION,'environment':{}}}])
def test_unverified_event_refuses(installed,overrides):
    attach()
    with pytest.raises(r.Refused): r.decide(event(**overrides),'preToolUse',r.verify())


@pytest.mark.parametrize('attachments',[[],[{'type':'file','file_path':'/private/SECRET'}],
 [{'type':'rule','file_path':'/wrong'}]])
def test_disk_rule_never_proves_attachment(installed,attachments):
    with pytest.raises(r.Refused):
        r.decide(event('beforeSubmitPrompt',attachments=attachments),'beforeSubmitPrompt',r.verify())


@pytest.mark.parametrize('raw',[b'{', b'null',b'[]',b'"SECRET"',b'{}',b'x'*65537])
def test_real_guard_malformed_and_missing_binding_are_safe(tmp_path,raw):
    result=subprocess.run([sys.executable,'-I','-B',str(CLIENT/'runtime.py'),'hook','preToolUse'],
                          cwd=tmp_path,input=raw,capture_output=True)
    assert json.loads(result.stdout)['permission']=='deny'
    assert b'SECRET' not in result.stdout and b'/home/' not in result.stdout
    assert not result.stderr


def test_guard_internal_timeout(tmp_path):
    process=subprocess.Popen([sys.executable,'-I','-B',str(CLIENT/'runtime.py'),'hook','preToolUse'],
                             cwd=tmp_path,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    # Keep stdin open: internal alarm must deny before native outer timeout.
    process.wait(timeout=5)
    assert json.loads(process.stdout.read())['permission']=='deny'
    process.stdin.close()
    assert not process.stderr.read()


def test_launcher_arguments_and_wrong_root(tmp_path):
    for arguments in ([],['--workspace','/private/SECRET'],[';pwd']):
        result=subprocess.run(['/bin/sh',str(CLIENT/'qcoder-context'),*arguments],cwd=tmp_path,capture_output=True)
        assert result.returncode==2 and b'/private' not in result.stdout


def test_context_uses_only_fixed_operation(installed,monkeypatch,capsys):
    calls=[]
    value={'schema':'d148.client_context.v1','status':'verified','new_scientific_jobs':0,
           'approval_created':False,'plan_mutated':False,'science_state':'completed'}
    value['digest']=r.digest(json.dumps(value,sort_keys=True,separators=(',',':')).encode())
    def run(args,**kw):
        calls.append((args,kw))
        return SimpleNamespace(returncode=0,stdout=json.dumps(value).encode(),stderr=b'PRIVATE')
    monkeypatch.setattr(r.subprocess,'run',run)
    before=snapshot(r.WORKSPACE)
    assert r.context()==0
    assert json.loads(capsys.readouterr().out)==value
    assert calls[0][0]==[str(r.PYTHON),'-I','-B','-m','qcoder.ml_research.client_context','--workspace',str(r.WORKSPACE)]
    assert not calls[0][1].get('shell')
    assert snapshot(r.WORKSPACE)==before


def test_rollback_preserves_later_legitimate_edit(installed):
    (r.ROOT/r.RULE).write_text('later legitimate edit')
    with pytest.raises(r.Refused): setup.rollback()
    assert (r.ROOT/r.RULE).read_text()=='later legitimate edit'


def test_configuration_has_no_partial_matchers():
    config=json.loads((CLIENT/'hooks.json').read_text())
    assert set(config['hooks'])==set(r.EVENTS)
    for event_name, definitions in config['hooks'].items():
        assert definitions==[{'command':'.d148/guard '+event_name,'timeout':5,'failClosed':True}]


def test_duplicate_fields_are_not_repaired():
    with pytest.raises(r.Refused):r.parse('{"tool_input":{"command":"pwd","command":"./qcoder-context"}}')


@pytest.mark.parametrize('text',['unrelated rule','D-147 fallback rule','D148 plus D147 mixed'])
def test_install_conflicts_do_not_change_files(installed,text):
    setup.rollback()
    (r.ROOT/'.cursor/rules/extra.mdc').write_text(text)
    before=snapshot(r.ROOT)
    with pytest.raises(r.Refused):setup.install('fixture-1')
    assert snapshot(r.ROOT)==before


def test_failed_install_restores_old_binding(installed,monkeypatch):
    setup.rollback()
    before=snapshot(r.ROOT)
    def failure(*a,**k):raise r.Refused()
    monkeypatch.setattr(r,'verify',failure)
    with pytest.raises(r.Refused):setup.install('fixture-1')
    assert snapshot(r.ROOT)==before


def test_unavailable_context_does_not_fall_back(installed,monkeypatch,capsys):
    calls=[]
    def fail(*a,**k):
        calls.append(a)
        raise subprocess.TimeoutExpired('/private/SECRET',90)
    monkeypatch.setattr(r.subprocess,'run',fail)
    assert r.context()==2
    text=capsys.readouterr().out
    assert json.loads(text)['status']=='unavailable'
    assert '/private' not in text and 'SECRET' not in text
    assert len(calls)==1


def test_generated_control_fixture_uses_real_guard_only(tmp_path):
    created=subprocess.run([sys.executable,'-I','-B',str(CLIENT/'control_fixture.py'),
                           '--cursor-version','fixture-1'],capture_output=True,text=True,check=True)
    root=Path(json.loads(created.stdout)['fixture_root'])
    base={'conversation_id':'fixture-session','generation_id':'fixture-turn',
          'cursor_version':'fixture-1','workspace_roots':[str(root)],'cwd':str(root)}
    def hook(name,**extra):
        ev={**base,'hook_event_name':name,**extra}
        p=subprocess.run([str(root/'.d148/guard'),name],cwd=root,input=json.dumps(ev),capture_output=True,text=True)
        assert p.returncode==0,p.stderr
        return json.loads(p.stdout)
    assert hook('beforeSubmitPrompt',attachments=[{'type':'rule','file_path':str(root/r.RULE)}])['continue']
    assert hook('preToolUse',tool_name='Shell',tool_input={'command':'./qcoder-context'})['permission']=='allow'
    assert hook('beforeShellExecution',command='./qcoder-context')['permission']=='allow'
    assert hook('preToolUse',tool_name='Read',tool_input={'path':str(root/'fixture-private.txt')})['permission']=='deny'
    assert hook('preToolUse',tool_name='Task',tool_input={})['permission']=='deny'
    assert hook('beforeShellExecution',command='cat fixture-private.txt')['permission']=='deny'
    assert subprocess.check_output([str(root/'qcoder-context')],cwd=root).strip()==b'D148_SYNTHETIC_CONTEXT_ONLY'


def test_real_client_rejects_synthetic_instruction_observation(installed):
    receipt=r.verify()
    receipt['cursor_version']='3.23.12'
    (r.ROOT/'.d148/instruction-observation.json').write_text(json.dumps({
        'basis':'synthetic_component_test'}))
    assert r.SYNTHETIC_FIXTURE is False
    with pytest.raises(r.Refused,match='profile_required'):
        r.instruction_profile(receipt)
