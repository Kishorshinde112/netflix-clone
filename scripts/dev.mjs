import {readFileSync,existsSync} from 'node:fs';
import {spawn} from 'node:child_process';
import {resolve} from 'node:path';
const env={...process.env};
if(existsSync('.env.local'))for(const line of readFileSync('.env.local','utf8').split('\n')){if(!line.trim()||line.startsWith('#'))continue;const i=line.indexOf('=');if(i>0&&!env[line.slice(0,i)])env[line.slice(0,i)]=line.slice(i+1).trim().replace(/^['"]|['"]$/g,'');}
const python=existsSync('backend/.venv/bin/python')?resolve('backend/.venv/bin/python'):'python';
const child=spawn(python,['-m','uvicorn','personal_server:app','--host','0.0.0.0','--port',env.PORT||process.argv[2]||'5173','--proxy-headers'],{cwd:resolve('backend'),env,stdio:'inherit'});
for(const sig of ['SIGTERM','SIGINT'])process.on(sig,()=>child.kill(sig));
child.on('exit',code=>process.exit(code??0));
