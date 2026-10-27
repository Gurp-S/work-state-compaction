"""CLI entry. Results are append-only per output directory; no scoring LLM."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
from hashlib import sha256
import sys
import time
from dataset import generate,canonical,seal
from evaluator import evaluate
from adapters import Identity,WscReplay,audit_native_archive
from report import write_report
from cases import lifecycle


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--adapters',default='identity-control,wsc-fixed-selection')
    parser.add_argument('--seed',type=int,default=1)
    parser.add_argument('--rounds',type=int,default=5)
    parser.add_argument('--noise',type=int,default=10)
    parser.add_argument('--byte-budget',type=int,default=32768)
    parser.add_argument('--token-budget',type=int)
    parser.add_argument('--encoding',default='o200k_base')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--dataset',type=Path)
    parser.add_argument('--case',choices=('synthetic','artifact-lifecycle','version-validation'),default='synthetic')
    parser.add_argument('--oracle',type=Path)
    parser.add_argument('--generator-command-json')
    parser.add_argument('--model-config-json')
    parser.add_argument('--selection-ordinals-json')
    parser.add_argument('--native-archive',type=Path)
    parser.add_argument('--recovery-calls',type=int,default=64)
    parser.add_argument('--recovery-bytes',type=int,default=32768)
    parser.add_argument('--rerun-failed',type=Path)
    args=parser.parse_args()
    if min(args.byte_budget,args.recovery_calls,args.recovery_bytes)<=0:parser.error('budgets must be positive')
    if args.token_budget is not None and args.token_budget<=0:parser.error('token budget must be positive')
    if args.generator_command_json and not args.model_config_json:parser.error('generator requires registered model config')
    if bool(args.dataset)!=bool(args.oracle):parser.error('dataset and oracle must be supplied together')
    args.out.mkdir(parents=True,exist_ok=False)
    public,oracle=(json.loads(args.dataset.read_text(encoding='utf-8')),json.loads(args.oracle.read_text(encoding='utf-8'))) if args.dataset else (generate(args.seed,args.rounds,args.noise) if args.case=='synthetic' else lifecycle(args.case))
    assert oracle['public_sha256']==seal(public),'oracle_dataset_binding_mismatch'
    for name,value in [('dataset.public.json',public)]:
        (args.out/name).write_text(canonical(value),encoding='utf-8')
    tokenizer=None
    try:
        import tiktoken
        tokenizer=tiktoken.get_encoding(args.encoding)
    except (ImportError,ValueError):pass
    run=dict(schema='wsc.benchmark.run/1',public_sha256=seal(public),environment=dict(python=sys.version,platform=platform.platform()),
        config={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
        tokenizer=dict(encoding=args.encoding,available=tokenizer is not None,model_encoding_verified=False),
        limitations=['No native live run was dispatched; native archive audit is unmatched input.',
            'Exact model-token equivalence is unverified; tokenizer counts, if available, are encoding-specific.',
            'Fixed full selection is not the WSC semantic algorithm or a replacement for native Codex.',
            'No inference about free-text semantics, Agent behavior, monetary savings or full goal success.'],
        experiments=dict(A='stage-only protocol replay',B='not executed without verified common tokenizer/model budget',
            C='repeated stage-only checkpoints; not native repeated installation',D='predefined overwrite/conflict protocol',
            E='bounded real WSC evidence read',F='noise/constraints/expiry/dependencies; broader real-trace cases pending'),results=[])
    code_root=Path(__file__).resolve().parent
    source_root=code_root.parents[1]/'src/wsc'
    run['environment']['source_sha256']={str(p):sha256(p.read_bytes()).hexdigest()
        for base in (code_root,source_root) for p in base.rglob('*.py')}
    run['fairness']=dict(shared_rendered_byte_limit=args.byte_budget,
        WSC_internal_serialized_view_byte_limit=args.byte_budget,
        internal_view_bytes_are_not_context_bytes=True,model_parameters_verified=False,
        oracle_on_disk_during_compression=False,paired_native_comparison=False)
    prior=json.loads(args.rerun_failed.read_text(encoding='utf-8')) if args.rerun_failed else None
    if prior and prior['public_sha256']!=seal(public):raise ValueError('rerun_dataset_mismatch')
    failed_adapters={x['adapter'] for x in prior['results'] if x['status']!='measured' or x.get('hot',{}).get('incorrect',0)>0} if prior else None
    for name in args.adapters.split(','):
        if failed_adapters is not None and name not in failed_adapters:continue
        area=args.out/name;area.mkdir()
        if name=='identity-control':adapter=Identity()
        elif name in ('wsc-fixed-selection','wsc-generator'):
            command=json.loads(args.generator_command_json) if args.generator_command_json else None
            if name=='wsc-generator' and command is None:raise ValueError('registered_generator_missing')
            adapter=WscReplay(area,generator=command if name=='wsc-generator' else None,
                selection_ordinals=json.loads(args.selection_ordinals_json) if args.selection_ordinals_json else None)
        else:raise ValueError('unknown_adapter:'+name)
        for checkpoint,answer in zip(public['checkpoints'],oracle['answers'],strict=True):
            number=checkpoint['round'];cell=area/f'round-{number:03d}';cell.mkdir()
            row=dict(adapter=name,round=number,status='failed',scope=adapter.scope)
            begin=time.perf_counter()
            try:
                if args.token_budget is not None:
                    raise ValueError('equal_token_experiment_unavailable_without_verified_model_tokenization_and_capacity')
                product=adapter.compress(public['events'][:checkpoint['event_count']],cell,byte_limit=args.byte_budget)
                raw=canonical(product['items']).encode()
                row.update(context_bytes=len(raw),context_tokens=len(tokenizer.encode(raw.decode())) if tokenizer else None,
                    external_bytes=product['external_bytes'],model_usage=product['model_usage'])
                (cell/'product.json').write_text(canonical(product),encoding='utf-8')
                if len(raw)>args.byte_budget:raise ValueError('rendered_context_byte_budget_exceeded')
                row.update(status='measured')
                if hasattr(adapter,'recover'):
                    recovery=adapter.recover(args.recovery_calls,args.recovery_bytes)
                    row['recovery']=recovery
            except Exception as error:row['error']=type(error).__name__+':'+str(error)
            row['seconds']=time.perf_counter()-begin
            (cell/'result.json').write_text(canonical(row),encoding='utf-8');run['results'].append(row)
    # Only now are answers/scoring material written. Adapters never receive oracle.
    (args.out/'oracle.private.json').write_text(canonical(oracle),encoding='utf-8')
    by_round={c['round']:(c,a) for c,a in zip(public['checkpoints'],oracle['answers'],strict=True)}
    for row in run['results']:
        if row['status']!='measured':continue
        cell=args.out/row['adapter']/f"round-{row['round']:03d}"
        product=json.loads((cell/'product.json').read_text(encoding='utf-8'))
        checkpoint,answer=by_round[row['round']]
        row['hot']=evaluate(product['items'],answer,checkpoint['tick'])
        if 'recovery' in row:
            combined=product['items']+row['recovery']['items']
            row['recovery']['evaluation']=evaluate(combined,answer,checkpoint['tick'])
            row['recovery']['expanded_context_bytes']=len(canonical(combined).encode())
            row['recovery']['equal_hot_byte_budget_met']=row['recovery']['expanded_context_bytes']<=args.byte_budget
        (cell/'result.json').write_text(canonical(row),encoding='utf-8')
    if args.native_archive:
        native=audit_native_archive(args.native_archive)
        (args.out/'native-archive.json').write_text(canonical(native),encoding='utf-8')
        run['native_archive']=dict(source_sha256=native['source_sha256'],boundaries=len(native['compactions']),paired=False)
    (args.out/'results.json').write_text(canonical(run),encoding='utf-8');write_report(args.out,run)
    print(canonical(dict(out=str(args.out),cells=len(run['results']),
        execution_errors=sum(x['status']!='measured' for x in run['results']),
        hot_incorrect_questions=sum(x.get('hot',{}).get('incorrect',0) for x in run['results']),
        hot_undecidable_questions=sum(x.get('hot',{}).get('undecidable',0) for x in run['results']),scoring_model_calls=0)))


if __name__=='__main__':main()
