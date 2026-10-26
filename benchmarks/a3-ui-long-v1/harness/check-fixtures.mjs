// Author-side fixture consistency, not application acceptance.
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {contractReport,contractDetail,modelIdentity} from './contract-fixtures.mjs';

const checks=[];
const near=(a,b)=>assert(Math.abs(a-b)<1e-7,`${a} != ${b}`);
for(const scenario of ['normal','unknown','zero','unpriced','small_cost','collision','long_names','large']) {
  const report=contractReport(scenario);
  assert.equal(report.days.length,report.day_count);
  for(const day of report.days) {
    assert(day.day<=report.generated_at.slice(0,10));
    for(const key of ['requests','prompt_tokens','cache_hit','cache_miss','output','tokens','cost_unknown_requests']) {
      near(day[key],day.by_model.reduce((n,r)=>n+r[key],0));
    }
    if(day.cost_cny!==null) near(day.cost_cny,day.by_model.reduce((n,r)=>n+(r.cost_cny??0),0));
    assert.equal(new Set(day.by_model.map(r=>JSON.stringify(modelIdentity(r)))).size,day.by_model.length);
  }
  const day=report.days.at(-1);
  const detail=contractDetail(day.day,scenario);
  near(detail.turns.reduce((n,t)=>n+t.events.length,0),day.requests);
  for(const key of ['requests','prompt_tokens','cache_hit','cache_miss','output','tokens','cost_unknown_requests'])
    near(detail.turns.reduce((n,t)=>n+t[key],0),day[key]);
  for(const turn of detail.turns) {
    near(turn.events.reduce((n,e)=>n+e.prompt_tokens,0),turn.prompt_tokens);
    if(turn.cost_cny!==null) near(turn.events.reduce((n,e)=>n+(e.cost_cny??0),0),turn.cost_cny);
    assert(turn.label.startsWith(day.day));
  }
  checks.push({scenario,days:report.days.length,detail_turns:detail.turns.length,detail_events:day.requests});
}
for(const scenario of ['empty','missing_store']) {
  assert.equal(contractReport(scenario).days.length,0);
  assert.equal(contractDetail('2026-10-22',scenario).missing,true);
  checks.push({scenario,empty:true});
}
assert.equal(contractReport('missing_fields').days.at(-1).requests,null);
checks.push({scenario:'missing_fields',null_preserved:true});
const collision=contractReport('collision').days.at(-1).by_model;
assert.equal(collision[0].model,collision[1].model);
assert.notEqual(collision[0].provider,collision[1].provider);
const files={};
for(const name of ['fixtures.mjs','contract-fixtures.mjs','check-fixtures.mjs']) {
  const data=await readFile(new URL(name,import.meta.url));
  files[name]=createHash('sha256').update(data).digest('hex');
}
const result={passed:true,checks,source_manifest:files,scope:'Fixture arithmetic and identity only; not browser or task qualification',model_calls:0};
if(!process.argv[2]) throw new Error('new receipt path required');
await writeFile(process.argv[2],JSON.stringify(result,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({passed:true,scenarios:checks.length,large:checks.find(c=>c.scenario==='large')}));
