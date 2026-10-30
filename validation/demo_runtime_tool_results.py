"""Actual local tool/CLI roundtrip; no LLM, task grading, or native comparison."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from wsc.contracts import encode
from wsc.tool_results import ResultStore,RuntimeResults,ResultPolicy,ToolText,ResultQueryTool
from wsc.denoise.strip_noise_lines import clean as old_clean


def save(path,value):
    with path.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)


def main(out):
    out.mkdir(parents=True,exist_ok=False)
    calls=[]
    def tool():
        calls.append(1)
        code="import json;print(json.dumps({'rows':[{'id':i,'payload':'sample '*30} for i in range(3500)],'revision':3}))"
        r=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,check=True)
        return ToolText(r.stdout.decode('utf-8'),kind='json',status='success',exit_code=r.returncode)
    original=tool()
    api=RuntimeResults(ResultStore(out/'store',session='demo'),policy=ResultPolicy(enabled=True))
    view=api.call('tool-call-1',lambda:original)
    assert calls==[1] and view['external']
    save(out/'model-view.json',view)
    rid=view['result_id'];record=api.store.record(rid)
    raw_path=api.store.objects/(record['hash']+'.txt')
    assert raw_path.read_bytes()==original.text.encode('utf-8')
    query=ResultQueryTool(api).call(dict(operation='json_pointer',result_id=rid,pointer='/rows/2048/id'))
    assert query.recovery and json.loads(query.text)['value']==2048
    recovery_view=api.present('query-call',query)
    assert recovery_view['recovery'] and not recovery_view['external']
    save(out/'query-view.json',recovery_view)
    env=dict(os.environ,PYTHONPATH=str(ROOT/'src'))
    cli=[sys.executable,'-B','-X','utf8','-m','wsc.tool_results.cli','--root',str(api.store.root),'--session','demo']
    actual=subprocess.run(cli+['present','--input',str(raw_path),'--call-id','tool-call-1','--kind','json','--status','success','--exit-code','0'],
                          capture_output=True,text=True,encoding='utf-8',env=env)
    assert actual.returncode==0 and json.loads(actual.stdout)==view
    save(out/'cli-present.json',dict(command=cli+['present'],exit_code=actual.returncode,stdout=actual.stdout,stderr=actual.stderr))
    actual=subprocess.run(cli+['json-pointer','--id',rid,'--pointer','/rows/2048/id'],capture_output=True,text=True,encoding='utf-8',env=env)
    assert actual.returncode==0 and json.loads(actual.stdout)['value']==2048
    save(out/'cli-query.json',dict(exit_code=actual.returncode,stdout=actual.stdout,stderr=actual.stderr))
    # Same CRLF source, old display rule versus new externalized representation.
    log='retained producer line\r\n'*3000
    legacy=old_clean(log)
    newer=api.present('crlf',ToolText(log,kind='terminal_log'))
    assert newer['external'] and 'retained producer line' in newer['text']
    chunks=[];offset=0
    while True:
        page=api.read(newer['result_id'],offset=offset,limit=32768);chunks.append(page['text'])
        if page['next_offset'] is None:break
        offset=page['next_offset']
    assert ''.join(chunks)==log
    save(out/'crlf-before-after.json',dict(source_sha256=sha256(log.encode()).hexdigest(),original_bytes=len(log.encode()),
         legacy_view_bytes=len(legacy.encode()),legacy_lost_body='retained producer line' not in legacy,
         new_view_preserves_preview=True,new_original_roundtrip=True,legacy_module_unchanged=True))
    sources=[ROOT/'src/wsc/tool_results'/name for name in ('__init__.py','storage.py','strategies.py','query_tool.py','cli.py')]
    result=dict(scope='Synthetic mechanism demo; no task quality or native comparison',model_calls=0,tool_executions=len(calls),
        producer_text_bytes=len(original.text.encode()),complete_model_view_bytes=len(encode(view).encode()),
        original_file_sha256=sha256(raw_path.read_bytes()).hexdigest(),json_query_exact=True,cli_roundtrip=True,
        recovery_not_summarized=True,actual_token_savings=None,model_task_quality=None,
        source_sha256={str(p):sha256(p.read_bytes()).hexdigest() for p in sources})
    save(out/'results.json',result);print(json.dumps(result))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);main(p.parse_args().out.resolve())
