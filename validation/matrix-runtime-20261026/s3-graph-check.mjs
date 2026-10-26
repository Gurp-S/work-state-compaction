import assert from 'node:assert/strict';
import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const [gui, output, fixture] = process.argv.slice(2);
const load = name => import(pathToFileURL(path.join(fixture, 'harness', name)).href);
const {openHost, manifest} = await load('browser-host.mjs');
const {contractReport} = await load('contract-fixtures.mjs');
const {selectDate} = await load('acceptance-cases.mjs');
await mkdir(output, {recursive: false});
const before = await manifest(path.join(gui, 'src'));
await writeFile(path.join(output, 'registration.json'), JSON.stringify({source_manifest: before,
  checks: ['legend_to_all_charts_and_table', 'date_resets_selection', 'keyboard_chart_selection']}, null, 2), {flag: 'wx'});
const host = await openHost(gui, output, 'none');
const checks = [], errors = [];
try {
  const context = await host.browser.newContext({viewport: {width: 1440, height: 1000}, locale: 'zh-CN', timezoneId: 'Asia/Shanghai'});
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(String(error)));
  await context.route('**/v1/**', route => {
    const url = new URL(route.request().url());
    return route.fulfill({json: url.pathname === '/v1/usage/report' ? contractReport() : {ok: true, exists: false}});
  });
  const expect = host.expect.configure({timeout: 5000});
  await page.goto(host.origin);
  const cost = page.locator('[data-a3-kpi="成本"]'), requests = page.locator('[data-a3-kpi="请求"]');
  const models = page.locator('[data-a3-models]');
  await expect(cost).toContainText(/[¥￥]\s*1\.50(?!\d)/);
  const legends = page.locator('[data-donut] button[role="switch"]');
  await legends.filter({hasText: 'boreal-fast'}).first().click();
  await expect(models).toContainText('provider-b');
  await expect(models).not.toContainText('provider-a');
  await expect(cost).toContainText(/[¥￥]\s*1\.50(?!\d)/);
  await expect(requests).toContainText(/\b12\b/);
  const chartRows = await page.locator('[data-donut]').evaluateAll(cards => cards.map(card => ({
    title: card.getAttribute('data-donut'),
    names: [...card.querySelectorAll('button[role="switch"]')].map(button => button.textContent)})).filter(card => card.names.length));
  assert(chartRows.length >= 3, 'expected linked model charts');
  assert(chartRows.every(card => card.names.every(name => name.includes('boreal-fast'))), 'charts did not share model selection');
  checks.push({id: 'legend_to_all_charts_and_table', passed: true, charts: chartRows});
  await page.screenshot({path: path.join(output, 'linked-selection.png'), fullPage: true});
  await selectDate(page, '2026-10-21');
  await expect(models).toContainText('provider-a'); await expect(models).toContainText('provider-b');
  await expect(cost).toContainText(/[¥￥]\s*3\.00(?!\d)/);
  await expect(requests).toContainText(/\b24\b/);
  checks.push({id: 'date_resets_selection', passed: true});
  await legends.filter({hasText: 'atlas-pro'}).first().focus();
  await page.keyboard.press('Space');
  await expect(models).toContainText('provider-a'); await expect(models).not.toContainText('provider-b');
  await expect(cost).toContainText(/[¥￥]\s*3\.00(?!\d)/);
  checks.push({id: 'keyboard_chart_selection', passed: true});
  assert.deepEqual(errors, []);
  await page.screenshot({path: path.join(output, 'keyboard-selection.png'), fullPage: true});
  await context.close();
} catch (error) {
  checks.push({id: 'graph_validation_unfinished', passed: false, error: String(error), errors});
} finally {
  await host.close();
}
const after = await manifest(path.join(gui, 'src'));
const result = {checks, source_unchanged: JSON.stringify(before) === JSON.stringify(after), model_calls: 0};
result.passed = result.source_unchanged && checks.length === 3 && checks.every(row => row.passed);
await writeFile(path.join(output, 'result.json'), JSON.stringify(result, null, 2), {flag: 'wx'});
console.log(JSON.stringify(result));
