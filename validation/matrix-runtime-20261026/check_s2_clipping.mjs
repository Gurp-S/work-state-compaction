// One source-bound historical-risk check; no source transformation or model call.
import {mkdir, writeFile, readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const [gui, fixture, output] = process.argv.slice(2);
const load = name => import(pathToFileURL(path.join(fixture, 'harness', name)).href);
const {openHost, manifest} = await load('browser-host.mjs');
const {contractReport} = await load('contract-fixtures.mjs');
await mkdir(output, {recursive: false});
const before = await manifest(path.join(gui, 'src'));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
await writeFile(path.join(output, 'registration.json'), JSON.stringify({source_manifest: before,
  package_sha256: sha(await readFile(path.join(gui, 'package.json'))), lock_sha256: sha(await readFile(path.join(gui, 'package-lock.json'))),
  viewport: {width: 1440, height: 1000}, scenario: 'normal', scope: 'One geometry/real-wheel check on the frozen S2 source'}, null, 2), {flag: 'wx'});
const host = await openHost(gui, output, 'none');
let result;
try {
  const context = await host.browser.newContext({viewport: {width: 1440, height: 1000}, locale: 'zh-CN', timezoneId: 'Asia/Shanghai'});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  await context.route('**/v1/**', route => {
    const url = new URL(route.request().url());
    return route.fulfill({json: url.pathname === '/v1/usage/report' ? contractReport() : {ok: true, exists: false}});
  });
  await page.goto(host.origin);
  await host.expect(page.locator('[data-a3-kpi="成本"]')).toBeVisible();
  const measure = () => page.evaluate(() => {
    const report = document.querySelector('.xy-a3-report');
    if (!report) throw new Error('report_missing');
    const chain = [];
    for (let node = report; node; node = node.parentElement) {
      const css = getComputedStyle(node);
      chain.push({tag: node.tagName, id: node.id, className: node.className,
        clientHeight: node.clientHeight, scrollHeight: node.scrollHeight, scrollTop: node.scrollTop,
        overflowY: css.overflowY, bottom: node.getBoundingClientRect().bottom});
    }
    return {viewportHeight: innerHeight, windowScrollY: scrollY, reportHeight: report.getBoundingClientRect().height, chain};
  });
  const initial = await measure();
  await page.mouse.move(700, 700); await page.mouse.wheel(0, 1800);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const afterWheel = await measure();
  const hasUserScrollableAncestor = initial.chain.some(row => /^(auto|scroll)$/.test(row.overflowY) && row.scrollHeight > row.clientHeight);
  const hasClippingAncestor = initial.chain.some(row => /^(hidden|clip)$/.test(row.overflowY) && row.scrollHeight > row.clientHeight);
  const changedScroll = initial.windowScrollY !== afterWheel.windowScrollY || initial.chain.some((row, i) => row.scrollTop !== afterWheel.chain[i]?.scrollTop);
  const clippingObserved = initial.reportHeight > initial.viewportHeight && hasClippingAncestor && !hasUserScrollableAncestor && !changedScroll;
  await page.screenshot({path: path.join(output, 'after-wheel.png')});
  result = {check_executed: true, clipping_observed: clippingObserved, initial, afterWheel, hasUserScrollableAncestor,
    hasClippingAncestor, changedScroll, errors, browser: host.browser.version(), model_calls: 0};
  await context.close();
} finally {await host.close();}
result.source_unchanged = JSON.stringify(before) === JSON.stringify(await manifest(path.join(gui, 'src')));
await writeFile(path.join(output, 'result.json'), JSON.stringify(result, null, 2), {flag: 'wx'});
console.log(JSON.stringify({clipping_observed: result.clipping_observed, source_unchanged: result.source_unchanged,
  reportHeight: result.initial.reportHeight, viewportHeight: result.initial.viewportHeight, changedScroll: result.changedScroll, errors: result.errors, model_calls: 0}));
