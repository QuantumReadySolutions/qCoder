/* Offline component proof against the installed Cursor CLI's own hook engine.
 * NOT a fresh Agent, Carbon observation, or supported application integration.
 * Loads unmodified functions in memory; bypasses CLI startup/provider/credentials.
 * The tiny shell adapter executes only synthetic scripts in a new /tmp directory.
 */
const fs=require('fs'), os=require('os'), path=require('path'), Module=require('module');
const crypto=require('crypto'), assert=require('assert'), cp=require('child_process');
const dir=process.argv[2], configPath=process.argv[3];
if(!dir||!configPath)throw Error('Pass exact installed CLI version directory and hooks.json');
const source=fs.readFileSync(path.join(dir,'index.js'),'utf8');
const needle='var __webpack_exports__=__webpack_require__("./src/main.tsx")';
assert(source.includes(needle),'Unknown build: do not infer support');
const moduleInstance=new Module(path.join(dir,'index.js'),module);
moduleInstance.filename=path.join(dir,'index.js');
moduleInstance.paths=Module._nodeModulePaths(dir);
moduleInstance._compile(source.replace(needle,'globalThis.d148NativeRequire=__webpack_require__'),moduleInstance.filename);
const req=globalThis.d148NativeRequire;
for(const file of fs.readdirSync(dir).filter(f=>/^\d+\.index\.js$/.test(f)))
  Object.assign(req.m,require(path.join(dir,file)).modules);
const schema=req('../hooks/dist/index.js'), Engine=req('../hooks-exec/dist/index.js').WL;
const config=JSON.parse(fs.readFileSync(configPath,'utf8'));
assert(schema.RV(config).isValid, 'Native schema rejected config');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'d148-native-hook-fixture-'));
const scripts={
  deny:'printf \'%s\\n\' \'{"permission":"deny","user_message":"Unavailable."}\'',
  allow:'printf \'%s\\n\' \'{"permission":"allow"}\'',
  malformed:'printf broken', invalid:'printf \'%s\' \'{"permission":"wrong"}\'',
  invalid_submit:'printf \'%s\' \'{"continue":"wrong"}\'',
  empty:'exit 0', crash:'exit 19', timeout:'exec sleep 2',
  submit_allow:'printf \'%s\\n\' \'{"continue":true}\'',
  submit_deny:'printf \'%s\\n\' \'{"continue":false}\''
};
for(const [name,body]of Object.entries(scripts))
  fs.writeFileSync(path.join(root,name),'#!/bin/sh\n'+body+'\n',{mode:0o700});
const shell={async *execute(_context,command,options){
  const child=cp.spawn('/bin/sh',['-c',command],{cwd:options.workingDirectory,
    env:{PATH:'/usr/bin:/bin',...options.env},stdio:['pipe','pipe','pipe']});
  let stdout='',stderr='';
  child.stdout.on('data',d=>stdout+=d);child.stderr.on('data',d=>stderr+=d);
  const done=new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',code=>resolve(code));});
  const abort=()=>child.kill('SIGKILL');options.signal.addEventListener('abort',abort,{once:true});
  if(options.pipeStdin)yield {type:'stdin_ready',stdin:child.stdin};else child.stdin.end();
  const code=await done;
  options.signal.removeEventListener('abort',abort);
  if(stdout)yield {type:'stdout',data:Buffer.from(stdout)};
  if(stderr)yield {type:'stderr',data:Buffer.from(stderr)};
  yield {type:'exit',code};
}};
(async()=>{
 const engine=new Engine({projectHooks:config},root,{cursor_version:path.basename(dir)},shell,
   undefined,undefined,undefined,{commandHookPayloadTransport:'stdin'});
 const rows=[];
 for(const event of Object.keys(config.hooks)){
  for(const failure of ['missing','crash','timeout','empty','malformed','invalid']){
   const script={...config.hooks[event][0],command:'./'+(failure==='invalid' && event==='beforeSubmitPrompt'?'invalid_submit':failure),timeout:failure==='timeout'?0.05:5};
   const result=await engine.executeCommandHook(event,script,root,{},
       {hook_event_name:event,workspace_roots:[root]},'project',0);
   const blocked=result.success && (event==='beforeSubmitPrompt'?result.data.continue===false:result.data.permission==='deny');
   assert(blocked,event+' '+failure+' failed open');
   rows.push({event,failure,blocked});
  }
  const script={...config.hooks[event][0],command:'./'+(event==='beforeSubmitPrompt'?'submit_allow':'allow')};
  const result=await engine.executeCommandHook(event,script,root,{}, {hook_event_name:event},'project',0);
  assert(result.success && (event==='beforeSubmitPrompt'?result.data.continue===true:result.data.permission==='allow'));
 }
 // Demonstrate this engine's fail-open default, so the proof would catch an
 // accidentally omitted failClosed key instead of treating all errors as deny.
 const control=await engine.executeCommandHook('preToolUse', {command:'./crash',timeout:5},root,{}, {},'project',0);
 assert(!control.success,'Unexpected default: investigate changed engine');
 // Real assembled guard through the same native engine, synthetic events only.
 const python=process.argv[4], generator=process.argv[5];
 const execFile=require('util').promisify(cp.execFile);
 assert(python && generator, 'Pass the exact conference Python and control_fixture.py');
 const assembled=[];
 for(const fault of ['normal','missing','crash','timeout','empty','malformed','invalid']){
  const created=JSON.parse((await execFile(python,['-I','-B',generator,'--cursor-version','3.23.12','--case',fault],{encoding:'utf8'})).stdout);
  const fixture=created.fixture_root;
  assert(created.launcher_preflight==='verified_synthetic_denial_not_native_acceptance');
  const fixtureConfig=JSON.parse(fs.readFileSync(path.join(fixture,'.cursor/hooks.json'),'utf8'));
  assert(schema.RV(fixtureConfig).isValid);
  const fixtureEngine=new Engine({projectHooks:fixtureConfig},fixture,{cursor_version:'3.23.12'},shell,
    undefined,undefined,undefined,{commandHookPayloadTransport:'stdin'});
  const receipt=JSON.parse(fs.readFileSync(path.join(fixture,'.d148/installed.json'),'utf8'));
  const observations=Object.fromEntries(['user_rules','team_rules','enterprise_rules','plugins_and_skills','other_attachments','same_name_sources'].map(k=>[k,'none_observed']));
  fs.writeFileSync(path.join(fixture,'.d148/instruction-observation.json'),JSON.stringify({
    schema:'cursor-3.23.12-single-rule-v1', root:fixture, cursor_version:'3.23.12',
    rule_sha256:receipt.files['.cursor/rules/d148-read-only.mdc'], basis:'synthetic_component_test',observations}));
  const common={workspace_roots:[fixture],cursor_version:'3.23.12',
    conversation_id:'synthetic-engine-conversation',generation_id:'synthetic-engine-generation',cwd:fixture};
  const run=async(name,extra={})=>fixtureEngine.executeCommandHook(name,fixtureConfig.hooks[name][0],fixture,{},
    {...common,hook_event_name:name,...extra},'project',0);
  const submit=await run('beforeSubmitPrompt',{prompt:'',attachments:[{type:'rule',file_path:'d148-read-only.mdc'}]});
  assert(submit.success && submit.data.continue===true, 'Assembled submit failed '+fault);
  const action=await run('preToolUse',{tool_name:'Shell',tool_input:{command:'./qcoder-context'}});
  assert(action.success && action.data.permission===(fault==='normal'?'allow':'deny'), 'Assembled control failed '+fault);
  let marker=false;
  if(fault==='normal'){
   const terminal=await run('beforeShellExecution',{command:'./qcoder-context'});
   assert(terminal.success && terminal.data.permission==='allow');
   assert((await execFile(path.join(fixture,'qcoder-context'),[],{cwd:fixture,encoding:'utf8'})).stdout.trim()==='D148_SYNTHETIC_CONTEXT_ONLY');
   marker=true;
   for(const [name,extra]of [['preToolUse',{tool_name:'Read',tool_input:{path:'fixture-private.txt'}}],
      ['preToolUse',{tool_name:'Task',tool_input:{}}],['beforeShellExecution',{command:'./qcoder-context; pwd'}]]){
    const denied=await run(name,extra);assert(denied.success && denied.data.permission==='deny');
   }
  }
  assembled.push({case:fault,synthetic_submit_allowed:true,context_action:action.data.permission,marker_executed:marker,
    launcher_preflight:created.launcher_preflight});
 }
 const output={kind:'installed_native_engine_component_test_not_Agent_acceptance',
  client_build:path.basename(dir), index_sha256:crypto.createHash('sha256').update(source).digest('hex'),
  engine_chunk_sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(dir,'190.index.js'))).digest('hex'),
  native_schema_accepted:true, exact_configuration_failClosed:true, assembled_synthetic_controls:assembled,
  failures:rows, allow_controls:7, omitted_failClosed_control:'fails_open_as_expected',
  model:null,mode:null,provider_calls:0,scientific_jobs:0};
 console.log(JSON.stringify(output,null,2));
})().catch(e=>{console.error(e.message);process.exitCode=1;});
