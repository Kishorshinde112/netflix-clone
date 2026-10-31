import json,os,tempfile
os.environ.setdefault('APP_USERS',json.dumps({'alice':'test-pass-alice-123'}))
os.environ.setdefault('SESSION_SECRET','unit-test-only-secret-'+('x'*40))
os.environ.setdefault('COOKIE_SECURE','false')
os.environ.setdefault('LIBRARY_DB',tempfile.mktemp(suffix='.sqlite3'))
import httpx
import pytest
from fastapi import HTTPException
from vyla_provider import VylaProvider

@pytest.fixture
def provider(monkeypatch):
 monkeypatch.setenv('VYLA_BASE_URL','http://127.0.0.1:7860')
 monkeypatch.setenv('TMDB_API_KEY','fixture-not-a-real-key')
 return VylaProvider()

def test_namespaced_ids_cannot_confuse_movies_shows_or_moviebox(provider):
 assert provider.identity('vyla:movie:550')==('movie','550')
 assert provider.identity('vyla:tv:550')==('tv','550')
 for bad in ['550','1382465867459478920','vyla:tv:0','vyla:tv:../../secret']:
  with pytest.raises(HTTPException):provider.identity(bad)

def test_catalog_filters_people_and_preserves_media_type(provider,monkeypatch):
 monkeypatch.setattr(provider,'get',lambda *a,**k:{'results':[{'id':1,'media_type':'person','name':'Actor'},{'id':2,'media_type':'movie','title':'Film'},{'id':2,'media_type':'tv','name':'Show'}]})
 items=provider.catalog('search',q='test')['data'][0]['items']
 assert [x['subjectId'] for x in items]==['vyla:movie:2','vyla:tv:2']

def test_exact_episode_validation(provider,monkeypatch):
 seen=[]
 def get(path,**kwargs):seen.append(path);return {'episodes':[{'episode_number':1}]}
 monkeypatch.setattr(provider,'get',get)
 assert provider.validate('vyla:tv:1396',2,1)==('tv','1396')
 with pytest.raises(HTTPException):provider.validate('vyla:tv:1396',2,10)
 assert seen==['/tv/1396/season/2']

def test_sse_sources_subtitles_and_exact_request(provider,monkeypatch):
 real_client=httpx.Client;seen=[]
 def handler(req):
  seen.append(req)
  if req.url.host=='api.themoviedb.org':return httpx.Response(200,json={'episodes':[{'episode_number':1}]})
  events=[{'type':'meta','subtitles':[{'file':'https://cdn.example/sub.vtt','label':'English'}]},
          {'type':'source','source':{'source':'fixture','index':0,'url':'https://cdn.example/s2e1.m3u8','label':'Fixture'}},
          {'type':'done','total':1}]
  return httpx.Response(200,headers={'Content-Type':'text/event-stream'},text=''.join('data: '+json.dumps(e)+'\n\n' for e in events))
 monkeypatch.setattr(httpx,'Client',lambda **kwargs:real_client(transport=httpx.MockTransport(handler),**kwargs))
 choices=provider.sources('vyla:tv:1396',2,1)
 selected,headers=provider.resolve('vyla:tv:1396',2,1,source_id=choices['sources'][0]['id'])
 assert selected['url'].endswith('s2e1.m3u8') and selected['format']=='hls'
 assert selected['_subtitles'][0]['label']=='English' and headers=={}
 req=seen[-1];assert req.url.path=='/tv' and dict(req.url.params)=={'id':'1396','season':'2','episode':'1'}
 assert 'fixture-not-a-real-key' not in str(req.url)
 with pytest.raises(HTTPException) as e:provider.resolve('vyla:tv:1396',2,1,source_id='stale')
 assert e.value.status_code==409

def test_downloads_are_independent_of_streaming_and_reject_hls(provider,monkeypatch):
 seen=[]
 def get(path,**kwargs):seen.append(path);return [{'url':'https://cdn.example/episode.m3u8'},{'url':'https://cdn.example/episode.mp4','label':'Direct'}]
 monkeypatch.setattr(provider,'get',get)
 selected,_=provider.resolve('vyla:movie:550',1,1,download=True)
 assert selected['url'].endswith('.mp4') and seen==['/downloads/movie/550']
 monkeypatch.setattr(provider,'get',lambda *a,**k:[{'url':'https://cdn.example/playlist.m3u8'}])
 with pytest.raises(HTTPException) as e:provider.resolve('vyla:movie:550',1,1,download=True)
 assert e.value.status_code==422

def test_setup_missing_is_actionable(provider,monkeypatch):
 monkeypatch.delenv('TMDB_API_KEY')
 assert provider.status()['mode']=='setup-required'
 with pytest.raises(HTTPException) as e:provider.config()
 assert e.value.status_code==503

def test_private_vyla_proxy_allows_only_public_nested_target(monkeypatch):
 import personal_server as p
 monkeypatch.setenv('MEDIA_PROVIDER','vyla');monkeypatch.setenv('VYLA_BASE_URL','http://127.0.0.1:7860')
 monkeypatch.setattr(p.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('8.8.8.8',443))])
 assert p.public_url('http://127.0.0.1:7860/api?url=https%3A%2F%2Fcdn.example%2Fa.m3u8')
 for bad in ['http://127.0.0.1:7860/health','http://127.0.0.1:7860/api?url=http%3A%2F%2Flocalhost%2Fsecret']:
  with pytest.raises(HTTPException):p.public_url(bad)

def test_vyla_routes_never_initialize_moviebox_and_proxy_is_not_mutable(provider,monkeypatch):
 import personal_server as p
 from fastapi.testclient import TestClient
 monkeypatch.setenv('MEDIA_PROVIDER','vyla')
 monkeypatch.setattr(p,'vyla',provider)
 monkeypatch.setattr(p,'session',lambda *a:pytest.fail('Vyla route initialized MovieBox'))
 monkeypatch.setattr(provider,'get',lambda *a,**k:{'results':[{'id':550,'media_type':'movie','title':'Fixture'}]})
 monkeypatch.setattr(p,'public_url',lambda u:u)
 with TestClient(p.app) as client:
  assert client.post('/auth/login',json={'username':'alice','password':'test-pass-alice-123'}).status_code==200
  assert client.get('/api/home').json()['data'][0]['items'][0]['subjectId']=='vyla:movie:550'
  assert client.get('/api/connection').json()['provider']=='vyla'
  url=p.media_url('http://127.0.0.1:7860/api?url=https%3A%2F%2Fcdn.example%2Fmovie.m3u8',{},'alice')
  assert client.get(url+'&tampered=1').status_code==403
