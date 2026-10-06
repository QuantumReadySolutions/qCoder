"""V5 contract evolution, generated guards, bounded diagnostics and noninterference."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_client_invocation import installed, setup, r, snapshot

CLIENT = Path(__file__).resolve().parents[2]/'conference/d148-client'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def create():
    mod = module('fixture_v5', CLIENT/'control_fixture.py')
    return Path(mod.create('older-synthetic-token', 'normal')['fixture_root'])


@pytest.fixture
def generated():
    return create()


def event(root, name='beforeSubmitPrompt', **extra):
    return {'hook_event_name': name, 'workspace_roots': [str(root)],
            'cursor_version': '3.23.23', 'conversation_id': 'conversation-v5',
            'generation_id': 'generation-v5', 'cwd': str(root),
            'attachments': [{'type': 'rule', 'file_path': 'd148-read-only.mdc'}],
            'model': 'PRIVATE_MODEL', 'prompt': 'PRIVATE_PROMPT',
            'user_email': 'PRIVATE_EMAIL', 'transcript_path': '/PRIVATE_TRANSCRIPT',
            'future_event_metadata': {'opaque': 'PRIVATE_VALUE'}, **extra}


def hook(root, name='beforeSubmitPrompt', **extra):
    result = subprocess.run([str(root/'.d148/guard'), name], cwd=root,
        input=json.dumps(event(root, name, **extra)), text=True, capture_output=True, timeout=5)
    assert result.returncode == 0 and not result.stderr
    return json.loads(result.stdout)


def action(root, **extra):
    return hook(root, 'preToolUse', tool_name='Shell', tool_input={'command': './qcoder-context'}, **extra)


def diagnose(root):
    result = subprocess.run([sys.executable, '-I', '-B', str(CLIENT/'setup.py'),
        'diagnose', '--root', str(root)], cwd=root, text=True, capture_output=True, timeout=5)
    assert not result.stderr
    assert 'PRIVATE' not in result.stdout and str(root) not in result.stdout
    return result, json.loads(result.stdout)


@pytest.mark.parametrize('version', ['3.23.12', '3.23.23', '3.24.0', '2026.08.11-e8db854', 'v4.0+future'])
@pytest.mark.parametrize('representation', ['absolute', 'project_relative', 'basename'])
def test_versions_shapes_and_metadata_evolve(generated, version, representation):
    root = generated
    forms = {'absolute': str(root/r.RULE), 'project_relative': r.RULE, 'basename': 'd148-read-only.mdc'}
    assert not list((root/'.d148').glob('attachment-*.json'))
    attachments = [{'type': 'file', 'file_path': 'PRIVATE_UNRELATED_FILE'},
                   {'type': 'rule', 'file_path': forms[representation], 'future': {'secret': 'PRIVATE_META'}},
                   {'type': 'rule', 'file_path': 'PRIVATE_UNRELATED_RULE'}]
    assert hook(root, cursor_version=version, attachments=attachments)['continue']
    bound = json.loads(next((root/'.d148').glob('attachment-*.json')).read_text())
    assert bound == {'conversation': 'conversation-v5', 'generation': 'generation-v5',
        'rule_hash': json.loads((root/'.d148/installed.json').read_text())['files'][r.RULE],
        'cursor_version': version, 'representation': representation}
    assert action(root, cursor_version=version)['permission'] == 'allow'
    assert hook(root, 'beforeShellExecution', cursor_version=version, command='./qcoder-context')['permission'] == 'allow'
    assert action(root, cursor_version='different-patch')['permission'] == 'deny'
    assert subprocess.check_output([str(root/'qcoder-context')], cwd=root).strip() == b'D148_SYNTHETIC_CONTEXT_ONLY'
    _, report = diagnose(root)
    submit = next(row for row in report['recent'] if row.get('decision') == 'allow' and row.get('event') == 'beforeSubmitPrompt')
    assert submit['qcoder_representation'] == representation
    assert submit['attachment_count'] == 3 and submit['qcoder_match_count'] == 1 and submit['extra_attachment_count'] == 2
    assert submit['cursor_version'] == version and submit['workspace_root_match'] is True
    assert not list((root.parent/'carbon-canonical-v4').iterdir())


@pytest.mark.parametrize('version', [None, '', ' ', '3.23.23 bad', '3/23', 'x'*81, 123, [], '\u2603', '3\nsecret', '\u001b[31m'])
def test_malformed_versions_refuse_safely(generated, version):
    response = hook(generated, cursor_version=version)
    assert response['continue'] is False and 'common:event_version' in response['user_message']
    assert not list((generated/'.d148').glob('attachment-*.json'))
    _, report = diagnose(generated)
    assert 'cursor_version' not in report['latest']


@pytest.mark.parametrize('attachments', [None, {}, '', [], [{'type': 'file', 'file_path': 'other'}],
    [{'type': 'rule'}], [{'type': 'rule', 'file_path': None}], [{'type': 'rule', 'file_path': ['d148-read-only.mdc']}],
    [{'type': 'file', 'file_path': 'd148-read-only.mdc'}],
    [{'type': 'rule', 'file_path': 'd148-read-only.mdc'}]*2,
    [{'type': 'rule', 'file_path': 'd148-read-only.mdc'}, {'type': 'rule', 'file_path': r.RULE}],
    [{'type': 'rule', 'file_path': 'other'}]*129])
def test_missing_malformed_and_multiple_candidates(generated, attachments):
    response = hook(generated, attachments=attachments)
    assert response['continue'] is False and 'attachment:' in response['user_message']
    assert not list((generated/'.d148').glob('attachment-*.json'))
    _, value = diagnose(generated)
    assert value['latest']['decision'] == 'deny'


@pytest.mark.parametrize('path', ['../d148-read-only.mdc', './d148-read-only.mdc',
    '.cursor/rules/../rules/d148-read-only.mdc', '.cursor/rules//d148-read-only.mdc',
    '/foreign/.cursor/rules/d148-read-only.mdc', 'prefix-d148-read-only.mdc',
    '/foreign/.cursor/rules/D148-READ-ONLY.mdc',
    'd148-read-only.mdc.backup', 'd148-read-only2.mdc', 'subdir/d148-read-only.mdc',
    '.cursor/rules/d148-read-only.mdc/extra'])
@pytest.mark.parametrize('with_valid', [False, True])
def test_near_traversing_suffix_foreign_paths_never_authorize(generated, path, with_valid):
    attachments = [{'type': 'rule', 'file_path': path}]
    if with_valid:
        attachments.append({'type': 'rule', 'file_path': 'd148-read-only.mdc'})
    assert hook(generated, attachments=attachments)['continue'] is False
    assert not list((generated/'.d148').glob('attachment-*.json'))
    _, value = diagnose(generated)
    assert value['latest']['qcoder_representation'] == ('ambiguous' if with_valid else 'unsupported')


@pytest.mark.parametrize('extra', [{'cursor_version': '3.24.0'}, {'cursor_version': ''},
    {'generation_id': ''}, {'generation_id': 'malformed/generation'},
    {'workspace_roots': ['/PRIVATE_FOREIGN_ROOT']}, {'attachments': []}])
def test_failed_resubmit_invalidates_earlier_generation(generated, extra):
    assert hook(generated)['continue']
    assert hook(generated, **extra)['continue'] is False
    assert action(generated)['permission'] == 'deny'


def test_new_conversation_binds_patch_update_without_reinstall(generated):
    assert hook(generated)['continue']
    assert action(generated)['permission'] == 'allow'
    assert hook(generated, cursor_version='3.24.0', conversation_id='new-conversation')['continue']
    assert action(generated, cursor_version='3.24.0', conversation_id='new-conversation')['permission'] == 'allow'
    assert action(generated, cursor_version='3.24.0')['permission'] == 'deny'
    assert action(generated, generation_id='different-generation')['permission'] == 'deny'


def test_new_generation_requires_its_own_attachment(generated):
    assert hook(generated)['continue']
    assert action(generated, generation_id='next-generation')['permission'] == 'deny'
    assert hook(generated, generation_id='next-generation')['continue']
    assert action(generated, generation_id='next-generation')['permission'] == 'allow'
    assert action(generated)['permission'] == 'deny'


@pytest.mark.parametrize('name', ['beforeSubmitPrompt', 'preToolUse', 'beforeShellExecution'])
def test_missing_version_not_silently_inherited(generated, name):
    assert hook(generated)['continue']
    value = event(generated, name, tool_name='Shell', tool_input={'command': './qcoder-context'}, command='./qcoder-context')
    del value['cursor_version']
    result = subprocess.run([str(generated/'.d148/guard'), name], cwd=generated,
        input=json.dumps(value), text=True, capture_output=True)
    response = json.loads(result.stdout)
    assert response.get('continue') is False or response.get('permission') == 'deny'


def test_unrelated_instruction_coexistence_uses_no_inventory(generated):
    root = generated
    for base in (root, root.parent, root.parent/'fixture-home', root.parent/'fixture-enterprise'):
        for name in ('AGENTS.md', 'CLAUDE.md', '.cursorrules', '.cursor/rules/unrelated.mdc',
                     '.cursor/skills/extra.txt', '.cursor/managed/active-team-hooks/hooks.json'):
            path = base/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('PRIVATE_UNRELATED_INSTRUCTION')
    (root/'.cursor/rules/unrelated-link.mdc').symlink_to('/PRIVATE_NEVER_READ')
    before = snapshot(root.parent)
    assert hook(root, attachments=[{'type': 'rule', 'file_path': 'd148-read-only.mdc'},
        {'type': 'rule', 'file_path': 'unrelated.mdc'}])['continue']
    assert action(root)['permission'] == 'allow'
    after = snapshot(root.parent)
    assert all(after[name] == content for name, content in before.items() if name != 'client-v5/.d148/events.jsonl')
    assert hook(root, 'preToolUse', tool_name='Read', tool_input={'path': '/PRIVATE'})['permission'] == 'deny'


@pytest.mark.parametrize('damage', ['runtime_missing', 'runtime_crashed', 'rule_changed', 'host', 'guard', 'events_corrupt'])
def test_one_failure_has_share_safe_diagnosis(generated, damage):
    root = generated
    if damage == 'runtime_missing':
        (root/'.d148/runtime.py').unlink()
    elif damage == 'runtime_crashed':
        (root/'.d148/runtime.py').write_text('raise RuntimeError("PRIVATE_CRASH")')
    elif damage == 'rule_changed':
        (root/r.RULE).write_text('PRIVATE_RULE_CHANGE')
    elif damage == 'host':
        p = root/'.d148/installed.json'
        value = json.loads(p.read_text()); value['host_id'] = 'other'; p.write_text(json.dumps(value))
    elif damage == 'guard':
        (root/'.d148/guard').write_text('PRIVATE_CHANGED_GUARD')
    else:
        (root/'.d148/events.jsonl').write_text(json.dumps({'event': 'PRIVATE_EVENT',
            'reason': 'PRIVATE_REASON', 'cursor_version': '/PRIVATE_PATH', 'prompt': 'PRIVATE_PROMPT',
            'qcoder_representation': 'PRIVATE_FILENAME', 'stage': 'PRIVATE_STAGE'})+'\n')
    result, report = diagnose(root)
    assert result.returncode == 0
    if damage != 'events_corrupt':
        assert report['disk_binding'] == 'refused'
        assert report['blocker'] in ('stale_binding_file', 'host_mismatch')
    else:
        assert report['latest'] == {}


def test_diagnose_bounded_large_audit(generated):
    p = generated/'.d148/events.jsonl'
    p.write_text((json.dumps({'event': 'preToolUse', 'decision': 'deny', 'reason': 'action_denied',
                              'private': 'PRIVATE_LARGE_LOG'})+'\n')*20000)
    _, value = diagnose(generated)
    assert len(value['recent']) == 20 and len(json.dumps(value)) < 10000


def test_diagnose_refuses_audit_symlink(generated):
    p = generated/'.d148/events.jsonl'
    p.unlink(); p.symlink_to('/PRIVATE_NEVER_READ')
    result, value = diagnose(generated)
    assert result.returncode == 2 and value['reason'] == 'unavailable'


def test_real_successor_preserves_client_v4_and_unrelated_material(installed):
    root, _ = installed
    old = root.parent/'client-v4'
    (old/'.cursor/rules').mkdir(parents=True)
    (old/'.cursor/rules/legacy.mdc').write_text('D148 HISTORICAL CLIENT V4')
    (root/'notes.txt').write_text('UNRELATED PRIVATE MATERIAL')
    (root/'.cursor/rules/unrelated.mdc').write_text('UNRELATED RULE')
    before = snapshot(old)
    assert r.verify()
    setup.remove()
    assert snapshot(old) == before
    assert (root/'notes.txt').read_text() == 'UNRELATED PRIVATE MATERIAL'
    assert (root/'.cursor/rules/unrelated.mdc').read_text() == 'UNRELATED RULE'
    assert set(snapshot(root)) == {'notes.txt', '.cursor/rules/unrelated.mdc', '.d148/events.jsonl'}


@pytest.mark.parametrize('path', list(r.MANAGED)+['.d148/installed.json'])
def test_fresh_installer_collision_never_overwrites(installed, monkeypatch, path):
    setup.remove()
    target = r.ROOT/path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('NON_QCODER_PRIVATE_MATERIAL')
    before = snapshot(r.ROOT)
    monkeypatch.chdir(r.BASE)
    with pytest.raises(r.Refused, match='managed_path_conflict'):
        setup.install()
    assert snapshot(r.ROOT) == before


def test_fresh_install_failure_keeps_new_unrelated_material(installed, monkeypatch):
    setup.remove()
    (r.ROOT/'.d148/events.jsonl').unlink(); (r.ROOT/'.d148').rmdir(); r.ROOT.rmdir()
    monkeypatch.chdir(r.BASE)
    def fail(*a, **k):
        (r.ROOT/'unrelated.txt').write_text('PRIVATE_UNRELATED')
        raise r.Refused('binding_mismatch')
    monkeypatch.setattr(r, 'verify', fail)
    with pytest.raises(r.Refused):
        setup.install()
    assert snapshot(r.ROOT) == {'unrelated.txt': (b'PRIVATE_UNRELATED', 0o644)}


def test_doctor_synthetic_contract_and_no_receipt_in_normal(installed):
    normal, count = setup.synthetic_doctor()
    root = Path(normal['fixture_root'])
    assert count == 9
    assert not list((root/'.d148').glob('attachment-*.json'))
    assert not list((root.parent/'carbon-canonical-v4').iterdir())


def test_doctor_real_exact_operation_and_identity(installed, monkeypatch):
    expected = json.loads((CLIENT/'carbon-context.json').read_text())
    value = {'schema': 'd148.client_context.v1', 'status': 'verified', 'new_scientific_jobs': 0,
             'approval_created': False, 'plan_mutated': False, 'science_state': 'completed',
             'lifecycle_state': 'completed_delivered_verified_readback', 'readback_verified': True,
             'authority_state': 'consumed_no_retry', 'qcoder_established': {
                 **expected['identities'], 'metrics': expected['metrics'], 'accounting': expected['accounting']}}
    value['digest'] = r.digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
    calls = []
    def run(args, **kwargs):
        from types import SimpleNamespace
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps(value).encode(), stderr=b'PRIVATE')
    monkeypatch.setattr(r.subprocess, 'run', run)
    before = snapshot(r.WORKSPACE)
    report = setup.doctor_real()
    assert report['status'] == 'D148_CARBON_READY_FOR_CURSOR'
    assert calls == [[str(r.PYTHON), '-I', '-B', '-m', 'qcoder.ml_research.client_context', '--workspace', str(r.WORKSPACE)]]
    assert snapshot(r.WORKSPACE) == before


@pytest.mark.parametrize('damage', ['digest', 'new_scientific_jobs', 'approval_created', 'plan_mutated',
    'job_id', 'plan_digest', 'result_digest', 'assessment_digest', 'metrics', 'accounting', 'science_state'])
def test_doctor_rejects_any_changed_completed_context(installed, monkeypatch, damage):
    expected = json.loads((CLIENT/'carbon-context.json').read_text())
    value = {'schema': 'd148.client_context.v1', 'status': 'verified', 'new_scientific_jobs': 0,
             'approval_created': False, 'plan_mutated': False, 'science_state': 'completed',
             'lifecycle_state': 'completed_delivered_verified_readback', 'readback_verified': True,
             'authority_state': 'consumed_no_retry', 'qcoder_established': {
                 **expected['identities'], 'metrics': expected['metrics'], 'accounting': expected['accounting']}}
    if damage in value['qcoder_established']:
        value['qcoder_established'][damage] = 'wrong'
    elif damage != 'digest':
        value[damage] = 1 if damage == 'new_scientific_jobs' else (True if damage in ('approval_created', 'plan_mutated') else 'pending')
    value['digest'] = r.digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()) if damage != 'digest' else 'wrong'
    def run(*a, **k):
        from types import SimpleNamespace
        return SimpleNamespace(returncode=0, stdout=json.dumps(value).encode(), stderr=b'PRIVATE')
    monkeypatch.setattr(r.subprocess, 'run', run)
    with pytest.raises(r.Refused):
        setup.context_doctor()


def test_fresh_install_ignores_and_preserves_ancestor_user_plugin_config(installed, monkeypatch):
    setup.remove()
    (r.ROOT/'.d148/events.jsonl').unlink(); (r.ROOT/'.d148').rmdir(); r.ROOT.rmdir()
    for directory in (r.BASE, r.CONFIG_HOME, r.ENTERPRISE):
        for name in ('AGENTS.md', '.cursor/hooks.json', '.cursor/rules/d148-read-only.mdc',
                     '.cursor/skills/tool.md', '.claude/settings.json'):
            path = directory/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('PRIVATE_UNRELATED_CONFIG')
    before = {str(d): snapshot(d) for d in (r.CONFIG_HOME, r.ENTERPRISE)}
    parent_instructions = (r.BASE/'AGENTS.md').read_bytes()
    monkeypatch.chdir(r.BASE)
    assert setup.install()['disk_binding'] == 'verified'
    assert {str(d): snapshot(d) for d in (r.CONFIG_HOME, r.ENTERPRISE)} == before
    assert (r.BASE/'AGENTS.md').read_bytes() == parent_instructions


def test_renderer_handles_an_already_rendered_runtime_without_cascading(tmp_path):
    import shutil
    source = tmp_path/'source'
    shutil.copytree(CLIENT, source)
    generator = module('render_again', source/'control_fixture.py')
    python = Path(sys.executable)
    first_base = tmp_path/'first source base'
    (source/'runtime.py').write_text(generator.render_runtime(first_base, python))
    # A path containing the former source base is embedded exactly once.
    next_base = first_base/'nested'/'source base'
    rendered = generator.render_runtime(next_base, python, synthetic=True)
    assert 'BASE = Path('+repr(str(next_base))+')' in rendered
    assert 'PYTHON = Path('+repr(str(python))+')' in rendered
    assert 'SYNTHETIC_FIXTURE = True' in rendered
