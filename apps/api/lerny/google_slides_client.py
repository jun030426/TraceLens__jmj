"""Bounded native Slides authoring. No HeyGen APIs and no public sharing."""
import hashlib
import io
import re
from urllib.parse import urlparse

import httpx
from PIL import Image

from lerny.lecture_slide_layout import slide_requests

DRIVE = "https://www.googleapis.com/drive/v3"
SLIDES = "https://slides.googleapis.com/v1/presentations"


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9_-]{5,200}",value):
        raise ValueError("GOOGLE_SLIDES_INVALID_RESPONSE")
    return value


class GoogleSlidesClient:
    def __init__(self, token):
        self.token=token

    def request(self, method, url, **kwargs):
        if not (url.startswith(DRIVE+'/') or url.startswith(SLIDES+'/')):
            raise ValueError("GOOGLE_SLIDES_INVALID_URL")
        try:
            with httpx.Client(timeout=60, trust_env=False, follow_redirects=False) as client:
                r=client.request(method,url,headers={"Authorization":"Bearer "+self.token},**kwargs)
            if r.status_code == 401:
                raise ValueError("GOOGLE_SLIDES_RECONNECT_REQUIRED")
            if r.status_code == 403:
                raise ValueError("GOOGLE_SLIDES_ACCESS_REQUIRED")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            raise ValueError("GOOGLE_SLIDES_UNAVAILABLE") from None

    def get(self, presentation_id):
        return self.request('GET',SLIDES+'/'+identifier(presentation_id))

    def find(self, job_id):
        identifier(job_id)
        files=self.request('GET',DRIVE+'/files',params={
            'q':"trashed = false and appProperties has { key='lerny_slide_job' and value='"+job_id+"' }",
            'fields':'files(id,name)','pageSize':10}).get('files',[])
        if len(files)>1:raise ValueError('GOOGLE_SLIDES_DUPLICATE_REVIEW_REQUIRED')
        return identifier(files[0]['id']) if files else None

    def create(self, title, job_id):
        # Native Workspace files do not support pre-generated IDs. Persist a creating
        # checkpoint first and recover by this private app property; never blindly retry.
        return identifier(self.request('POST',DRIVE+'/files',params={'fields':'id'},json={
            'name':title[:180], 'mimeType':'application/vnd.google-apps.presentation',
            'appProperties':{'lerny_slide_job':identifier(job_id)}})['id'])

    def batch(self, pid, requests, revision):
        return self.request('POST',SLIDES+'/'+identifier(pid)+':batchUpdate',json={
            'requests':requests,'writeControl':{'requiredRevisionId':revision}})

    def populate(self, pid, plan, scripts, job_id=None):
        deck=self.get(pid)
        size=deck['pageSize'];width=size['width']['magnitude'];height=size['height']['magnitude']
        if abs(width/height-16/9)>.01:raise ValueError('GOOGLE_SLIDES_WIDESCREEN_REQUIRED')
        # Native default presentations normally report EMU. Normalize to points.
        width_pt=width/(12700 if size['width']['unit']=='EMU' else 1)
        expected=[f'lerny_scene_{i:03d}' for i in range(len(scripts))]
        pages=deck.get('slides',[])
        initial=[]
        if pages and [p['objectId'] for p in pages] != expected:
            # Drive files.create materializes one empty title slide. Replace only
            # that exact blank default in this job's app-owned file. A populated
            # or edited page remains held, and requiredRevisionId prevents races.
            if not job_id or len(pages)!=1 or not empty_default_title(pages[0]):
                raise ValueError('GOOGLE_SLIDES_CHANGED_REVIEW_REQUIRED')
            metadata=self.request('GET',DRIVE+'/files/'+identifier(pid),params={'fields':'appProperties'})
            if metadata.get('appProperties',{}).get('lerny_slide_job')!=job_id:
                raise ValueError('GOOGLE_SLIDES_CHANGED_REVIEW_REQUIRED')
            initial=[{'deleteObject':{'objectId':pages[0]['objectId']}}]
            pages=[]
        if not pages:
            requests=initial
            for i,slide in enumerate(plan.slides):
                requests+=slide_requests(slide,expected[i],i+1,len(scripts),width_pt/960)
            self.batch(pid,requests,deck['revisionId'])
            deck=self.get(pid)
        notes=[]
        for page,script in zip(deck['slides'],scripts,strict=True):
            note_id=page['slideProperties']['notesPage']['notesProperties']['speakerNotesObjectId']
            existing=notes_text(page)
            if existing.strip() and existing.rstrip('\n') != script.rstrip('\n'):
                raise ValueError('GOOGLE_SLIDES_CHANGED_REVIEW_REQUIRED')
            # A newly created notes shape is only materialized by insertText.
            # deleteText against the absent/empty shape is rejected by Google.
            if existing.strip():
                notes.append({'deleteText':{'objectId':note_id,'textRange':{'type':'ALL'}}})
            notes.append({'insertText':{'objectId':note_id,'text':script}})
        self.batch(pid,notes,deck['revisionId'])
        return self.get(pid)

    def thumbnail(self, pid, page_id):
        data=self.request('GET',SLIDES+'/'+identifier(pid)+'/pages/'+identifier(page_id)+'/thumbnail',
                          params={'thumbnailProperties.mimeType':'PNG','thumbnailProperties.thumbnailSize':'LARGE'})
        url=data.get('contentUrl','');parsed=urlparse(url)
        if (parsed.scheme!='https' or not (parsed.hostname or '').endswith('.googleusercontent.com')
                or parsed.username or parsed.password or parsed.port not in {None,443}):
            raise ValueError('GOOGLE_SLIDES_INVALID_THUMBNAIL')
        # Never send the bearer token to a thumbnail origin, and never follow redirects.
        try:
            with httpx.Client(timeout=45,trust_env=False,follow_redirects=False) as client:
                with client.stream('GET',url) as r:
                    r.raise_for_status();buf=bytearray()
                    for block in r.iter_bytes(65536):
                        buf.extend(block)
                        if len(buf)>8*1024*1024:raise ValueError('GOOGLE_SLIDES_IMAGE_TOO_LARGE')
            raw=bytes(buf)
            with Image.open(io.BytesIO(raw)) as picture:
                if picture.format!='PNG' or abs(picture.width/picture.height-16/9)>.01:
                    raise ValueError('GOOGLE_SLIDES_INVALID_THUMBNAIL')
                picture.verify()
            return raw
        except (httpx.HTTPError,OSError):
            raise ValueError('GOOGLE_SLIDES_THUMBNAIL_FAILED') from None


def notes_text(page):
    notes=page['slideProperties']['notesPage']
    oid=notes['notesProperties']['speakerNotesObjectId']
    return ''.join(e.get('textRun',{}).get('content','') for shape in notes.get('pageElements',[])
                   if shape['objectId']==oid for e in shape.get('shape',{}).get('text',{}).get('textElements',[]))


def empty_default_title(page):
    """Only Google's untouched default title/subtitle placeholders are disposable."""
    elements=page.get('pageElements',[])
    if (page.get('objectId')!='p' or page.get('slideProperties',{}).get('isSkipped')
            or notes_text(page).strip() or len(elements)!=2):
        return False
    expected={'i0':'CENTERED_TITLE','i1':'SUBTITLE'}
    if {e.get('objectId') for e in elements}!=set(expected):return False
    for element in elements:
        shape=element.get('shape',{})
        if (shape.get('shapeType')!='TEXT_BOX' or element.get('title') or element.get('description')
                or shape.get('placeholder',{}).get('type')!=expected[element['objectId']]):return False
        if any(e.get('textRun',{}).get('content','').strip()
               for e in shape.get('text',{}).get('textElements',[])):return False
    return True


def validate_deck(deck,scripts):
    slides=deck.get('slides',[])
    if len(slides)!=len(scripts):raise ValueError('GOOGLE_SLIDES_SCRIPT_MISMATCH')
    for page,script in zip(slides,scripts,strict=True):
        if (page.get('slideProperties',{}).get('isSkipped') or
                notes_text(page).rstrip('\n') != script.rstrip('\n')):
            raise ValueError('GOOGLE_SLIDES_SCRIPT_MISMATCH')
    return [page['objectId'] for page in slides]


def fingerprint(raw):
    return hashlib.sha256(raw).hexdigest()
