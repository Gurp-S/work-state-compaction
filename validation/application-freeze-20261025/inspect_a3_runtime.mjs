import {createRequire} from 'node:module';
import {readFile, writeFile} from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';

const [dependencyBase, output] = process.argv.slice(2);
const require = createRequire(path.join(path.dirname(dependencyBase), 'package.json'));
const versions = {};
for (const name of ['react', 'react-dom', 'vite', '@vitejs/plugin-react', '@tailwindcss/vite', '@playwright/test', 'typescript']) {
  versions[name] = JSON.parse(await readFile(path.join(dependencyBase, name, 'package.json'), 'utf8')).version;
}
async function hashed(file) {
  const digest = createHash('sha256');
  for await (const chunk of createReadStream(file)) digest.update(chunk);
  return digest.digest('hex');
}
const {chromium} = require('@playwright/test');
const browser = chromium.executablePath();
const result = {node:{version:process.version, executable:process.execPath, sha256:await hashed(process.execPath)},
  versions, chromium:{executable:browser, sha256:await hashed(browser)},
  browser_launched:false, model_calls:0};
await writeFile(output, JSON.stringify(result,null,2)+'\n', {flag:'wx'});
console.log(JSON.stringify(result));
