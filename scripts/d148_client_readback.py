"""Read-only Phase E projection from installed qCoder and real local MLflow.

No evaluator, authority, tracker mutation, source/model import, or LLM integration.
This acceptance launcher is outside the wheel; hash it with the client binding.
"""
import argparse
import json
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    args = parser.parse_args()
    from qcoder.ml_research import job, tracker
    from qcoder.ml_research.contracts import read, seal
    from pathlib import Path
    start = time.perf_counter()
    root = Path(args.workspace)
    plan, result = job.verify_completed(root)
    verified = tracker.readback(root, read(root / 'assessment.json'))
    value = verified['projection']
    assert value['result_digest'] == result['digest']
    assert value['plan_digest'] == plan['digest']
    assert value['source_run_ids'] == {role: plan['selected'][role]['run_id'] for role in ('candidate', 'baseline')}
    assert all(value[key] == result[key] for key in ('job_id', 'receipt_digest', 'metrics', 'accounting', 'evidence_conclusion', 'next_action', 'evaluation_time'))
    # Small share-safe current-task view: no raw rows, labels, predictions,
    # checkpoint weights, source text, local paths, UID, terminal or free text.
    established = {key: value[key] for key in ('source_run_ids', 'assessment_run_id', 'job_id', 'plan_digest', 'result_digest', 'receipt_digest', 'metrics', 'accounting', 'evidence_conclusion', 'next_action', 'rationale', 'limitations', 'evaluation_time', 'tracker_write_time')}
    established.update(assessment_digest=value['digest'], readback_digest=verified['digest'], evaluation_state=result['evaluation_state'], currentness=result['currentness'])
    established['scientific_digests'] = {key: value['identities'][key] for key in ('fixture_digest', 'data_digest', 'labels_digest', 'split_digest', 'preprocessing_digest')}
    projection = seal({'schema': 'd148.client_readback_projection.v1', 'qcoder_established': established,
                       'external_reported': {role: plan['selected'][role]['external_reported'] for role in ('candidate', 'baseline')},
                       'assistant_inference': [],
                       'not_established': ['quantum advantage', 'population/general performance', 'refinement outcome', 'authorship or test basis of excluded tracker free text'],
                       'new_scientific_jobs': 0, 'projection_operation_seconds': time.perf_counter() - start})
    print(json.dumps(projection, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
