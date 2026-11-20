"""Local picture text observations. Spatial agreement, never semantic approval."""
import math
import re
from pathlib import Path
from PIL import Image, ImageOps
from lerny import local_ocr
from lerny.local_media_checks import text_issues
from video_extraction.shared.common import digest_file, signature, save, read

POLICY = 'picture-regions-v1'


def normalized(text):
    # Whitespace alone may differ; O/0, numbers, punctuation and case may not.
    return re.sub(r'\s+', '', text)


def overlap(a, b):
    area=lambda r:max(0,r[2]-r[0])*max(0,r[3]-r[1])
    intersection=area([max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])])
    return intersection/max(1,area(a)+area(b)-intersection)


def good(line):
    return line['min_confidence'] >= 55 and line['mean_confidence'] >= 80 and not text_issues(line['text'])


def reasons_for(line, agreed):
    reasons=text_issues(line['text'])
    if not good(line): reasons.append('ocr_low_confidence')
    if not agreed: reasons.append('ocr_region_disagreement')
    text=line['text']
    if re.search(r'(^|\s)(def |class |import |public |void |return )|[{};]|==|!=|<=|>=|[=∑∫√→←]',text):
        reasons.append('ocr_code_or_formula_requires_review')
    # Numeric lookalikes are not corrected to big-O by a substitution rule.
    if re.search(r'[0-9]\s*\(',text): reasons.append('ocr_ambiguous_formula')
    if len(text)>1800: reasons.append('oversized_ocr_line')
    if not re.search(r'[가-힣]{2,}|[A-Za-z]{3,}',text):reasons.append('picture_label_without_context')
    return list(dict.fromkeys(reasons))


def _crop(image, bbox, dest, scale):
    w,h=image.size
    # Bounding boxes are rounded outward. Never cut a glyph's baseline/top.
    box=(max(0,math.floor(bbox[0]*w/1000)-3),max(0,math.floor(bbox[1]*h/1000)-3),
         min(w,math.ceil(bbox[2]*w/1000)+3),min(h,math.ceil(bbox[3]*h/1000)+3))
    crop=image.crop(box)
    if crop.width*crop.height*scale*scale>12_000_000: raise ValueError('LOCAL_OCR_IMAGE_LIMIT')
    crop=crop.resize((crop.width*scale,crop.height*scale),Image.Resampling.LANCZOS)
    ImageOps.expand(crop,border=20,fill='white').save(dest)


def _read_crop(image, bbox, folder, config, scale, language):
    path=folder/('crop-'+signature([bbox,scale,language])+'.png')
    if not path.exists(): _crop(image,bbox,path,scale)
    lines=local_ocr.recognize(path,folder/'receipts',{**config,'psm':7,'languages':language})
    if len(lines)!=1:return None
    return lines[0]


def recognize(path, root, config, check=lambda:None):
    binding={'policy':POLICY,'source_image':digest_file(path),'runtime':config,
             'code':digest_file(__file__),'ocr_code':digest_file(local_ocr.__file__)}
    folder=Path(root)/signature(binding);folder.mkdir(parents=True,exist_ok=True)
    dest=folder/'result.json'
    if dest.exists():
        result=read(dest)
        if result['binding']!=binding or result['payload_hash']!=signature({k:v for k,v in result.items() if k!='payload_hash'}):
            raise ValueError('LOCAL_OCR_CACHE_CHANGED')
        return result
    with Image.open(path) as source:
        if source.width*source.height>12_000_000:raise ValueError('LOCAL_OCR_IMAGE_LIMIT')
        image=source.convert('RGB')
    reads=[]
    for scale in (1,2):
        check();target=folder/f'scan-{scale}.png'
        # Avoid unbounded upscaling of large diagrams.
        effective=min(scale,math.sqrt(12_000_000/(image.width*image.height)))
        image.resize((round(image.width*effective),round(image.height*effective)),Image.Resampling.LANCZOS).save(target)
        reads.append(local_ocr.recognize(target,folder/'receipts',{**config,'psm':11}))
    # Prefer the larger image's region layout; include unmatched first-pass regions.
    candidates=[(line,1) for line in reads[1]]
    candidates += [(line,0) for line in reads[0] if not any(overlap(line['bbox'],other['bbox'])>.7 or
                  (overlap(line['bbox'],other['bbox'])>.3 and normalized(line['text'])==normalized(other['text'])) for other in reads[1])]
    regions=[]
    for index,(line,origin) in enumerate(candidates):
        check();matches=[r for r in reads[1-origin] if overlap(line['bbox'],r['bbox'])>.55]
        agreed=good(line) and any(good(r) and normalized(r['text'])==normalized(line['text']) for r in matches)
        observations=[{'text':r['text'],'min_confidence':r['min_confidence'],'mean_confidence':r['mean_confidence']} for r in [line,*matches]]
        # Crop rereads recover labels without accepting a whole noisy illustration.
        if not agreed or re.search(r'\d',line['text']):
            crops=[_read_crop(image,line['bbox'],folder,config,s,lang) for s,lang in ((2,'kor+eng'),(3,'eng+kor'))]
            observations += [{k:r[k] for k in ('text','min_confidence','mean_confidence')} for r in crops if r]
            votes=[r for r in [line,*matches,*crops] if r and good(r)]
            supported=[r for r in votes if sum(normalized(r['text'])==normalized(v['text']) for v in votes)>=2]
            if supported:
                winner=max(supported,key=lambda r:r['mean_confidence'])
                line={**line,**{k:winner[k] for k in ('text','min_confidence','mean_confidence')}};agreed=True
        reasons=reasons_for(line,agreed)
        # Numbers/formulae additionally need a local English pass to agree on their
        # actual symbols. Mixed-language OCR can report high confidence for 6006/Edge.
        if re.search(r'\d',line['text']):
            english=[_read_crop(image,line['bbox'],folder,config,s,'eng') for s in (2,3)]
            numeric=lambda t:re.findall(r'[A-Za-z0-9]*\([^()]*\)|\d+(?:\.\d+)?',normalized(t))
            expected=numeric(line['text'])
            if not expected or any(r is None or numeric(r['text'])!=expected for r in english):
                reasons.append('ocr_numeric_disagreement')
            observations += [{'language':'eng',**{k:r[k] for k in ('text','min_confidence','mean_confidence')}} for r in english if r]
        regions.append({'id':f'region-{index+1}','bbox':line['bbox'],'text':line['text'],
                        'reasons':list(dict.fromkeys(reasons)),'eligible_for_chunking':not reasons,'observations':observations})
    unique=[]
    for r in regions:
        duplicate=next((other for other in unique if normalized(r['text'])==normalized(other['text']) and overlap(r['bbox'],other['bbox'])>.3),None)
        if duplicate is not None:
            if r['eligible_for_chunking'] and not duplicate['eligible_for_chunking']:unique.remove(duplicate)
            else:continue
        unique.append(r)
    conflicts=[r for r in unique if r['eligible_for_chunking'] and any(other is not r and other['eligible_for_chunking'] and
           overlap(r['bbox'],other['bbox'])>.7 and normalized(r['text'])!=normalized(other['text']) for other in unique)]
    for r in conflicts:r['reasons'].append('ocr_region_disagreement');r['eligible_for_chunking']=False
    result={'binding':binding,'regions':unique,'dimensions':list(image.size),'api_calls':0,'semantic_verified':False}
    result['payload_hash']=signature(result);save(dest,result)
    return result
