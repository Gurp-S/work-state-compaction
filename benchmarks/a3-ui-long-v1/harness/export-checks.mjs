import assert from 'node:assert/strict';
import {modelIdentity} from './contract-fixtures.mjs';

const identity=row=>JSON.stringify(modelIdentity(row));
function subset(actual,expected,label) {
  assert(actual&&typeof actual==='object',`${label}: object missing`);
  for(const [key,value] of Object.entries(expected)) {
    assert.deepEqual(actual[key],value,`${label}.${key}`);
  }
}
function sameRows(actual,expected) {
  assert(Array.isArray(actual),'rows missing');
  assert.equal(actual.length,expected.length,'row count');
  const rows=new Map(actual.map(row=>[identity(row),row]));
  assert.equal(rows.size,actual.length,'duplicate model identity');
  for(const row of expected) subset(rows.get(identity(row)),row,identity(row));
}
export function checkAllExport(payload,report,detail=null) {
  subset(payload,{source:'live_ledger',schema_version:1,generated_at:report.generated_at,
    scope:{kind:'all',day:null,models:[]}},'export');
  assert.equal(payload.report?.days?.length,report.days.length,'report days');
  subset(payload.report,{ok:true,live:true,generated_at:report.generated_at,day_count:report.day_count},'report');
  subset(payload.report.source,report.source,'report.source');
  const days=new Map(payload.report.days.map(day=>[day.day,day]));
  assert.equal(days.size,report.days.length,'duplicate day');
  for(const day of report.days) {
    const {by_model,...values}=day;
    subset(days.get(day.day),values,day.day);
    sameRows(days.get(day.day).by_model,by_model);
  }
  if(detail===null) assert.equal(payload.day_detail,null,'unloaded detail');
  else {
    assert.equal(payload.day_detail?.day,detail.day,'stale detail');
    assert.deepEqual(payload.day_detail.turns.map(t=>t.events.map(e=>[e.request_id,e.provider,e.model,e.cost_cny])),
      detail.turns.map(t=>t.events.map(e=>[e.request_id,e.provider,e.model,e.cost_cny])),'detail event identity and cost');
  }
}
export function checkFilteredExport(payload,report,date,identities) {
  const day=report.days.find(d=>d.day===date);
  assert(day,'selected date missing');
  const wanted=new Set(identities.map(i=>JSON.stringify(i)));
  assert.equal(wanted.size,identities.length,'duplicate requested identities');
  const rows=day.by_model.filter(row=>wanted.has(identity(row)));
  assert.equal(rows.length,identities.length,'unknown selected identity');
  subset(payload,{source:'live_ledger',schema_version:1,generated_at:report.generated_at},'filtered export');
  assert.equal(payload.scope?.kind,'filtered');assert.equal(payload.scope?.day,date);
  assert.deepEqual(payload.scope.models.map(i=>JSON.stringify(i)).sort(),[...wanted].sort(),'filter scope');
  sameRows(payload.rows,rows);
  assert.equal(payload.report,undefined,'filtered export includes full report');
}
