// Device-local downloads with validated byte-range resume when the source supports it.
export function createDownloads({database='fakeflix-offline',fetcher=(...args)=>fetch(...args),concurrency=2}={}){
 let dbPromise, jobs=[], owner='', active=0;
 const listeners=new Set(),controllers=new Map(),running=new Map();
 const db=()=>dbPromise ||= new Promise((resolve,reject)=>{
  const request=indexedDB.open(database,1);
  request.onupgradeneeded=()=>{request.result.createObjectStore('jobs',{keyPath:'id'});request.result.createObjectStore('chunks',{keyPath:['job','index']});};
  request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
 });
 async function transaction(store,mode,run){const database=await db();return new Promise((resolve,reject)=>{
  const tx=database.transaction(store,mode);let result;const req=run(tx.objectStore(store));
  if(req)req.onsuccess=()=>{result=req.result};tx.oncomplete=()=>resolve(result);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||new Error('Storage operation aborted'));
 });}
 const range=id=>IDBKeyRange.bound([id,0],[id,Number.MAX_SAFE_INTEGER]);
 const put=job=>transaction('jobs','readwrite',store=>store.put(job));
 const emit=()=>listeners.forEach(fn=>fn([...jobs]));
 async function update(job,patch){Object.assign(job,patch);await put(job);if(job.owner===owner)emit();}
 const clear=id=>transaction('chunks','readwrite',store=>store.delete(range(id)));
 // A cursor avoids loading a partly downloaded multi-GB video into memory just to resume it.
 async function summary(id){const database=await db();return new Promise((resolve,reject)=>{
  const tx=database.transaction('chunks');const req=tx.objectStore('chunks').openCursor(range(id));let bytes=0,index=0,head=new Uint8Array();
  req.onsuccess=()=>{const cursor=req.result;if(!cursor)return;const value=cursor.value;bytes+=value.data.byteLength;index=Math.max(index,value.index+1);if(head.length<32){const next=value.data.slice(0,32-head.length);const merged=new Uint8Array(head.length+next.length);merged.set(head);merged.set(next,head.length);head=merged;}cursor.continue();};
  tx.oncomplete=()=>resolve({bytes,index,head});tx.onerror=()=>reject(tx.error);
 });}
 async function stopAll(){for(const c of controllers.values())c.abort();await Promise.allSettled([...running.values()]);}
 const manager={
  subscribe(fn){listeners.add(fn);fn([...jobs]);return()=>listeners.delete(fn)},
  async init(user){owner='';await stopAll();owner=user;const all=await transaction('jobs','readonly',store=>store.getAll());jobs=all.filter(job=>job.owner===user);for(const job of jobs){if(['downloading','queued'].includes(job.status)){job.status='interrupted';job.error='Browser stopped. Resume if supported, or retry.';await put(job);}}emit();},
  async enqueue(item,season,episode,quality='auto',sourceId=''){
   if(!owner)throw new Error('Sign in first');
   const id=JSON.stringify([owner,String(item.subjectId),Number(season),Number(episode),quality,sourceId]);
   if(jobs.some(job=>job.id===id))return;
   const job={id,owner,item,season:Number(season),episode:Number(episode),quality,sourceId,status:'queued',bytes:0,total:0,created:Date.now()};
   await put(job);jobs=[job,...jobs];emit();pump();
  },
  async stop(id){const job=jobs.find(job=>job.id===id);if(!job)return;controllers.get(id)?.abort();await running.get(id);if(job.status!=='completed')await update(job,{status:'interrupted',speed:0,error:'Paused. Resume continues only when the source supplies a strong ETag.'});},
  async retry(id,restart=false){await running.get(id);const job=jobs.find(job=>job.id===id);if(!job||job.status==='completed')return;
   if(restart){await clear(id);Object.assign(job,{bytes:0,total:0,etag:null});}
   await update(job,{status:'queued',error:'',speed:0});pump();
  },
  async remove(id){const job=jobs.find(job=>job.id===id);if(!job)return;controllers.get(id)?.abort();await running.get(id);await clear(id);await transaction('jobs','readwrite',store=>store.delete(id));jobs=jobs.filter(job=>job.id!==id);emit();},
  async blob(id){const job=jobs.find(job=>job.id===id);if(!job||job.status!=='completed')throw new Error('Download is not complete');const chunks=await transaction('chunks','readonly',store=>store.getAll(range(id)));if(!chunks.length)throw new Error('Saved video missing from this device');return new Blob(chunks.map(c=>c.data),{type:'video/mp4'});},
  async save(id){const job=jobs.find(job=>job.id===id);const url=URL.createObjectURL(await manager.blob(id));const a=document.createElement('a');a.href=url;a.download=`${job.item.title.replace(/[<>:"/\\|?*]/g,'_')}.S${String(job.season).padStart(2,'0')}E${String(job.episode).padStart(2,'0')}.${job.quality}.mp4`;a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);},
  snapshot:()=>[...jobs],
  async idle(){while(running.size)await Promise.allSettled([...running.values()]);},
 };
 function pump(){while(owner&&active<concurrency){const job=jobs.find(job=>job.status==='queued');if(!job)break;job.status='downloading';active++;const task=run(job).finally(()=>{running.delete(job.id);active--;pump();});running.set(job.id,task);}}
 async function run(job){const controller=new AbortController();controllers.set(job.id,controller);
  const transfer=async()=>{
   if(controller.signal.aborted)throw new DOMException('Paused','AbortError');
   const persisted=await transaction('jobs','readonly',store=>store.get(job.id));
   if(persisted?.status==='completed'){Object.assign(job,persisted);emit();return;}
   let state=await summary(job.id);
   const strong=typeof job.etag==='string'&&job.etag.startsWith('"')&&job.etag.endsWith('"');
   if(state.bytes&&!strong){await clear(job.id);state={bytes:0,index:0,head:new Uint8Array()};}
   const headers={'X-App-User':job.owner,...(state.bytes?{Range:`bytes=${state.bytes}-`,'If-Range':job.etag}:{})};
   await update(job,{status:'downloading',bytes:state.bytes});
   const qs=new URLSearchParams({season:job.season,episode:job.episode,quality:job.quality,source_id:job.sourceId||''});
   const response=await fetcher(`/download/${encodeURIComponent(job.item.subjectId)}?${qs}`,{headers,signal:controller.signal,credentials:'same-origin'});
   if(!response.ok){let detail=await response.text();try{const parsed=JSON.parse(detail);detail=parsed.detail?.message||parsed.detail||parsed.message||detail;}catch{}if([409,416].includes(response.status)){await clear(job.id);job.etag=null;}throw new Error(typeof detail==='string'?detail:'Source request failed');}
   const etag=response.headers.get('etag');let total=Number(response.headers.get('content-length'))||0;
   if(response.status===206){
    const match=/^bytes (\d+)-(\d+)\/(\d+)$/.exec(response.headers.get('content-range')||'');
    if(!match||Number(match[1])!==state.bytes||!state.bytes||etag!==job.etag){await clear(job.id);job.etag=null;throw new Error('Source changed or returned the wrong byte range. Restart required.');}
    total=Number(match[3]);
   }else if(state.bytes){await clear(job.id);state={bytes:0,index:0,head:new Uint8Array()};}
   if(navigator.storage?.estimate){const space=await navigator.storage.estimate();if(total&&space.quota-space.usage<(total-state.bytes)*1.15)throw new Error('Not enough browser storage. Delete old downloads.');}
   await update(job,{total,etag:etag?.startsWith('"')?etag:null});
   const reader=response.body.getReader();let {bytes,index,head}=state,last=0,start=Date.now(),received=0;
   while(true){const {value,done}=await reader.read();if(done)break;if(controller.signal.aborted)throw new DOMException('Paused','AbortError');
    if(head.length<32){const next=value.slice(0,32-head.length),joined=new Uint8Array(head.length+next.length);joined.set(head);joined.set(next,head.length);head=joined;}
    if(head.length>=8&&String.fromCharCode(...head.slice(4,8))!=='ftyp'){await clear(job.id);job.etag=null;throw new Error('Source did not return MP4 video. Download rejected.');}
    await transaction('chunks','readwrite',store=>store.put({job:job.id,index:index++,data:value}));bytes+=value.length;received+=value.length;
    if(Date.now()-last>500){await update(job,{bytes,speed:received/Math.max(.1,(Date.now()-start)/1000)});last=Date.now();}
   }
   if(!bytes||head.length<8||String.fromCharCode(...head.slice(4,8))!=='ftyp')throw new Error('Source was not an MP4 video');
   if(total&&bytes!==total)throw new Error('Transfer interrupted. Resume or retry.');
   await update(job,{status:'completed',bytes,total:bytes,error:'',speed:0});
  };
  try{if(navigator.locks)await navigator.locks.request('fakeflix-download-'+job.id,{signal:controller.signal},transfer);else await transfer();}
  catch(error){controller.abort();const partial=await summary(job.id);await update(job,{status:error.name==='AbortError'?'interrupted':'failed',bytes:partial.bytes,error:error.name==='AbortError'?'Paused. Resume when ready.':error.message,speed:0});}
  finally{controllers.delete(job.id);}
 }
 return manager;
}
export const downloads=createDownloads();
