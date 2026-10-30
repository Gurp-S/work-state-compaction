export interface Row { id: string; tenant: string; provider: string; model: string; archived: boolean; amount: number }
export interface Query { tenant: string; model?: { provider: string; name: string } | null; includeArchived?: boolean; pageSize?: number; after?: string | null }
export interface Page { items: Row[]; nextCursor: string | null }

export function listUsage(rows: Row[], query: Query): Page {
  if (!query || typeof query !== 'object' || typeof query.tenant !== 'string' || !query.tenant) throw new Error('invalid_tenant');
  const size = query.pageSize === undefined ? 2 : query.pageSize;
  if (!Number.isInteger(size) || size < 1 || size > 100) throw new Error('invalid_page_size');
  if (query.includeArchived !== undefined && typeof query.includeArchived !== 'boolean') throw new Error('invalid_archive_flag');
  const key = query.model;
  if (key != null && (typeof key.provider !== 'string' || !key.provider || typeof key.name !== 'string' || !key.name)) throw new Error('invalid_model_key');
  const selected = rows.filter(row => row.tenant === query.tenant && (query.includeArchived || !row.archived)
    && (key == null || (row.provider === key.provider && row.model === key.name)))
    .sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
  let start = 0;
  if (query.after != null) {
    if (typeof query.after !== 'string' || !query.after) throw new Error('invalid_cursor');
    const index = selected.findIndex(row => row.id === query.after);
    if (index < 0) throw new Error('cursor_outside_query');
    start = index + 1;
  }
  const items = selected.slice(start, start + size);
  return { items, nextCursor: start + size < selected.length ? items[items.length - 1].id : null };
}
