import {readdir,writeFile} from 'node:fs/promises';
const assets=await readdir('dist/assets');
const files=['/','/index.html','/manifest.json','/Fakeflix_favicon_192.png',...assets.map(x=>'/assets/'+x)];
const worker=`
const CACHE='fakeflix-${Date.now()}';
const FILES=${JSON.stringify(files)};
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(FILES))));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('fakeflix-')&&key!==CACHE).map(key=>caches.delete(key))))));
self.addEventListener('fetch',event=>{
 const url=new URL(event.request.url);
 if(url.origin!==location.origin||event.request.method!=='GET'||['/api','/auth','/media','/download','/library'].some(path=>url.pathname.startsWith(path)))return;
 if(event.request.mode==='navigate'){
  event.respondWith(fetch(event.request).catch(()=>caches.match('/index.html')));return;
 }
 event.respondWith(caches.match(event.request).then(response=>response||fetch(event.request)));
});
`;
await writeFile('dist/sw.js',worker);
