import {existsSync,readFileSync,writeFileSync} from 'node:fs';
import {randomBytes} from 'node:crypto';
const args=new Set(process.argv.slice(2));
const file='.env.local';
if(!existsSync(file)){
 const users=args.has('--demo')?{preview:'preview-only-12345'}:{kishor:randomBytes(15).toString('base64url'),friend:randomBytes(15).toString('base64url')};
 writeFileSync(file,`APP_USERS=${JSON.stringify(users)}\nSESSION_SECRET=${randomBytes(48).toString('base64url')}\nCOOKIE_SECURE=false\nMEDIA_PROVIDER=vyla\nVYLA_BASE_URL=http://127.0.0.1:7860\nTMDB_API_KEY=\n`,{mode:0o600,flag:'wx'});
 console.log('Created local HTTP configuration. These accounts are local; no hosted app was created.');
 for(const[user,password]of Object.entries(users))console.log(`Username: ${user}\nPassword: ${password}\n`);
}else if(args.has('--show')){
 const line=readFileSync(file,'utf8').split('\n').find(line=>line.startsWith('APP_USERS='));
 if(!line)throw new Error('APP_USERS was not found in .env.local');
 for(const[user,password]of Object.entries(JSON.parse(line.slice('APP_USERS='.length))))console.log(`Username: ${user}\nPassword: ${password}\n`);
}else console.log('.env.local already exists; it was not overwritten. Use npm run credentials:local to show your local login.');
console.log('After installing README prerequisites: npm run build && npm start');
console.log('Then open http://localhost:5173 on the machine running the app.');
console.log('Demo credentials are for local testing only; configure unique passwords before hosting.');
