import { listUsage, Query, Page, Row } from './api';
const rows: Row[] = [];
const query: Query = { tenant: 'a', pageSize: 1 };
const page: Page = listUsage(rows, query);
if (!Array.isArray(page.items)) throw new Error('missing Page.items');
