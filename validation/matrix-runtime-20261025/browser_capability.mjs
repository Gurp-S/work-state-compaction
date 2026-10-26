import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import path from 'node:path';

const [gui,output,mode]=process.argv.slice(2);
const requireGui=createRequire(path.join(gui,'package.json'));
const {chromium}=requireGui('@playwright/test');
await mkdir(output,{recursive:true});
let browser,server;
const result={mode,passed:false,model_calls:0};
try {
  const options={headless:true,timeout:10000};
  if(mode==='full')options.executablePath=chromium.executablePath();
  result.executable_override=options.executablePath??null;
  browser=await chromium.launch(options);
  result.browser_version=browser.version();
  server=createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end('<h1 id="status">CAPABILITY_OK</h1>');});
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  const page=await browser.newPage({viewport:{width:640,height:480}});
  await page.goto(`http://127.0.0.1:${server.address().port}`,{timeout:10000});
  result.text=await page.locator('#status').innerText();
  if(result.text!=='CAPABILITY_OK')throw new Error('unexpected local response');
  await page.screenshot({path:path.join(output,'browser.png')});
  result.passed=true;
} catch(error){result.error=error.stack;}
finally {
  await browser?.close();
  if(server?.listening){server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
}
await writeFile(path.join(output,'result.json'),JSON.stringify(result,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify(result));
