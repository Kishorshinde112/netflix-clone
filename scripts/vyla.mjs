import {readFileSync,existsSync} from 'node:fs';
import {spawn} from 'node:child_process';
import {resolve} from 'node:path';
const env={...process.env};
if(existsSync('.env.local'))for(const line of readFileSync('.env.local','utf8').split('\n')){if(!line.trim()||line.startsWith('#'))continue;const i=line.indexOf('=');if(i>0&&!env[line.slice(0,i)])env[line.slice(0,i)]=line.slice(i+1).trim().replace(/^['"]|['"]$/g,'');}
if(!env.TMDB_API_KEY){console.error('Add TMDB_API_KEY to .env.local before starting Vyla.');process.exit(1);}
Object.assign(env,{PORT:'7860',BIND_HOST:'127.0.0.1',PUBLIC_BASE_URL:'http://127.0.0.1:7860',WORKER_COUNT:'1',ENABLE_DEBUG_ROUTE:'false',PROXY_STREAMS:'true',GA_MEASUREMENT_ID:'',GA_API_SECRET:''});
const child=spawn(process.execPath,['server.js'],{cwd:resolve('services/vyla'),env,stdio:'inherit'});
for(const sig of ['SIGTERM','SIGINT'])process.on(sig,()=>child.kill(sig));
child.on('exit',code=>process.exit(code??0));
