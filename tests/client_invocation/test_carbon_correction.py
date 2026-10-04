"""Synthetic component events, never Carbon observations or canonical science."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

CLIENT = Path(__file__).resolve().parents[2]/'conference/d148-client'
CARBON = '/home/user/projects/qcoder-iqt-2026-ml-successor-v1'
RULE = '.cursor/rules/d148-read-only.mdc'
PROFILE = 'cursor-3.23.12-single-rule-v1'


def create(tmp_path, placement='outside'):
    source = tmp_path/'source'
    shutil.copytree(CLIENT, source)
    # A disposable substitute for Carbon, never either scientific workspace.
    for name in ('runtime.py', 'guard', 'control_fixture.py'):
        p = source/name
        p.write_text(p.read_text().replace(CARBON, str(source)))
    python = (source if placement == 'inside' else tmp_path/'external')/'.venv/bin/python'
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    result = subprocess.run([str(python), '-I', '-B', str(source/'control_fixture.py'),
                             '--cursor-version', '3.23.12'], capture_output=True, text=True, check=True)
    return Path(json.loads(result.stdout)['fixture_root']), python


def event(root, name='beforeSubmitPrompt', **extra):
    return {'hook_event_name': name, 'workspace_roots': [str(root)],
            'cursor_version': '3.23.12', 'conversation_id': 'synthetic-conversation-0000000000000001',
            'generation_id': 'synthetic-generation-00000000000000001',
            'cwd': str(root), 'composer_mode': 'agent', 'session_id': 'synthetic-session',
            'model': 'PRIVATE_MODEL', 'model_id': 'PRIVATE_MODEL_ID',
            'model_params': [{'id':'PRIVATE_PARAM','value':'PRIVATE_VALUE'}],
            'user_email': 'PRIVATE_EMAIL', 'transcript_path': 'PRIVATE_TRANSCRIPT',
            'prompt': '', 'attachments': [{'type':'rule','file_path':'d148-read-only.mdc'}], **extra}


def hook(root, name='beforeSubmitPrompt', **extra):
    p = subprocess.run([str(root/'.d148/guard'), name], cwd=root,
                       input=json.dumps(event(root, name, **extra)), capture_output=True, text=True, timeout=5)
    assert not p.stderr
    return p, json.loads(p.stdout)


def synthetic_observation(root):
    # Explicit synthetic stand-in for an operator UI observation, only admitted
    # by disposable synthetic fixtures. It does NOT forge an attachment event.
    receipt = json.loads((root/'.d148/installed.json').read_text())
    value = {'schema': PROFILE, 'root': str(root), 'cursor_version':'3.23.12',
             'rule_sha256':receipt['files'][RULE], 'basis':'synthetic_component_test',
             'observations': {key:'none_observed' for key in
                ('user_rules','team_rules','enterprise_rules','plugins_and_skills','other_attachments','same_name_sources')}}
    (root/'.d148/instruction-observation.json').write_text(json.dumps(value))


def test_old_carbon_guard_receipt_reconstruction():
    original = (Path(__file__).parent/'fixtures/guard-v1').read_text()
    generated = original.replace(CARBON+'/.venv/bin/python', CARBON+'/.venv/bin/python').replace(
        CARBON, '/tmp/d148-cursor-control-bvbfkxww')
    assert hashlib.sha256(generated.encode()).hexdigest() == '8027eaaa9e18f4515d87bcfec08d522b52b2bdf2f3382bb51a779765f31a4f67'


@pytest.mark.parametrize('placement', ['outside','inside'])
def test_generated_interpreter_and_observed_basename(tmp_path, placement):
    root, python = create(tmp_path, placement)
    synthetic_observation(root)
    receipt = json.loads((root/'.d148/installed.json').read_text())
    assert receipt['python'] == str(python)
    p, value = hook(root)
    assert p.returncode == 0
    assert value['continue'], value
    for name, extra in [('preToolUse',{'tool_name':'Shell','tool_input':{'command':'./qcoder-context'}}),
                        ('beforeShellExecution',{'command':'./qcoder-context'})]:
        assert hook(root, name, **extra)[1]['permission'] == 'allow'
    assert subprocess.check_output([str(root/'qcoder-context')],cwd=root).strip() == b'D148_SYNTHETIC_CONTEXT_ONLY'
    assert not list((root.parent/'carbon-canonical-v4').iterdir())


@pytest.fixture
def generated(tmp_path):
    root, _ = create(tmp_path)
    synthetic_observation(root)
    return root


@pytest.mark.parametrize('attachment', [None, [], {}, 'd148-read-only.mdc',
    [{'type':'rule'}], [{'type':'file','file_path':'d148-read-only.mdc'}],
    [{'type':'rule','file_path':None}], [{'type':'rule','file_path':['d148-read-only.mdc']}],
    [{'type':'rule','file_path':'d148-read-only.mdc','unknown':True}],
    [{'type':'rule','file_path':'./d148-read-only.mdc'}],
    [{'type':'rule','file_path':'.cursor/rules/d148-read-only.mdc'}],
    [{'type':'rule','file_path':'../d148-read-only.mdc'}],
    [{'type':'rule','file_path':'/foreign/.cursor/rules/d148-read-only.mdc'}],
    [{'type':'rule','file_path':'wrong.mdc'}],
    [{'type':'rule','file_path':'d148-read-only.mdc'}]*2,
    [{'type':'rule','file_path':'d148-read-only.mdc'},{'type':'file','file_path':'other'}]])
def test_attachment_negatives_generated_guard(generated, attachment):
    p, value = hook(generated, attachments=attachment)
    assert p.returncode == 0 and value['continue'] is False
    assert '[attachment:' in value['user_message']
    assert not list((generated/'.d148').glob('attachment-*.json'))


@pytest.mark.parametrize('extra', [{'cursor_version':'3.23.13'}, {'workspace_roots':['/foreign']},
    {'conversation_id':''}, {'generation_id':None}, {'generation_id':'bad/id'},
    {'conversation_id':'x'*161}, {'hook_event_name':'preToolUse'}])
def test_common_negatives_generated_guard(generated, extra):
    p = subprocess.run([str(generated/'.d148/guard'),'beforeSubmitPrompt'],cwd=generated,
        input=json.dumps(event(generated,**extra)),capture_output=True,text=True)
    value = json.loads(p.stdout)
    assert value['continue'] is False and '[common:' in value['user_message']


@pytest.mark.parametrize('damage',['rule','guard','runtime','hooks','python_receipt','host_receipt',
    'missing_profile','unknown_profile','plugin_ambiguity','same_name_ambiguity',
    'extra_rule','inherited_same_name','symlink_rule','unknown_profile_field'])
def test_disk_and_profile_negatives(generated, damage):
    root = generated
    files={'rule':RULE,'guard':'.d148/guard','runtime':'.d148/runtime.py','hooks':'.cursor/hooks.json'}
    if damage in files:
        p=root/files[damage]
        p.write_text(p.read_text()+'\n# changed\n')
    elif damage in ('python_receipt','host_receipt'):
        path=root/'.d148/installed.json'
        value=json.loads(path.read_text())
        value['python' if damage=='python_receipt' else 'host_id']='wrong'
        path.write_text(json.dumps(value))
    elif damage=='extra_rule':
        (root/'.cursor/rules/other.mdc').write_text('other')
    elif damage=='inherited_same_name':
        target=root.parent/'.cursor/rules'
        target.mkdir(parents=True)
        (target/'d148-read-only.mdc').write_text('ambiguous')
    elif damage=='symlink_rule':
        (root/RULE).unlink()
        (root/RULE).symlink_to(root/'fixture-private.txt')
    else:
        path=root/'.d148/instruction-observation.json'
        if damage=='missing_profile': path.unlink()
        else:
            value=json.loads(path.read_text())
            if damage=='unknown_profile': value['schema']='unknown'
            if damage=='plugin_ambiguity': value['observations']['plugins_and_skills']='unknown'
            if damage=='same_name_ambiguity': value['observations']['same_name_sources']='present'
            if damage=='unknown_profile_field': value['origin']='forged-absolute'
            path.write_text(json.dumps(value))
    assert hook(root)[1]['continue'] is False


def test_absolute_representation_needs_no_basename_profile(generated):
    (generated/'.d148/instruction-observation.json').unlink()
    assert hook(generated,attachments=[{'type':'rule','file_path':str(generated/RULE)}])[1]['continue']
    bound=json.loads(next((generated/'.d148').glob('attachment-*.json')).read_text())
    assert bound['representation']=='exact_absolute_reported' and bound['profile_digest'] is None


def test_synthetic_event_safe_diagnostics_and_profile_binding(generated):
    assert hook(generated)[1]['continue']
    rows=(generated/'.d148/events.jsonl').read_text()
    assert 'PRIVATE_' not in rows and 'model' not in rows and 'prompt' not in rows
    assert 'bound_identifier_reported' in rows
    # Observation is independently pinned to the conversation/generation.
    p=generated/'.d148/instruction-observation.json'
    p.write_text(p.read_text()+'\n')
    assert hook(generated,'preToolUse',tool_name='Shell',tool_input={'command':'./qcoder-context'})[1]['permission']=='deny'


def test_failed_resubmission_cannot_reuse_attachment(generated):
    assert hook(generated)[1]['continue']
    assert not hook(generated,attachments=[])[1]['continue']
    assert hook(generated,'preToolUse',tool_name='Shell',tool_input={'command':'./qcoder-context'})[1]['permission']=='deny'


@pytest.mark.parametrize('damage', ['missing_runtime','crash_runtime','arguments','stdin_deadline'])
def test_wrapper_failure_and_deadline(generated,damage):
    args=[str(generated/'.d148/guard'),'beforeSubmitPrompt']
    if damage=='missing_runtime': (generated/'.d148/runtime.py').unlink()
    if damage=='crash_runtime': (generated/'.d148/runtime.py').write_text('raise RuntimeError("PRIVATE_ERROR")')
    if damage=='arguments': args.append('PRIVATE_ARGUMENT')
    if damage=='stdin_deadline':
        p=subprocess.Popen(args,cwd=generated,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        p.wait(timeout=5)
        out=p.stdout.read().decode()
        p.stdin.close()
        assert 'input:deadline' in out and not p.stderr.read()
    else:
        p=subprocess.run(args,cwd=generated,input='{}',text=True,capture_output=True)
        out=p.stdout
        assert p.returncode==2 and 'bootstrap:' in out and not p.stderr
    assert 'PRIVATE_' not in out
    value=json.loads(out)
    assert value.get('continue') is False or value.get('permission')=='deny'


def test_preflight_catches_launcher_mismatch(generated):
    spec=importlib.util.spec_from_file_location('fixture_generator', CLIENT/'control_fixture.py')
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.launcher_preflight(generated).startswith('verified_')
    p=generated/'.d148/guard'
    p.write_text(p.read_text().replace(' -I -B ', ' -B '))
    with pytest.raises(ValueError,match='launcher_receipt_mismatch'):
        mod.launcher_preflight(generated)


def test_shell_quoting_of_fixed_interpreter(tmp_path):
    spec=importlib.util.spec_from_file_location('fixture_generator', CLIENT/'control_fixture.py')
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    python=tmp_path/"python space's"
    python.symlink_to(sys.executable)
    original=mod.sys.executable
    try:
        mod.sys.executable=str(python)
        root=Path(mod.create('3.23.12','normal')['fixture_root'])
    finally:
        mod.sys.executable=original
    synthetic_observation(root)
    assert hook(root)[1]['continue']


def test_unknown_ui_observations_and_old_fixtures_cannot_enable_profile(generated):
    root=generated
    (root/'.d148/instruction-observation.json').unlink()
    p=subprocess.run([json.loads((root/'.d148/installed.json').read_text())['python'],'-I','-B',str(root/'.d148/runtime.py'),'observe-instructions'],
                     cwd=root,input='unknown\n'*6,text=True,capture_output=True)
    assert p.returncode==2
    assert not (root/'.d148/instruction-observation.json').exists()
    # Even explicit clean responses cannot reseal v1 or diagnostic fixtures.
    receipt_path=root/'.d148/installed.json'
    receipt=json.loads(receipt_path.read_text())
    receipt['schema']='d148.synthetic_client.v1'
    receipt_path.write_text(json.dumps(receipt))
    p=subprocess.run([json.loads((root/'.d148/installed.json').read_text())['python'],'-I','-B',str(root/'.d148/runtime.py'),'observe-instructions'],
                     cwd=root,input='none_observed\n'*6,text=True,capture_output=True)
    assert p.returncode==2 and not (root/'.d148/instruction-observation.json').exists()


def test_observation_is_not_an_attachment(generated):
    root=generated
    assert not list((root/'.d148').glob('attachment-*.json'))
    assert hook(root,'preToolUse',tool_name='Shell',tool_input={'command':'./qcoder-context'})[1]['permission']=='deny'


def test_missing_attachments_and_duplicate_json_keys(generated):
    value=event(generated)
    del value['attachments']
    raw=json.dumps(value)
    duplicate=json.dumps(event(generated)).replace('"attachments":', '"attachments": [], "attachments":')
    for payload in (raw, duplicate):
        p=subprocess.run([str(generated/'.d148/guard'),'beforeSubmitPrompt'],cwd=generated,
                         input=payload,text=True,capture_output=True)
        assert json.loads(p.stdout)['continue'] is False


def test_operator_observation_records_only_inventory(generated):
    root=generated
    (root/'.d148/instruction-observation.json').unlink()
    python=json.loads((root/'.d148/installed.json').read_text())['python']
    p=subprocess.run([python,'-I','-B',str(root/'.d148/runtime.py'),'observe-instructions'],
                     cwd=root,input='none_observed\n'*6,text=True,capture_output=True)
    assert p.returncode==0,p.stdout
    observed=json.loads((root/'.d148/instruction-observation.json').read_text())
    assert observed['basis']=='operator_client_ui_observation'
    assert not list((root/'.d148').glob('attachment-*.json'))
    assert '"active_attachment": "unobserved"' in p.stdout
    # Even the operator command refuses to overwrite an existing observation.
    again=subprocess.run([python,'-I','-B',str(root/'.d148/runtime.py'),'observe-instructions'],
                         cwd=root,input='none_observed\n'*6,text=True,capture_output=True)
    assert again.returncode==2
