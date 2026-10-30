import { listUsage, Row } from './api';
export function run(rows: Row[], tenant: string, provider: string, model: string) {
  return listUsage(rows, { tenant, model: null, includeArchived: true });
}
