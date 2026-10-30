"""Existing native V2 stage plus blackbox completion evidence; no summary access."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'benchmarks/deterministic_v1'))
from blackbox import compression_evidence
from native_evidence import state, save
from native_rollout_snapshot import parse_rollout


def bounded(path,limit):
    with Path(path).open('rb') as source:raw=source.read(limit+1)
    if len(raw)>limit:raise ValueError('chain_native_evidence_size_exceeded')
    return raw


def compact(session,destination,limits,record_phase,*,max_evidence_bytes=32*1024*1024):
    if type(max_evidence_bytes) is not int or max_evidence_bytes<=0:
        raise ValueError('chain_native_evidence_limit_invalid')
    area=Path(destination);area.mkdir(parents=True,exist_ok=False)
    before=bounded(session.rollout_path(),max_evidence_bytes)
    (area/'before.jsonl').write_bytes(before)
    phase=session.execute_stage('Native compaction boundary',area/'phase',limits,record_phase,compact=True)
    after=bounded(area/'phase/rollout.jsonl',max_evidence_bytes)
    events=[json.loads(line) for line in bounded(area/'phase/events.jsonl',max_evidence_bytes).splitlines() if line]
    proof=compression_evidence(before,after,phase,events)
    effective=state(parse_rollout(after).rows)
    opaque=sum(item.get('type')=='compaction' and type(item.get('encrypted_content')) is str for item in effective)
    result=dict(confirmed=proof['confirmed'] and opaque>0,compression_evidence=proof,
        opaque_item_count=opaque,summary_content_inspected=False,usage_complete=phase.get('usage_complete'),
        scope='Native V2 compaction completion only, not information fidelity or task success.')
    save(area/'compression-evidence.json',result)
    return result
