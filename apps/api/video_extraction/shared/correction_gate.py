"""Offline, field-scoped checks between model candidates and usable results.

Passing this gate means implemented checks passed, not a proof of transcription.
Inspected pixel ROIs are hash-bound; they are never reused on unrelated images.
"""
from video_extraction._layout import PACKAGE_ROOT
#AI가 제안한 수정의 안전장치입니다. 좌표, 표의 열·빈칸, 코드 들여쓰기, 0/o, 구분선 변경을 검사하고 근거 없는 변경은 되돌리거나 보류
import copy
import difflib
import re
from pathlib import Path
from video_extraction.shared.common import read, signature, digest_file
from video_extraction.video.separator_pixels import count_dashes

VERSION = 1
EVIDENCE = (PACKAGE_ROOT/'fixtures')/'correction-gate'/'source-evidence.json'
SEPARATOR = re.compile(r'[-=]{5,}')


def table_shape(text):
    rows=[]
    for line in text.splitlines():
        if not line.strip().startswith('|'): continue
        cells=re.split(r'(?<!\\)\|',line.strip())[1:-1]
        if cells and all(re.fullmatch(r'\s*:?-+:?\s*',c) for c in cells): continue
        rows.append(len(cells))
    return rows


def table_blanks(text):
    rows=[]
    for line in text.splitlines():
        if not line.strip().startswith('|'):continue
        cells=re.split(r'(?<!\\)\|',line.strip())[1:-1]
        if cells and all(re.fullmatch(r'\s*:?-+:?\s*',c) for c in cells):continue
        rows.append([not c.strip() for c in cells])
    return rows


def nesting_changed(before,after):
    """Allow consistent 4->2 formatting; disallow lost block-external depth.

    Compare surviving lines, including absolute zero/nonzero and pairwise depth.
    This works on split code blocks without executing or 'repairing' source code.
    """
    b=[s for s in before.splitlines() if s.strip()]
    a=[s for s in after.splitlines() if s.strip()]
    pairs=[]
    for match in difflib.SequenceMatcher(None,[s.lstrip() for s in b],[s.lstrip() for s in a],autojunk=False).get_matching_blocks():
        for k in range(match.size):
            x=b[match.a+k];y=a[match.b+k]
            pairs.append((len(x.expandtabs(8))-len(x.lstrip()),len(y.expandtabs(8))-len(y.lstrip())))
    if any((x==0)!=(y==0) for x,y in pairs): return True
    # A rank change changes Python nesting even when every line stays indented.
    return any((x>u)-(x<u)!=(y>v)-(y<v) for x,y in pairs for u,v in pairs)


def zero_changes(before,after):
    edits=[]
    for op,i,j,k,l in difflib.SequenceMatcher(None,before,after,autojunk=False).get_opcodes():
        if op=='replace' and j-i==l-k:
            for n,(a,b) in enumerate(zip(before[i:j],after[k:l])):
                if {a,b} in ({'0','o'},{'0','O'}): edits.append((k+n,a,b))
    return edits


def payload_digest(result):
    return signature({k:result.get(k,[]) for k in ('final_blocks','visuals','holds','deferred_regions')})

#수정 검사 제한
def enforce(result,image_path,evidence=None):
    """Recheck all final candidates before authoritative save and selection.

    Never erase pre-existing holds. Rejected proposals remain in receipts.
    Exact reviewed repairs may recover a field; other rejections stay held.
    """
    from PIL import Image
    out=copy.deepcopy(result); sha=digest_file(image_path)
    evidence=read(EVIDENCE) if evidence is None else evidence
    originals={(layer,b['id']):b for layer,key in [('text','blocks'),('visual','visuals')]
               for b in result['original'][key]}
    receipt=[];holds=out['holds']; image=Image.open(image_path)
    reviewed=evidence.get('reviewed',[])
    def proven(field,b,a):
        return any(e['image_sha256']==sha and e['field']==field and e['before']==b
                   and e['after']==a for e in reviewed)
    for layer,key in [('text','final_blocks'),('visual','visuals')]:
        for item in out[key]:
            before=originals.get((layer,item['id'])); proposed=copy.deepcopy(item)
            checks=[];blocking=[]
            if before and item['bbox']!=before['bbox']:
                # Crop bounds provide context; a text edit has no geometry authority.
                item['bbox']=copy.deepcopy(before['bbox'])
                checks.append('source_reviewed_bbox_restore' if proven('bbox',before,proposed) else 'crop_bbox_not_promoted')
                if not proven('bbox',before,proposed): blocking.append('geometry_change_requires_source_evidence')
            if layer=='text':
                text=item['text'];old=before['text'] if before else None
                bad_shape=table_shape(text)
                if bad_shape and (len(set(bad_shape))>1 or (old is not None and
                        (table_shape(old)!=bad_shape or table_blanks(old)!=table_blanks(text)))):
                    if old is not None and old!=text:
                        item['text']=old
                        checks.append('table_columns_restored')
                        if not proven('table_columns',before,proposed): blocking.append('table_structure_change_unverified')
                    else: blocking.append('inconsistent_table_columns')
                if before and (before['kind']=='code' or item['kind']=='code') and nesting_changed(old,item['text']):
                    item['text']=old;checks.append('code_nesting_restored')
                    if not proven('indentation',before,proposed): blocking.append('code_nesting_change_unverified')
                edits=zero_changes(old,item['text']) if old is not None else []
                if edits:
                    chars=list(item['text'])
                    for pos,observed,candidate in edits: chars[pos]=observed
                    item['text']=''.join(chars);checks.append('ambiguous_zero_preserved')
                    blocking.append('zero_or_o_unresolved')
                # Only inspected, source-hash-bound ROIs may authorize dash counts.
                matches=list(SEPARATOR.finditer(item['text']))
                if matches:
                    b=item['bbox']; w,h=image.size
                    rois=[r for r in evidence.get('pixels',[]) if r['image_sha256']==sha
                          and b[0] <= (r['bbox_pixels'][0]+r['bbox_pixels'][2])*500/w <= b[2]
                          and b[1] <= (r['bbox_pixels'][1]+r['bbox_pixels'][3])*500/h <= b[3]]
                    if len(matches)==len(rois)==1 and set(matches[0].group())=={'-'}:
                        r=rois[0]; counted=count_dashes(image,r['bbox_pixels'],r['thresholds'])
                        if counted['status']=='verified':
                            m=matches[0];item['text']=item['text'][:m.start()]+counted['value']+item['text'][m.end():]
                            checks.append('separator_pixel_verified')
                            checks.append({'pixel_evidence':counted})
                        else: blocking.append('separator_pixels_unstable')
                    elif old is None or SEPARATOR.findall(old)!=SEPARATOR.findall(item['text']):
                        # Preserve candidate as evidence; never accept a guessed count.
                        if old is not None: item['text']=old
                        blocking.append('separator_requires_pixel_evidence')
                # A kind change must not bypass the stricter code/table checks.
                if before and before['kind'] in ('code','table') and item['kind']!=before['kind']:
                    if not (before['kind']=='table' and table_shape(old)==[1] and item['text'].strip()==old.strip().strip('|').strip()):
                        item['kind']=before['kind'];blocking.append('structural_kind_change_unverified')
                if edits:
                    checks.append({'observed_preserved':True,'context_candidate':'0','decision':'unresolved'})
            if blocking:
                holds.append({'layer':layer,'target_id':item['id'],'reason':'calculation_gate',
                              'problems':sorted(set(blocking))})
            receipt.append({'layer':layer,'target_id':item['id'],'checks':checks,
                            'blocking':sorted(set(blocking)),'candidate':proposed,
                            'effective':copy.deepcopy(item),'changed_by_gate':item!=proposed})
    image.close()
    out['model_candidate_changes']=result.get('changed_blocks',0)
    out['text']='\n\n'.join(b['text'] for b in out['final_blocks'])
    out['changed_blocks']=sum(originals.get((layer,b['id']))!=b for layer,key in [('text','final_blocks'),('visual','visuals')] for b in out[key])
    out['status']='needs_review' if holds else 'calculation_checked'
    out['calculation_gate']={'version':VERSION,'image_sha256':sha,'evidence_sha256':signature(evidence),
                             'checks':receipt,'payload_sha256':payload_digest(out),
                             'scope':'geometry preservation, table columns, surviving code nesting, ambiguous 0/o edits, inspected separator pixels; not ground truth'}
    return out

#검사 결과와 저장 내용 일치 확인
def require_gate(result,image_path):
    g=result.get('calculation_gate',{})
    if g.get('version')!=VERSION or g.get('image_sha256')!=digest_file(image_path) or g.get('payload_sha256')!=payload_digest(result):
        raise ValueError('missing_or_stale_calculation_gate')


def process_guarded(frame,frames,segments,out,client,max_text_regions=40,max_visual_regions=40):
    from video_extraction.video.vision_layers import process_frame_layers
    from video_extraction.shared.common import save
    out=Path(out); image=Path(frame['path'])
    if not image.is_absolute(): image=out/image
    # Old engine output is explicitly an untrusted candidate, never selected here.
    staged={**frame,'path':str(image)}
    result=process_frame_layers(staged,frames,segments,out/'model-candidates',client,max_text_regions,max_visual_regions)
    result=enforce(result,image);require_gate(result,image)
    save(out/'vision'/frame['id']/'result.json',result)
    return result
