import 'fake-indexeddb/auto';
import test from 'node:test';
import assert from 'node:assert/strict';
import {createDownloads}from'../src/personal/downloads.js';
Object.defineProperty(globalThis,'navigator',{configurable:true,value:{storage:{estimate:async()=>({quota:1e9,usage:0})}}});
const data=new Uint8Array([0,0,0,16,102,116,121,112,105,115,111,109,0,0,0,0]);
const item={subjectId:'series-1',title:'Series'};
const setup=fetcher=>createDownloads({database:'test-'+crypto.randomUUID(),fetcher});
const response=(body,headers={},status=200)=>new Response(body,{status,headers:{'content-type':'video/mp4','content-length':String(body.byteLength),'etag':'"same-file"',...headers}});
async function partial(){let reads=0;return new ReadableStream({pull(c){if(!reads++){c.enqueue(data.slice(0,10));return}c.error(new Error('Connection lost'));}})}

test('two concurrent downloads, four separate season/episode identities',async()=>{
 let active=0,max=0;const urls=[];
 const manager=setup(async url=>{urls.push(url);active++;max=Math.max(active,max);let read=false;return new Response(new ReadableStream({async pull(c){if(read)return;read=true;await new Promise(r=>setTimeout(r,25));c.enqueue(data);c.close();active--;}}),{headers:{'content-type':'video/mp4','content-length':'16','etag':'"same-file"'}});});
 await manager.init('alice');
 for(const [s,e]of[[1,10],[2,1],[2,2],[2,3]])await manager.enqueue(item,s,e,'auto');
 await manager.idle();assert.equal(max,2);assert.equal(manager.snapshot().filter(j=>j.status==='completed').length,4);
 assert.ok(urls.some(url=>url.includes('season=1&episode=10')));assert.ok(urls.some(url=>url.includes('season=2&episode=1')));
 assert.equal(new Set(manager.snapshot().map(j=>j.id)).size,4);
});

test('resume appends only the matching source ETag and byte range',async()=>{
 const calls=[];let attempt=0;const manager=setup(async(url,options)=>{calls.push(options.headers);if(!attempt++)return new Response(await partial(),{headers:{etag:'"same-file"','content-type':'video/mp4','content-length':'16'}});return response(data.slice(10),{'content-range':'bytes 10-15/16'},206);});
 await manager.init('alice');await manager.enqueue(item,2,1,'auto');await manager.idle();
 const job=manager.snapshot()[0];assert.equal(job.status,'failed');assert.equal(job.bytes,10);
 await manager.retry(job.id);await manager.idle();assert.equal(calls[1].Range,'bytes=10-');assert.equal(calls[1]['If-Range'],'"same-file"');
 assert.equal(manager.snapshot()[0].status,'completed');assert.deepEqual(new Uint8Array(await(await manager.blob(job.id)).arrayBuffer()),data);
});

test('200 on resume replaces partial data instead of corrupting the movie',async()=>{
 let attempt=0;const manager=setup(async()=>!attempt++?new Response(await partial(),{headers:{etag:'"same-file"','content-type':'video/mp4','content-length':'16'}}):response(data,{etag:'"new-file"'}));
 await manager.init('alice');await manager.enqueue(item,2,1);await manager.idle();const job=manager.snapshot()[0];await manager.retry(job.id);await manager.idle();
 assert.equal((await manager.blob(job.id)).size,16);assert.equal(manager.snapshot()[0].etag,'"new-file"');
});

test('wrong 206 offset is rejected and partial data is cleared',async()=>{
 let attempt=0;const manager=setup(async()=>!attempt++?new Response(await partial(),{headers:{etag:'"same-file"','content-type':'video/mp4','content-length':'16'}}):response(data,{'content-range':'bytes 0-15/16'},206));
 await manager.init('alice');await manager.enqueue(item,2,1);await manager.idle();const job=manager.snapshot()[0];await manager.retry(job.id);await manager.idle();
 assert.equal(manager.snapshot()[0].status,'failed');assert.equal(manager.snapshot()[0].bytes,0);await assert.rejects(()=>manager.blob(job.id));
});

test('source notice rejection is shown as a useful error, not a saved movie',async()=>{
 const manager=setup(async()=>new Response(JSON.stringify({detail:{code:'SOURCE_PREVIEW_ONLY',message:'Source returned a notice video.'}}),{status:409}));
 await manager.init('alice');await manager.enqueue(item,2,1);await manager.idle();assert.equal(manager.snapshot()[0].status,'failed');assert.match(manager.snapshot()[0].error,/notice video/);
});

test('MP4 signature is checked across small chunks',async()=>{
 const manager=setup(async()=>{let i=0;return new Response(new ReadableStream({pull(c){if(i>=data.length){c.close();return}c.enqueue(data.slice(i,i+4));i+=4;}}),{headers:{'content-length':'16','content-type':'video/mp4'}});});
 await manager.init('alice');await manager.enqueue(item,2,1);await manager.idle();assert.equal(manager.snapshot()[0].status,'completed');
});

test('HTML/error body cannot become a completed offline movie',async()=>{
 const manager=setup(async()=>response(new TextEncoder().encode('<html>Access denied</html>')));await manager.init('alice');await manager.enqueue(item,2,1);await manager.idle();assert.equal(manager.snapshot()[0].status,'failed');assert.equal(manager.snapshot()[0].bytes,0);
});

test('switching users exposes only that user’s device library',async()=>{
 const manager=setup(async()=>response(data));await manager.init('alice');await manager.enqueue(item,2,1);await manager.idle();await manager.init('bob');assert.equal(manager.snapshot().length,0);await manager.init('alice');assert.equal(manager.snapshot().length,1);
});

test('a complete generated H.264 MP4 survives device storage/export and ffprobe validation',async t=>{
 const{spawnSync}=await import('node:child_process');
 if(spawnSync('ffmpeg',['-version']).error||spawnSync('ffprobe',['-version']).error){t.skip('ffmpeg/ffprobe not installed');return;}
 const generated=spawnSync('ffmpeg',['-v','error','-f','lavfi','-i','color=c=black:s=64x64:r=10','-t','1','-c:v','libx264','-pix_fmt','yuv420p','-movflags','frag_keyframe+empty_moov','-f','mp4','pipe:1']);
 assert.equal(generated.status,0,generated.stderr.toString());const movie=new Uint8Array(generated.stdout);
 const manager=setup(async()=>response(movie));await manager.init('alice');await manager.enqueue(item,2,1);await manager.idle();
 const blob=await manager.blob(manager.snapshot()[0].id);const exported=Buffer.from(await blob.arrayBuffer());assert.deepEqual(exported,generated.stdout);
 const probe=spawnSync('ffprobe',['-v','error','-show_entries','stream=codec_name,width,height','-of','json','-i','pipe:0'],{input:exported});
 assert.equal(probe.status,0,probe.stderr.toString());const stream=JSON.parse(probe.stdout.toString()).streams[0];assert.equal(stream.codec_name,'h264');assert.equal(stream.width,64);
});
