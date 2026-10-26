// Independent, additional S3 checks; no changes to the frozen official harness.
import assert from 'node:assert/strict';
import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const [gui, output, frozen] = process.argv.slice(2);
const load = name => import(pathToFileURL(path.join(frozen, 'task-contract/a3-ui-long-v1/harness', name)).href);
const {openHost, manifest, hash} = await load('browser-host.mjs');
const {contractReport, contractDetail} = await load('contract-fixtures.mjs');
const {selectDate} = await load('acceptance-cases.mjs');
await mkdir(output, {recursive: false});
const save = (name, value) => writeFile(path.join(output, name), JSON.stringify(value, null, 2) + '\n', {flag: 'wx'});
const before = await manifest(path.join(gui, 'src'));
await save('registration.json', {source_manifest: before, checks: ['pending_refresh_and_date', 'out_of_order_or_serialized_refresh', 'failed_refresh_stale_label'],
  scope: 'Supplemental S3 checks; not full task qualification'});
const outcomes = [];
let host;
try {
  host = await openHost(gui, output, 'none');
  const expect = host.expect.configure({timeout: 5000});
  for (const mode of ['concurrent', 'failure']) {
    const context = await host.browser.newContext({viewport: {width: 1440, height: 1000}, locale: 'zh-CN', timezoneId: 'Asia/Shanghai'});
    const page = await context.newPage();
    const errors = [], calls = [];
    page.on('pageerror', error => errors.push(String(error)));
    let count = 0, held, unblock, observed;
    const seen = new Promise(resolve => {observed = resolve;});
    const gate = new Promise(resolve => {unblock = resolve;});
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== host.origin) return route.abort('blockedbyclient');
      if (!url.pathname.startsWith('/v1/')) return route.continue();
      calls.push(url.pathname + url.search);
      if (url.pathname === '/v1/usage/report') {
        if (url.searchParams.has('day')) return route.fulfill({json: contractDetail(url.searchParams.get('day'))});
        count++;
        if (count === 1) return route.fulfill({json: contractReport()});
        if (mode === 'failure') return route.fulfill({status: 503, json: {detail: 'independent_refresh_failure'}});
        if (count === 2) {
          held = route; observed(); await gate;
          try {return await route.fulfill({json: contractReport('zero')});}
          catch (error) {if (!route.request().failure()) throw error; return;}
        }
        return route.fulfill({json: contractReport()});
      }
      if (url.pathname === '/v1/settings/memory/report') return route.fulfill({json: {ok: true, exists: false}});
      return route.fulfill({status: 404, json: {detail: 'not_in_supplemental_scope'}});
    });
    try {
      await page.goto(host.origin);
      const cost = page.locator('[data-a3-kpi="成本"]');
      await expect(cost).toContainText(/[¥￥]\s*1\.50(?!\d)/);
      const refresh = await page.getByRole('button', {name: '刷新用量数据', exact: true}).elementHandle();
      assert(refresh, 'refresh control missing');
      await refresh.click();
      if (mode === 'concurrent') {
        await Promise.race([seen, new Promise((_, reject) => setTimeout(() => reject(new Error('refresh not issued')), 5000))]);
        await expect(cost).toContainText(/[¥￥]\s*1\.50(?!\d)/);
        await page.screenshot({path: path.join(output, 'pending.png')});
        await selectDate(page, '2026-10-21');
        await expect(cost).toContainText(/[¥￥]\s*3\.00(?!\d)/);
        await selectDate(page, '2026-10-22');
        await expect(cost).toContainText(/[¥￥]\s*1\.50(?!\d)/);
        outcomes.push({id: 'pending_refresh_and_date', passed: true});
        const serialized = await refresh.evaluate(el => el.disabled || el.getAttribute('aria-disabled') === 'true');
        if (!serialized) {
          const response = page.waitForResponse(r => new URL(r.url()).pathname === '/v1/usage/report' && !new URL(r.url()).search);
          await refresh.evaluate(el => el.click());
          await (await response).finished();
          await expect(cost).toContainText(/[¥￥]\s*1\.50(?!\d)/);
        }
        unblock();
        const old = await held.request().response();
        if (old) await old.finished();
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        await expect(cost).toContainText(serialized ? /[¥￥]\s*0\.00(?!\d)/ : /[¥￥]\s*1\.50(?!\d)/);
        assert(serialized ? count === 2 : count === 3, 'unexpected extra refresh requests');
        outcomes.push({id: 'out_of_order_or_serialized_refresh', passed: true, strategy: serialized ? 'serialized' : 'latest_response_wins', requests: count});
      } else {
        await expect(page.locator('[data-a3-live-status]')).toContainText(/没读到|失败/);
        await expect(cost).toContainText(/[¥￥]\s*1\.50(?!\d)/);
        await expect(page.locator('body')).toContainText(/上次成功|旧读数|旧数据|保留[^。\n]{0,35}(读数|数据)|未更新|过期/);
        outcomes.push({id: 'failed_refresh_stale_label', passed: true});
      }
      assert.deepEqual(errors, [], 'browser errors');
      await page.screenshot({path: path.join(output, mode + '.png')});
    } catch (error) {
      outcomes.push({id: mode + '_unfinished', passed: false, error: String(error), errors, calls});
      await page.screenshot({path: path.join(output, mode + '-failure.png')});
    } finally {
      unblock();
      await context.close();
    }
  }
} finally {
  await host?.close();
}
const after = await manifest(path.join(gui, 'src'));
const result = {outcomes, source_unchanged: JSON.stringify(before) === JSON.stringify(after), model_calls: 0};
result.passed = result.source_unchanged && outcomes.length === 3 && outcomes.every(row => row.passed);
await save('result.json', result);
console.log(JSON.stringify(result));
