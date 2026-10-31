"""Private gateway; the upstream debug and external-player routes are not exposed."""
import base64,hashlib,hmac,ipaddress,json,os,re,secrets,socket,sqlite3,time,threading
from pathlib import Path
from urllib.parse import urljoin,urlparse
from fastapi import FastAPI,Request,Response,HTTPException
from fastapi.responses import FileResponse,StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
import httpx
import moviebox_api_server as upstream
from vyla_provider import provider as vyla
from media_selection import choose_stream, describe_sources, validate_episode, normalize_episodes, direct_metadata_streams, clean_streams
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
def uses_vyla():return os.getenv('MEDIA_PROVIDER','moviebox').lower()=='vyla'
USERS=json.loads(os.getenv('APP_USERS','{}'));SECRET=os.getenv('SESSION_SECRET','')
if not USERS or len(SECRET)<32 or any(not isinstance(p,str) or len(p)<12 for p in USERS.values()):
 raise RuntimeError('Configure APP_USERS JSON with 12+ character passwords and SESSION_SECRET with 32+ characters.')
if os.getenv('DYNO') and not os.getenv('DATABASE_URL'):raise RuntimeError('Heroku requires DATABASE_URL for durable user libraries.')
PASSWORDS={u:hashlib.pbkdf2_hmac('sha256',p.encode(),SECRET.encode(),180000) for u,p in USERS.items()}
TOKENS={};ATTEMPTS={};UPSTREAM_IDS={};SESSION_LOCK=threading.Lock();SOURCE_CACHE={};REVOKED={}
DIST=Path(os.getenv('STATIC_DIR',str(Path(__file__).resolve().parents[1]/'dist')))
def sign(data):
 raw=base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip('=')
 return raw+'.'+hmac.new(SECRET.encode(),raw.encode(),'sha256').hexdigest()
def read_session(request):
 try:
  raw,sig=request.cookies.get('personal_session','').rsplit('.',1)
  if not hmac.compare_digest(sig,hmac.new(SECRET.encode(),raw.encode(),'sha256').hexdigest()):return None
  d=json.loads(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)))
  return d if d['user'] in USERS and d['exp']>time.time() and d['sid'] not in REVOKED else None
 except Exception:return None
@app.middleware('http')
async def protect(request,call_next):
 path=request.url.path
 if path.startswith(('/api','/library','/media','/download','/auth/me','/auth/logout')):
  request.state.session=read_session(request)
  if not request.state.session:return Response('Sign in required',status_code=401)
  expected=request.headers.get('x-app-user')
  if expected and expected!=request.state.session['user']:return Response('Account changed. Reopen this page.',status_code=403)
 if request.method not in ('GET','HEAD','OPTIONS'):
  origin=request.headers.get('origin')
  if origin and urlparse(origin).netloc!=request.headers.get('host'):return Response('Origin rejected',status_code=403)
 try:response=await call_next(request)
 except (httpx.HTTPError,upstream.requests.RequestException):return Response('Source connection unavailable. Please retry.',status_code=502)
 response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='same-origin';response.headers['X-Frame-Options']='DENY'
 if path.startswith(('/api','/auth','/library','/media','/download')):response.headers['Cache-Control']='no-store'
 return response
class Login(BaseModel):
 username:str=Field(max_length=100)
 password:str=Field(max_length=500)
@app.post('/auth/login')
def login(body:Login,request:Request,response:Response):
 key=request.client.host if request.client else 'unknown';recent=[t for t in ATTEMPTS.get(key,[]) if time.time()-t<900];ATTEMPTS[key]=recent
 if len(recent)>=10:raise HTTPException(429,'Too many attempts. Try again in 15 minutes.')
 recent.append(time.time());candidate=hashlib.pbkdf2_hmac('sha256',body.password.encode(),SECRET.encode(),180000)
 if not hmac.compare_digest(candidate,PASSWORDS.get(body.username,b'0'*32)):raise HTTPException(401,'Incorrect username or password')
 ATTEMPTS.pop(key,None);data={'user':body.username,'sid':secrets.token_urlsafe(24),'exp':time.time()+7*86400}
 response.set_cookie('personal_session',sign(data),httponly=True,secure=os.getenv('COOKIE_SECURE','true')=='true',samesite='strict',max_age=7*86400)
 return {'username':body.username}
@app.get('/auth/me')
def me(request:Request):return {'username':request.state.session['user']}
@app.post('/auth/logout')
def logout(request:Request,response:Response):
 data=request.state.session;REVOKED[data['sid']]=data['exp']
 for sid,exp in list(REVOKED.items()):
  if exp<time.time():REVOKED.pop(sid,None)
 disconnect_source(request)
 response.delete_cookie('personal_session');return {'ok':True}
@app.get('/health')
def health():return {'status':'ok'}
def query(sql,args=(),fetch=False):
 if os.getenv('DATABASE_URL'):
  import psycopg
  conn=psycopg.connect(os.environ['DATABASE_URL']);sql=sql.replace('?','%s')
 else:conn=sqlite3.connect(os.getenv('LIBRARY_DB','library.sqlite3'))
 try:
  c=conn.cursor();c.execute(sql,args);data=c.fetchall() if fetch else None;conn.commit();return data
 finally:conn.close()
query('CREATE TABLE IF NOT EXISTS personal_library (username TEXT NOT NULL,key TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(username,key))')
@app.get('/library')
def library(request:Request):return {k:json.loads(v) for k,v in query('SELECT key,payload FROM personal_library WHERE username=?',(request.state.session['user'],),True)}
class LibraryValue(BaseModel):
 key:str=Field(max_length=200)
 value:dict
@app.put('/library')
def save_library(body:LibraryValue,request:Request):
 raw=json.dumps(body.value)
 if len(raw)>30000:raise HTTPException(413,'Entry too large')
 query('INSERT INTO personal_library(username,key,payload) VALUES(?,?,?) ON CONFLICT(username,key) DO UPDATE SET payload=excluded.payload',(request.state.session['user'],body.key,raw));return {'ok':True}
@app.delete('/library/{key}')
def delete_library(key:str,request:Request):query('DELETE FROM personal_library WHERE username=? AND key=?',(request.state.session['user'],key));return {'ok':True}
def session(request):
 sid=request.state.session['sid']
 with SESSION_LOCK:
  if sid not in UPSTREAM_IDS:UPSTREAM_IDS[sid]=upstream.get_session()['id']
  return upstream.get_session(UPSTREAM_IDS[sid])
@app.get('/api/{endpoint}')
@app.get('/api/{endpoint}/{subject_id}')
def catalog(endpoint:str,request:Request,subject_id:str='',q:str='',page:int=1,season:int=1,episode:int=1,quality:str='auto',source_id:str=''):
 if endpoint=='stream':return stream(subject_id,request,season,episode,quality,source_id)
 if endpoint=='sources':return sources(subject_id,request,season,episode)
 if endpoint=='connection':return connection_status(request)
 if endpoint not in {'home','movies','anime','trending','rankings','search','detail','episodes'}:raise HTTPException(404)
 if uses_vyla():return vyla.catalog(endpoint,subject_id,q,page,season)
 sid=session(request)['id']
 if endpoint in ('detail','episodes'):
  source=upstream.get_session(sid)
  if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',subject_id):raise HTTPException(422,'Invalid source title ID')
  if endpoint=='episodes':return {'code':0,'data':{'seasons':normalize_episodes(cached_source(source,'episodes',subject_id))}}
  raw=cached_source(source,'detail',subject_id)
  mapped=upstream.map_item(raw)
  mapped['languages']=[{'type':'dub','subjectId':str(d['subjectId']),'name':d.get('lanName') or 'Audio version'} for d in raw.get('dubs',[]) if d.get('subjectId')]
  return {'code':0,'data':mapped}
 if endpoint=='search':return upstream.search(Response(),q=q,page=page,session_id=sid)
 if endpoint=='rankings':return upstream.get_rankings(Response(),session_id=sid)
 if endpoint=='trending':return upstream.get_trending(Response(),session_id=sid)
 return {'home':upstream.get_home,'movies':upstream.get_movies,'anime':upstream.get_anime}[endpoint](page=page,session_id=sid)
def public_url(url):
 p=urlparse(url)
 base=os.getenv('VYLA_BASE_URL','').rstrip('/')
 if uses_vyla() and base and url.startswith(base+'/api?'):
  # Only the administrator-configured Vyla media proxy may use a private origin.
  # Its nested media URL must still pass the normal public HTTPS check.
  from urllib.parse import parse_qs
  nested=parse_qs(p.query).get('url',[])
  if len(nested)!=1 or nested[0].startswith(base+'/'):raise HTTPException(502,'Invalid Vyla proxy target')
  public_url(nested[0]);return url
 if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):raise HTTPException(502,'Invalid media URL')
 try:
  addresses=socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)
  if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError()
 except Exception:raise HTTPException(502,'Media source must use public HTTPS')
 return url
def media_url(url,headers,owner):
 public_url(url)
 for k,v in list(TOKENS.items()):
  if v['expires']<time.time():TOKENS.pop(k,None)
 if len(TOKENS)>1000:raise HTTPException(503,'Too many media links')
 p=urlparse(url)
 for existing,v in TOKENS.items():
  if v['owner']==owner and v['headers']==headers and v['url']==url:
   return '/media/'+existing+p.path+('?' + p.query if p.query else '')
 key=secrets.token_urlsafe(24);TOKENS[key]={'url':url,'headers':headers,'owner':owner,'expires':time.time()+6*3600};p=urlparse(url)
 return '/media/'+key+p.path+('?' + p.query if p.query else '')
def cached_source(s, kind, subject_id):
 key=(s['id'],kind,subject_id)
 cached=SOURCE_CACHE.get(key)
 if cached and cached[0]>time.time():return cached[1]
 result=(s['content'].get_movie_detail(subject_id) if kind=='detail' else s['content'].get_episode_list(subject_id)).get('data') or {}
 if not result:raise HTTPException(502,'Source metadata unavailable. Retry later.')
 SOURCE_CACHE[key]=(time.time()+120,result)
 if len(SOURCE_CACHE)>500:SOURCE_CACHE.pop(next(iter(SOURCE_CACHE)))
 return result

def source_payload(request,subject_id,season,episode):
 s=session(request)
 detail=cached_source(s,'detail',subject_id)
 is_movie=str(detail.get('subjectType') or detail.get('type'))=='1'
 seasons={} if is_movie else cached_source(s,'episodes',subject_id)
 validate_episode(detail,seasons,season,episode)
 # Only normal API calls are used. Access errors are not retried as another entitlement.
 res=s['stream'].get_play_info_v2(subject_id,season=None if is_movie else season,episode=None if is_movie else episode)
 data=res.get('data') or {}
 if res.get('code') not in (0,200,None):raise HTTPException(502,'Source rejected the playback request. Check source account/access.')
 try:clean_streams(data,season,episode)
 except HTTPException as error:
  if error.status_code not in (404,409):raise
  legacy=s['stream'].get_play_info(subject_id,season=None if is_movie else season,episode=None if is_movie else episode)
  if legacy.get('code') not in (0,200,None):raise HTTPException(502,'Source rejected the playback request.')
  legacy_data=legacy.get('data') or {}
  try:
   clean_streams(legacy_data,season,episode)
   data=legacy_data
  except HTTPException as legacy_error:
   if legacy_error.status_code not in (404,409):raise
   direct=direct_metadata_streams(detail,subject_id,season,episode)
   if direct:data={**data,'streams':direct,'streamList':[]}

 return s,data

def resolve(request,subject_id,season,episode,quality='auto',source_id=None,download=False):
 if uses_vyla():return vyla.resolve(subject_id,season,episode,quality,source_id,download)
 s,data=source_payload(request,subject_id,season,episode)
 selected=dict(choose_stream(data,season,episode,quality,source_id))
 selected['_subtitles']=data.get('subTitleList') or data.get('subtitles') or []
 headers={'User-Agent':'ExoPlayerLib/2.18.7','Accept-Encoding':'identity'}
 cookie='' if selected.get('_metadataDirect') else selected.get('signCookie') or data.get('signCookie') or ''
 if cookie:headers['Cookie']=cookie
 return selected,headers

@app.get('/api/sources/{subject_id}')
def sources(subject_id:str,request:Request,season:int=1,episode:int=1):
 if uses_vyla():return vyla.sources(subject_id,season,episode)
 s,data=source_payload(request,subject_id,season,episode)
 return {'season':season,'episode':episode,'sources':describe_sources(data,season,episode)}

@app.get('/api/stream/{subject_id}')
def stream(subject_id:str,request:Request,season:int=1,episode:int=1,quality:str='auto',source_id:str=''):
 selected,headers=resolve(request,subject_id,season,episode,quality,source_id or None)
 owner=request.state.session['user']
 subtitles=[]
 for sub in selected.get('_subtitles',[]):
  if not isinstance(sub,dict) or not sub.get('url'):continue
  subtitles.append({'label':sub.get('label') or sub.get('lanName') or sub.get('language') or 'Subtitles','url':media_url(sub['url'],headers,owner)})
 return {'url':media_url(selected['url'],headers,owner),'season':season,'episode':episode,
         'quality':quality,'sourceId':str(selected.get('id') or ''),'codec':selected.get('codecName') or '',
         'subtitles':subtitles,'format':selected.get('format') or ('hls' if selected.get('_vyla') else '')}

async def open_media(url,headers,accepted=(200,206)):
 client=httpx.AsyncClient(timeout=httpx.Timeout(30,read=60),follow_redirects=False)
 try:
  for _ in range(5):
   await run_in_threadpool(public_url,url);r=await client.send(client.build_request('GET',url,headers=headers),stream=True)
   if r.status_code in (301,302,303,307,308):
    nxt=urljoin(url,r.headers.get('location',''))
    if urlparse(nxt).hostname!=urlparse(url).hostname:headers={k:v for k,v in headers.items() if k.lower()!='cookie'}
    await r.aclose();url=nxt;continue
   if r.status_code not in accepted:await r.aclose();raise HTTPException(502,'Source returned '+str(r.status_code))
   return client,r,url
  raise HTTPException(502,'Too many redirects')
 except Exception:await client.aclose();raise
@app.get('/media/{token}/{path:path}')
async def proxy(token:str,path:str,request:Request):
 item=TOKENS.get(token)
 if not item or item['expires']<time.time() or item['owner']!=request.state.session['user']:raise HTTPException(404,'Media link expired; reopen title')
 origin=urlparse(item['url']);target=origin.scheme+'://'+origin.netloc+'/'+path+('?' + request.url.query if request.url.query else '');headers=dict(item['headers'])
 if uses_vyla() and os.getenv('VYLA_BASE_URL') and item['url'].startswith(os.environ['VYLA_BASE_URL'].rstrip('/')+'/') and target!=item['url']:
  raise HTTPException(403,'Media URL changed. Reopen the title.')
 if request.headers.get('range'):headers['Range']=request.headers['range']
 client,res,final_url=await open_media(target,headers);ctype=res.headers.get('content-type','application/octet-stream')
 async def close():await res.aclose();await client.aclose()
 if '.m3u8' in urlparse(final_url).path or 'mpegurl' in ctype:
  try:
   text=(await res.aread()).decode();lines=[]
   def rewrite(u):return media_url(urljoin(final_url,u),item['headers'],item['owner'])
   for line in text.splitlines():
    if line and not line.startswith('#'):line=rewrite(line)
    else:line=re.sub(r'URI="([^"]+)"',lambda m:'URI="'+rewrite(m[1])+'"',line)
    lines.append(line)
   return Response('\n'.join(lines),media_type='application/vnd.apple.mpegurl')
  finally:await close()
 if '.mpd' in urlparse(final_url).path or 'dash+xml' in ctype:
  try:
   text=(await res.aread()).decode()
   text=re.sub(r'(<(?:\w+:)?BaseURL[^>]*>)(https://[^<]+)(</(?:\w+:)?BaseURL>)',lambda m:m[1]+media_url(m[2],item['headers'],item['owner'])+m[3],text)
   if re.search(r'(?:media|initialization)="https?://',text):raise HTTPException(422,'Unsupported absolute DASH segment URLs')
   return Response(text,media_type='application/dash+xml')
  finally:await close()
 if urlparse(final_url).path.lower().endswith(('.srt','.vtt')) or 'subrip' in ctype:
  try:
   text=(await res.aread()).decode('utf-8-sig')
   if not text.lstrip().startswith('WEBVTT'):
    text='WEBVTT\n\n'+re.sub(r'(\d{2}:\d{2}:\d{2}),(\d{3})',r'\1.\2',text)
   return Response(text,media_type='text/vtt')
  finally:await close()
 forwarded={k:v for k,v in res.headers.items() if k in ('content-length','content-range','accept-ranges','content-type')}
 return StreamingResponse(res.aiter_bytes(),status_code=res.status_code,headers=forwarded,background=BackgroundTask(close))
@app.get('/download/{subject_id}')
async def download(subject_id:str,request:Request,season:int=1,episode:int=1,quality:str='auto',source_id:str=''):
 if uses_vyla():selected,headers=await run_in_threadpool(vyla.resolve,subject_id,season,episode,quality,source_id or None,True)
 else:selected,headers=await run_in_threadpool(resolve,request,subject_id,season,episode,quality,source_id or None)
 url=selected['url']
 await run_in_threadpool(public_url,url)
 if re.search(r'\.(m3u8|mpd)(?:\?|$)',url,re.I):
  raise HTTPException(422,'This source is a streaming manifest. Offline MP4 merging is not available for this source yet.')
 requested_range=request.headers.get('range')
 if requested_range:
  if not re.fullmatch(r'bytes=\d+-',requested_range):raise HTTPException(422,'Only a single open-ended byte range is supported.')
  validator=request.headers.get('if-range','')
  if not validator.startswith('"') or not validator.endswith('"'):raise HTTPException(422,'Safe resume requires a strong source ETag.')
  headers.update({'Range':requested_range,'If-Range':validator})
 client,res,_=await open_media(url,headers,accepted=(200,206,416))
 async def close():await res.aclose();await client.aclose()
 if res.status_code==416:
  await close();raise HTTPException(416,'Source range is no longer valid. Restart this download.')
 ctype=res.headers.get('content-type','').lower()
 if 'video/' not in ctype and 'octet-stream' not in ctype:
  await close();raise HTTPException(422,'Source did not return a video file.')
 if res.status_code==206:
  expected=int(requested_range[6:-1]) if requested_range else 0
  content_range=res.headers.get('content-range','')
  m=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',content_range)
  if not m or int(m[1])!=expected or (requested_range and res.headers.get('etag')!=request.headers.get('if-range')):
   await close();raise HTTPException(409,'Source changed or returned the wrong byte range. Restart required.')
 forwarded={k:v for k,v in res.headers.items() if k in ('content-length','content-type','content-range','accept-ranges','etag')}
 forwarded['Content-Disposition']='attachment; filename="'+re.sub(r'[^a-zA-Z0-9_-]','_',subject_id)+f'_S{season:02d}E{episode:02d}.mp4"'
 return StreamingResponse(res.aiter_bytes(1024*1024),status_code=res.status_code,headers=forwarded,background=BackgroundTask(close))

class SourceLogin(BaseModel):
 account:str=Field(min_length=1,max_length=200)
 password:str=Field(min_length=1,max_length=500)

@app.get('/api/connection')
def connection_status(request:Request):
 if uses_vyla():return vyla.status()
 sid=UPSTREAM_IDS.get(request.state.session['sid'])
 source=upstream.sessions.get(sid)
 return {'provider':'moviebox','mode':'account' if source and not source['auth'].is_guest_mode else 'guest','initialized':bool(source),
         'message':'Source connection is session-local and resets after sign-out or server restart.'}

@app.post('/api/connection')
def connect_source(body:SourceLogin,request:Request):
 if uses_vyla():raise HTTPException(422,'Vyla is configured by the server owner; no MovieBox login is needed.')
 key='source:'+request.state.session['user']
 recent=[t for t in ATTEMPTS.get(key,[]) if time.time()-t<900];ATTEMPTS[key]=recent
 if len(recent)>=5:raise HTTPException(429,'Too many source login attempts. Retry later.')
 recent.append(time.time())
 source=session(request)
 result=source['client'].login(body.account,body.password,auth_type=1)
 if result.get('status')!='success':raise HTTPException(401,'Source login failed. Check account details and source availability.')
 ATTEMPTS.pop(key,None)
 for key in list(SOURCE_CACHE):
  if key[0]==source['id']:SOURCE_CACHE.pop(key,None)
 return {'mode':'account','message':'Source account connected for this app session. Playback access still depends on the source.'}

@app.delete('/api/connection')
def disconnect_source(request:Request):
 sid=UPSTREAM_IDS.pop(request.state.session['sid'],None)
 if sid:
  old=upstream.sessions.pop(sid,None)
  if old:old['client'].session.close()
 return {'mode':'guest'}

if (DIST/'assets').exists():app.mount('/assets',StaticFiles(directory=DIST/'assets'),name='assets')
@app.get('/{path:path}')
def frontend(path:str):
 target=(DIST/path).resolve()
 if DIST.resolve() not in target.parents or not target.is_file():target=DIST/'index.html'
 if not target.exists():raise HTTPException(503,'Build frontend first: npm run build')
 return FileResponse(target)
