// Isolated source host shared by acceptance and fault calibration. No live backend.
import {createRequire} from 'node:module';
import {createServer as createHttpServer} from 'node:http';
import {readFile,readdir,writeFile,mkdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath,pathToFileURL} from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

export const here=path.dirname(fileURLToPath(import.meta.url));
export const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
export async function manifest(root) {
  const files={};
  async function walk(dir) {
    for(const item of await readdir(dir,{withFileTypes:true})) {
      const target=path.join(dir,item.name);
      if(item.isDirectory()) await walk(target);
      else if(item.isFile()) files[path.relative(root,target).replaceAll('\\','/')]=hash(await readFile(target));
      else throw new Error('unsupported source entry: '+target);
    }
  }
  await walk(root);
  return Object.fromEntries(Object.entries(files).sort(([a],[b])=>a.localeCompare(b)));
}
export async function openHost(gui,output,mutation='none') {
  assert(path.isAbsolute(gui)&&path.isAbsolute(output),'absolute roots required');
  const requireGui=createRequire(path.join(gui,'package.json'));
  const load=name=>import(pathToFileURL(requireGui.resolve(name)).href);
  const {createServer}=await load('vite');
  const {default:react}=await load('@vitejs/plugin-react');
  const {default:tailwindcss}=await load('@tailwindcss/vite');
  const {chromium,expect}=requireGui('@playwright/test');
  const overrides=new Map(),mutationEvidence=[];
  if(mutation!=='none') {
    const definitions={
      unknown_as_zero:['components/usage/labels.ts','if (value === null) return NO_PRICE;',"if (value === null) return '¥0.00';"],
      // Two guards exist (success/catch). Remove only the first, successful-response guard.
      stale_detail:['components/A3NativePanel.tsx','if (requestRef.current !== requestId) return;','/* calibration: stale response protection removed */',2],
    };
    assert(mutation in definitions,'unknown calibration mutation');
    const [relative,from,to,expectedOccurrences=1]=definitions[mutation];
    const filename=path.join(gui,'src',relative);
    const original=await readFile(filename,'utf8');
    assert.equal(original.split(from).length-1,expectedOccurrences,'calibration source changed');
    const transformed=original.replace(from,to);
    overrides.set(filename.replaceAll('\\','/'),transformed);
    const evidence=path.join(output,'mutated-source',relative);
    await mkdir(path.dirname(evidence),{recursive:true});
    await writeFile(evidence,transformed,{flag:'wx'});
    mutationEvidence.push({relative,original_sha256:hash(original),transformed_sha256:hash(transformed),
      expected_occurrences:expectedOccurrences,replaced_occurrences:1,evidence});
  }
  let vite,server,browser;
  async function close() {
    await browser?.close();
    await vite?.close();
    server?.closeAllConnections();
    if(server?.listening) await new Promise(resolve=>server.close(resolve));
  }
  try {
    vite=await createServer({configFile:false,envFile:false,root:gui,publicDir:false,
      cacheDir:path.join(output,'node_modules/.vite'),logLevel:'error',resolve:{alias:{'@':path.join(gui,'src')}},
      optimizeDeps:{noDiscovery:true,include:['react','react-dom/client','react/jsx-runtime','react/jsx-dev-runtime','lucide-react','zustand','clsx','tailwind-merge']},
      plugins:[{name:'a3-calibration-source',enforce:'pre',load(id){return overrides.get(id.split('?')[0]);}},
        react(),tailwindcss(),{name:'a3-acceptance-host',
          resolveId(id){if(id==='/benchmark-main.tsx')return path.join(gui,'__wsc_benchmark_main.tsx').replaceAll('\\','/');},
          load(id){if(id===path.join(gui,'__wsc_benchmark_main.tsx').replaceAll('\\','/'))return readFile(path.join(here,'main.tsx'),'utf8');},
          configureServer(instance){instance.middlewares.use(async(req,res,next)=>{
            if(req.url==='/'||req.url?.startsWith('/?')) {
              res.setHeader('Content-Type','text/html');
              return res.end(await instance.transformIndexHtml('/',await readFile(path.join(here,'index.html'),'utf8')));
            }
            if(/^\/(v1|api|health)(\/|\?|$)/.test(req.url??'')) {
              res.statusCode=503;return res.end('No real backend in acceptance');
            }
            next();
          });}}],server:{middlewareMode:true,hmr:false,fs:{allow:[gui,here,output]}}});
    server=createHttpServer(vite.middlewares);
    await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
    browser=await chromium.launch({headless:true});
    return {browser,expect,origin:`http://127.0.0.1:${server.address().port}`,mutationEvidence,close};
  } catch(error) {await close();throw error;}
}
