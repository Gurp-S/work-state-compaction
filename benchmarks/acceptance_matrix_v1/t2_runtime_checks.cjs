// Coordinator-side assertions, never copied to the model workspace.
const path = require('node:path');
const directory = process.argv[2];
const api = require(path.join(directory, 'api.js'));
const clients = Object.fromEntries(['cli', 'dashboard', 'exporter', 'worker'].map(name => [name, require(path.join(directory, name + '.js'))]));
function data() {
  return [
    {id:'a3',tenant:'t',provider:'p',model:'m',archived:false,amount:3},
    {id:'00u',tenant:'u',provider:'p',model:'m',archived:false,amount:99},
    {id:'a1',tenant:'t',provider:'p',model:'m',archived:false,amount:1},
    {id:'00q',tenant:'t',provider:'q',model:'m',archived:true,amount:5},
    {id:'a0',tenant:'t',provider:'p',model:'m',archived:true,amount:4},
    {id:'a2',tenant:'t',provider:'p',model:'m',archived:false,amount:2}
  ];
}
const query = {tenant:'t',model:{provider:'p',name:'m'}};
function equal(a,b) { if (JSON.stringify(a)!==JSON.stringify(b)) throw new Error('value_mismatch'); }
function ids(items) { return items.map(row=>row.id); }
function throws(call) { let caught=false; try {call();} catch {caught=true;} if(!caught) throw new Error('expected_rejection'); }
const checks=[];
function check(id,constraint,run) {
  try {run();checks.push({check_id:id,passed:true,constraint_id:constraint});}
  catch(error) {checks.push({check_id:id,passed:false,constraint_id:constraint,error_type:error.name,reason:String(error.message).slice(0,2000)});}
}
check('query-page',null,()=>{const page=api.listUsage(data(),query);equal(ids(page.items),['a1','a2']);equal(page.nextCursor,'a2');});
check('provider-pair','provider-identity',()=>equal(ids(api.listUsage(data(),{tenant:'t',model:{provider:'q',name:'m'},includeArchived:true}).items),['00q']));
check('archive-scope',null,()=>equal(ids(api.listUsage(data(),{...query,includeArchived:true,pageSize:100}).items),['a0','a1','a2','a3']));
check('scoped-cursor','tenant-boundary',()=>{for(const after of ['00u','00q']) throws(()=>api.listUsage(data(),{...query,after}));});
check('tail-and-empty',null,()=>{const page=api.listUsage(data(),{...query,after:'a2'});equal(ids(page.items),['a3']);equal(page.nextCursor,null);equal(api.listUsage(data(),{...query,after:'a3'}),{items:[],nextCursor:null});});
check('null-model',null,()=>equal(ids(api.listUsage(data(),{tenant:'t',model:null,includeArchived:true,pageSize:100}).items),['00q','a0','a1','a2','a3']));
check('invalid-query','query-validation',()=>{for(const change of [{tenant:''},{pageSize:0},{pageSize:true},{pageSize:101},{includeArchived:'false'},{model:{name:'m'}}]) throws(()=>api.listUsage(data(),{...query,...change}));});
check('no-input-mutation','input-integrity',()=>{const rows=data(),before=JSON.stringify(rows);api.listUsage(rows,query);equal(JSON.stringify(rows),before);});
check('cli-caller',null,()=>equal(ids(clients.cli.run(data(),'t','p','m').items),['a1','a2']));
check('dashboard-caller',null,()=>equal(ids(clients.dashboard.run(data(),'t','p','m').items),['a0','a1']));
check('export-pages','export-completeness',()=>equal(ids(clients.exporter.run(data(),'t','p','m')),['a1','a2','a3']));
check('worker-caller',null,()=>equal(ids(clients.worker.run(data(),'t','p','m').items),['00q','a0']));
process.stdout.write(JSON.stringify({checks}));
