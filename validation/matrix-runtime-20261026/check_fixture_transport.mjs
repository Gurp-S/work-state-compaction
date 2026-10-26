import {mkdir, writeFile} from 'node:fs/promises';
import {createServer} from 'node:net';
import {pathToFileURL} from 'node:url';
import path from 'node:path';

const [gui, oldHarness, newHarness, output] = process.argv.slice(2);
await mkdir(output, {recursive: false});
const load = p => import(pathToFileURL(path.join(p, 'browser-host.mjs')).href);
const fixture = await import(pathToFileURL(path.join(oldHarness, 'contract-fixtures.mjs')).href);
// Occupancy is deliberate and bounded; no pre-existing listener is terminated.
const sockets = new Set();
const blocker = createServer(socket => {
  sockets.add(socket); socket.once('close', () => sockets.delete(socket));
  socket.end('HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n');
});
const ownedPort = await new Promise((resolve, reject) => {
  blocker.once('error', error => error.code === 'EADDRINUSE' ? resolve(false) : reject(error));
  blocker.listen(24678, '127.0.0.1', () => resolve(true));
});
const results = [];
try {
  for (const [name, folder] of [['before', oldHarness], ['after', newHarness]]) {
    const {openHost} = await load(folder);
    const hosts = [], contexts = [];
    try {
      const opened = await Promise.all([0, 1].map(async index => {
        const dir = path.join(output, `${name}-${index}`);
        await mkdir(dir);
        const host = await openHost(gui, dir, 'none'); hosts.push(host);
        const context = await host.browser.newContext(); contexts.push(context);
        const page = await context.newPage();
        let connected = false;
        const errors = [], consoles = [];
        let finished;
        const terminal = new Promise(resolve => {finished = resolve;});
        page.on('pageerror', error => {errors.push(String(error)); finished();});
        page.on('console', message => {
          consoles.push(message.text());
          if (message.text().includes('[vite] connected')) {connected = true; finished();}
        });
        await context.route('**/v1/**', route => {
          const url = new URL(route.request().url());
          return route.fulfill({json: url.pathname === '/v1/usage/report' ? fixture.contractReport() : {ok: true, exists: false}});
        });
        await page.goto(host.origin);
        await host.expect(page.locator('[data-a3-kpi="成本"]')).toBeVisible();
        let timer;
        await Promise.race([terminal, new Promise(resolve => {timer = setTimeout(resolve, 5000);})]);
        clearTimeout(timer);
        await page.screenshot({path: path.join(dir, 'page.png')});
        return {index, origin: host.origin, connected, errors, consoles,
          passed: connected && errors.length === 0};
      }));
      results.push({name, hosts: opened, passed: opened.every(row => row.passed)});
      await writeFile(path.join(output, name + '.json'), JSON.stringify(results.at(-1), null, 2) + '\n', {flag: 'wx'});
    } finally {
      await Promise.allSettled(contexts.map(context => context.close()));
      await Promise.allSettled(hosts.map(host => host.close()));
    }
  }
} finally {
  if (ownedPort) {
    for (const socket of sockets) socket.destroy();
    await new Promise(resolve => blocker.close(resolve));
  }
}
const value = {results, deliberate_port_occupancy: ownedPort ? 'owned temporary listener' : 'pre-existing listener left untouched', model_calls: 0};
value.reproduced_and_fixed = !results[0].passed && results[1].passed;
await writeFile(path.join(output, 'result.json'), JSON.stringify(value, null, 2) + '\n', {flag: 'wx'});
console.log(JSON.stringify(value));
