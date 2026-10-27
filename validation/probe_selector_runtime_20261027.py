"""Zero-model, private-process startup experiment; native B is untouched."""
from pathlib import Path
import argparse,json,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from native_owned_process import OwnedNativeRPC
from native_host_controls import settings
from native_source_tool import SOURCE_TOOL
from native_evidence import read,save,state
from native_rollout_snapshot import capture_rollout


def main():
    parser=argparse.ArgumentParser()
    for name in ('registration','baseline','workspace','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--omit-global-memory',action='store_true')
    parser.add_argument('--skills-context-tokens',type=int)
    parser.add_argument('--omit-apps',action='store_true')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    instructions=args.out/'selector-facts.json'
    instructions.write_text(json.dumps(dict(component='working_state_selection',generation_scope='selection_without_task_execution',semantic_status='unverified')),encoding='utf-8')
    base=read(args.registration)['sessions']['B'];reg={**base,'workspace':str(args.workspace)}
    for key in ('browser_cache','native_c_auto_compaction'):reg.pop(key,None)
    extra=['features.shell_tool=false','features.skip_host_skill_discovery=true','model_instructions_file='+json.dumps(str(instructions.resolve()))]
    if args.omit_global_memory:extra.append('memories.use_memories=false')
    if args.skills_context_tokens is not None:
        if args.skills_context_tokens<1:raise ValueError('skills_context_budget_invalid')
        extra.append('skills.max_context_tokens='+str(args.skills_context_tokens))
    if args.omit_apps:extra.append('features.apps=false')
    server=None;begin=time.monotonic();result=dict(model_calls=0,inference_sent=False,configuration_only=True,settings=extra)
    try:
        server=OwnedNativeRPC(reg['executable'],cwd=args.workspace,stderr_path=args.out/'stderr.txt',settings=settings(reg)+extra)
        save(args.out/'initialized.json',server.call('initialize',{'clientInfo':{'name':'wsc_selector_scope_probe','version':'1'},'capabilities':{'experimentalApi':True}}));server.send({'method':'initialized'})
        opened=server.call('thread/start',dict(cwd=str(args.workspace),model=reg['model'],allowProviderModelFallback=False,approvalPolicy='never',sandbox='read-only',runtimeWorkspaceRoots=[str(args.workspace)],ephemeral=False,dynamicTools=[SOURCE_TOOL]))
        save(args.out/'opened.json',opened)
        server.call('thread/inject_items',dict(threadId=opened['thread']['id'],items=[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'{"record_type":"selector_scope_probe/1"}'}]}]))
        snap=capture_rollout(opened['thread']['path'],archive=args.out/'bootstrap.jsonl')
        if not snap.metadata['parse_complete'] or any(r['type']=='token_usage_record' for r in snap.rows):raise ValueError('unexpected_source_or_inference')
        def measure(values):return [{'type':v.get('type'),'role':v.get('role'),'bytes':len(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())} for v in values]
        result.update(status='observed',baseline=measure(state(capture_rollout(args.baseline).rows)),candidate=measure(state(snap.rows)),source_sha256=snap.metadata['sha256'],actual_model_input_tokens=None,
            generic_tools_absent_proven=False,scope='Startup packets only, no model request or behavioral claim. Configuration acceptance is not proof of a narrowed effective tool surface.')
    except Exception as error:result.update(status='failed_preserved',error=type(error).__name__+':'+str(error))
    finally:
        result['cleanup']=server.close() if server else None;result['seconds']=time.monotonic()-begin;save(args.out/'result.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
