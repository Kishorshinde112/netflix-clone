"""Adapter for the self-hosted Vyla Stream API (GitLab commit 295c0ef).

Vyla uses TMDB IDs, never MovieBox IDs. API keys stay on the server.
"""
import hashlib,json,os,re,time,threading,logging
from urllib.parse import urlparse,parse_qs
import httpx
from fastapi import HTTPException
# httpx's INFO request log includes the TMDB query key; never emit it.
logging.getLogger('httpx').setLevel(logging.WARNING)

class VylaProvider:
 def __init__(self):
  self.cache={};self.lock=threading.Lock()
  self.client=httpx.Client(timeout=httpx.Timeout(75,connect=15),follow_redirects=False,trust_env=False)

 def config(self):
  base=os.getenv('VYLA_BASE_URL','').rstrip('/')
  key=os.getenv('TMDB_API_KEY','')
  if not base or not key:raise HTTPException(503,'Vyla setup incomplete. Configure VYLA_BASE_URL and TMDB_API_KEY on the server.')
  p=urlparse(base)
  if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.path not in ('','/') or p.query or p.fragment:
   raise HTTPException(503,'VYLA_BASE_URL must be the origin of your own Vyla service.')
  return base,key

 def get(self,path,params=None,tmdb=False,timeout=None):
  base,key=self.config()
  url=('https://api.themoviedb.org/3' if tmdb else base)+path
  query={**(params or {}),**({'api_key':key} if tmdb else {})}
  for attempt in range(3):
   try:
    r=self.client.get(url,params=query,timeout=timeout or (35 if tmdb else 75))
    if r.status_code!=200:raise HTTPException(502,f'{"TMDB" if tmdb else "Vyla"} returned HTTP {r.status_code}. Check service configuration.')
    return r.json()
   except (httpx.HTTPError,ValueError) as e:
    if attempt==2:raise HTTPException(502,'Vyla or TMDB connection failed. Check the service and retry.')
    time.sleep(0.35)

 def cached(self,key,load,ttl=120):
  value=self.cache.get(key)
  if value and value[0]>time.time():return value[1]
  data=load()
  with self.lock:
   if len(self.cache)>=500:self.cache.pop(next(iter(self.cache)),None)
   self.cache[key]=(time.time()+ttl,data)
  return data

 @staticmethod
 def identity(subject_id):
  m=re.fullmatch(r'vyla:(movie|tv):([1-9][0-9]{0,9})',subject_id)
  if not m:raise HTTPException(422,'This title uses a different source. Open it again from the Vyla catalog.')
  return m[1],m[2]

 @staticmethod
 def item(d,kind=None):
  kind=kind or d.get('media_type')
  if kind not in ('movie','tv') or not d.get('id'):return None
  cover='https://image.tmdb.org/t/p/w500'+d['poster_path'] if d.get('poster_path') else ''
  return {'subjectId':f'vyla:{kind}:{d["id"]}','subjectType':1 if kind=='movie' else 2,
          'title':d.get('title') or d.get('name') or '', 'cover':cover,'poster':cover,
          'description':d.get('overview') or '', 'score':round(d.get('vote_average') or 0,1),
          'genre':' · '.join(x['name'] for x in d.get('genres',[])), 'languages':[], 'provider':'vyla'}

 def detail(self,subject_id):
  kind,id=self.identity(subject_id)
  return self.cached(('detail',subject_id),lambda:self.get(f'/{kind}/{id}',tmdb=True))

 def catalog(self,endpoint,subject_id='',q='',page=1,season=1):
  if endpoint=='detail':return {'code':0,'data':self.item(self.detail(subject_id),self.identity(subject_id)[0])}
  if endpoint=='episodes':
   kind,id=self.identity(subject_id)
   if kind!='tv':return {'code':0,'data':{'seasons':[]}}
   ss=[{'seasonNumber':s['season_number'],'episodes':[{'episodeNumber':n,'title':f'Episode {n}'} for n in range(1,s.get('episode_count',0)+1)]}
       for s in self.detail(subject_id).get('seasons',[]) if s.get('season_number',0)>0 and s.get('episode_count',0)>0]
   return {'code':0,'data':{'seasons':ss}}
  page=max(1,min(page,500))
  if endpoint=='search':path='/search/multi';params={'query':q,'page':page,'include_adult':'false'};kind=None
  elif endpoint=='movies':path='/movie/popular';params={'page':page};kind='movie'
  elif endpoint=='anime':path='/discover/tv';params={'page':page,'with_genres':16,'with_original_language':'ja'};kind='tv'
  elif endpoint in ('home','trending','rankings'):path='/trending/all/week';params={'page':page};kind=None
  else:raise HTTPException(404)
  raw=self.cached(('catalog',path,json.dumps(params,sort_keys=True)),lambda:self.get(path,params,tmdb=True))
  items=[item for x in raw.get('results',[]) if (item:=self.item(x,kind))]
  return {'code':0,'data':[{'title':'Vyla · '+('Search results' if endpoint=='search' else endpoint.title()),'items':items}]}

 def validate(self,subject_id,season,episode):
  kind,id=self.identity(subject_id)
  if kind=='movie':
   if (season,episode)!=(1,1):raise HTTPException(422,'Movies do not have seasons or episodes.')
  else:
   if season<1 or episode<1:raise HTTPException(422,'Select a valid season and episode.')
   data=self.cached(('season',id,season),lambda:self.get(f'/tv/{id}/season/{season}',tmdb=True))
   if not any(x.get('episode_number')==episode for x in data.get('episodes',[])):
    raise HTTPException(422,'Episode does not exist in this TMDB season. Playback blocked.')
  return kind,id

 def playback(self,subject_id,season,episode):
  kind,id=self.validate(subject_id,season,episode)
  key=('playback',subject_id,season,episode)
  def load():
   base,_=self.config();sources=[];subtitles=[];size=0
   params={'id':id,**({'season':season,'episode':episode} if kind=='tv' else {})}
   try:
    with self.client.stream('GET',base+('/tv' if kind=='tv' else '/movie'),params=params,timeout=httpx.Timeout(75,read=55)) as r:
      if r.status_code!=200:raise HTTPException(502,f'Vyla playback returned HTTP {r.status_code}.')
      if 'text/event-stream' not in r.headers.get('content-type',''):raise HTTPException(502,'Vyla did not return a playback event stream.')
      started=time.monotonic()
      for line in r.iter_lines():
       size+=len(line)
       if size>2_000_000 or time.monotonic()-started>55:break
       if not line.startswith('data:'):continue
       try:event=json.loads(line[5:].strip())
       except ValueError:continue
       if event.get('type')=='meta':subtitles=event.get('subtitles') or []
       elif event.get('type')=='source':
        s=event.get('source') or {}
        if isinstance(s.get('url'),str):
         fmt_hint=str(s.get('type') or s.get('format') or '').lower()
         fmt='dash' if 'dash' in fmt_hint or '.mpd' in s.get('url','') else 'mp4' if 'mp4' in fmt_hint or '.mp4' in s.get('url','') else 'hls'
         sources.append({**s,'id':hashlib.sha256((str(s.get('source',''))+':'+str(s.get('index',0))).encode()).hexdigest()[:20],'_format':fmt})
       elif event.get('type')=='done':break
   except httpx.HTTPError:
    if not sources:raise HTTPException(502,'Vyla playback timed out or could not connect.')
   if not sources:raise HTTPException(404,'Vyla returned no playable sources for this title. Try another title or check Vyla provider health.')
   sources.sort(key=lambda x:1 if x.get('_format')=='dash' else 0)
   return {'sources':sources[:40],'subtitles':subtitles[:30]}
  return self.cached(key,load,ttl=60)

 def sources(self,subject_id,season,episode):
  data=self.playback(subject_id,season,episode)
  return {'season':season,'episode':episode,'sources':[{'id':s['id'],'quality':str(s.get('quality') or 'auto'),
    'format':s.get('_format','hls').upper(),
    'label':(s.get('label') or s.get('source') or 'Vyla source')+('' if (s.get('_format') or '').upper() in (s.get('label') or '').upper() else f" · {s.get('_format','hls').upper()}"),
    'advertisedQualities':[]} for s in data['sources']]}

 def resolve(self,subject_id,season,episode,quality='auto',source_id=None,download=False):
  if download:
   kind,id=self.validate(subject_id,season,episode)
   data={'subtitles':[]}
   path=f'/downloads/{kind}/{id}'+(f'/{season}/{episode}' if kind=='tv' else '')
   raw=self.get(path,timeout=90)
   candidates=raw.get('downloads',[]) if isinstance(raw,dict) else raw if isinstance(raw,list) else []
   sources=[s for s in candidates if isinstance(s,dict) and s.get('url') and
            (str(s.get('format','')).upper()=='MP4' or re.search(r'\.mp4(?:\?|$)',s['url'],re.I))]
   if quality!='auto':sources=[s for s in sources if str(s.get('quality','')).lower()==quality.lower()]
   if not sources:raise HTTPException(422,'Vyla has no matching direct MP4 download for this episode. Streaming may still be available; HLS offline merging is not implemented.')
   selected=sources[0]
  else:
   data=self.playback(subject_id,season,episode)
   selected=next((s for s in data['sources'] if s['id']==source_id),None) if source_id else data['sources'][0]
   if not selected:raise HTTPException(409,'Vyla source changed. Reopen the source list.')
  raw_url=parse_qs(urlparse(selected['url']).query).get('url',[selected['url']])[0]
  kind_hint=str(selected.get('type') or selected.get('format') or '').lower()
  media_format='dash' if 'dash' in kind_hint or '.mpd' in raw_url else 'mp4' if 'mp4' in kind_hint or '.mp4' in raw_url else 'hls'
  selected={**selected,'format':media_format}
  return {**selected,'_subtitles':[{'url':s.get('file') or s.get('url'),'label':s.get('label') or s.get('lang') or 'Subtitles'} for s in data['subtitles'] if isinstance(s,dict)],'_vyla':True},{}

 def status(self):
  ready=bool(os.getenv('VYLA_BASE_URL') and os.getenv('TMDB_API_KEY'))
  return {'provider':'vyla','mode':'self-hosted' if ready else 'setup-required','initialized':ready,
          'message':'Vyla uses your self-hosted service and TMDB catalog. No MovieBox account is needed. Configuration does not confirm provider playback health.'}

provider=VylaProvider()
