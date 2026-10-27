import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const script=fs.readFileSync(new URL('../public/sw.js',import.meta.url),'utf8');
function worker(){const handlers={},cached=[];vm.runInNewContext(script,{self:{location:{origin:'http://localhost'},addEventListener:(name,fn)=>handlers[name]=fn},URL,caches:{open:async()=>({addAll:async urls=>cached.push(...urls)}),keys:async()=>[],match:async()=>new Response('Safe offline page')},fetch:()=>Promise.reject(Error('Offline')),Promise});return{handlers,cached};}
test('PWA installation only caches public shell assets',async()=>{const {handlers,cached}=worker();let done;handlers.install({waitUntil:p=>done=p});await done;assert.deepEqual([...cached],['/offline.html','/manifest.webmanifest','/icon.svg']);});
test('API requests are never cached or intercepted',()=>{const {handlers}=worker();let intercepted=false;handlers.fetch({request:{url:'http://localhost/api/me/export',mode:'cors'},respondWith:()=>intercepted=true});assert.equal(intercepted,false);});
test('offline navigation returns the safe offline page',async()=>{const {handlers}=worker();let response;handlers.fetch({request:{url:'http://localhost/',mode:'navigate'},respondWith:p=>response=p});assert.equal(await(await response).text(),'Safe offline page');});
