// Coordinator-only assertions. Candidate receives normal config/data, never expected answers.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require('../../../gui/node_modules/playwright');
const workspace=fs.realpathSync(process.argv[2]);
const smoke=process.argv.includes('--smoke');
const shotIndex=process.argv.indexOf('--screenshot');
const screenshot=shotIndex<0?null:process.argv[shotIndex+1];
const checks=[];
const rows=[
 {id:'zero',provider:'alpha',model:'same',tokens:0,cost_cny:0,price_state:'priced'},
 {id:'unknown',provider:'beta',model:'same',tokens:null,cost_cny:null,price_state:'missing'},
 {id:'unpriced',provider:'alpha',model:'other',tokens:4,cost_cny:null,price_state:'unpriced'},
 {id:'paid',provider:'alpha',model:'same',tokens:9,cost_cny:1.25,price_state:'priced'}
];
const server=http.createServer((req,res)=>{
 try{
  const target=fs.realpathSync(path.join(workspace,decodeURIComponent(new URL(req.url,'http://local').pathname)));
  const relative=path.relative(workspace,target);
  if(relative.startsWith('..')||path.isAbsolute(relative))throw Error('outside_workspace');
  const extension=path.extname(target);
  if(!['.html','.js','.css','.json','.png'].includes(extension)||fs.statSync(target).size>2**20)throw Error('artifact_resource_boundary');
  res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.png':'image/png'})[extension]);
  res.end(fs.readFileSync(target));
 }catch(error){res.writeHead(404);res.end('Not found');}
});
let browser;
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const origin='http://127.0.0.1:'+server.address().port;
 browser=await chromium.launch({headless:true});
 const page=await browser.newPage({viewport:{width:1024,height:720}});
 page.setDefaultTimeout(1800);
 await page.route('**/*',route=>route.request().url().startsWith(origin+'/')?route.continue():route.abort());
 async function check(id,constraint,fn){
  try{await fn();checks.push({check_id:id,constraint_id:constraint,passed:true});}
  catch(error){checks.push({check_id:id,constraint_id:constraint,passed:false,reason:String(error).slice(0,2000)});}
 }
 await page.goto(origin+'/index.html');
 await page.waitForFunction(()=>typeof window.mountUsage==='function');
 const config=JSON.parse(fs.readFileSync(path.join(workspace,'config.json'),'utf8'));
 async function mount(data={kind:'ready',rows}){
  await page.evaluate(({data,config})=>{
   if(window.testInstance)window.testInstance.destroy();
   window.testQueue=[];
   window.testInstance=window.mountUsage(document.getElementById('app'),config,data,
     ()=>new Promise((resolve,reject)=>window.testQueue.push({resolve,reject})));
  },{data,config});
 }
 // <output> has an implicit status role too; the policy's explicit status is separate.
 const status=()=>page.locator('[role="status"]').innerText();
 async function select(provider,model){await page.getByRole('combobox',{name:'Model'}).selectOption(JSON.stringify([provider,model]));}
 async function ids(){return page.locator('tbody tr').evaluateAll(nodes=>nodes.map(n=>n.dataset.rowId));}
 await check('entrypoint-mount','entrypoint',async()=>{
  await page.getByRole('heading',{name:'Usage desk'}).waitFor();
  assert.equal(await page.locator('tbody tr').count(),3);
 });
 if(screenshot)await page.screenshot({path:screenshot,fullPage:true});
 if(smoke){
  await check('public-missing-state','value-states',async()=>{
   assert.equal(await page.locator('tbody tr').filter({hasText:'beta / same'}).locator('td').last().innerText(),'Unknown');
  });
 }else{
  await check('current-config','config-revision',async()=>{
   assert.equal(config.revision,2);assert.equal(config.currency,'CNY');
   assert.deepEqual(config.model_identity,['provider','model']);assert.equal(config.filter_scope,'loaded_rows_only');
   assert.equal(config.missing_cost,'Unknown');assert.equal(config.refresh_failure,'retain_rows_mark_stale');
   assert.equal(config.request_race,'latest_request_wins');
  });
  await check('provider-filter','provider-identity',async()=>{
   await mount();await select('beta','same');assert.deepEqual(await ids(),['unknown']);
   await select('alpha','same');assert.deepEqual(await ids(),['zero','paid']);
  });
  await check('distinct-value-states','value-states',async()=>{
   await mount();
   assert.deepEqual(await page.locator('tr[data-row-id="zero"] td').allTextContents(),['alpha / same','0','0.00']);
   assert.deepEqual(await page.locator('tr[data-row-id="unknown"] td').allTextContents(),['beta / same','Unknown','Unknown']);
   assert.equal(await page.locator('tr[data-row-id="unpriced"] td').last().innerText(),'Unpriced');
  });
  await check('filtered-total','aggregate-scope',async()=>{
   await mount();assert.equal(await page.getByLabel('Cost total').innerText(),'Incomplete');
   await select('alpha','same');assert.equal(await page.getByLabel('Cost total').innerText(),'1.25');
  });
  await check('empty-state','value-states',async()=>{
   await mount({kind:'ready',rows:[]});assert.equal(await status(),'No matching rows');assert.deepEqual(await ids(),[]);
  });
  await check('missing-state','value-states',async()=>{
   await mount({kind:'missing'});assert.equal(await status(),'Data unavailable');assert.deepEqual(await ids(),[]);
  });
  await check('stale-on-failure','refresh-integrity',async()=>{
   await mount();await select('alpha','same');await page.getByRole('button',{name:'Refresh'}).click();
   await page.evaluate(()=>window.testQueue[0].reject(new Error('fixture_read_failed')));
   assert.equal(await status(),'Stale: refresh failed');assert.deepEqual(await ids(),['zero','paid']);
  });
  await check('request-race','request-order',async()=>{
   await mount();await page.getByRole('button',{name:'Refresh'}).click();await page.getByRole('button',{name:'Refresh'}).click();
   await page.evaluate(()=>window.testQueue[1].resolve({kind:'ready',rows:[]}));
   await page.evaluate(()=>window.testQueue[0].resolve({kind:'ready',rows:[{id:'old',provider:'old',model:'old',tokens:1,cost_cny:1,price_state:'priced'}]}));
   assert.equal(await status(),'No matching rows');assert.deepEqual(await ids(),[]);
  });
  await check('filter-reset','filter-validity',async()=>{
   await mount();await select('beta','same');await page.getByRole('button',{name:'Refresh'}).click();
   await page.evaluate(row=>window.testQueue[0].resolve({kind:'ready',rows:[row]}),rows[0]);
   assert.equal(await page.getByRole('combobox',{name:'Model'}).inputValue(),'');assert.deepEqual(await ids(),['zero']);
  });
  await check('destroy-pending','lifecycle',async()=>{
   await mount();await page.getByRole('button',{name:'Refresh'}).click();
   await page.evaluate(()=>{window.testInstance.destroy();window.testQueue[0].resolve({kind:'ready',rows:[]});});
   assert.equal(await page.locator('#app').innerHTML(),'');
  });
  await check('literal-text','data-integrity',async()=>{
   await mount({kind:'ready',rows:[{...rows[0],provider:'<img src=x onerror="window.fixtureInjected=1">'}]});
   assert.equal(await page.locator('#app img').count(),0);assert.equal(await page.evaluate(()=>window.fixtureInjected),undefined);
  });
  await check('responsive-scope','visible-scope',async()=>{
   await mount();await page.setViewportSize({width:390,height:720});
   assert.equal(await page.getByText('Filter scope: loaded rows only',{exact:true}).isVisible(),true);
   assert.equal(await page.getByRole('button',{name:'Refresh'}).isVisible(),true);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  });
 }
 console.log(JSON.stringify({task:'T4',success:checks.every(c=>c.passed),checks,
  constraint_violations:[...new Set(checks.filter(c=>!c.passed).map(c=>c.constraint_id))].sort(),
  browser:browser.version(),scope:'Actual Chromium DOM interactions; no aesthetic, semantic or model score.'}));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{
 if(browser)await browser.close();await new Promise(resolve=>server.close(resolve));
});
