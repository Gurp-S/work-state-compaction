// Usage: node run-acceptance.mjs <gui> <new-output> <S1..S8> [none|unknown_as_zero|stale_detail] [case-id,...]
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {openHost,here,manifest,hash} from './browser-host.mjs';
import {contractReport,contractDetail} from './contract-fixtures.mjs';
import {cases} from './acceptance-cases.mjs';

const [gui,output,stageArg,mutation='none',selection='']=process.argv.slice(2);
assert(gui&&output&&path.isAbsolute(gui)&&path.isAbsolute(output),'absolute roots required');
assert(/^S[1-8]$/.test(stageArg??''),'explicit stage required');
const stage=Number(stageArg.slice(1)),selected=selection?selection.split(','):null;
assert(!selected||selected.every(id=>cases.some(c=>c.id===id)), 'unregistered check');
const active=cases.filter(c=>c.stage<=stage&&(!selected||selected.includes(c.id)));
assert(active.length,'no checks selected');
await mkdir(output,{recursive:false});
const save=(name,value)=>writeFile(path.join(output,name),JSON.stringify(value,null,2)+'\n',{flag:'wx'});
const before=await manifest(path.join(gui,'src'));
const harnessBefore=await manifest(here);
const contractFile=path.join(here,'../public-contract.json');
const contract=JSON.parse(await readFile(contractFile,'utf8'));
await save('registration.json',{gui,stage:stageArg,mutation,selected_checks:active.map(c=>c.id),source_manifest:before,
  harness_manifest:harnessBefore,contract_sha256:hash(await readFile(contractFile)),
  package_sha256:hash(await readFile(path.join(gui,'package.json'))),
  lock_sha256:hash(await readFile(path.join(gui,'package-lock.json'))),
  source_note:'Mutation calibration transforms selected source in memory; see transformed source evidence, not current-code qualification.'});
let host;
const outcomes=[];
const deadline=setTimeout(async()=>{
  await save('deadline.json',{completed_checks:outcomes,scope:'Infrastructure deadline; not completed acceptance'});
  await host?.close();process.exit(2);
},180000);
async function bounded(promise,ms,label) {
  let timer;
  try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(label)),ms);})]);}
  finally{clearTimeout(timer);}
}
try {
  host=await openHost(gui,output,mutation);
  const {browser,expect,origin}=host;
  const testExpect=expect.configure({timeout:2500});
  await save('runtime.json',{browser:browser.version(),node:process.version,origin,mutation_evidence:host.mutationEvidence});
  for(const item of active) {
    const context=await browser.newContext({viewport:{width:1440,height:1000},locale:'zh-CN',timezoneId:'Asia/Shanghai',serviceWorkers:'block',acceptDownloads:true});
    const state={calls:[],reportFailure:item.scenario==='error',snapshotStatusFailure:false,snapshotMode:'success',reverseModels:false,holdDay:null};
    const errors=[],forbidden=[],timings={};
    let heldRoute,release,heldReady;
    const ready=new Promise(resolve=>{heldReady=resolve;});
    const gate=new Promise(resolve=>{release=resolve;});
    state.waitHeld=()=>bounded(ready,5000,'old-date request never issued');
    state.releaseHeld=async()=>{
      assert(heldRoute,'no held request');release();
      const response=await bounded(heldRoute.request().response(),5000,'old response never settled');
      if(response)await bounded(response.finished(),5000,'old response did not finish');
      state.old_response_status=response?'delivered':'request_cancelled';
    };
    await context.route('**/*',async route=>{
      const url=new URL(route.request().url());
      if(url.origin!==origin){forbidden.push(url.href);return route.abort('blockedbyclient');}
      if(!url.pathname.startsWith('/v1/'))return route.continue();
      state.calls.push(url.pathname+url.search);
      if(url.pathname==='/v1/usage/report') {
        const date=url.searchParams.get('day');
        if(date) {
          if(date===state.holdDay&&!heldRoute){heldRoute=route;heldReady();await gate;}
          // An implementation may correctly cancel the obsolete request.
          try{return await route.fulfill({json:contractDetail(date,item.scenario)});}
          catch(error){if(route.request().failure())return;throw error;}
        }
        if(state.reportFailure)return route.fulfill({status:503,json:{detail:'fixture_ledger_unavailable'}});
        const report=contractReport(item.scenario);
        if(state.reverseModels)report.days.forEach(d=>d.by_model.reverse());
        return route.fulfill({json:report});
      }
      if(url.pathname==='/v1/settings/memory/report') return state.snapshotStatusFailure
        ?route.fulfill({status:500,json:{detail:'fixture_snapshot_status_unavailable'}})
        :route.fulfill({json:{ok:true,exists:false}});
      if(url.pathname==='/v1/settings/memory/snapshot') {
        assert.equal(route.request().method(),'POST');
        return route.fulfill({status:state.snapshotMode==='unconfirmed'?503:200,json:
          state.snapshotMode==='success'?{ok:true,day:'2026-10-22',days:['2026-10-22'],rc:0}:
          state.snapshotMode==='failed'?{ok:false,error:'fixture_snapshot_failed',rc:1}:{detail:'fixture_receipt_unavailable'}});
      }
      forbidden.push(url.href);return route.abort('blockedbyclient');
    });
    const page=await context.newPage();
    page.setDefaultTimeout(5000);
    page.on('pageerror',e=>errors.push(e.message));
    await page.clock.setFixedTime(new Date('2026-10-22T10:00:00Z'));
    const begin=Date.now();
    let failure=null;
    try {
      await page.goto(origin,{waitUntil:'domcontentloaded',timeout:30000});
      if(['empty','missing_store'].includes(item.scenario))
        await expect(page.locator('[data-a3-live-status]')).toContainText(/没有用量记录|暂无.*记录/,{timeout:10000});
      else if(item.scenario==='error')await expect(page.locator('[data-a3-live-status]')).toContainText(/没读到|失败/,{timeout:10000});
      else await page.locator('[data-a3-kpi="成本"]').waitFor({timeout:30000});
      // Compilation/bootstrap is recorded separately, not part of interaction latency.
      timings.bootstrap_ms=Date.now()-begin;
      await bounded(item.run({page,expect:item.id==='C11'?expect.configure({timeout:10000}):testExpect,state,timings}),
        item.id==='C11'?60000:30000,'case execution deadline');
      assert.equal(errors.length,0,'page script error');assert.equal(forbidden.length,0,'unexpected external/API request');
    } catch(error) {failure=error.stack;}
    release();
    const screenshot=`${item.id}.png`;
    await page.screenshot({path:path.join(output,screenshot),animations:'disabled'});
    const observed={id:item.id,stage:item.stage,scenario:item.scenario,passed:failure===null,failure,
      seconds:(Date.now()-begin)/1000,timings,calls:state.calls,old_response_status:state.old_response_status??null,
      errors,forbidden,screenshot:{path:screenshot,sha256:hash(await readFile(path.join(output,screenshot)))},
      visible_text:await page.locator('body').innerText()};
    await save(`${item.id}.json`,observed);outcomes.push(observed);
    console.log(JSON.stringify({id:item.id,passed:observed.passed,seconds:observed.seconds}));
    await context.close();
  }
  assert.deepEqual(await manifest(path.join(gui,'src')),before,'source changed during acceptance');
  assert.deepEqual(await manifest(here),harnessBefore,'harness changed during acceptance');
  const automatedPassed=outcomes.every(o=>o.passed);
  const manual=contract.coverage.filter(c=>c.method.includes('manual')&&Number(c.stage.slice(1))<=stage).map(c=>({id:c.id,status:'not_reviewed'}));
  await save('result.json',{status:'completed_checks',stage:stageArg,mutation,
    automated_passed:automatedPassed,automated_count:outcomes.length,automated_passes:outcomes.filter(o=>o.passed).length,
    manual,full_task_qualified:false,selected_subset:!!selected,
    outcomes:outcomes.map(o=>({id:o.id,passed:o.passed,receipt:`${o.id}.json`})),model_calls:0,
    scope:'Named automated checks only; manual review and untouched acceptance protection remain required'});
} catch(error) {
  await save('infrastructure-error.json',{message:error.stack,completed_checks:outcomes.map(o=>o.id),model_calls:0});
  throw error;
} finally {clearTimeout(deadline);await host?.close();}
