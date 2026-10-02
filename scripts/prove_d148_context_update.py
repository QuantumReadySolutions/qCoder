"""Two-phase dev7->dev8 proof on newly created synthetic isolated states only.

Requires copied test_d148.py on the proof runner's import path. Never pass a
canonical workspace: prepare exclusively creates a new directory itself.
"""
import argparse
import hashlib
import json
from pathlib import Path

from qcoder.ml_research import job, tracker, runtime
from qcoder.ml_research.contracts import now, read, seal, write_new
from qcoder.focused_loop.canonical import canonical_digest


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--phase', choices=('prepare','verify'), required=True)
    args = parser.parse_args()
    root = args.root
    if args.phase == 'prepare':
        from test_d148 import prepared, approval_seam
        root.mkdir()  # Refuse existing state, including every canonical workspace.
        for state in ('prepared','completed'):
            path = root/state
            path.mkdir()
            _, plan = prepared.__wrapped__(path)
            if state == 'prepared': continue
            approval_seam(path, plan)
            entry = seal({'schema':'d148.entry.v1','attempt_id':plan['attempt_id'],
                          'plan_digest':plan['digest'], 'approval_digest':read(path/'approval.json')['digest'],
                          'entered_at':now(), 'research_job_attempts':1,'outcome':'unknown_until_durable_completion'})
            write_new(path/'entered.json', entry)
            labels = read(path/'test.json')['labels']
            predictions = labels[:37] + [1-x for x in labels[37:]]
            outcome = {'predictions':{role:predictions for role in ('candidate','baseline')},
                       'test_ids':read(path/'test.json')['ids'], 'accounting':{
                           'research_job_attempts':1,'candidate_model_invocations':40,'baseline_model_invocations':40,
                           'qnode_invocations':40,'heldout_examples_per_model':40,'heldout_examples_unique':40,
                           'heldout_model_example_pairs':80,'shots':None,'shots_semantics':'not_applicable',
                           'pennylane_tracker':{'executions':40,'simulations':40,'batches':40},
                           'device_count_provenance':'synthetic proof only'}}
            receipt = seal({'schema':'d148.receipt.v1','entry_digest':entry['digest'],'plan_digest':plan['digest'],
                            'status':'completed','outcome_digest':canonical_digest(outcome),'ended_at':now(),'elapsed_seconds':0.01})
            write_new(path/'receipt.json',receipt)
            write_new(path/'result.json',job.result_from(path,plan,outcome,receipt))
            tracker.deliver(path)
        record = {'test_only':'synthetic sin/cos; constructed outcome; zero evaluator calls',
                  'identities':{name:getattr(runtime,name)()['digest'] for name in ('code_identity','scientific_identity','approval_identity','scientific_runtime')},
                  'snapshots':{state:snapshot(root/state) for state in ('prepared','completed')}}
        (root/'before.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n')
        print(json.dumps({'status':'dev7_synthetic_states_prepared','new_canonical_science':0}))
    else:
        from qcoder.ml_research.client_context import project
        before = json.loads((root/'before.json').read_text())
        assert all(getattr(runtime,n)()['digest'] == d for n,d in before['identities'].items())
        def forbidden(*a, **k): raise AssertionError('evaluator called')
        job.evaluate = forbidden
        views = {state:project(root/state) for state in ('prepared','completed')}
        assert views['prepared']['lifecycle_state'] == 'prepared_awaiting_user_authority'
        assert views['completed']['lifecycle_state'] == 'completed_delivered_verified_readback'
        assert views['completed']['qcoder_established']['metrics']['candidate']['correct'] == 37
        assert job.run(root/'completed')['new_research_jobs'] == 0
        assert all(snapshot(root/state) == before['snapshots'][state] for state in views)
        print(json.dumps({'status':'dev7_to_dev8_state_preservation_pass','new_canonical_science':0,
                          'identities_preserved':before['identities'], 'workspace_bytes_preserved':True,
                          'exact_reuse_new_jobs':0,'projections':views}, sort_keys=True,indent=2))


if __name__ == '__main__':
    main()
