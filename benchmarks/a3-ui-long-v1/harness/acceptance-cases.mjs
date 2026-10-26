import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {contractReport,contractDetail,modelIdentity} from './contract-fixtures.mjs';
import {checkAllExport,checkFilteredExport} from './export-checks.mjs';

const kpi=(page,name)=>page.locator(`[data-a3-kpi="${name}"]`);
const models=page=>page.locator('[data-a3-models]');
const drill=page=>page.locator('[data-a3-drill]');
const button=(page,name)=>page.getByRole('button',{name,exact:true});
export async function selectDate(page,date) {
  const select=page.getByRole('combobox',{name:'选择查看的日期',exact:true});
  if(await select.isVisible()) await select.selectOption(date);
  else await page.getByRole('button',{name:new RegExp(date)}).click();
}
async function selectModel(page,model,provider=null) {
  const regex=new RegExp((provider?`(?=.*${provider})`:'')+`(?=.*${model})`);
  const choice=page.getByRole('button',{name:regex}).or(page.getByRole('checkbox',{name:regex}));
  assert.equal(await choice.count(),1,'model selection must have one unambiguous accessible identity');
  await choice.click();
}
async function money(expect,page,value) {
  await expect(kpi(page,'成本')).toBeVisible();
  await expect(kpi(page,'成本')).toContainText(new RegExp(`[¥￥]\\s*${value.replace('.','\\.')}(?![0-9])`));
}
async function refreshSettled(page) {
  const [response]=await Promise.all([
    page.waitForResponse(r=>new URL(r.url()).pathname==='/v1/usage/report'&&!new URL(r.url()).search),
    button(page,'刷新用量数据').click(),
  ]);
  await response.finished();
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
}
async function downloaded(page,name) {
  const [download]=await Promise.all([page.waitForEvent('download',{timeout:5000}),button(page,name).click()]);
  return JSON.parse(await readFile(await download.path(),'utf8'));
}
export const cases=[
  {id:'C01',stage:1,scenario:'normal',run:async({page,expect})=>{
    await money(expect,page,'1.50');
    await expect(kpi(page,'请求')).toContainText(/\b12\b/);
    await expect(kpi(page,'命中率')).toContainText('65.0%');
    await expect(kpi(page,'输入 token')).toContainText(/100(?:\.00)?\s*k|100,?000|10(?:\.0+)?万/i);
    await expect(kpi(page,'输出 token')).toContainText(/5(?:\.00)?\s*k|5,?000|0\.5万/i);
    await expect(models(page)).toContainText('provider-a');await expect(models(page)).toContainText('provider-b');
  }},
  ...['zero','unknown','unpriced','missing_fields','empty','missing_store','error','small_cost'].map(scenario=>({
    id:`C02-${scenario}`,stage:2,scenario,run:async({page,expect})=>{
      if(scenario==='zero') {await money(expect,page,'0.00');await expect(kpi(page,'成本')).not.toContainText(/未知|无价目/);}
      if(scenario==='unknown') {await money(expect,page,'1.20');await expect(kpi(page,'成本')).toContainText('部分未知');await expect(models(page)).toContainText('无价目');}
      if(scenario==='unpriced') {await expect(kpi(page,'成本')).toContainText(/无价目|未知/);await expect(kpi(page,'成本')).not.toContainText(/[¥￥]\s*0\.00/);}
      if(scenario==='missing_fields') {await expect(kpi(page,'请求')).toContainText('数据里没有');}
      if(scenario==='empty'||scenario==='missing_store') {
        await expect(page.locator('[data-a3-live-status]')).toContainText(/没有用量记录|暂无.*记录/);
        assert.equal(await kpi(page,'成本').count(),0,'empty ledger must not show numeric KPIs');
      }
      if(scenario==='error') {
        await expect(page.locator('[data-a3-live-status]')).toContainText(/没读到|失败/);
        await expect(page.locator('[data-a3-live-status]')).not.toContainText('没有用量记录');
        assert.equal(await page.locator('iframe').count(),0,'failure replaced by snapshot iframe');
      }
      if(scenario==='small_cost') await money(expect,page,'0.0005');
    }})),
  {id:'C03',stage:3,scenario:'normal',run:async({page,expect})=>{
    await selectModel(page,'atlas-pro');
    await expect(models(page)).toContainText('provider-a');await expect(models(page)).not.toContainText('provider-b');
    await money(expect,page,'1.50');await expect(kpi(page,'请求')).toContainText(/\b12\b/);
    await selectDate(page,'2026-10-21');
    await money(expect,page,'3.00');await expect(models(page)).toContainText('provider-b');
  }},
  {id:'C04',stage:3,scenario:'normal',run:async({page,expect,state})=>{
    state.reportFailure=true;
    await button(page,'刷新用量数据').click();
    await expect(page.locator('[data-a3-live-status]')).toContainText(/没读到|失败/);
    await money(expect,page,'1.50');
    state.reportFailure=false;
    await button(page,'刷新用量数据').click();
    await expect(page.locator('[data-a3-live-status]')).not.toContainText(/没读到|失败/);
    await money(expect,page,'1.50');
  }},
  {id:'C05',stage:4,scenario:'normal',run:async({page,expect,state})=>{
    assert.equal(state.calls.filter(c=>c.includes('?day=')).length,0,'eager detail request');
    await button(page,'查看会话明细').click();
    await expect(drill(page)).toContainText('2026-10-22 修复列表筛选');
    assert.equal(state.calls.filter(c=>c.includes('?day=')).length,1,'extra detail request');
    await page.getByRole('searchbox',{name:'搜索用户消息'}).fill('修复列表筛选');
    await expect(drill(page)).not.toContainText('2026-10-22 完善图表导出');
    await page.getByRole('searchbox',{name:'搜索用户消息'}).fill('');
    await expect(drill(page)).toContainText('2026-10-22 完善图表导出');
  }},
  {id:'C06',stage:4,scenario:'normal',run:async({page,expect,state})=>{
    await selectDate(page,'2026-10-21');
    state.holdDay='2026-10-21';
    await button(page,'查看会话明细').click();
    await state.waitHeld();
    await selectDate(page,'2026-10-22');
    await expect(drill(page)).toContainText('2026-10-22 修复列表筛选');
    await state.releaseHeld();
    // Await the old HTTP delivery plus two rendering frames, not an arbitrary sleep.
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await expect(drill(page)).not.toContainText('2026-10-21 修复列表筛选');
    await expect(drill(page)).toContainText('2026-10-22 修复列表筛选');
  }},
  {id:'C07',stage:5,scenario:'collision',run:async({page,expect,state})=>{
    await selectModel(page,'atlas-pro','provider-a');
    await expect(models(page)).toContainText('provider-a');await expect(models(page)).not.toContainText('provider-b');
    await money(expect,page,'1.50');
    state.reverseModels=true;
    await refreshSettled(page);
    await expect(models(page)).toContainText('provider-a');await expect(models(page)).not.toContainText('provider-b');
    await selectModel(page,'atlas-pro','provider-a');
    await selectModel(page,'atlas-pro','provider-b');
    await expect(models(page)).toContainText('provider-b');await expect(models(page)).not.toContainText('provider-a');
  }},
  {id:'C08',stage:6,scenario:'unknown',run:async({page,expect,state})=>{
    assert.equal(await button(page,'导出全部数据').count(),1,'all-export control missing');
    assert.equal(await button(page,'导出筛选数据').count(),1,'filtered-export control missing');
    const report=contractReport('unknown');
    checkAllExport(await downloaded(page,'导出全部数据'),report);
    await selectModel(page,'boreal-fast');
    checkFilteredExport(await downloaded(page,'导出筛选数据'),report,'2026-10-22',[modelIdentity(report.days.at(-1).by_model[1])]);
    assert.equal(state.calls.filter(c=>c.includes('?day=')).length,0,'export fetched unrelated details');
    await expect(kpi(page,'成本')).toContainText('部分未知');
    await button(page,'查看会话明细').click();
    await expect(drill(page)).toContainText('2026-10-22 修复列表筛选');
    checkAllExport(await downloaded(page,'导出全部数据'),report,contractDetail('2026-10-22','unknown'));
    await selectDate(page,'2026-10-21');
    await expect(drill(page)).toContainText('2026-10-21 修复列表筛选');
    checkAllExport(await downloaded(page,'导出全部数据'),report,contractDetail('2026-10-21','unknown'));
  }},
  ...['success','failed','unconfirmed','status_error'].map(mode=>({id:`C09-${mode}`,stage:6,scenario:'normal',run:async({page,expect,state})=>{
    if(mode==='status_error') {
      state.snapshotStatusFailure=true;
      await button(page,'重读快照状态').click();
      await expect(page.locator('[data-a3-snapshot-status]')).toContainText(/未读到|失败/);
    } else {
      state.snapshotMode=mode;
      await button(page,'生成网页报告').click();
      if(mode==='success') await expect(page.locator('[data-a3-snapshot-status]')).toContainText(/已更新|补齐/);
      if(mode==='failed') await expect(page.getByRole('alert')).toContainText('fixture_snapshot_failed');
      if(mode==='unconfirmed') await expect(page.getByRole('alert')).toContainText('未确认');
    }
    await money(expect,page,'1.50');
    assert.equal(state.calls.filter(c=>c==='/v1/usage/report').length,1,'snapshot changed main data source');
  }})),
  {id:'C10',stage:7,scenario:'normal',run:async({page,expect})=>{
    const density=page.locator('[data-a3-density]');
    await expect(density).toBeVisible();
    await expect(density).toHaveAttribute('data-a3-density','comfortable');
    await button(page,'紧凑布局').click();await page.reload();
    await expect(density).toHaveAttribute('data-a3-density','compact');await money(expect,page,'1.50');
    await button(page,'重置显示偏好').click();await page.reload();
    await expect(density).toHaveAttribute('data-a3-density','comfortable');
    for(const raw of ['{bad','{"version":0,"density":"compact"}','{"version":1,"density":"nonsense"}']) {
      await page.evaluate(raw=>localStorage.setItem('xeyo.a3.display.v1',raw),raw);await page.reload();
      await expect(density).toHaveAttribute('data-a3-density','comfortable');await money(expect,page,'1.50');
    }
  }},
  {id:'C11',stage:7,scenario:'large',run:async({page,expect,timings})=>{
    page.setDefaultTimeout(10000);
    const started=Date.now();
    await selectModel(page,'model-0');
    await expect(models(page)).not.toContainText('provider-1');
    timings.filter_ms=Date.now()-started;
    const opened=Date.now();await selectDate(page,'2026-10-21');await button(page,'查看会话明细').click();
    await expect(drill(page)).toContainText('2026-10-21 修复列表筛选 0');
    timings.date_and_open_ms=Date.now()-opened;
    const searched=Date.now();await page.getByRole('searchbox',{name:'搜索用户消息'}).fill('修复列表筛选 39');
    await expect(drill(page)).toContainText('2026-10-21 修复列表筛选 39');
    await expect(drill(page)).not.toContainText('2026-10-21 修复列表筛选 0');
    timings.search_ms=Date.now()-searched;
    const switched=Date.now();await selectDate(page,'2026-10-22');
    await expect(drill(page)).toContainText('2026-10-22 修复列表筛选');
    await expect(drill(page)).not.toContainText('2026-10-21 修复列表筛选');
    timings.date_switch_ms=Date.now()-switched;
    assert(Object.entries(timings).filter(([key])=>key!=='bootstrap_ms').every(([,ms])=>ms<=10000),
      'single UI operation exceeded 10 seconds');
  }},
];
