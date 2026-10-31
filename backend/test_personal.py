import os,tempfile,json
os.environ['APP_USERS']=json.dumps({'alice':'test-pass-alice-123','bob':'test-pass-bob-123'})
os.environ['SESSION_SECRET']='unit-test-only-secret-'+('x'*40)
os.environ['COOKIE_SECURE']='false'
os.environ['LIBRARY_DB']=tempfile.mktemp(suffix='.sqlite3')
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
import personal_server as p
@pytest.fixture
def client():
 p.ATTEMPTS.clear();p.SOURCE_CACHE.clear();p.REVOKED.clear()
 with TestClient(p.app) as c:yield c

def auth(c,name='alice'):
 r=c.post('/auth/login',json={'username':name,'password':f'test-pass-{name}-123'});assert r.status_code==200

def test_private_routes_and_login(client):
 assert client.get('/health').status_code==200
 assert client.get('/library').status_code==401
 assert client.get('/api/home').status_code==401
 auth(client)
 assert client.get('/auth/me').json()=={'username':'alice'}
 assert client.post('/auth/logout').status_code==200
 assert client.get('/auth/me').status_code==401

def test_accounts_isolate_watchlists(client):
 auth(client)
 assert client.put('/library',json={'key':'saved:1','value':{'item':{'title':'Alice movie'}}}).status_code==200
 auth(client,'bob');assert 'saved:1' not in client.get('/library').json()
 auth(client);assert client.get('/library').json()['saved:1']['item']['title']=='Alice movie'
 assert client.delete('/library/saved:1').status_code==200

def test_wrong_password_and_csrf(client):
 assert client.post('/auth/login',json={'username':'alice','password':'wrong'}).status_code==401
 assert client.post('/auth/login',headers={'Origin':'https://evil.invalid'},json={'username':'alice','password':'test-pass-alice-123'}).status_code==403

def test_forged_session(client):
 client.cookies.set('personal_session','forged.bad');assert client.get('/library').status_code==401

def test_rate_limit(client):
 for _ in range(10):assert client.post('/auth/login',json={'username':'alice','password':'wrong'}).status_code==401
 assert client.post('/auth/login',json={'username':'alice','password':'wrong'}).status_code==429

def test_episode_and_quality_match():
 d={'se':2,'ep':1,'streams':[{'url':'https://cdn.example/episode.mp4','quality':'720P','se':2,'ep':1}]}
 assert p.choose_stream(d,2,1,'720p')['url'].endswith('episode.mp4')
 with pytest.raises(HTTPException):p.choose_stream(d,1,10,'720p')
 with pytest.raises(HTTPException):p.choose_stream(d,2,1,'1080p')

def test_download_passes_exact_episode(client,monkeypatch):
 auth(client)
 seen=fake_source(monkeypatch,[{'url':'https://cdn.example/file.mpd','quality':'720p'}])
 r=client.get('/download/show?season=2&episode=1&quality=720p')
 assert r.status_code==422 and seen==[('show',2,1)]
 assert 'manifest' in r.json()['detail']


def test_stream_route_not_swallowed_by_catalog(client,monkeypatch):
 auth(client);monkeypatch.setattr(p,'resolve',lambda *a:({'url':'https://cdn.example/movie.mp4','quality':'720p'},{}));monkeypatch.setattr(p,'public_url',lambda u:u)
 r=client.get('/api/stream/show?season=2&episode=1&quality=720p')
 assert r.status_code==200 and r.json()['season']==2 and r.json()['episode']==1
 assert r.json()['url'].startswith('/media/')

def test_arbitrary_upstream_routes_blocked(client):
 auth(client);assert client.get('/api/debug-history').status_code==404
 assert client.post('/api/launch-player').status_code==405

def test_private_media_host_rejected(monkeypatch):
 monkeypatch.setattr(p.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
 with pytest.raises(HTTPException):p.public_url('https://private.example/movie.mp4')
 with pytest.raises(HTTPException):p.public_url('http://example.com/movie.mp4')

# New API integration regression cases use full metadata fixtures.
class SourceContent:
 def get_movie_detail(self,subject_id):return {'data':{'subjectType':2,'title':'Test series'}}
 def get_episode_list(self,subject_id):return {'data':{'seasons':[{'se':1,'maxEp':10},{'se':2,'maxEp':13}]}}


def fake_source(monkeypatch,streams):
 seen=[]
 class Stream:
  def get_play_info_v2(self,subject_id,season=None,episode=None):
   seen.append((subject_id,season,episode));return {'code':0,'data':{'streams':streams}}
  def get_play_info(self,*args,**kwargs):return {'code':0,'data':{'streams':[]}}
 p.SOURCE_CACHE.clear()
 monkeypatch.setattr(p,'session',lambda request:{'id':'fixture','content':SourceContent(),'stream':Stream()})
 monkeypatch.setattr(p,'public_url',lambda u:u)
 return seen


def test_sources_endpoint_reports_real_metadata(client,monkeypatch):
 auth(client);seen=fake_source(monkeypatch,[{'id':'e2-1','url':'https://cdn.example/episode.mp4','resolutions':'480,720,1080','format':'MP4','codecName':'h264','duration':2400,'size':500000000}])
 response=client.get('/api/sources/show?season=2&episode=1')
 assert response.status_code==200
 source=response.json()['sources'][0]
 assert source['quality']=='auto' and source['advertisedQualities']==[480,720,1080]
 assert 'url' not in source
 assert seen==[('show',2,1)]


def test_notice_video_blocked_before_play_or_download(client,monkeypatch):
 auth(client);fake_source(monkeypatch,[{'id':'s2e1','url':'https://cdn.example/notice.mp4','duration':23,'size':824720}])
 for path in ['/api/sources/show','/api/stream/show','/download/show']:
  response=client.get(path+'?season=2&episode=1&quality=auto')
  assert response.status_code==409
  assert response.json()['detail']['code']=='SOURCE_PREVIEW_ONLY'


def test_unlisted_episode_rejected_before_resolution(client,monkeypatch):
 auth(client);seen=fake_source(monkeypatch,[{'url':'https://cdn.example/episode.mp4'}])
 assert client.get('/api/sources/show?season=2&episode=14').status_code==422
 assert client.get('/download/show?season=3&episode=1&quality=auto').status_code==422
 assert seen==[]


def test_source_id_cannot_select_previous_episode():
 with pytest.raises(HTTPException):
  p.choose_stream({'streams':[{'id':'s2e1','url':'https://cdn.example/s2e1.mp4'}]},2,1,'auto','s1e10')


def test_resolutions_are_advertised_not_a_quality_selection():
 from media_selection import describe_sources
 data={'streams':[{'id':'1','url':'https://cdn.example/video.mp4','resolutions':'1080,720,480','duration':2400}]}
 assert describe_sources(data,2,1)[0]['quality']=='auto'
 with pytest.raises(HTTPException):p.choose_stream(data,2,1,'720p')


def test_logged_out_cookie_is_revoked(client):
 auth(client);cookie=client.cookies.get('personal_session');client.post('/auth/logout');client.cookies.set('personal_session',cookie)
 assert client.get('/auth/me').status_code==401


def test_stale_account_requests_cannot_write_to_other_account(client):
 auth(client,'bob')
 assert client.put('/library',headers={'X-App-User':'alice'},json={'key':'saved:1','value':{'item':{'title':'Wrong account'}}}).status_code==403
 assert client.get('/library').json()=={}


def test_download_forwards_validated_range_and_closes_connection(client,monkeypatch):
 import httpx
 auth(client);seen=[];closed=[]
 monkeypatch.setattr(p,'resolve',lambda *args:({'url':'https://cdn.example/video.mp4'},{}))
 monkeypatch.setattr(p,'public_url',lambda u:u)
 class Client:
  async def aclose(self):closed.append(True)
 async def open_media(url,headers,accepted):
  seen.append(headers)
  return Client(),httpx.Response(206,headers={'content-type':'video/mp4','content-length':'6','content-range':'bytes 10-15/16','etag':'"file-one"'},content=b'abcdef'),url
 monkeypatch.setattr(p,'open_media',open_media)
 response=client.get('/download/show?season=2&episode=1&quality=auto',headers={'Range':'bytes=10-','If-Range':'"file-one"'})
 assert response.status_code==206 and response.content==b'abcdef'
 assert seen[0]['Range']=='bytes=10-' and closed


def test_download_rejects_wrong_range(client,monkeypatch):
 import httpx
 auth(client)
 monkeypatch.setattr(p,'resolve',lambda *args:({'url':'https://cdn.example/video.mp4'},{}))
 monkeypatch.setattr(p,'public_url',lambda u:u)
 class Client:
  async def aclose(self):pass
 async def open_media(url,headers,accepted):return Client(),httpx.Response(206,headers={'content-type':'video/mp4','content-range':'bytes 0-15/16','etag':'"file-one"'},content=b'abcdef'),url
 monkeypatch.setattr(p,'open_media',open_media)
 assert client.get('/download/show',headers={'Range':'bytes=10-','If-Range':'"file-one"'}).status_code==409
 assert client.get('/download/show',headers={'Range':'bytes=10-','If-Range':'W/"weak"'}).status_code==422

def test_source_connection_never_returns_password_or_token(client,monkeypatch):
 from types import SimpleNamespace
 auth(client);seen=[]
 class SourceClient:
  def login(self,account,password,auth_type):
   seen.append((account,password,auth_type));return {'status':'success','user':{'token':'must-not-leak'}}
 monkeypatch.setattr(p,'session',lambda request:{'id':'fixture','auth':SimpleNamespace(is_guest_mode=False),'client':SourceClient()})
 r=client.post('/api/connection',json={'account':'source@example.com','password':'source-test-only'})
 assert r.status_code==200 and r.json()['mode']=='account'
 assert 'must-not-leak' not in r.text and 'source-test-only' not in r.text
 assert seen==[('source@example.com','source-test-only',1)]


def test_srt_subtitles_are_converted_to_vtt(client,monkeypatch):
 import httpx
 auth(client)
 token='subtitle-test';p.TOKENS[token]={'url':'https://cdn.example/captions.srt','headers':{},'owner':'alice','expires':__import__('time').time()+60}
 class Client:
  async def aclose(self):pass
 async def open_media(url,headers):return Client(),httpx.Response(200,headers={'content-type':'application/x-subrip'},content=b'1\n00:00:01,000 --> 00:00:03,000\nHello\n'),url
 monkeypatch.setattr(p,'open_media',open_media)
 r=client.get('/media/subtitle-test/captions.srt')
 assert r.status_code==200 and r.text.startswith('WEBVTT')
 assert '00:00:01.000' in r.text
 assert r.headers['content-type'].startswith('text/vtt')


def test_episode_normalization_handles_real_source_maxep_response():
 from media_selection import normalize_episodes
 actual={'seasons':[{'se':2,'maxEp':13,'allEp':'','resolutions':[{'resolution':720,'epNum':11}]},{'se':1,'maxEp':7}]}
 result=normalize_episodes(actual)
 assert [s['seasonNumber'] for s in result]==[1,2]
 assert len(result[1]['episodes'])==13
 assert result[1]['episodes'][0]['episodeNumber']==1

def test_movie_source_omits_series_parameters(client,monkeypatch):
 auth(client);seen=[]
 class Content:
  def get_movie_detail(self,subject_id):return {'data':{'subjectType':1,'title':'Test movie','subjectId':subject_id}}
  def get_episode_list(self,subject_id):raise AssertionError('Movies must not request seasons')
 class Stream:
  def get_play_info_v2(self,subject_id,season=None,episode=None):
   seen.append((subject_id,season,episode));return {'code':0,'data':{'streams':[{'id':'movie-stream','url':'https://cdn.example/movie.mp4','quality':'720p','duration':7200}]}}
 monkeypatch.setattr(p,'session',lambda request:{'id':'movie-fixture','content':Content(),'stream':Stream()})
 assert client.get('/api/sources/movie?season=1&episode=1').status_code==200
 assert seen==[('movie',None,None)]
 assert client.get('/api/sources/movie?season=2&episode=1').status_code==422


def test_detail_gateway_returns_only_needed_metadata(client,monkeypatch):
 auth(client)
 class Content:
  def get_movie_detail(self,subject_id):return {'data':{'subjectType':1,'title':'Test movie','subjectId':subject_id,'dubs':[{'subjectId':'dub-id','lanName':'Hindi'}]}}
 source={'id':'detail-fixture','content':Content()}
 monkeypatch.setattr(p,'session',lambda request:source)
 monkeypatch.setattr(p.upstream,'get_session',lambda sid:source)
 r=client.get('/api/detail/movie')
 assert r.status_code==200 and r.json()['data']['title']=='Test movie'
 assert r.json()['data']['languages'][0]['subjectId']=='dub-id'

def test_direct_metadata_fallback_requires_exact_episode_and_no_cookies():
 from media_selection import direct_metadata_streams
 detail={'subjectType':2,'resourceDetectors':[{'subjectId':'series','resourceId':'r','resolutionList':[
  {'se':1,'ep':10,'resourceLink':'https://cdn.example/s1e10.mp4'},
  {'se':2,'ep':1,'resourceLink':'https://cdn.example/s2e1.mp4'},
  {'resourceLink':'https://cdn.example/no-episode.mp4'},
  {'se':2,'ep':1,'resourceLink':'https://cdn.example/signed.mp4','signCookie':'do-not-forward'},
 ]}]}
 candidates=direct_metadata_streams(detail,'series',2,1)
 assert len(candidates)==1 and candidates[0]['url'].endswith('s2e1.mp4')
 assert direct_metadata_streams(detail,'different-series',2,1)==[]


def test_notice_filter_does_not_block_red_notice_movie():
 from media_selection import preview_reason
 assert preview_reason({'url':'https://cdn.example/films/red-notice.mp4'}) is None
 assert preview_reason({'url':'https://new-cdn.example/other/2026/10/31/placeholder.mp4'})
