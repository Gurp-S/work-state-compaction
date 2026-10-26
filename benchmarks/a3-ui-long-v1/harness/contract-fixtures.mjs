import {reportFor, source, generated_at} from './fixtures.mjs';

const additive = ['requests','prompt_tokens','cache_hit','cache_miss','output','tokens','cost_cny','cost_unknown_requests'];
const copy = value => structuredClone(value);
function scale(row, n) {
  for (const key of additive) if (typeof row[key] === 'number') row[key] *= n;
  return row;
}
function largeReport() {
  const days = Array.from({length: 120}, (_, d) => {
    const day = new Date(Date.UTC(2026, 5, 25+d)).toISOString().slice(0,10);
    const by_model = Array.from({length: 24}, (_, i) => ({provider: `provider-${i%4}`, model: `model-${i}`,
      requests: 160, prompt_tokens: 160000, cache_hit: 120000, cache_miss: 40000, hit_rate: .75,
      output: 16000, tokens: 176000, cost_cny: i%7 === 0 ? null : 1.6, cost_unknown_requests: i%7 === 0 ? 160 : 0}));
    const totals = Object.fromEntries(additive.map(k => [k, by_model.reduce((n,r) => n+(r[k]??0),0)]));
    return {day, accepted: d%3 === 0 ? null : d%3 === 1, snapshot: d%3 !== 0, ...totals,
      hit_rate: .75, c2_count: 0, sessions: 24, turns: 960,
      hour_counts: Array.from({length:24}, () => 40), hour_unknown: 0, unattributed_requests: 0, by_model};
  });
  return {ok:true,live:true,generated_at,source:{...source,rows:120*3840},day_count:120,days};
}
export function contractReport(scenario='normal') {
  if (scenario === 'large') return largeReport();
  const report = reportFor(scenario === 'unknown' ? 'unknown' : 'normal');
  // Different days have different values so a stale date cannot accidentally pass.
  scale(report.days[0],2);
  report.days[0].by_model.forEach(row => scale(row,2));
  report.source.rows = 36;
  const day = report.days[1];
  if (scenario === 'empty' || scenario === 'missing_store') {
    return {...report,source:{...report.source,store:scenario==='empty'?'empty_store':'missing_store',rows:0,bytes:0},days:[],day_count:0};
  }
  if (scenario === 'zero') {
    scale(day,0); day.by_model.forEach(row=>scale(row,0)); day.hit_rate=null;
    day.by_model.forEach(row=>{ row.hit_rate=null; });
    day.sessions=0;day.turns=0;day.hour_counts.fill(0);
  }
  if (scenario === 'missing_fields') {
    day.requests=null;day.cost_cny=null;day.cost_unknown_requests=null;
    day.by_model=[];
  }
  if (scenario === 'unpriced') {
    day.cost_cny=null;day.cost_unknown_requests=day.requests;
    day.by_model.forEach(row=>{row.cost_cny=null;row.cost_unknown_requests=row.requests;});
  }
  if (scenario === 'small_cost') {
    day.by_model[0].cost_cny=.0004;day.by_model[1].cost_cny=.0001;day.cost_cny=.0005;
  }
  if (scenario === 'collision') day.by_model[1].model=day.by_model[0].model;
  if (scenario === 'long_names') day.by_model[0].model='研发平台/跨区域用量分析与可恢复导出服务/'+'long-model-name-'.repeat(8);
  return report;
}
export function contractDetail(date, scenario='normal') {
  const report = contractReport(scenario);
  const summary = report.days.find(d=>d.day===date)??null;
  const turns=[];
  for (const [i,row] of (summary?.by_model??[]).entries()) {
    const count=scenario==='large'?40:row.requests?1:0;
    for(let t=0;t<count;t++) {
      const ts=Date.parse(`${date}T${String(scenario==='large'?i:9).padStart(2,'0')}:00:00+08:00`)/1000+t;
      const events=Array.from({length:row.requests/count},(_,n)=>({ts:ts+n/100,provider:row.provider,model:row.model,
        request_id:`${date}-${i}-${t}-${n}`,prompt_tokens:row.prompt_tokens/row.requests,
        cache_hit:row.cache_hit/row.requests,cache_miss:row.cache_miss/row.requests,
        output:row.output/row.requests,tokens:row.tokens/row.requests,
        cost_cny:row.cost_cny===null?null:row.cost_cny/row.requests,
        cost_source:row.cost_cny===null?'unpriced':'api',kind:'response',attempt:1}));
      turns.push({...scale(copy(row),1/count),session_id:`fixture-session-${i}`,first_ts:ts,last_ts:ts+1,
        label:`${date} ${i===0?'修复列表筛选':'完善图表导出'} ${t}`,event_count:events.length,events_truncated:0,events});
    }
  }
  return {ok:true,live:true,generated_at,source:copy(report.source),day:date,missing:!summary,summary,
    sessions:(summary?.by_model??[]).map((row,i)=>({...row,session_id:`fixture-session-${i}`})),turns,events_truncated:0};
}
export function modelIdentity(row) { return [row.provider??null,row.model??null]; }
