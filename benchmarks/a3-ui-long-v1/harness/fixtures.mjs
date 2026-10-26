// Synthetic, internally consistent data. Never read the user's real ledger.
export const source = {kind: 'live_ledger', path: 'fixture/usage.jsonl', rows: 24, store: 'ok', bytes: 24000, mtime: 1792634400};
export const generated_at = '2026-10-22T18:00:00+08:00';
const hours = (n, at) => Array.from({length: 24}, (_, i) => i === at ? n : 0);
function day(date, multiplier, accepted) {
  const by_model = [
    {provider: 'provider-a', model: 'atlas-pro', requests: 8, prompt_tokens: 80000, cache_hit: 60000, cache_miss: 20000, hit_rate: 0.75, output: 4000, tokens: 84000, cost_cny: 1.2, cost_unknown_requests: 0},
    {provider: 'provider-b', model: 'boreal-fast', requests: 4, prompt_tokens: 20000, cache_hit: 5000, cache_miss: 15000, hit_rate: 0.25, output: 1000, tokens: 21000, cost_cny: 0.3, cost_unknown_requests: 0},
  ].map(row => Object.fromEntries(Object.entries(row).map(([k,v]) => [k, typeof v === 'number' && k !== 'hit_rate' ? v * multiplier : v])));
  return {day: date, accepted, snapshot: accepted !== null, requests: 12*multiplier, prompt_tokens: 100000*multiplier,
    cache_hit: 65000*multiplier, cache_miss: 35000*multiplier, hit_rate: 0.65, c2_count: 0,
    output: 5000*multiplier, tokens: 105000*multiplier, cost_cny: 1.5*multiplier,
    cost_unknown_requests: 0, sessions: 2, turns: 2*multiplier,
    hour_counts: hours(2*multiplier, 9), hour_unknown: 0, unattributed_requests: 0, by_model};
}
export function reportFor(scenario = 'normal') {
  const days = [day('2026-10-21', 1, false), day('2026-10-22', 1, null)];
  const report = {ok: true, live: true, generated_at, source: {...source}, day_count: 2, days};
  if (scenario === 'empty') return {...report, source: {...source, store: 'empty_store', rows: 0, bytes: 0}, days: [], day_count: 0};
  if (scenario === 'unknown') {
    const current = days[1];
    current.cost_cny = 1.2;
    current.cost_unknown_requests = 4;
    current.by_model[1].cost_cny = null;
    current.by_model[1].cost_unknown_requests = 4;
  }
  if (scenario === 'collision') {
    days[1].by_model[1].model = days[1].by_model[0].model;
  }
  return report;
}
export function detailFor(date, scenario = 'normal') {
  const summary = reportFor(scenario).days.find(d => d.day === date) ?? null;
  const ts = Date.parse(`${date}T09:00:00+08:00`) / 1000;
  const turns = summary ? summary.by_model.map((model, i) => ({
    ...model, session_id: `fixture-session-${i}`, label: i === 0 ? '修复列表筛选并检查当前版本' : '完善用量图表与导出',
    first_ts: ts, last_ts: ts+120, event_count: model.requests, events_truncated: 0,
    events: Array.from({length: model.requests}, (_, n) => ({
      ts: ts+n, provider: model.provider, model: model.model, request_id: `${date}-${i}-${n}`,
      prompt_tokens: model.prompt_tokens/model.requests, cache_hit: model.cache_hit/model.requests,
      cache_miss: model.cache_miss/model.requests, output: model.output/model.requests,
      tokens: model.tokens/model.requests, cost_cny: model.cost_cny === null ? null : model.cost_cny/model.requests,
      cost_source: model.cost_cny === null ? 'unpriced' : 'api', kind: 'response', attempt: 1,
    })),
  })) : [];
  return {ok: true, live: true, generated_at, source: {...source}, day: date, missing: !summary,
    summary, sessions: turns.map(({events, label, ...rest}) => rest), turns, events_truncated: 0};
}
export const snapshot = {ok: true, exists: false};
