import { listUsage, Row } from './api';
export function run(rows: Row[], tenant: string, provider: string, model: string): Row[] {
  const result: Row[] = [];
  let after: string | null = null;
  do {
    const page = listUsage(rows, { tenant, model: { provider, name: model }, after });
    result.push(...page.items);
    after = page.nextCursor;
  } while (after !== null);
  return result;
}
