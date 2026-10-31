"""Pure normalization of source responses. No entitlement overrides or mirror recovery."""
import re
from urllib.parse import urlparse
from fastapi import HTTPException

def integer(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def qualities(stream):
    value = stream.get('quality') or stream.get('resolution')
    # A resolutions list advertises available variants. It does NOT prove this URL's quality.
    return re.findall(r'\d{3,4}', str(value)) if value else []

def advertised_qualities(stream):
    value = stream.get('resolutions') or []
    if isinstance(value, list):
        return sorted(set(integer(x.get('resolution') if isinstance(x, dict) else x) for x in value) - {0})
    return sorted(set(map(int, re.findall(r'\d{3,4}', str(value)))))

def preview_reason(stream):
    url = stream.get('url', '')
    parsed = urlparse(url)
    path = parsed.path.lower()
    if path.endswith('/notice.mp4') or re.search(r'/other/\d{4}/\d{2}/\d{2}/',path) or (parsed.hostname == 'macdn.aoneroom.com' and path.startswith('/other/')):
        return 'The source returned an upgrade/notice video instead of the selected title.'
    duration = integer(stream.get('duration'))
    size = integer(stream.get('size'))
    if 0 < duration <= 30 and 0 < size <= 1024 * 1024:
        return 'The source returned a very short preview/notice clip; full-episode playback was blocked.'
    return None

def assert_identity(item, season, episode):
    for keys, expected in [(('season', 'seasonNumber', 'se'), season), (('episode', 'episodeNumber', 'ep'), episode)]:
        for key in keys:
            if item.get(key) is not None and integer(item[key], -1) != expected:
                raise HTTPException(502, 'Source episode mismatch. Playback/download blocked.')

def validate_episode(detail, season_data, season, episode):
    if season < 1 or episode < 1:
        raise HTTPException(422, 'Season and episode start at 1.')
    kind = integer(detail.get('subjectType') or detail.get('type'))
    if kind == 1:
        if (season, episode) != (1, 1):
            raise HTTPException(422, 'Movies do not have season/episode selections.')
        return
    if kind != 2:
        raise HTTPException(502, 'Source did not identify this title as a movie or series.')
    seasons = season_data.get('seasons') or season_data.get('seasonList') or []
    selected = next((s for s in seasons if integer(s.get('se') or s.get('seasonNumber')) == season), None)
    if not selected:
        raise HTTPException(422, 'Selected season is not available for this source title.')
    explicit = selected.get('allEp') or selected.get('episodes') or selected.get('epList') or selected.get('episodeList')
    if isinstance(explicit, str) and explicit.strip():
        valid = {integer(x) for x in explicit.split(',')}
    elif isinstance(explicit, list) and explicit:
        valid = {integer(x.get('ep') or x.get('episodeNumber') or x.get('episode_number')) if isinstance(x, dict) else integer(x) for x in explicit}
    else:
        count = integer(selected.get('maxEp') or selected.get('max_ep'))
        valid = set(range(1, min(count, 10000) + 1))
    if episode not in valid:
        raise HTTPException(422, 'Selected episode is not listed in this season. Nothing was downloaded.')

def clean_streams(data, season, episode):
    assert_identity(data, season, episode)
    candidates = data.get('streamList') or data.get('streams') or []
    valid, previews = [], []
    for stream in candidates:
        if not isinstance(stream, dict) or not stream.get('url'):
            continue
        assert_identity(stream, season, episode)
        reason = preview_reason(stream)
        if reason:
            previews.append(reason)
        else:
            valid.append(stream)
    if not valid:
        if previews:
            raise HTTPException(409, {'code': 'SOURCE_PREVIEW_ONLY', 'message': previews[0] + ' Source access or app compatibility may be required; a source-account login does not guarantee access.'})
        raise HTTPException(404, 'No playable source was returned for this exact episode.')
    return valid

def choose_stream(data, season, episode, quality='auto', source_id=None):
    streams = clean_streams(data, season, episode)
    if source_id:
        streams = [s for i, s in enumerate(streams) if str(s.get('id') or s.get('resourceId') or f'index-{i}') == source_id]
        if not streams:
            raise HTTPException(409, 'The selected source changed. Refresh available sources.')
    if quality and quality.lower() != 'auto':
        wanted = ''.join(re.findall(r'\d', quality))
        exact = [s for s in streams if wanted in qualities(s)]
        if not exact:
            raise HTTPException(422, 'That exact quality is not exposed as a separate stream. Choose Source default.')
        streams = exact
    # Prefer browser-friendly codecs, while keeping an explicit source choice authoritative.
    def rank(s):
        codec = str(s.get('codecName') or s.get('codec') or '').lower()
        return 1 if 'hevc' in codec or '265' in codec else 0
    return sorted(streams, key=rank)[0]

def describe_sources(data, season, episode):
    result = []
    for index, s in enumerate(clean_streams(data, season, episode)):
        fixed = qualities(s)
        codec = s.get('codecName') or s.get('codec') or 'Unknown codec'
        quality = fixed[0] + 'p' if len(fixed) == 1 else 'auto'
        fmt = str(s.get('format') or ('HLS' if '.m3u8' in s['url'] else 'DASH' if '.mpd' in s['url'] else 'MP4')).upper()
        result.append({'id': str(s.get('id') or s.get('resourceId') or f'index-{index}'), 'quality': quality,
                       'label': (quality if quality != 'auto' else 'Source default') + f' · {fmt} · {codec}',
                       'format': fmt, 'codec': codec, 'advertisedQualities': advertised_qualities(s),
                       'size': integer(s.get('size')), 'duration': integer(s.get('duration'))})
    return result

def normalize_episodes(season_data):
    result=[]
    for raw in season_data.get('seasons') or season_data.get('seasonList') or []:
        number=integer(raw.get('se') or raw.get('seasonNumber'))
        if number<1:continue
        explicit=raw.get('allEp') or raw.get('episodes') or raw.get('epList') or raw.get('episodeList')
        episodes=[]
        if isinstance(explicit,str) and explicit.strip():
            episodes=[{'episodeNumber':integer(n),'title':f'Episode {integer(n)}'} for n in explicit.split(',') if integer(n)>0]
        elif isinstance(explicit,list) and explicit:
            for item in explicit:
                n=integer(item.get('ep') or item.get('episodeNumber') or item.get('episode_number')) if isinstance(item,dict) else integer(item)
                if n>0:episodes.append({'episodeNumber':n,'title':(item.get('title') if isinstance(item,dict) else None) or f'Episode {n}'})
        else:
            count=min(integer(raw.get('maxEp') or raw.get('max_ep')),10000)
            episodes=[{'episodeNumber':n,'title':f'Episode {n}'} for n in range(1,count+1)]
        if episodes:result.append({'seasonNumber':number,'episodes':episodes})
    return sorted(result,key=lambda item:item['seasonNumber'])


def direct_metadata_streams(detail, subject_id, season, episode):
    """Accept API-provided, explicitly mapped direct links; never derive URLs from cookies."""
    movie=integer(detail.get('subjectType') or detail.get('type'))==1
    result=[]
    for detector in detail.get('resourceDetectors') or []:
        detector_subject=detector.get('subjectId')
        if detector_subject is not None and str(detector_subject)!=str(subject_id):continue
        entries=detector.get('resolutionList') or []
        if not entries and movie:entries=[detector]
        for entry in entries:
            if not isinstance(entry,dict):continue
            if not movie:
                actual_se=entry.get('se',entry.get('season',entry.get('seasonNumber')))
                actual_ep=entry.get('ep',entry.get('episode',entry.get('episodeNumber')))
                if integer(actual_se,-1)!=season or integer(actual_ep,-1)!=episode:continue
            if entry.get('signCookie') or detector.get('signCookie'):continue
            url=entry.get('resourceLink') or entry.get('downloadUrl') or entry.get('url')
            if not isinstance(url,str) or not url.startswith('https://'):continue
            candidate={'url':url,'id':str(entry.get('resourceId') or detector.get('resourceId') or ''),
                       'resolution':entry.get('resolution'),'size':entry.get('size'),
                       'duration':entry.get('duration'),'codecName':entry.get('codecName') or detector.get('codecName'),
                       'season':season,'episode':episode,'_metadataDirect':True}
            if not preview_reason(candidate):result.append(candidate)
    return result
