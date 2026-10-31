import test from'node:test';
import assert from'node:assert/strict';
import{libraryStore}from'../src/personal/library.js';
const memory=new Map();
globalThis.localStorage={getItem:key=>memory.get(key)??null,setItem:(key,value)=>memory.set(key,value),removeItem:key=>memory.delete(key)};
const json=value=>new Response(JSON.stringify(value),{headers:{'content-type':'application/json'}});

test('offline watchlist additions/removals sync on reconnect with account identity',async()=>{
 memory.clear();libraryStore.set('alice','saved:1',{item:{title:'Episode'}});
 globalThis.fetch=async()=>{throw new Error('Offline')};await assert.rejects(()=>libraryStore.sync('alice'));
 assert.equal(libraryStore.read('alice')['saved:1'].item.title,'Episode');
 const remote={};let writes=0;
 globalThis.fetch=async(path,options)=>{assert.equal(options.headers['X-App-User'],'alice');if(options.method==='PUT'){const body=JSON.parse(options.body);remote[body.key]=body.value;writes++}else if(options.method==='DELETE'){delete remote[decodeURIComponent(path.slice(9))];writes++}return json(options.method?{ok:true}:remote)};
 await libraryStore.sync('alice');assert.equal(writes,1);assert.equal(remote['saved:1'].item.title,'Episode');
 libraryStore.set('alice','saved:1',null);await libraryStore.sync('alice');assert.equal(writes,2);assert.equal(remote['saved:1'],undefined);
 assert.deepEqual(libraryStore.read('bob'),{});
});

test('a newer progress update survives an older in-flight sync',async()=>{
 memory.clear();libraryStore.set('alice','progress:show:2:1',{position:10});let release;const gate=new Promise(resolve=>release=resolve);let started;const entered=new Promise(resolve=>started=resolve);const remote={};
 globalThis.fetch=async(path,options)=>{if(options.method==='PUT'){const body=JSON.parse(options.body);started();await gate;remote[body.key]=body.value;return json({ok:true})}return json(remote)};
 const sync=libraryStore.sync('alice');await entered;libraryStore.set('alice','progress:show:2:1',{position:20});release();const result=await sync;
 assert.equal(result['progress:show:2:1'].position,20);
 globalThis.fetch=async(path,options)=>{if(options.method==='PUT'){const body=JSON.parse(options.body);remote[body.key]=body.value;return json({ok:true})}return json(remote)};
 await libraryStore.sync('alice');assert.equal(remote['progress:show:2:1'].position,20);
});
