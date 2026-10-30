export interface Row { id: string; tenant: string; provider: string; model: string; archived: boolean; amount: number }

export function listUsage(rows: Row[], tenant: string, model: string): Row[] {
  return rows.filter(row => row.tenant === tenant && row.model === model);
}
