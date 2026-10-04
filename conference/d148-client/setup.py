"""Operator-only installer/verifier/rollback; never invoked by the Agent."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('d148_runtime', HERE/'runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
MANAGED = ('qcoder-context', '.cursor/hooks.json', runtime.RULE,
           '.cursorignore', '.d148/runtime.py', '.d148/guard', '.d148/package.json')


def check_payload():
    manifest = runtime.load(HERE/'payload.json')
    runtime.hashes(HERE, manifest)
    return manifest


def preflight():
    r = runtime
    r.require(Path.cwd() == r.ROOT and r.ROOT.resolve() == r.ROOT, 'wrong_root')
    r.require(r.ROOT.is_dir() and r.WORKSPACE.is_dir() and r.WORKSPACE.resolve() == r.WORKSPACE)
    r.require(sys.executable == str(r.PYTHON), 'wrong_interpreter')
    r.require(r.importlib.metadata.version('qcoder') == r.VERSION)
    dist = r.importlib.metadata.distribution('qcoder')
    for name, sha in r.load(HERE/'package.json').items():
        r.require(r.digest(r.regular(Path(dist.locate_file(name)))) == sha)
    inventory = r.instruction_inventory(r.ROOT)
    # No inheritance silently accepted; operator can inspect/reconcile in the
    # dedicated client. Global settings and other projects are never changed.
    r.require(all(Path(path).is_relative_to(r.ROOT) for path in inventory), 'inherited_instruction_source')
    r.require('additional_instruction_source_present' not in inventory.values(), 'additional_instruction_source')
    for name in ('.cursor', '.cursor/rules', '.d148'):
        p = r.ROOT/name
        r.require(not p.is_symlink())
        if p.exists():
            r.require(p.is_dir())
    return inventory


def old_binding(inventory):
    r = runtime
    old = set()
    for path in inventory:
        name = Path(path).relative_to(r.ROOT).as_posix()
        text = r.regular(Path(path)).decode()
        r.require(('D-148' in text or 'D148' in text) and 'D-147' not in text and 'D147' not in text, 'unrelated_or_mixed_binding')
        old.add(name)
    for name in MANAGED + ('.d148/installed.json',):
        p = r.ROOT/name
        if os.path.lexists(p):
            r.regular(p)
            old.add(name)
    # A preexisting hook configuration is only replaced if identified D-148.
    # The legacy launcher and ignore file are backed up at their exact paths.
    return old


def install(cursor_version):
    r = runtime
    r.require(r.bounded_token(cursor_version))
    check_payload()
    inventory = preflight()
    r.require(not (r.ROOT/'.d148/installed.json').exists())
    old = old_binding(inventory)
    backup_root = r.BASE/'client-binding-backups'
    r.require(not backup_root.is_symlink())
    backup_root.mkdir(exist_ok=True, mode=0o700)
    backup = backup_root/('d148-'+str(time.time_ns())+'.tar')
    # Archive extension and location are outside the opened client and all active
    # rule-discovery paths. No duplicate live .mdc rules are retained.
    with tarfile.open(backup, 'x') as archive:
        for name in sorted(old):
            archive.add(r.ROOT/name, arcname=name, recursive=False)
    backup.chmod(0o600)
    targets = {'qcoder-context':'qcoder-context', '.cursor/hooks.json':'hooks.json',
               r.RULE:'binding.mdc', '.cursorignore':'cursorignore',
               '.d148/runtime.py':'runtime.py', '.d148/guard':'guard', '.d148/package.json':'package.json'}
    removed = []
    written = []
    try:
        for name in sorted(old):
            (r.ROOT/name).unlink()
            removed.append(name)
        for name, source in targets.items():
            p = r.ROOT/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(r.regular(HERE/source))
            p.chmod(0o755 if name in ('qcoder-context','.d148/guard') else 0o600)
            written.append(name)
        receipt = {'schema':'d148.client_binding.v2', 'root':str(r.ROOT),
                   'workspace':str(r.WORKSPACE), 'python':str(r.PYTHON),
                   'python_resolved':str(r.PYTHON.resolve()), 'python_sha256':r.digest(r.PYTHON.read_bytes()),
                   'host_id':r.host_id(), 'cursor_version':cursor_version,
                   'cursor_version_source':'operator About/version observation; confirmed by hook event on use',
                   'files':{name:r.digest(r.regular(r.ROOT/name)) for name in MANAGED},
                   'instruction_inventory':r.instruction_inventory(r.ROOT),
                   'backup':str(backup), 'backup_sha256':r.digest(r.regular(backup)),
                   'old_files':sorted(old), 'native_acceptance':'pending', 'active_attachment':'unobserved'}
        (r.ROOT/'.d148/installed.json').write_text(json.dumps(receipt,indent=2)+'\n')
        (r.ROOT/'.d148/installed.json').chmod(0o600)
        r.verify()
    except BaseException:
        for name in written + ['.d148/installed.json']:
            (r.ROOT/name).unlink(missing_ok=True)
        restore_archive(backup, set(removed))
        raise
    return {'installed':True, 'disk_binding':'verified', 'active_attachment':'unobserved',
            'native_enforcement':'Carbon validation pending', 'rollback_archive':str(backup)}


def restore_archive(backup, names):
    # Never use extractall, and never accept symlinks or traversal.
    r = runtime
    with tarfile.open(backup) as archive:
        for member in archive:
            r.require(member.isfile())
            r.require(not Path(member.name).is_absolute() and '..' not in Path(member.name).parts)
            if member.name not in names:
                continue
            p = r.ROOT/member.name
            r.require(not p.is_symlink() and p.parent.resolve().is_relative_to(r.ROOT))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(archive.extractfile(member).read())
            p.chmod(member.mode)


def rollback():
    r = runtime
    r.require(Path.cwd() == r.ROOT and r.ROOT.resolve() == r.ROOT)
    receipt = r.load(r.ROOT/'.d148/installed.json')
    r.require(receipt['root'] == str(r.ROOT) and receipt['host_id'] == r.host_id())
    # Preserve later edits rather than overwriting them during rollback.
    r.hashes(r.ROOT, receipt['files'])
    backup = Path(receipt['backup'])
    r.require(backup.parent == r.BASE/'client-binding-backups')
    r.require(r.digest(r.regular(backup)) == receipt['backup_sha256'])
    with tarfile.open(backup) as archive:
        r.require({m.name for m in archive} == set(receipt['old_files']))
        r.require(all(m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts for m in archive))
    for name in MANAGED:
        (r.ROOT/name).unlink()
    (r.ROOT/'.d148/installed.json').unlink()
    restore_archive(backup, set(receipt['old_files']))
    # Audit/attachment receipts are retained as local operational evidence;
    # they are not rules and grant no permission without an installed binding.
    return {'rollback':'restored', 'scientific_state_accessed':False}


def verify():
    r = runtime
    receipt = r.verify()
    observed = []
    path = r.ROOT/'.d148/events.jsonl'
    if path.exists():
        observed = [json.loads(line) for line in r.regular(path).splitlines()]
    return {'disk_binding':'verified', 'cursor_version':receipt['cursor_version'],
            'active_attachment':'identifier_reported_in_hook_event' if any(x.get('attachment_observed') for x in observed) else 'unobserved',
            'source_origin':'not_established_by_basename_payload',
            'ordered_events':observed, 'native_enforcement':'requires isolated client acceptance',
            'global_ui_team_instructions':'operator observation required; not inferred from disk',
            'scientific_state_accessed':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install','verify','rollback'])
    parser.add_argument('--cursor-version')
    args = parser.parse_args()
    try:
        value = install(args.cursor_version) if args.action == 'install' else globals()[args.action]()
        print(json.dumps(value,indent=2))
        return 0
    except BaseException as error:
        print(json.dumps({'status':'refused', 'message':runtime.MESSAGE,
                          'reason':str(error) if isinstance(error,runtime.Refused) else 'missing_invalid_or_unavailable_binding',
                          'operator_check':'exact root/interpreter, payload, inherited/conflicting rules or changed binding; no automatic discovery'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
