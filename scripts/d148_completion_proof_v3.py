"""Verify an already completed D-148 job, real read-back and zero-science reuse."""
import argparse,hashlib,json,time
from datetime import datetime,timezone
from pathlib import Path
from qcoder.ml_research import job,tracker
from qcoder.ml_research.contracts import read,seal,write_new
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--workspace',type=Path,required=True)
parser.add_argument('--evidence',type=Path,required=True)
args=parser.parse_args()
root=args.workspace
out=args.evidence
out.mkdir(parents=True,exist_ok=True)
assert not any((out/name).exists() for name in ('completion-proof.json','approval.json','result.json')), 'fresh evidence destination required'
immutable=(*job.INPUT_FILES,'plan.json','approval.json','entered.json','receipt.json','result.json','assessment.json','readback.json','qcoder-assessment.json')
hashes=lambda:{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in immutable}
before=hashes()
start=time.perf_counter();plan,result=job.verify_completed(root);verification_seconds=time.perf_counter()-start
approval=job.valid_approval(root,plan,completed=True)
entry=read(root/'entered.json');receipt=read(root/'receipt.json');assessment=read(root/'assessment.json')
assert approval['approved_at'] <= entry['entered_at'] <= receipt['ended_at'] <= assessment['tracker_write_time']
start=time.perf_counter();repeated=job.run(root);reuse_seconds=time.perf_counter()-start
assert repeated['reused'] and repeated['new_research_jobs']==0 and repeated['result']==result
assert hashes()==before
start=time.perf_counter();delivered=tracker.deliver(root);delivery_seconds=time.perf_counter()-start
start=time.perf_counter();verified=tracker.readback(root,assessment);readback_seconds=time.perf_counter()-start
assert delivered['projection']==verified['projection']==assessment
assert verified['result_digest']==result['digest'] and verified['assessment_digest']==assessment['digest']
assert hashes()==before
for name in ('approval','entered','receipt','result','assessment','readback'):
 raw=(root/(name+'.json')).read_bytes()
 with (out/(name+'.json')).open('xb') as stream:stream.write(raw)
write_new(out/'repeat-response.json',seal({'schema':'d148.completed_repeat.v1',**repeated}))
write_new(out/'fresh-readback.json',verified)
body={'schema':'d148.canonical_completion_verification.v1','observed_completed_before_this_turn_dispatch':True,'this_turn_new_scientific_jobs':0,'original_invoking_process_authorship':'not_established; pre-existing accepted records independently verified','approval_digest':approval['digest'],'plan_digest':plan['digest'],'job_id':plan['job_id'],'attempt_id':plan['attempt_id'],'entry_digest':entry['digest'],'receipt_digest':receipt['digest'],'result_digest':result['digest'],'assessment_digest':assessment['digest'],'assessment_run_id':assessment['assessment_run_id'],'source_run_ids':assessment['source_run_ids'],'metrics':result['metrics'],'accounting':result['accounting'],'evidence_conclusion':result['evidence_conclusion'],'next_action':result['next_action'],'compatible':result['compatible'],'authority_precedes_entry':True,'immutable_files_before':before,'immutable_files_after':hashes(),'reuse_new_research_jobs':0,'duplicate_delivery_same_assessment':True,'real_client_readback_verified':True,'installed_origin':job.__file__,'times_utc':{name:datetime.fromtimestamp(value,tz=timezone.utc).isoformat() for name,value in {'approval':approval['approved_at'],'entry':entry['entered_at'],'evaluation_complete':receipt['ended_at'],'assessment_write':assessment['tracker_write_time']}.items()},'latency_seconds':{'original_science_receipt_elapsed_including_post_currentness':receipt['elapsed_seconds'],'completed_verification':verification_seconds,'exact_result_reuse':reuse_seconds,'duplicate_delivery_with_readback':delivery_seconds,'separate_real_readback':readback_seconds,'original_delivery_wall_time':None,'original_natural_client_wall_time':None},'provenance':{'qcoder_established':['exact joins','metric recomputation','currentness','MLflow readback','reuse'],'external_reported':['Rob performed foreground approval (current user report)'],'assistant_inference':[],'not_established':['original invoking process authorship','original natural-client end-to-end timing','quantum advantage']}}
write_new(out/'completion-proof.json',seal(body))
print(json.dumps({k:body[k] for k in ('metrics','accounting','evidence_conclusion','next_action','reuse_new_research_jobs','times_utc','latency_seconds')},indent=2))
