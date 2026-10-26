import {mkdir, writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import path from 'node:path';

const [gui, fixture, output] = process.argv.slice(2);
await mkdir(output, {recursive: false});
const {openHost} = await import(pathToFileURL(path.join(fixture, 'harness/browser-host.mjs')).href);
const host = await openHost(gui, output, 'none');
const errors = [];
let connected = false, done;
const ready = new Promise(resolve => {done = resolve;});
let timer;
try {
  const context = await host.browser.newContext();
  const page = await context.newPage();
  page.on('pageerror', error => {errors.push(String(error)); done();});
  page.on('console', message => {if (message.text().includes('[vite] connected')) {connected = true; done();}});
  await page.route('**/benchmark-main.tsx', route => route.fulfill({contentType: 'application/javascript', body: "document.body.innerHTML='<p>transport-ready</p>'"}));
  await page.goto(host.origin);
  await host.expect(page.locator('body')).toHaveText('transport-ready');
  await Promise.race([ready, new Promise(resolve => {timer = setTimeout(resolve, 5000);})]);
  clearTimeout(timer);
  const result = {passed: connected && errors.length === 0, connected, errors, origin: host.origin, model_calls: 0,
    scope: 'Isolated fixture/native browser transport only; application module is replaced with a smoke page'};
  await writeFile(path.join(output, 'result.json'), JSON.stringify(result, null, 2), {flag: 'wx'});
  console.log(JSON.stringify(result));
  await context.close();
  if (!result.passed) process.exitCode = 2;
} finally {
  clearTimeout(timer);
  await host.close();
}
