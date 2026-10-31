// Last-write-wins device outbox. No passwords or auth cookies are stored here.
const flights=new Map();
const cacheKey=user=>'fakeflix-library-'+user;
const pendingKey=user=>'fakeflix-library-outbox-'+user;
const readJSON=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key))??fallback}catch{return fallback}};
async function request(path,options={},user){const r=await fetch(path,{...options,credentials:'same-origin',headers:{'Content-Type':'application/json','X-App-User':user}});if(!r.ok)throw new Error('Library sync unavailable');return r.json();}
export const libraryStore={
 read(user){return readJSON(cacheKey(user),{});},
 set(user,key,value){const data=this.read(user),outbox=readJSON(pendingKey(user),{});if(value===null)delete data[key];else data[key]=value;outbox[key]={value,revision:crypto.randomUUID()};localStorage.setItem(cacheKey(user),JSON.stringify(data));localStorage.setItem(pendingKey(user),JSON.stringify(outbox));return data;},
 async sync(user){
  if(flights.has(user))return flights.get(user);
  const task=(async()=>{
   const pending=readJSON(pendingKey(user),{});
   for(const [key,entry]of Object.entries(pending)){
    await request(entry.value===null?'/library/'+encodeURIComponent(key):'/library',{method:entry.value===null?'DELETE':'PUT',...(entry.value===null?{}:{body:JSON.stringify({key,value:entry.value})})},user);
    const current=readJSON(pendingKey(user),{});if(current[key]?.revision===entry.revision){delete current[key];localStorage.setItem(pendingKey(user),JSON.stringify(current));}
   }
   const remote=await request('/library',{},user),remaining=readJSON(pendingKey(user),{});
   for(const [key,entry]of Object.entries(remaining)){if(entry.value===null)delete remote[key];else remote[key]=entry.value;}
   localStorage.setItem(cacheKey(user),JSON.stringify(remote));return remote;
  })();flights.set(user,task);try{return await task}finally{flights.delete(user)}
 },
};
