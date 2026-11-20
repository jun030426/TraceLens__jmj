"""Full preparation path with isolated DB and fake providers; no paid calls."""
import copy
import hashlib
import io

import pytest
from PIL import Image, ImageFont

from lerny import lecture_poster, lecture_slides as slides, video_worker, worker
from lerny.heygen_lecture_profile import NarrationLesson
from lerny.heygen_site_video import scene_scripts
from lerny.lecture_slide_layout import TeachingPlan, TeachingSlide, slide_requests
from lerny.lecture_theme import COLORS, THEME_ID
from lerny.models import Job, Material
from test_google_slides import (api, configured, integration, weekly, network, fixture_video,
    plan, deck, lesson, publish, login)  # noqa: F401


@pytest.fixture
def prepared(weekly, monkeypatch):
    client, session, tokens, generation, video = fixture_video(weekly)
    calls, blobs = [], {}
    scripts = scene_scripts(NarrationLesson.model_validate(video.script['lesson']))
    class Google:
        def __init__(self, token): assert token == 'test'
        def find(self, job_id): calls.append('find'); return None
        def create(self, *args): calls.append('create'); return 'warm-presentation'
        def populate(self, *args): calls.append('populate'); return deck(scripts)
        def get(self, *args): return deck(scripts)
        def thumbnail(self, pid, page):
            calls.append('thumbnail')
            output=io.BytesIO();Image.new('RGB',(160,90),(int(page[-1])*100,0,0)).save(output,'PNG');return output.getvalue()
    def upload(method, path, **kwargs):
        assert method == 'POST' and path.startswith('/object/')
        calls.append(('upload', kwargs['headers']['Content-Type']))
        key = path.split('/object/', 1)[1].split('/', 1)[1]
        blobs[key] = kwargs['content']
    def download(key, limit):
        assert len(blobs[key]) <= limit
        return blobs[key]
    monkeypatch.setattr(slides, 'GoogleSlidesClient', Google)
    monkeypatch.setattr(slides, 'access_token', lambda *args: 'test')
    monkeypatch.setattr(slides, 'make_plan', lambda *args: calls.append('plan') or plan())
    monkeypatch.setattr(slides, 'engine', lambda: session.bind)
    monkeypatch.setattr(slides.storage, 'request', upload)
    monkeypatch.setattr(slides.storage, 'download', download)
    job = slides.enqueue(session, video); session.commit()
    assert worker.run_once(job.id)
    session.expire_all()
    assert job.status == 'succeeded', job.error_code
    return client, session, tokens, generation, video, job, calls, blobs


def test_preparation_reuses_assets_preserves_video_and_enforces_publication(prepared, monkeypatch):
    client, session, tokens, generation, video, job, calls, blobs = prepared
    before = copy.deepcopy((video.script, video.request, video.object_key, video.provider_video_id, video.status))
    assert job.payload['design_version'] == job.result['design_version'] == THEME_ID
    receipt = job.result['poster']
    cover = blobs[receipt['object_key']]
    assert hashlib.sha256(cover).hexdigest() == receipt['sha256']
    with Image.open(io.BytesIO(cover)) as image:
        assert image.format == 'WEBP' and image.size == (1600, 900)
    url = f'/api/v1/concept-videos/{video.id}/poster'
    response = client.get(url)
    assert response.status_code == 200 and response.content == cover
    assert 'no-store' in response.headers['cache-control']
    login(client, tokens, 'outsider')
    assert client.get(url).status_code in {403,404}
    login(client, tokens, 'student')
    assert client.get(url).status_code == 404
    login(client, tokens, 'teacher')
    assert publish(client, generation.id).status_code == 200
    login(client, tokens, 'student')
    catalogue = client.get('/api/v1/sections/section/concept-videos').json()['items']
    assert catalogue[0]['poster_url'] == url
    assert client.get(url).content == cover
    assert before == (video.script, video.request, video.object_key, video.provider_video_id, video.status)

    # A finished job must not enqueue a different plan or remake the original video.
    assert slides.enqueue(session, video).id == job.id
    login(client, tokens, 'teacher')
    assert client.post(f'/api/v1/lecture-slides/{job.id}/refresh').status_code == 200
    session.expire_all(); assert worker.run_once(job.id)
    session.expire_all()
    assert calls.count('plan') == calls.count('create') == calls.count('populate') == 1
    assert calls.count(('upload', 'image/webp')) == 1
    assert job.result['poster'] == receipt
    # Revocation is checked before returning even a cached cover.
    login(client, tokens, 'student')
    session.get(Material, 'material').visibility = 'private'; session.commit()
    assert client.get(url).status_code == 404


def test_native_scaling_and_warm_studio_composition():
    from lerny.lecture_theme import scene_image
    from lerny.heygen_site_video import BACKGROUND
    requests=slide_requests(plan().slides[0],'scaled_page',1,1,.75)
    sizes=[r['updateTextStyle']['style']['fontSize']['magnitude'] for r in requests if 'updateTextStyle' in r]
    assert max(sizes)==22*.75
    buffer=io.BytesIO();Image.new('RGB',(1600,900),'#aabbcc').save(buffer,'PNG')
    rendered=Image.open(io.BytesIO(scene_image(buffer.getvalue())))
    assert rendered.size==(1920,1080)
    with Image.open(BACKGROUND) as original:
        assert rendered.getpixel((200,400))==original.convert('RGB').getpixel((200,400))
    assert rendered.getpixel((1000,400))==(170,187,204)


def test_exact_scene_script_binding_and_pause_prevent_provider_submission(prepared, configured, monkeypatch):
    monkeypatch.setattr(configured, 'heygen_rendering_enabled', False)
    client, session, _, generation, video, job, calls, blobs = prepared
    uploads = []
    class HeyGen:
        def post(self, url, **kwargs):
            assert url == 'https://api.heygen.com/v3/assets'
            uploads.append(kwargs['files']['file'][1])
            class Response:
                def raise_for_status(self): pass
                def json(self): return {'data': {'asset_id': f'asset_{len(uploads)}'}}
            return Response()
    heygen = HeyGen()
    with pytest.raises(ValueError, match='HEYGEN_RENDERING_PAUSED'):
        slides.prepare_video_request(video.id, heygen)
    assert not uploads
    token = job.result['review_token']
    assert client.post(f'/api/v1/lecture-slides/{job.id}/approve', json={'review_token': token}).status_code == 200
    session.expire_all()
    monkeypatch.setattr(configured, 'heygen_rendering_enabled', True)
    body = slides.prepare_video_request(video.id, heygen)
    expected = scene_scripts(NarrationLesson.model_validate(video.script['lesson']))
    assert [s['input']['script'] for s in body['scenes']] == expected
    assert ''.join(expected) == ''.join(video.script['lesson']['narration'])
    assert [s['input']['background']['source']['asset_id'] for s in body['scenes']] == ['asset_1', 'asset_2']
    assert uploads == [blobs[p['object_key']] for p in job.result['previews']]
    assert slides.prepare_video_request(video.id, heygen) == body
    assert len(uploads) == len(expected)
    session.expire_all()
    assert video.object_key == 'synthetic.mp4' and video.provider_video_id == 'preserved-receipt'
    # Corrupted cover is rejected before any additional provider upload.
    blobs[job.result['poster']['object_key']] = b'corrupted'
    with pytest.raises(ValueError, match='POSTER_CHANGED_REVIEW_REQUIRED'):
        slides.prepare_video_request(video.id, heygen)
    assert len(uploads) == len(expected)


def test_poster_is_bound_to_script_and_integrity_checked(prepared):
    client, session, tokens, generation, video, job, calls, blobs = prepared
    url = f'/api/v1/concept-videos/{video.id}/poster'
    blobs[job.result['poster']['object_key']] = b'changed'
    assert client.get(url).status_code == 409
    video.script = {**video.script, 'new_version': True}; session.commit()
    assert client.get(url).status_code == 404


@pytest.mark.parametrize('kind', ['code', 'compare', 'steps', 'keypoints'])
def test_theme_covers_every_supported_explanation_and_keeps_presenter_clear(kind):
    slide = TeachingSlide(heading='같은 테마의 설명 화면', key_point='설명과 대본의 순서를 유지해요',
        kind=kind, items=['입력 → 처리', '결과 확인'], code='print(len("Ab@ex.com"))' if kind=='code' else '', caption='핵심 확인')
    requests = slide_requests(slide, 'warm_page', 1, 1)
    page_fill = requests[1]['updatePageProperties']['pageProperties']['pageBackgroundFill']['solidFill']['color']['rgbColor']
    assert page_fill['red'] == int(COLORS['background'][:2], 16) / 255
    for request in requests:
        if 'createShape' in request:
            element = request['createShape']['elementProperties']
            assert element['transform']['translateX'] >= 398
            assert element['transform']['translateY'] + element['size']['height']['magnitude'] <= 460
    assert '6941C6' not in str(requests)


def test_poster_long_korean_copy_fits_and_does_not_use_network():
    content = plan(); content.slides[0].heading = '한' * 28; content.slides[0].key_point = '한' * 64
    narration = NarrationLesson.model_validate({**lesson(), 'title': '한' * 200})
    first = lecture_poster.render_poster(narration, content)
    assert first == lecture_poster.render_poster(narration, content)
    assert len(first) < 2 * 1024 * 1024
    with Image.open(io.BytesIO(first)) as image: assert image.size == (1600, 900)


def test_poster_wraps_at_word_boundaries_before_splitting_hangul():
    font=ImageFont.truetype(str(lecture_poster.font_path()),30)
    width=font.getlength('문자열의 길이를 확인하는 방')
    lines=lecture_poster.text_lines('문자열의 길이를 확인하는 방법을 알아봅니다.',font,width)
    assert lines[0]=='문자열의 길이를 확인하는'
    assert lines[1].startswith('방법을')
    assert all(font.getlength(line)<=width for line in lines)
