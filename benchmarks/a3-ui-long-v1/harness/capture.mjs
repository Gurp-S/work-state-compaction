// Offline baseline capture. Real components and HTTP parsing; synthetic HTTP bodies.
// Usage: node capture.mjs <absolute gui directory> <new absolute output directory>
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {createServer as httpServer} from 'node:http';
import {readFile, readdir, mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {reportFor, detailFor, snapshot} from './fixtures.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const [gui, output] = process.argv.slice(2);
assert(gui && output && path.isAbsolute(gui) && path.isAbsolute(output), 'absolute gui and output required');
const requireGui = createRequire(path.join(gui, 'package.json'));
const load = name => import(pathToFileURL(requireGui.resolve(name)).href);
const {createServer} = await load('vite');
const {default: react} = await load('@vitejs/plugin-react');
const {default: tailwindcss} = await load('@tailwindcss/vite');
const {chromium} = requireGui('@playwright/test');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const save = (name, value) => writeFile(path.join(output, name), JSON.stringify(value, null, 2)+'\n', {flag: 'wx'});
async function manifest(root) {
  const files = {};
  async function walk(dir) {
    for (const item of await readdir(dir, {withFileTypes: true})) {
      const target = path.join(dir, item.name);
      if (item.isDirectory()) await walk(target);
      else if (item.isFile()) files[path.relative(root, target).replaceAll('\\','/')] = hash(await readFile(target));
      else throw new Error('unsupported source entry: '+target);
    }
  }
  await walk(root);
  return Object.fromEntries(Object.entries(files).sort(([a],[b]) => a.localeCompare(b)));
}
await mkdir(output, {recursive: false});
const before = await manifest(path.join(gui, 'src'));
await save('source-manifest.json', {gui, source: before,
  package_sha256: hash(await readFile(path.join(gui, 'package.json'))), harness: await manifest(here)});
let server, host, browser, activePage;
const results = [], forbiddenRequests = [], errors = [], requests = [];
const deadline = setTimeout(async () => {
  console.error('capture deadline exceeded');
  await browser?.close();
  await server?.close();
  host?.closeAllConnections();
  host?.close();
  process.exit(2);
}, 90000);
try {
  server = await createServer({configFile: false, envFile: false, root: gui, publicDir: false,
    cacheDir: path.join(output, 'node_modules/.vite'), logLevel: 'error',
    resolve: {alias: {'@': path.join(gui, 'src')}},
    optimizeDeps: {noDiscovery: true, include: ['react', 'react-dom/client', 'react/jsx-runtime', 'react/jsx-dev-runtime', 'lucide-react', 'zustand', 'clsx', 'tailwind-merge']},
    plugins: [react(), tailwindcss(), {name: 'a3-benchmark-host',
      resolveId(id) { if (id === '/benchmark-main.tsx') return path.join(gui, '__wsc_benchmark_main.tsx').replaceAll('\\','/'); },
      load(id) { if (id === path.join(gui, '__wsc_benchmark_main.tsx').replaceAll('\\','/')) return readFile(path.join(here,'main.tsx'),'utf8'); },
      configureServer(vite) {
      vite.middlewares.use(async (req, res, next) => {
        if (req.url === '/' || req.url?.startsWith('/?')) {
          res.setHeader('Content-Type', 'text/html');
          return res.end(await vite.transformIndexHtml('/', await readFile(path.join(here, 'index.html'), 'utf8')));
        }
        if (/^\/(v1|api|health)(\/|\?|$)/.test(req.url ?? '')) {
          res.statusCode = 503;
          return res.end('No real backend in benchmark');
        }
        next();
      });
    }}],
    server: {middlewareMode: true, hmr: false, fs: {allow: [gui, here, output]}},
  });
  host = httpServer(server.middlewares);
  host.on('request', (req, res) => {
    const entry = {url: req.url, started: Date.now(), status: null};
    requests.push(entry);
    res.once('finish', () => { entry.status = res.statusCode; entry.elapsed_ms = Date.now() - entry.started; });
  });
  await new Promise((resolve, reject) => { host.once('error', reject); host.listen(0, '127.0.0.1', resolve); });
  const origin = `http://127.0.0.1:${host.address().port}`;
  browser = await chromium.launch({headless: true});
  for (const scenario of ['normal', 'unknown', 'empty', 'error']) {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', serviceWorkers: 'block'});
    const calls = [];
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) {
        forbiddenRequests.push(url.href);
        return route.abort('blockedbyclient');
      }
      if (url.pathname.startsWith('/v1/')) {
        calls.push(url.pathname+url.search);
        if (url.pathname === '/v1/usage/report') {
          const date = url.searchParams.get('day');
          return route.fulfill({status: scenario === 'error' ? 503 : 200, json: scenario === 'error'
            ? {detail: 'fixture_ledger_unavailable'} : date ? detailFor(date, scenario) : reportFor(scenario)});
        }
        if (url.pathname === '/v1/settings/memory/report') return route.fulfill({json: snapshot});
        forbiddenRequests.push(url.href);
        return route.abort('blockedbyclient');
      }
      return route.continue();
    });
    const page = await context.newPage();
    activePage = page;
    await page.clock.setFixedTime(new Date('2026-10-22T10:00:00Z'));
    page.on('pageerror', e => errors.push({scenario, message: e.message}));
    await page.goto(origin, {waitUntil: 'domcontentloaded', timeout: 30000});
    const ready = scenario === 'empty' || scenario === 'error'
      ? page.getByText(scenario === 'empty' ? '本机还没有用量记录' : '没读到本机用量账本', {exact: false}).first()
      : page.getByRole('heading', {name: '2026-10-22', exact: true});
    await ready.waitFor({timeout: 15000});
    const beforeDetail = calls.filter(c => c.includes('?day=')).length;
    const screenshots = [];
    if (scenario === 'normal') {
      assert.equal(beforeDetail, 0, 'detail must be lazy');
      await page.getByRole('button', {name: '查看会话明细'}).click();
      await page.getByText('修复列表筛选并检查当前版本', {exact: false}).first().waitFor();
      assert(calls.some(c => c.includes('day=2026-10-22')));
      await page.getByText('修复列表筛选并检查当前版本', {exact: false}).first().scrollIntoViewIfNeeded();
      const name = 'normal-detail-1440-light.png';
      await page.screenshot({path: path.join(output,name), animations: 'disabled'});
      screenshots.push({name, sha256: hash(await readFile(path.join(output,name)))});
    }
    for (const width of scenario === 'normal' ? [1440,1024,390] : [1440]) {
      for (const theme of ['light','dark']) {
        await page.setViewportSize({width, height: width === 390 ? 844 : width === 1024 ? 768 : 1000});
        await page.evaluate(theme => {
          document.documentElement.dataset.scheme = theme;
          document.documentElement.dataset.theme = theme === 'dark' ? 'graphite' : 'paper';
        }, theme);
        await page.evaluate(() => document.fonts.ready);
        // PageShell scrolls internally. fullPage alone does not reset or capture it.
        await page.evaluate(() => {
          for (const element of document.querySelectorAll('*')) {
            if (element.scrollHeight > element.clientHeight) element.scrollTop = 0;
            if (element.scrollWidth > element.clientWidth) element.scrollLeft = 0;
          }
          window.scrollTo(0, 0);
        });
        const name = `${scenario}-${width}-${theme}.png`;
        await page.screenshot({path: path.join(output,name), animations: 'disabled'});
        screenshots.push({name, sha256: hash(await readFile(path.join(output,name)))});
      }
    }
    results.push({scenario, calls, beforeDetail, screenshots, body: await page.locator('body').innerText()});
    await context.close();
  }
  assert.deepEqual(await manifest(path.join(gui,'src')), before, 'production source changed');
  assert.equal(forbiddenRequests.length, 0, 'unexpected outbound/API access');
  assert.equal(errors.length, 0, 'browser script error');
  await save('result.json', {status: 'captured_existing_UI', results, errors, forbiddenRequests, origin,
    browser: browser.version(), node: process.version, fixed_time: '2026-10-22T10:00:00Z',
    packages: Object.fromEntries(await Promise.all(['vite','@playwright/test','react','@vitejs/plugin-react','@tailwindcss/vite']
      .map(async name => [name, JSON.parse(await readFile(path.join(gui,'node_modules',name,'package.json'),'utf8')).version]))),
    model_calls: 0, scope: 'Baseline viewport capture and lazy-detail smoke only; not full task acceptance'});
  console.log(JSON.stringify({output, scenarios: results.length, screenshots: results.reduce((n,r) => n+r.screenshots.length,0)}));
} catch (error) {
  if (activePage && !activePage.isClosed()) {
    await writeFile(path.join(output,'failure.html'), await activePage.content(), {flag: 'wx'});
    await activePage.screenshot({path: path.join(output,'failure.png')});
  }
  await save('error.json', {message: error.stack, results, errors, forbiddenRequests, requests});
  throw error;
} finally {
  clearTimeout(deadline);
  await browser?.close();
  await server?.close();
  host?.closeAllConnections();
  if (host?.listening) await new Promise(resolve => host.close(resolve));
}
