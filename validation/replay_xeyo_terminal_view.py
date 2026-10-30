"""Measure existing typed terminal display on recorded outputs, never task quality."""
import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time


def digest(data):
    return sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / 'python'))
    started = time.perf_counter()
    from tools.bash_tool.output_view import SHELL_TERMINAL, denoise, prepare
    import_seconds = time.perf_counter() - started
    sources = [root / 'python/tools/bash_tool' / name for name in
               ('output_view.py', 'terminal_ops.py', 'ansi.py', 'bash_tool.py')]
    bindings = {str(p): digest(p.read_bytes()) for p in sources}
    inputs = Path(args.inputs)
    raw = inputs.read_bytes()
    receipts = json.loads(raw)['receipts']
    folder = Path(args.output).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    old_setting = os.environ.get('XEYO_OUTPUT_VIEW_OPS')
    os.environ['XEYO_OUTPUT_VIEW_OPS'] = '1'
    cases = []
    try:
        for index, receipt in enumerate(receipts):
            text = receipt['output']
            assert digest(text.encode()) == receipt['output_sha256']
            start = time.perf_counter()
            body, operations = denoise(text, output_kind=SHELL_TERMINAL)
            denoise_seconds = time.perf_counter() - start
            work = folder / f'case-{index:02d}'
            work.mkdir()
            # Deliberately avoid preview truncation; this isolates existing denoise.
            start = time.perf_counter()
            prepared = prepare(text, cwd=str(work), limit=max(8192,len(text)+8192),
                               output_kind=SHELL_TERMINAL, wire_bytes=text.encode())
            prepare_seconds = time.perf_counter() - start
            restored = None
            storage = 0
            if prepared.facts:
                raw_ref = prepared.facts['raw']
                recovered = Path(raw_ref['path']).read_bytes()
                assert digest(recovered) == receipt['output_sha256']
                assert recovered == text.encode()
                restored = True
                assert prepared.facts['truncated'] is False
                storage = sum(p.stat().st_size for p in work.rglob('*') if p.is_file())
            else:
                assert prepared.text == text
            if set(operations) <= {'crlf'}:
                assert body == text.replace('\r\n','\n')
            assert denoise(text,output_kind='unregistered')[0] == text
            cases.append(dict(rollout=receipt['rollout'],call_id=receipt['call_id'],block=receipt['block'],
                exit_code=receipt['exit_code'],operations=operations,
                original_bytes=len(text.encode()),body_bytes=len(body.encode()),
                final_view_bytes=len(prepared.text.encode()),
                persisted_bytes=storage,raw_file_roundtrip_verified=restored,
                original_kept_inline=prepared.facts is None,
                denoise_seconds=denoise_seconds,prepare_including_denoise_io_seconds=prepare_seconds,
                original_sha256=receipt['output_sha256'],view_sha256=digest(prepared.text.encode())))
        assert bindings == {str(p): digest(p.read_bytes()) for p in sources}
    finally:
        if old_setting is None:
            os.environ.pop('XEYO_OUTPUT_VIEW_OPS',None)
        else:
            os.environ['XEYO_OUTPUT_VIEW_OPS'] = old_setting
    totals = {name: sum(c[name] for c in cases) for name in
              ('original_bytes','body_bytes','final_view_bytes','persisted_bytes',
               'denoise_seconds','prepare_including_denoise_io_seconds')}
    result = dict(scope='offline existing XEYO display replay, not native runtime or model task comparison',
        new_model_calls=0,inputs_sha256=digest(raw),source_hashes=bindings,
        cases=len(cases),changed_cases=sum(bool(c['operations']) for c in cases),
        operation_counts=dict(Counter(op for c in cases for op in c['operations'])),
        import_seconds=import_seconds,totals=totals,receipts=cases,
        actual_token_savings=None,model_task_quality_verified=False,model_recovery_verified=False,
        known_wire_bytes=False,timing_distribution_qualified=False,
        note='Decoded visible receipt used as wire stand-in only; no original wire recovery claim.')
    (folder/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('receipts','source_hashes')}))


if __name__ == '__main__':
    main()
