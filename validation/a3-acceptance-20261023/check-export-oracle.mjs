// Validate the download oracle with valid data and independently corrupted payloads.
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {contractReport,contractDetail,modelIdentity} from '../../benchmarks/a3-ui-long-v1/harness/contract-fixtures.mjs';
import {checkAllExport,checkFilteredExport} from '../../benchmarks/a3-ui-long-v1/harness/export-checks.mjs';

const report=contractReport('unknown');
const base={source:'live_ledger',schema_version:1,generated_at:report.generated_at,
  scope:{kind:'all',day:null,models:[]},report:structuredClone(report),day_detail:null};
checkAllExport(base,report);
const withDetail=structuredClone(base);withDetail.day_detail=contractDetail('2026-10-22','unknown');
checkAllExport(withDetail,report,contractDetail('2026-10-22','unknown'));
const row=report.days.at(-1).by_model[1];
const filtered={source:'live_ledger',schema_version:1,generated_at:report.generated_at,
  scope:{kind:'filtered',day:'2026-10-22',models:[modelIdentity(row)]},rows:[structuredClone(row)]};
checkFilteredExport(filtered,report,'2026-10-22',[modelIdentity(row)]);
const rejected=[];
for(const [name,change] of [
  ['unknown_to_zero',p=>{p.report.days[1].by_model[1].cost_cny=0;}],
  ['lost_provider',p=>{delete p.report.days[1].by_model[1].provider;}],
  ['missing_day',p=>{p.report.days.pop();}],
  ['wrong_scope',p=>{p.scope.kind='filtered';}],
  ['duplicate_model',p=>{p.report.days[1].by_model[1]=structuredClone(p.report.days[1].by_model[0]);}],
  ['invented_detail',p=>{p.day_detail={day:'2026-10-21'};}],
]) {
  const payload=structuredClone(base);change(payload);
  assert.throws(()=>checkAllExport(payload,report),name);rejected.push(name);
}
for(const [name,change] of [
  ['unselected_row_leaked',p=>p.rows.push(structuredClone(report.days[1].by_model[0]))],
  ['filtered_zero_unknown',p=>{p.rows[0].cost_cny=0;}],
  ['stale_filter_day',p=>{p.scope.day='2026-10-21';}],
  ['full_report_in_filtered',p=>{p.report=report;}],
]) {
  const payload=structuredClone(filtered);change(payload);
  assert.throws(()=>checkFilteredExport(payload,report,'2026-10-22',[modelIdentity(row)]),name);rejected.push(name);
}
const collision=contractReport('collision');
const selected=collision.days.at(-1).by_model[0];
const collisionFiltered={...filtered,generated_at:collision.generated_at,
  scope:{kind:'filtered',day:'2026-10-22',models:[modelIdentity(selected)]},rows:[selected]};
checkFilteredExport(collisionFiltered,collision,'2026-10-22',[modelIdentity(selected)]);
const source_manifest={};
for(const relative of ['check-export-oracle.mjs','../../benchmarks/a3-ui-long-v1/harness/export-checks.mjs',
  '../../benchmarks/a3-ui-long-v1/harness/contract-fixtures.mjs','../../benchmarks/a3-ui-long-v1/harness/fixtures.mjs']) {
  source_manifest[relative]=createHash('sha256').update(await readFile(new URL(relative,import.meta.url))).digest('hex');
}
await writeFile(new URL('export-oracle-checks.json',import.meta.url),JSON.stringify({passed:true,
  accepted_examples:4,rejected_mutations:rejected,source_manifest,model_calls:0,
  scope:'JSON download oracle calibration; not browser UI acceptance'},null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({accepted:4,rejected:rejected.length}));
