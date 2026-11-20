"""Source coverage, partial OCR holds and pixel-proven reuse (no model calls)."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest
import numpy as np
import cv2
from PIL import Image
from pptx import Presentation
from pptx.util import Inches
from sqlalchemy import select
from lerny import picture_ocr, ppt_pictures, local_ocr, media_picture_reuse, worker
from lerny.config import settings
from lerny.models import Chunk, Job, MaterialVersion
from lerny.team_engine import native_document
from test_gemini_integration import configured, integration
from test_lecture_specs import api
from test_document_materials import site, synthetic_engine


def line(text,box=(10,10,300,100),confidence=96):
    return {'text':text,'bbox':list(box),'min_confidence':confidence,'mean_confidence':confidence}


def test_repeated_reads_do_not_normalize_numbers_negations_or_case():
    assert picture_ocr.normalized('부 모 노드')==picture_ocr.normalized('부모 노드')
    assert picture_ocr.normalized('O(1)')!=picture_ocr.normalized('0(1)')
    assert picture_ocr.normalized('아니다')!=picture_ocr.normalized('이다')
    assert 'ocr_ambiguous_formula' in picture_ocr.reasons_for(line('검색 0(1)'),True)
    assert 'ocr_region_disagreement' in picture_ocr.reasons_for(line('서로 다른 결과'),False)


def test_two_regions_preserve_good_label_hold_bad_and_cache_is_tamper_checked(tmp_path,monkeypatch):
    image=tmp_path/'source.png';Image.new('RGB',(300,200),'white').save(image)
    before=image.read_bytes();calls=[]
    def read(path,folder,config):
        calls.append(str(path))
        if config['psm']==7:return [line('읽기 불명',confidence=20)]
        return [line('루트 노드'),line('불확실한 영역',(400,500,900,600),20)]
    monkeypatch.setattr(local_ocr,'recognize',read)
    result=picture_ocr.recognize(image,tmp_path/'cache',{'runtime':'test'})
    assert [r['text'] for r in result['regions'] if r['eligible_for_chunking']]==['루트 노드']
    assert len([r for r in result['regions'] if not r['eligible_for_chunking']])==1
    count=len(calls)
    assert picture_ocr.recognize(image,tmp_path/'cache',{'runtime':'test'})==result
    assert len(calls)==count and image.read_bytes()==before
    dest=next((tmp_path/'cache').glob('*/result.json'));dest.write_text(dest.read_text().replace('루트','가짜'),encoding='utf-8')
    with pytest.raises(ValueError,match='LOCAL_OCR_CACHE_CHANGED'):picture_ocr.recognize(image,tmp_path/'cache',{'runtime':'test'})


def make_ppt(path, *, hidden=False,crop=False,overlay=False):
    p=Presentation();s=p.slides.add_slide(p.slide_layouts[6]);s.shapes.add_textbox(Inches(0),Inches(0),Inches(5),Inches(.5)).text='기존 강의 본문'
    image=path.parent/'picture.png';pixels=np.full((200,300,3),255,np.uint8);pixels[:,0:150]=0;Image.fromarray(pixels).save(image)
    pic=s.shapes.add_picture(str(image),Inches(1),Inches(1),width=Inches(4),height=Inches(3))
    if hidden:pic._element.find('.//{http://schemas.openxmlformats.org/presentationml/2006/main}cNvPr').set('hidden','1')
    if crop:pic.crop_left=.5
    if overlay:s.shapes.add_textbox(Inches(2),Inches(2),Inches(2),Inches(1)).text='비공개 영역 가림'
    p.save(path)


@pytest.mark.parametrize('hidden,overlay',[(True,False),(False,True)])
def test_hidden_or_overlaid_picture_text_never_enters_ocr(tmp_path,hidden,overlay):
    path=tmp_path/'slide.pptx';make_ppt(path,hidden=hidden,overlay=overlay)
    document,*_=native_document(path)
    allowed={r['locator'] for r in document['issues'] if r['reason']=='image_or_graphic_requires_visual_extraction'}
    assert not ppt_pictures.pictures(path,tmp_path/'out',allowed)


def test_crop_excludes_nonvisible_original_pixels(tmp_path):
    path=tmp_path/'slide.pptx';make_ppt(path,crop=True)
    doc,*_=native_document(path)
    pictures=ppt_pictures.pictures(path,tmp_path/'out',{r['locator'] for r in doc['issues']})
    assert len(pictures)==1
    with Image.open(pictures[0]['path']) as image:
        assert image.size==(150,200) and np.asarray(image).min()==255


def observations(path,root,doc,check=lambda:None):
    return [{'locator':next(r['locator'] for r in doc['issues'] if r['reason']=='image_or_graphic_requires_visual_extraction'),
             'slide':1,'source_part':'ppt/slides/slide1.xml','image_sha256':'image',
             'ocr':{'payload_hash':'proof','regions':[
                 {'id':'region-1','bbox':[1,2,3,4],'text':'트리의 루트 노드','eligible_for_chunking':True,'reasons':[]},
                 {'id':'region-2','bbox':[5,6,7,8],'text':'불확실 수식 0(0)','eligible_for_chunking':False,'reasons':['ocr_numeric_disagreement']} ]}}]


def test_picture_text_enters_real_db_and_weekly_input_but_held_does_not(site,synthetic_engine,monkeypatch):
    from lerny import weekly_content
    _,db,_=site
    path=settings().runtime_root/'data/files/pictures.pptx';path.parent.mkdir(parents=True,exist_ok=True);make_ppt(path)
    source=path.read_bytes()
    # Site documents now use Gemini candidates + real mandatory calculation gates.
    # Model I/O is synthetic, while lease/source checks, selection and DB writes are real.
    from video_extraction.pipeline import connected
    from video_extraction.tests.test_correction_gate import block, result
    from video_extraction.shared.common import digest_file
    synthetic_engine.boundary_texts = {'b':'트리의 루트 노드', 'native':'기존 강의 본문', 'bad':'불확실 수식 0(0)'}
    def candidate(frame, *_args, **_kwargs):
        good = block('트리의 루트 노드', 'text', [0,0,1000,300])
        bad = {**block('불확실 수식 0(0)', 'code', [0,500,1000,900]), 'id':'bad'}
        changed = {**bad, 'text':'불확실 수식 O(O)'}
        native = {**block('기존 강의 본문', 'text', [0,320,1000,450]), 'id':'native'}
        value = result(good, good)
        value.update(original={'blocks':[good,native,bad], 'visuals':[]}, final_blocks=[good,native,changed],
                     signature='synthetic', image_sha256=digest_file(frame['path']), audit={})
        return value
    monkeypatch.setattr(connected.base.visual, 'process_frame_layers', candidate)
    version=db.get(MaterialVersion,'version');version.filename=version.object_key=path.name;version.sha256=hashlib.sha256(source).hexdigest()
    job=Job(owner_id='teacher',course_id='course',kind='extract',payload={'version_id':version.id});db.add(job);db.commit()
    assert worker.run_once(job.id)
    db.expire_all()
    assert job.status == 'succeeded', job.error_code
    chunks=list(db.scalars(select(Chunk).where(Chunk.version_id==version.id)))
    content = '\n'.join(c.content for c in chunks)
    assert '기존 강의 본문' in content and '트리의 루트 노드' in content
    assert '불확실 수식' not in content
    assert path.read_bytes()==source and version.extraction_report['held_count'] > 0
    assert version.extraction_report['native_evidence']['mandatory_calculation_gate']
    assert '불확실 수식' in str(version.extraction_report['review_queue'])
    monkeypatch.setattr(weekly_content,'generation_for_job',lambda *a:SimpleNamespace(sources=[{'version_id':version.id,'title':'강의자료'}]))
    captured=[]
    class Stop(Exception):pass
    def capture(prompt,schema):captured.append(prompt);raise Stop()
    monkeypatch.setattr(worker,'model_json',capture)
    with pytest.raises(Stop):weekly_content.generate_job(db,job)
    assert '트리의 루트 노드' in captured[0] and '불확실 수식' not in captured[0]


def test_missing_local_ocr_keeps_native_text_and_picture_hold(tmp_path,monkeypatch):
    path=tmp_path/'lecture.pptx';make_ppt(path)
    doc,chunks,held,evidence=native_document(path)
    def absent():raise ValueError('LOCAL_OCR_NOT_READY')
    monkeypatch.setattr(local_ocr,'runtime',absent)
    new,review,_=ppt_pictures.enrich(path,tmp_path/'ocr',doc,chunks,held,evidence)
    assert [c['text'] for c in new]==['기존 강의 본문'] and len(review)==1
    assert review[0]['reason']=='local_ocr_unavailable'


@pytest.mark.parametrize('recover',[True,False])
def test_transient_ocr_timeout_retries_once_and_records_failure(tmp_path,monkeypatch,recover):
    import subprocess
    path=tmp_path/'lecture.pptx';make_ppt(path)
    doc,chunks,held,evidence=native_document(path)
    monkeypatch.setattr(local_ocr,'runtime',lambda:{'runtime':'test'})
    calls=[]
    def recognize(*args):
        calls.append(1)
        if not recover or len(calls)==1:raise subprocess.TimeoutExpired('tesseract',45)
        return observations(path,tmp_path,doc)[0]['ocr']
    monkeypatch.setattr(picture_ocr,'recognize',recognize)
    new,review,proof=ppt_pictures.enrich(path,tmp_path/'ocr',doc,chunks,held,evidence)
    assert len(calls)==2
    assert ('트리의 루트 노드' in [c['text'] for c in new])==recover
    if not recover:
        assert review[0]['reason']=='local_ocr_timeout'
        assert proof[-1]['error']=='local_ocr_timeout' and proof[-1]['attempts']==2


def fixture_picture(tmp_path):
    rng=np.random.default_rng(42);pixels=np.full((320,400,3),255,np.uint8)
    for _ in range(70):
        x,y=rng.integers([15,15],[370,290]);cv2.putText(pixels,str(x),(int(x),int(y)),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,0,0),1)
    image=tmp_path/'reference.png';cv2.imwrite(str(image),pixels)
    frame=np.full((500,700,3),245,np.uint8);frame[90:410,150:550]=pixels
    target=tmp_path/'frame.png';cv2.imwrite(str(target),frame)
    return image,target,frame


def test_pixel_proof_matches_scale_translation_and_rejects_different_picture_or_changed_region(tmp_path):
    image,target,frame=fixture_picture(tmp_path)
    match=media_picture_reuse.pixel_match(image,target)
    assert match and media_picture_reuse.region_matches(match,[0,0,1000,1000])
    frame[150:210,190:350]=(0,0,255);cv2.imwrite(str(target),frame)
    match=media_picture_reuse.pixel_match(image,target)
    assert match is None or not media_picture_reuse.region_matches(match,[100,180,500,380])
    cv2.imwrite(str(target),np.full_like(frame,255))
    assert media_picture_reuse.pixel_match(image,target) is None


def test_reuse_repeats_once_and_keeps_unmatched_screen_text(tmp_path,monkeypatch):
    image,target,_=fixture_picture(tmp_path)
    item={'path':str(image),'image_sha256':'image','locator':'slide:1/shape:2','reference':{'version_id':'allowed'},
          'ocr':{'payload_hash':'receipt','regions':[{'id':'r1','text':'LIFO','bbox':[0,0,1000,1000],'eligible_for_chunking':True,'reasons':[]}]}}
    seen=set();rows,boxes,proofs=media_picture_reuse.reuse(target,[item],0,30,seen,lambda:None)
    assert len(rows)==2 and rows[0]['text']=='LIFO' and rows[0]['isolated']
    assert len(proofs)==1 and media_picture_reuse.inside({'bbox':[300,300,600,600]},boxes[0])
    assert not media_picture_reuse.inside({'bbox':[0,0,50,50]},boxes[0])
    rows,boxes,proofs=media_picture_reuse.reuse(target,[item],30,60,seen,lambda:None)
    assert not rows and len(proofs)==1


def test_small_changed_symbol_is_not_hidden_by_large_white_region():
    diff=np.zeros((100,400),np.float32)
    ink=np.zeros((100,400),np.uint8);ink[30:32,50:58]=1
    diff[30:32,50:58]=255
    # Overall pixel mean/fraction alone would accept this changed symbol.
    assert diff.mean()<12 and (diff>35).mean()<.08
    match={'dimensions':[400,100],'diff':diff,'changed_ink':ink}
    assert not media_picture_reuse.region_matches(match,[0,0,1000,1000])
    assert media_picture_reuse.region_matches(match,[500,0,1000,1000])


def test_anisotropic_slide_scaling_still_requires_actual_pixels(tmp_path):
    image,target,_=fixture_picture(tmp_path)
    original=cv2.imread(str(image));scaled=cv2.resize(original,(440,384),interpolation=cv2.INTER_LINEAR)
    frame=np.full((500,700,3),245,np.uint8);frame[70:454,120:560]=scaled;cv2.imwrite(str(target),frame)
    assert media_picture_reuse.pixel_match(image,target) is not None
