"""Operator-only fresh successor install, read-only doctor and bounded diagnose."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


runtime = module('d148_runtime', HERE/'runtime.py')
MANAGED = runtime.MANAGED
OPERATOR_REASONS = frozenset(('managed_path_conflict', 'successor_root_exists',
    'payload_integrity', 'package_identity', 'doctor_synthetic_contract',
    'doctor_attachment_receipt', 'doctor_science_access', 'completed_context_required',
    'completed_identity_mismatch', 'completed_metrics_mismatch', 'diagnose_audit_invalid',
    'doctor_locator_conflict'))


def check_payload():
    r = runtime
    manifest = r.load(HERE/'payload.json')
    expected = {'runtime.py', 'setup.py', 'guard', 'qcoder-context', 'binding.mdc',
                'hooks.json', 'cursorignore', 'package.json', 'control_fixture.py',
                'CARBON-INSTALL.txt', 'acceptance-template.json', 'carbon-context.json'}
    r.require(set(manifest) == expected, 'payload_integrity')
    r.hashes(HERE, manifest)
    sums = r.regular(HERE/'SHA256SUMS').decode('ascii').splitlines()
    expected_sums = {**manifest, 'payload.json': r.digest(r.regular(HERE/'payload.json'))}
    r.require(len(sums) == len(expected_sums), 'payload_integrity')
    r.require(set(sums) == {sha+'  '+name for name, sha in expected_sums.items()}, 'payload_integrity')
    return manifest


def environment():
    r = runtime
    r.require(os.path.abspath(sys.executable) == str(r.PYTHON), 'wrong_interpreter')
    r.require(r.BASE.is_dir() and r.BASE.resolve() == r.BASE, 'wrong_root')
    r.require(r.WORKSPACE.is_dir() and r.WORKSPACE.resolve() == r.WORKSPACE, 'workspace_unavailable')
    distribution = r.importlib.metadata.distribution('qcoder')
    r.require(distribution.version == r.VERSION, 'dev8_version_mismatch')
    expected = r.load(HERE/'package.json')
    r.require(isinstance(expected, dict) and len(expected) == 157, 'package_identity')
    for name, sha in expected.items():
        r.require(name.startswith('qcoder/') and '..' not in Path(name).parts, 'package_identity')
        r.require(r.digest(r.regular(Path(distribution.locate_file(name)))) == sha, 'installed_dev8_payload_mismatch')


def preflight():
    r = runtime
    check_payload()
    environment()
    r.require(Path.cwd() == r.BASE, 'wrong_root')
    if os.path.lexists(r.ROOT):
        r.require(r.ROOT.is_dir() and not r.ROOT.is_symlink(), 'managed_path_conflict')
        for name in MANAGED + ('.d148/installed.json',):
            if os.path.lexists(r.ROOT/name):
                raise r.Refused('managed_path_conflict')
        raise r.Refused('successor_root_exists')


def install():
    r = runtime
    preflight()
    generator = module('d148_generator', HERE/'control_fixture.py')
    targets = {'qcoder-context': generator.render_context(r.PYTHON, r.ROOT).encode(),
               '.cursor/hooks.json': r.regular(HERE/'hooks.json'),
               r.RULE: generator.replace_once((HERE/'binding.mdc').read_text(), generator.CARBON+'/client-v5', str(r.ROOT)).encode(),
               '.cursorignore': r.regular(HERE/'cursorignore'),
               '.d148/runtime.py': generator.render_runtime(r.BASE, r.PYTHON).encode(),
               '.d148/guard': generator.render_guard(r.PYTHON, r.ROOT).encode(),
               '.d148/package.json': r.regular(HERE/'package.json')}
    # Exactly one absent successor directory. No old binding discovery or backup.
    r.ROOT.mkdir(mode=0o700)
    written = {}
    created_dirs = []
    previous_cwd = Path.cwd()
    try:
        for name, content in targets.items():
            p = r.ROOT/name
            for parent in reversed(p.parents):
                if parent.is_relative_to(r.ROOT) and not parent.exists():
                    parent.mkdir(mode=0o700)
                    created_dirs.append(parent)
            with p.open('xb') as stream:
                stream.write(content)
            p.chmod(0o755 if name in ('qcoder-context', '.d148/guard') else 0o600)
            written[name] = r.digest(content)
        receipt = {'schema': 'd148.client_binding.v5', 'root': str(r.ROOT),
                   'workspace': str(r.WORKSPACE), 'python': str(r.PYTHON),
                   'python_resolved': str(r.PYTHON.resolve()), 'python_sha256': r.digest(r.PYTHON.read_bytes()),
                   'host_id': r.host_id(), 'files': written,
                   'version_binding': 'native_event_per_generation',
                   'native_acceptance': 'pending', 'active_attachment': 'unobserved'}
        content = (json.dumps(receipt, indent=2)+'\n').encode()
        p = r.ROOT/'.d148/installed.json'
        with p.open('xb') as stream:
            stream.write(content)
        p.chmod(0o600)
        written['.d148/installed.json'] = r.digest(content)
        # Keep the immutable file map separate from the receipt itself.
        os.chdir(r.ROOT)
        r.verify()
        generator.launcher_preflight(r.ROOT)
    except BaseException:
        for name, sha in written.items():
            p = r.ROOT/name
            if os.path.lexists(p) and r.digest(r.regular(p)) == sha:
                p.unlink()
        for directory in list(reversed(created_dirs)) + [r.ROOT]:
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    finally:
        os.chdir(previous_cwd)
    return {'installed': True, 'disk_binding': 'verified', 'active_attachment': 'unobserved',
            'version_binding': 'native_event_per_generation', 'target_acceptance': 'pending'}


def remove():
    r = runtime
    check_payload()
    receipt = r.verify()
    # Verify every owned byte before deleting any. Unrelated material is retained.
    r.require(set(receipt['files']) == set(MANAGED), 'binding_mismatch')
    for name in MANAGED + ('.d148/installed.json',):
        (r.ROOT/name).unlink()
    for name in ('.cursor/rules', '.cursor', '.d148', ''):
        try:
            (r.ROOT/name).rmdir()
        except OSError:
            pass
    return {'removed_managed_binding': True, 'audit_and_unrelated_material': 'preserved',
            'scientific_state_accessed': False}


def context_doctor():
    r = runtime
    value, elapsed, code = r.read_context()
    r.require(code == 0 and value['status'] == 'verified' and
        value.get('lifecycle_state') == 'completed_delivered_verified_readback' and
        value.get('science_state') == 'completed' and value.get('readback_verified') is True and
        value.get('authority_state') == 'consumed_no_retry', 'completed_context_required')
    actual = value['qcoder_established']
    r.require(isinstance(actual, dict), 'context_invalid')
    expected = r.load(HERE/'carbon-context.json')
    r.require(all(actual.get(key) == item for key, item in expected['identities'].items()), 'completed_identity_mismatch')
    r.require(actual.get('metrics') == expected['metrics'], 'completed_metrics_mismatch')
    accounting = actual.get('accounting', {})
    r.require(isinstance(accounting, dict), 'completed_metrics_mismatch')
    r.require(all(accounting.get(key) == item for key, item in expected['accounting'].items()), 'completed_metrics_mismatch')
    return {'status': 'verified', 'science_state': 'completed',
            'projection_digest': value['digest'], 'context_ns': elapsed,
            **expected['identities'], 'candidate': '37/40', 'baseline': '37/40', 'delta': 0,
            'new_scientific_jobs': 0, 'approval_created': False, 'plan_mutated': False}


def synthetic_doctor():
    r = runtime
    generator = module('d148_generator', HERE/'control_fixture.py')
    created = generator.create(None, 'normal')
    root = Path(created['fixture_root'])
    r.require(not list((root/'.d148').glob('attachment-*.json')), 'doctor_attachment_receipt')
    checks = 0
    for version in ('3.23.12', '3.23.23', '3.24.0'):
        for form in (str(root/r.RULE), r.RULE, 'd148-read-only.mdc'):
            common = {'workspace_roots': [str(root)], 'cursor_version': version,
                      'conversation_id': 'doctor-'+str(checks), 'generation_id': 'doctor-generation', 'cwd': str(root)}
            def guard(name, **extra):
                result = r.subprocess.run([str(root/'.d148/guard'), name], cwd=root,
                    input=json.dumps({**common, 'hook_event_name': name, **extra}),
                    text=True, capture_output=True, timeout=5, check=False)
                r.require(result.returncode == 0 and not result.stderr, 'doctor_synthetic_contract')
                return r.parse(result.stdout)
            r.require(guard('beforeSubmitPrompt', attachments=[
                {'type': 'file', 'file_path': 'unrelated.txt'},
                {'type': 'rule', 'file_path': form, 'future_metadata': {'opaque': True}},
                {'type': 'rule', 'file_path': 'unrelated.mdc'}]).get('continue') is True, 'doctor_synthetic_contract')
            r.require(guard('preToolUse', tool_name='Shell', tool_input={'command': r.ACTION}).get('permission') == 'allow', 'doctor_synthetic_contract')
            r.require(guard('beforeShellExecution', command=r.ACTION).get('permission') == 'allow', 'doctor_synthetic_contract')
            for command in ('pwd', './qcoder-context; pwd', './qcoder-context x'):
                r.require(guard('preToolUse', tool_name='Shell', tool_input={'command': command}).get('permission') == 'deny', 'doctor_synthetic_contract')
                r.require(guard('beforeShellExecution', command=command).get('permission') == 'deny', 'doctor_synthetic_contract')
            for tool in ('Read', 'Task', 'Write', 'MCP:any'):
                r.require(guard('preToolUse', tool_name=tool, tool_input={}).get('permission') == 'deny', 'doctor_synthetic_contract')
            for name in ('beforeReadFile', 'beforeMCPExecution', 'subagentStart', 'beforeTabFileRead'):
                r.require(guard(name).get('permission') == 'deny', 'doctor_synthetic_contract')
            changed = {**common, 'cursor_version': '3.99.0', 'hook_event_name': 'preToolUse',
                       'tool_name': 'Shell', 'tool_input': {'command': r.ACTION}}
            result = r.subprocess.run([str(root/'.d148/guard'), 'preToolUse'], cwd=root,
                input=json.dumps(changed), text=True, capture_output=True, timeout=5)
            r.require(r.parse(result.stdout).get('permission') == 'deny', 'doctor_synthetic_contract')
            checks += 1
    # No qCoder package/context/scientific operation occurs in these fixtures.
    marker = r.subprocess.run([str(root/'qcoder-context')], cwd=root,
        text=True, capture_output=True, timeout=5)
    r.require(marker.returncode == 0 and marker.stdout.strip() == 'D148_SYNTHETIC_CONTEXT_ONLY', 'doctor_synthetic_contract')
    denied = r.subprocess.run([str(root/'qcoder-context'), 'unsupported'], cwd=root,
        text=True, capture_output=True, timeout=5)
    r.require(denied.returncode == 2 and not denied.stdout, 'doctor_synthetic_contract')
    r.require(not list((root.parent/'carbon-canonical-v4').iterdir()), 'doctor_science_access')
    normal = generator.create(None, 'normal')
    r.require(not list((Path(normal['fixture_root'])/'.d148').glob('attachment-*.json')), 'doctor_attachment_receipt')
    return normal, checks


def doctor():
    r = runtime
    check_payload()
    environment()
    locator = HERE/'carbon-doctor.json'
    if os.path.lexists(locator):
        previous = r.load(locator)
        r.require(previous.get('schema') == 'd148.carbon_doctor.v5', 'doctor_locator_conflict')
    context = context_doctor()
    normal, checks = synthetic_doctor()
    content = {'schema': 'd148.carbon_doctor.v5', 'fixture_root': normal['fixture_root'],
               'context': context, 'synthetic_combinations': checks, 'native_acceptance': 'pending'}
    # Only this task-owned pointer is replaced; all previous fixtures survive.
    fd = os.open(locator, os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        r.require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode) and os.fstat(stream.fileno()).st_nlink == 1, 'doctor_locator_conflict')
        json.dump(content, stream, indent=2)
    return {'status': 'D148_CARBON_READY_FOR_CURSOR', 'fixture_locator': 'carbon-doctor.json',
            'synthetic_combinations': checks, 'completed_context': context, 'target_acceptance': 'pending'}


def doctor_real():
    check_payload()
    runtime.verify()
    return {'status': 'D148_CARBON_READY_FOR_CURSOR', 'disk_binding': 'verified',
            'completed_context': context_doctor(), 'target_acceptance': 'pending'}


def safe_row(row):
    r = runtime
    if not isinstance(row, dict):
        return {}
    out = {}
    enums = {'event': r.EVENTS+('context',), 'decision': ('allow', 'deny'),
             'stage': r.STAGES, 'reason': r.REASONS|{'accepted'},
             'tool_class': ('Shell', 'Read', 'Grep', 'Task', 'Write', 'Delete', 'Glob', 'other'),
             'qcoder_representation': r.REPRESENTATIONS+('missing', 'ambiguous', 'unsupported'),
             'status': ('verified', 'refused')}
    for key, values in enums.items():
        if row.get(key) in values:
            out[key] = row[key]
    for key in ('workspace_root_match', 'exact_context_action', 'synthetic_fixture', 'attachment_observed'):
        if type(row.get(key)) is bool:
            out[key] = row[key]
    for key in ('time_ns', 'context_ns', 'attachment_count', 'qcoder_match_count', 'extra_attachment_count', 'new_scientific_jobs'):
        if type(row.get(key)) is int and 0 <= row[key] < 2**63:
            out[key] = row[key]
    for key in ('conversation_hash', 'generation_hash', 'projection_digest'):
        if isinstance(row.get(key), str) and re.fullmatch('[a-f0-9]{64}', row[key]):
            out[key] = row[key]
    if r.bounded_version(row.get('cursor_version')):
        out['cursor_version'] = row['cursor_version']
    return out


def diagnose():
    r = runtime
    binding, blocker = 'verified', None
    try:
        r.verify(package=not r.SYNTHETIC_FIXTURE)
    except BaseException as error:
        binding = 'refused'
        blocker = str(error) if isinstance(error, r.Refused) and str(error) in r.REASONS else 'unavailable'
    path = r.ROOT/'.d148/events.jsonl'
    rows = []
    audit_state = 'absent'
    if os.path.lexists(path):
        fd = os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            r.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'diagnose_audit_invalid')
            start = max(0, info.st_size-65536)
            stream.seek(start)
            lines = stream.read(65536).splitlines()
            if start:
                lines = lines[1:]
            for line in lines[-20:]:
                try:
                    rows.append(safe_row(r.parse(line)))
                except BaseException:
                    rows.append({'reason': 'invalid_input'})
        audit_state = 'bounded_latest_20'
    return {'disk_binding': binding, 'blocker': blocker, 'audit_state': audit_state,
            'latest': rows[-1] if rows else None, 'recent': rows,
            'source_origin': 'identifier_and_pinned_local_rule_hash_only',
            'hidden_instruction_absence': 'not_established', 'native_acceptance': 'requires_actual_Cursor_observation',
            'scientific_state_accessed': False}


def verify():
    runtime.verify()
    return diagnose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'verify', 'remove', 'doctor', 'doctor-real', 'diagnose'])
    parser.add_argument('--root', type=Path, help='diagnose an existing generated fixture or real successor')
    args = parser.parse_args()
    try:
        if args.root:
            runtime.require(args.action == 'diagnose', 'wrong_root')
            root = Path(os.path.abspath(args.root))
            runtime.require(root.resolve() == root and Path.cwd() == root, 'wrong_root')
            # Diagnose using the trusted bundle code even if installed runtime crashed.
            runtime.require((root/'.d148/installed.json').is_file(), 'missing_binding')
            receipt = runtime.load(root/'.d148/installed.json')
            runtime.require(root.name == 'client-v5' and receipt.get('schema') in
                ('d148.client_binding.v5', 'd148.synthetic_client.v5'), 'binding_mismatch')
            runtime.ROOT, runtime.BASE = root, root.parent
            runtime.WORKSPACE = root.parent/'carbon-canonical-v4'
            runtime.PYTHON = Path(os.path.abspath(sys.executable))
            runtime.SYNTHETIC_FIXTURE = receipt['schema'] == 'd148.synthetic_client.v5'
        value = globals()[args.action.replace('-', '_')]()
        print(json.dumps(value, indent=2))
        return 0
    except BaseException as error:
        known = runtime.REASONS|OPERATOR_REASONS
        print(json.dumps({'status': 'refused', 'stage': args.action,
            'reason': str(error) if isinstance(error, runtime.Refused) and str(error) in known else 'unavailable'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
