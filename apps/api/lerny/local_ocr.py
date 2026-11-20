"""Bounded offline Tesseract Korean/English OCR; source-bound receipts, no network."""
import csv
import io
import math
import os
import shutil
import subprocess
from pathlib import Path
from video_extraction.shared.common import digest_file, read, save, signature


def runtime():
    executable=shutil.which('tesseract')
    if not executable:raise ValueError('LOCAL_OCR_NOT_READY')
    options={'capture_output':True,'text':True,'encoding':'utf-8','timeout':15,'check':True}
    version=subprocess.run([executable,'--version'],**options).stdout.splitlines()[0]
    langs=subprocess.run([executable,'--list-langs'],**options).stdout.splitlines()
    if not {'kor','eng'} <= set(langs):raise ValueError('LOCAL_OCR_NOT_READY')
    candidates=[Path(os.environ['TESSDATA_PREFIX'])] if os.environ.get('TESSDATA_PREFIX') else []
    candidates += list(Path('/usr/share/tesseract-ocr').glob('*/tessdata'))
    candidates += [Path(executable).parent/'tessdata']
    root=next((p for p in candidates if all((p/(n+'.traineddata')).is_file() for n in ('kor','eng'))),None)
    if root is None:raise ValueError('LOCAL_OCR_NOT_READY')
    return {'executable':executable,'version':version,'languages':'kor+eng',
            'weights':{n:digest_file(root/(n+'.traineddata')) for n in ('kor','eng')},'psm':3}


def parse_tsv(value, dimensions):
    width,height=dimensions;groups={}
    for row in csv.DictReader(io.StringIO(value),delimiter='\t',quoting=csv.QUOTE_NONE):
        if row.get('level')!='5' or not (row.get('text') or '').strip():continue
        try:
            x,y,w,h=[int(row[k]) for k in ('left','top','width','height')]
            confidence=float(row['conf'])
            if not (math.isfinite(confidence) and 0<=confidence<=100 and 0<=x<x+w<=width and 0<=y<y+h<=height):
                raise ValueError()
        except (KeyError,TypeError,ValueError):raise ValueError('LOCAL_OCR_INVALID_RESULT') from None
        key=tuple(row[k] for k in ('block_num','par_num','line_num'))
        groups.setdefault(key,[]).append({'text':row['text'],'box':[x,y,x+w,y+h],'confidence':confidence})
    lines=[]
    for words in groups.values():
        box=[min(w['box'][0] for w in words),min(w['box'][1] for w in words),
             max(w['box'][2] for w in words),max(w['box'][3] for w in words)]
        lines.append({'text':' '.join(w['text'] for w in words),
            'bbox':[round(v/scale*1000,3) for v,scale in zip(box,[width,height,width,height])],
            'words':[{'text':w['text'],'confidence':w['confidence'],
                      'bbox':[round(v/s*1000,3) for v,s in zip(w['box'],[width,height,width,height])]} for w in words],
            'min_confidence':min(w['confidence'] for w in words),
            'mean_confidence':sum(w['confidence'] for w in words)/len(words)})
    return lines


def recognize(image, folder, config):
    from PIL import Image
    binding={'source_image':digest_file(image),'runtime':config,'policy':'tesseract-lines-v2'}
    dest=Path(folder)/(signature(binding)+'.json')
    if dest.exists():
        saved=read(dest)
        if saved.get('binding')!=binding or saved.get('payload_hash')!=signature({k:v for k,v in saved.items() if k!='payload_hash'}):
            raise ValueError('LOCAL_OCR_CACHE_CHANGED')
        return saved['lines']
    with Image.open(image) as im:dimensions=list(im.size)
    result=subprocess.run([config['executable'],str(image),'stdout','-l',config['languages'],
                          '--psm',str(config['psm']),'tsv'],capture_output=True,text=True,encoding='utf-8',
                          timeout=45,env={**os.environ,'OMP_THREAD_LIMIT':'1'},check=True)
    lines=parse_tsv(result.stdout,dimensions)
    saved={'binding':binding,'dimensions':dimensions,'lines':lines,'api_calls':0}
    saved['payload_hash']=signature(saved);save(dest,saved)
    return lines
