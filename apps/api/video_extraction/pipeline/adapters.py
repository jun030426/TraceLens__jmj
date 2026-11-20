"""Local modality adapters. No model/network calls, project-specific sources or IDs."""
import json
import math
import os
import re
import shutil
import subprocess
import wave
import xml.etree.ElementTree as ET
from pathlib import Path
from video_extraction.shared.progress import report
from PIL import Image,ImageOps,ImageSequence
from video_extraction.shared import media
from video_extraction.shared.common import digest_file,save
from video_extraction.audio.audio_accuracy import clip
from video_extraction.ppt.other_data import ppt_native

KINDS={'.py':'code','.java':'code','.pptx':'ppt','.pdf':'pdf','.png':'image','.jpg':'image','.jpeg':'image','.webp':'image','.tif':'image','.tiff':'image','.bmp':'image',
       '.wav':'audio','.mp3':'audio','.m4a':'audio','.flac':'audio','.ogg':'audio','.aac':'audio',
       '.mp4':'video','.mov':'video','.mkv':'video','.webm':'video','.avi':'video'}


def binary_path(name):
    binary=shutil.which(name)
    if not binary:
        bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override'/name
        if bundled.is_file():binary=str(bundled)
    if not binary:
        bundled=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/poppler/bin'/name
        if bundled.is_file():binary=str(bundled)
    return binary


def command(name,args,env=None):
    binary=binary_path(name)
    if not binary:raise ValueError('missing_local_tool:'+name)
    try:p=subprocess.run([binary,*map(str,args)],capture_output=True,timeout=300,env=env)
    except subprocess.TimeoutExpired as ex:raise ValueError(name+'_timed_out') from ex
    if p.returncode:raise ValueError(name+'_failed:'+p.stderr.decode(errors='replace')[-500:])
    return p.stdout.decode(errors='replace')


def font_environment(folder):
    """Bundled headless LibreOffice must see installed system CJK fonts too."""
    dirs=[p for p in (Path('/System/Library/Fonts'),Path('/Library/Fonts'),Path('/usr/share/fonts'),Path.home()/'.local/share/fonts') if p.is_dir()]
    config=ET.Element('fontconfig')
    for p in dirs:ET.SubElement(config,'dir').text=str(p)
    ET.SubElement(config,'cachedir').text=str(folder/'font-cache')
    path=folder/'fontconfig.xml';ET.ElementTree(config).write(path,encoding='utf-8',xml_declaration=True)
    return {**os.environ,'FONTCONFIG_FILE':str(path),'SAL_FONTPATH':os.pathsep.join(map(str,dirs))}


def render_health(image,bbox_xml):
    """Detect blank glyph areas, not text correctness. Unknown remains explicit."""
    tree=ET.fromstring(bbox_xml);page=next((n for n in tree.iter() if n.tag.split('}')[-1]=='page'),None)
    if page is None:return {'status':'no_native_words','checked':0,'blank_words':[]}
    missing=[];checked=0
    with Image.open(image) as im:
        sx=im.width/float(page.attrib['width']);sy=im.height/float(page.attrib['height'])
        for word in page.iter():
            text=word.text or ''
            if word.tag.split('}')[-1]!='word' or len(text.strip())<2:continue
            box=[float(word.attrib[k])*(sx if k[0]=='x' else sy) for k in ('xMin','yMin','xMax','yMax')]
            if box[2]<=box[0] or box[3]<=box[1]:missing.append(text);checked+=1;continue
            crop=im.crop(tuple(box)).convert('L');low,high=crop.getextrema();checked+=1
            if high-low<8:missing.append(text)
    return {'status':'suspected_missing_glyphs' if missing and len(missing)/max(checked,1)>=.35 else 'checked' if checked else 'no_native_words',
            'checked':checked,'blank_words':missing,'not_an_accuracy_measure':True}


def pdf_pages(pdf,folder,dpi,env=None):
    info=command('pdfinfo',[pdf]);match=re.search(r'^Pages:\s+(\d+)',info,re.M)
    if not match or int(match[1])<=0:raise ValueError('pdf_page_count_unavailable')
    count=int(match[1]);pages=[]
    for n in range(1,count+1):
        stem=folder/f'page-{n:05}'
        command('pdftoppm',['-f',n,'-l',n,'-r',dpi,'-png','-singlefile',pdf,stem],env)
        image=stem.with_suffix('.png')
        if not image.is_file():raise ValueError('page_render_missing')
        native=command('pdftotext',['-f',n,'-l',n,'-layout',pdf,'-']) if binary_path('pdftotext') else ''
        bbox=command('pdftotext',['-f',n,'-l',n,'-bbox',pdf,'-']) if binary_path('pdftotext') else None
        health=render_health(image,bbox) if bbox else {'status':'render_check_unavailable'}
        from video_extraction.pdf.workflow import native_inventory
        pages.append({'image':str(image),'location':{'page':n},'native_text':native.rstrip('\f\n'),'render_health':health,
                      'pdf_inventory':native_inventory(bbox) if bbox else {'route':'unknown','words':[]},
                      'preparation_holds':[health['status']] if health['status'] in ('suspected_missing_glyphs','render_check_unavailable') else []})
    return pages


def audio_units(path,folder,config,offset=0):
    report('prepare_audio')
    meta=media.prepare_audio(path,folder,normalize=False);audio=folder/meta['original_audio']
    with wave.open(str(audio)) as w:duration=w.getnframes()/w.getframerate()
    if duration<=0:raise ValueError('empty_audio')
    units=[];size=config['audio_window_seconds'];context=config['context_seconds']
    for i in range(math.ceil(duration/size)):
        report('audio_clips', i, math.ceil(duration/size))
        a=i*size;b=min(duration,a+size);lo=max(0,a-context);hi=min(duration,b+context)
        primary=folder/f'audio-{i:05}-target.wav';surround=folder/f'audio-{i:05}-context.wav'
        target_meta=clip(audio,primary,a,b);context_meta=clip(audio,surround,lo,hi)
        units.append({'modality':'audio','source_audio':str(audio),'target_clip':str(primary),'target_clip_meta':target_meta,
            'context_clip':str(surround),'context_clip_meta':context_meta,'interval':[a,b],'review_interval':[lo,hi],
            'location':{'start_seconds':a+offset,'end_seconds':b+offset,'audio_offset_seconds':offset},
            'review_protocol':4,'neighbors':[]})
    return units,{'audio_duration_seconds':duration,'audio_windows':len(units),'audio_coverage':'all_contiguous_windows','audio_offset_seconds':offset}


def prepare_source(path,folder,config,kind=None):
    path=Path(path).resolve();folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    kind=kind or KINDS.get(path.suffix.lower())
    if kind not in ('ppt','pdf','audio','video','image','ink','code'):raise ValueError('unsupported_source_type')
    pages=[];units=[];info={'kind':kind,'source_file':str(path),'source_sha256':digest_file(path)}
    if kind=='code':
        language={'.py':'python','.java':'java'}.get(path.suffix.lower())
        if not language:raise ValueError('unsupported_code_language')
        return {**info,'language':language},[{'modality':'code','language':language,'location':{'file':path.name}}]
    elif kind in ('image','ink'):
        with Image.open(path) as im:
            for i,frame in enumerate(ImageSequence.Iterator(im)):
                target=folder/f'image-{i:05}.png';ImageOps.exif_transpose(frame.copy()).convert('RGB').save(target)
                pages.append({'image':str(target),'location':{'image_page':i+1},'native_text':''})
        info['image_pages']=len(pages)
    elif kind in ('pdf','ppt'):
        pdf=path;env=font_environment(folder)
        if kind=='ppt':
            native,assets,pending=ppt_native(path)
            save(folder/'native-ppt.json',{'rows':native,'assets':assets,'pending':pending})
            command('soffice',['-env:UserInstallation='+(folder/'libreoffice-profile').as_uri(),
                               '--headless','--convert-to','pdf','--outdir',folder,path],env)
            pdf=folder/(path.stem+'.pdf')
            if not pdf.is_file():raise ValueError('ppt_render_missing')
        pages=pdf_pages(pdf,folder,config['pdf_dpi'],env);info['pages']=len(pages)
    elif kind=='audio':units,extra=audio_units(path,folder,config);info.update(extra)
    else:
        meta=media.probe(path)
        frames=media.select_frames(path,folder,meta,{'scan_fps':config['scan_fps'],'change_fraction':.015,'min_frame_gap':.5,'max_frame_gap':config['max_frame_gap']}, progress=lambda stage, at, total: report('frames', at, total))
        from video_extraction.pipeline.video_followup import expand
        frames=expand(path,frames,meta,folder,config)
        pages=[{'image':str(folder/f['path']),'location':{'frame_time_seconds':f['time_seconds'],'frame_id':f['id']},'native_text':''} for f in frames]
        info.update(video_metadata=meta,video_frame_coverage='sampled_changes_with_decoded_followup_not_every_frame',frames=len(frames),
                    supplemental_scan=str(folder/'supplemental-frames.json'))
        if meta['audio_present']:
            units,extra=audio_units(path,folder,config,meta['audio_offset_seconds']);info.update(extra)
    for page in pages:
        with Image.open(page['image']) as im:size=list(im.size)
        units.append({**page,'modality':'visual','dimensions':size,'source_kind':kind,
                      'time_seconds':page['location'].get('frame_time_seconds',float(page['location'].get('page',page['location'].get('image_page',1))))})
    return info,units
