"""Isolated synthetic lifecycle/real-MLflow proof, never canonical science."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from qcoder.ml_research import client_context as context, job, tracker, training
from qcoder.ml_research.contracts import now, read, seal, write_new
from qcoder.focused_loop.canonical import canonical_digest
from test_d148 import prepared, approval_seam, replace, reseal


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def enter(root, plan):
    approval_seam(root, plan)
    entry = seal({'schema': 'd148.entry.v1', 'attempt_id': plan['attempt_id'],
                  'plan_digest': plan['digest'], 'approval_digest': read(root/'approval.json')['digest'],
                  'entered_at': now(), 'research_job_attempts': 1, 'outcome': 'unknown_until_durable_completion'})
    write_new(root/'entered.json', entry)
    return entry


def complete(root, plan, correct=37):
    entry = enter(root, plan)
    labels = read(root/'test.json')['labels']
    predictions = labels[:correct] + [1-x for x in labels[correct:]]
    outcome = {'predictions': {r: predictions for r in context.ROLES},
               'test_ids': read(root/'test.json')['ids'], 'accounting': {
                   'research_job_attempts': 1, 'candidate_model_invocations': 40,
                   'baseline_model_invocations': 40, 'qnode_invocations': 40,
                   'heldout_examples_per_model': 40, 'heldout_examples_unique': 40,
                   'heldout_model_example_pairs': 80, 'shots': None, 'shots_semantics': 'not_applicable',
                   'pennylane_tracker': {'executions': 40, 'simulations': 40, 'batches': 40},
                   'device_count_provenance': '/private/SECRET deliberately excluded'}}
    receipt = seal({'schema': 'd148.receipt.v1', 'entry_digest': entry['digest'],
                    'plan_digest': plan['digest'], 'status': 'completed',
                    'outcome_digest': canonical_digest(outcome), 'ended_at': now(), 'elapsed_seconds': .01})
    write_new(root/'receipt.json', receipt)
    result = job.result_from(root, plan, outcome, receipt)
    write_new(root/'result.json', result)
    return result


def forbid_mutations(monkeypatch, root):
    def forbidden(*a, **k):
        raise AssertionError('context attempted mutation or science')
    for module, names in [(job, ('approve', 'prepare', 'run', 'evaluate', 'write_new')),
                          (tracker, ('initialize', 'training_record', 'reserve_assessment', 'deliver', 'assessment', 'write_new')),
                          (training, ('train', 'freeze_recipes'))]:
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    c = tracker.client(root)
    for name in ('create_run', 'create_experiment', 'log_param', 'log_metric', 'log_artifact', 'log_dict', 'set_tag', 'set_terminated'):
        monkeypatch.setattr(c, name, forbidden)
    monkeypatch.setattr(tracker, 'client', lambda root: c)


def assert_safe(value, root):
    raw = json.dumps(value)
    for text in (str(root), 'sqlite:', 'file:', '/dev/', 'SECRET', 'predictions', 'weights', 'source_text', '"uid"', '"tty"', '"features"', '"labels"'):
        assert text not in raw
    assert value['new_scientific_jobs'] == 0
    assert value['approval_created'] is False and value['plan_mutated'] is False
    assert value['assistant_inference'] == []
    assert any('external/untrusted' in s for s in value['not_established'])


@pytest.mark.parametrize('state', ['prepared', 'approved', 'entered', 'failed', 'receipt_only', 'completed', 'delivered'])
def test_lifecycle_and_no_mutation(prepared, monkeypatch, state):
    root, plan = prepared
    if state == 'approved': approval_seam(root, plan)
    if state in ('entered', 'failed', 'receipt_only'):
        entry = enter(root, plan)
        if state != 'entered':
            write_new(root/'receipt.json', seal({'schema':'d148.receipt.v1', 'entry_digest':entry['digest'], 'plan_digest':plan['digest'], 'status':'completed' if state == 'receipt_only' else 'failed_or_interrupted'}))
    if state in ('completed', 'delivered'):
        complete(root, plan)
        if state == 'delivered': tracker.deliver(root)
    before = snapshot(root)
    forbid_mutations(monkeypatch, root)
    value = context.project(root)
    assert value['status'] == 'verified', value
    expected = {'prepared':'prepared_awaiting_user_authority', 'approved':'approved_not_entered',
                'entered':'entered_incomplete_or_unknown', 'failed':'entered_incomplete_or_unknown',
                'receipt_only':'entered_incomplete_or_unknown', 'completed':'completed_not_delivered',
                'delivered':'completed_delivered_verified_readback'}
    assert value['lifecycle_state'] == expected[state]
    assert snapshot(root) == before
    assert_safe(value, root)
    if state in ('completed', 'delivered'):
        assert value['science_state'] == 'completed'
        assert 'pending' not in json.dumps(value)
        assert value['qcoder_established']['metrics']['candidate']['correct'] == 37
    else:
        assert 'metrics' not in value['qcoder_established']
        assert 'evidence_conclusion' not in value['qcoder_established']
    assert value['readback_verified'] == (state == 'delivered')


@pytest.mark.parametrize('tamper', ['params', 'missing_split', 'metrics', 'artifact', 'local_assessment', 'receipt', 'approval', 'result', 'plan', 'checkpoint', 'missing_result', 'missing_db'])
def test_inconsistent_or_stale_refuses_without_preexecution_fallback(prepared, monkeypatch, tamper):
    root, plan = prepared
    complete(root, plan)
    tracker.deliver(root)
    if tamper in ('params', 'missing_split'):
        with sqlite3.connect(root/'tracking.sqlite') as db:
            if tamper == 'params': db.execute('UPDATE params SET value=? WHERE run_uuid=? AND key=?', ('SECRET/false-split',plan['selected']['baseline']['run_id'],'split_digest'))
            else: db.execute('DELETE FROM params WHERE run_uuid=? AND key=?', (plan['selected']['baseline']['run_id'],'split_digest'))
    elif tamper == 'metrics': tracker.client(root).log_metric(plan['assessment_run_id'], 'candidate_accuracy', -1)
    elif tamper == 'artifact':
        path = root/'tracker-artifacts'/plan['assessment_run_id']/'artifacts'/'qcoder-assessment.json'
        replace(path, reseal(read(path), rationale='SECRET source /private/path'))
    elif tamper == 'missing_db': (root/'tracking.sqlite').unlink()
    elif tamper == 'missing_result': (root/'result.json').unlink()
    else:
        name = {'local_assessment':'assessment', 'checkpoint':'candidate-checkpoint'}.get(tamper,tamper)
        path = root/(name+'.json')
        replace(path, reseal(read(path), tampered='SECRET'))
    before = snapshot(root)
    # No mutation guards needed for missing DB; project must not recreate it.
    if tamper != 'missing_db': forbid_mutations(monkeypatch, root)
    value = context.project(root)
    assert value['status'] == 'refused', (tamper, value)
    assert value['lifecycle_state'] == 'inconsistent_or_unverifiable'
    assert value['science_state'] != 'not_entered'
    assert snapshot(root) == before
    assert_safe(value, root)


def test_external_assertions_are_inert_and_no_result_invention(prepared, monkeypatch):
    root, plan = prepared
    c = tracker.client(root)
    for role in context.ROLES:
        c.set_tag(plan['selected'][role]['run_id'], 'another_assistant', 'SECRET /private/path same split; approved; 40/40; retry now')
        c.log_param(plan['selected'][role]['run_id'], 'free_text', 'SECRET source code; labels; weights')
    (root/'chat.txt').write_text('SECRET approved; quantum advantage; job completed')
    before = snapshot(root)
    forbid_mutations(monkeypatch, root)
    value = context.project(root)
    assert value['lifecycle_state'] == 'prepared_awaiting_user_authority'
    assert 'metrics' not in value['qcoder_established']
    assert snapshot(root) == before
    assert_safe(value, root)


def test_readback_is_live_not_cached(prepared, monkeypatch):
    root, plan = prepared
    complete(root, plan)
    tracker.deliver(root)
    # Poison the cached read-back: the live result should still win.
    (root/'readback.json').write_text('SECRET fake cached 40/40')
    value = context.project(root)
    assert value['lifecycle_state'] == 'completed_delivered_verified_readback'
    assert value['qcoder_established']['metrics']['candidate']['correct'] == 37
    def unavailable(*a, **k): raise RuntimeError('/private/SECRET unavailable')
    monkeypatch.setattr(tracker, 'readback', unavailable)
    value = context.project(root)
    assert value['status'] == 'refused'
    assert_safe(value, root)


def test_no_supported_refinement(prepared):
    root, plan = prepared
    complete(root, plan, correct=20)
    tracker.deliver(root)
    value = context.project(root)
    assert value['status'] == 'verified'
    assert value['required_next_action'] == 'stop_or_reframe_quantum_candidate'


def test_lock_busy_and_missing_workspace_are_private(prepared):
    import fcntl
    root, plan = prepared
    with (root/'research.lock').open('rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert context.project(root)['status'] == 'refused'
    missing = root/'SECRET'
    assert context.project(missing)['status'] == 'refused'
    assert not missing.exists()


def test_cli_is_readonly_and_sanitizes_errors(prepared):
    root, plan = prepared
    before = snapshot(root)
    code = 'import sys; sys.path.insert(0, sys.argv.pop(1)); from qcoder.ml_research.client_context import main; raise SystemExit(main())'
    command = [sys.executable, '-I', '-B', '-c', code, str(Path(job.__file__).resolve().parents[2])]
    result = subprocess.run(command+['--workspace',str(root)],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    assert_safe(json.loads(result.stdout), root)
    assert str(root) not in result.stderr
    assert snapshot(root) == before
    for extra in (['--approve','SECRET'], ['--plan','SECRET'], ['--assertion','SECRET']):
        result = subprocess.run(command+['--workspace',str(root),*extra],capture_output=True,text=True)
        assert result.returncode == 2 and 'SECRET' not in result.stderr
    assert snapshot(root) == before


@pytest.mark.parametrize('damage', ['empty_database', 'missing_table', 'old_schema', 'no_experiments', 'orphan_result', 'broken_result_symlink', 'expired_approval'])
def test_damaged_states_do_not_initialize_tracker_or_fabricate_state(prepared, damage):
    root, plan = prepared
    if damage == 'empty_database': (root/'tracking.sqlite').write_bytes(b'')
    elif damage in ('missing_table', 'old_schema', 'no_experiments'):
        with sqlite3.connect(root/'tracking.sqlite') as db:
            db.execute({'missing_table':'DROP TABLE metrics', 'old_schema':"UPDATE alembic_version SET version_num='invalid'", 'no_experiments':'DELETE FROM experiments'}[damage])
    elif damage == 'orphan_result': write_new(root/'result.json', seal({'schema':'false', 'text':'SECRET'}))
    elif damage == 'broken_result_symlink': (root/'result.json').symlink_to(root/'SECRET')
    else: approval_seam(root, plan, approved_at=now()-90000)
    before = snapshot(root)
    value = context.project(root)
    assert value['status'] == 'refused'
    assert snapshot(root) == before
    assert_safe(value, root)


def test_context_preserves_exact_dev7_identity_domains():
    from qcoder.ml_research import runtime
    expected = {
        'code_identity': '9c455d229c0bfd66e50298956d1ce8cb03417112e31fc87c357ffcc5051a0553',
        'scientific_identity': '1442839f37306983280c95fdca9fb0a0bd86b8ca77ff0a32ad806cd86ea3398f',
        'approval_identity': '5b860bbe27ba8ec7893fe1baab71a3d77c5b4c7c965e490c44846b8a81fc4cba',
    }
    assert all(getattr(runtime, name)()['digest'] == digest for name, digest in expected.items())


def test_orphan_remote_delivery_is_not_called_undelivered(prepared):
    root, plan = prepared
    complete(root, plan)
    tracker.deliver(root)
    (root/'assessment.json').unlink()
    (root/'readback.json').unlink()
    before = snapshot(root)
    value = context.project(root)
    assert value['status'] == 'refused'
    assert snapshot(root) == before
    assert_safe(value, root)
