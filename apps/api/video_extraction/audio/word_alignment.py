"""Align approved text to local PCM without re-transcribing or changing decisions.

prepare is model-free. run uses WhisperX forced alignment, not a paid API. Failed
alignment disables word-level timing use, not previously verified text retrieval.
"""
import argparse
import copy
import importlib.metadata
import json
import math
import os
import re
import wave
from pathlib import Path
from video_extraction.shared.common import read, save, jsonl, signature, digest_file


def compact(text): return re.sub(r'\s+', '', text)


def inspect_alignment(text, span, result, supported_chars=None, minimum_score=.5):
    words=result.get('word_segments',[]);reasons=[]
    if not words or compact(''.join(w.get('word','') for w in words))!=compact(text):
        reasons.append('aligned_word_text_missing_duplicated_or_changed')
    previous=span[0]
    for word in words:
        values=[word.get(k) for k in ('start','end','score')]
        if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in values):
            reasons.append('missing_or_nonfinite_word_timing');continue
        a,b,score=values
        if not span[0]<=a<b<=span[1] or a<previous-.001:reasons.append('word_order_overlap_or_outside_target')
        if score<minimum_score:reasons.append('low_alignment_score')
        previous=b
    chars=[c for s in result.get('segments',[]) for c in (s.get('chars') or []) if c.get('char','').isalnum()]
    expected=[c for c in text if c.isalnum()]
    if ''.join(c['char'] for c in chars)!=''.join(expected):reasons.append('character_coverage_incomplete')
    for c in chars:
        if supported_chars is not None and c['char'].lower() not in supported_chars:
            reasons.append('character_not_supported_by_alignment_model')
        if any(not isinstance(c.get(k),(int,float)) or not math.isfinite(c[k]) for k in ('start','end','score')):
            reasons.append('unaligned_character');continue
        if not span[0]<=c['start']<c['end']<=span[1] or c['score']<minimum_score:
            reasons.append('unreliable_character_alignment')
    return {'passed':not reasons,'reasons':sorted(set(reasons)),
            'minimum_score':minimum_score,'accuracy_guarantee':False}


def prepare(records,output,language='ko',source_plan=None,model=None):
    output=Path(output).resolve();records=Path(records).resolve()
    rows=[json.loads(line) for line in records.read_text().splitlines() if line.strip()]
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('duplicate_alignment_record_id')
    provenance=read(source_plan) if source_plan else {}
    inputs={str(records):digest_file(records)}
    if source_plan:inputs[str(Path(source_plan).resolve())]=digest_file(source_plan)
    jobs=[];excluded=[]
    for r in rows:
        if r.get('modality')!='audio' or r.get('kind')!='speech' or not r.get('eligible_for_chunking'):
            continue
        if not r.get('word_alignment_required'):continue
        target_language=r.get('detected_language') or language
        if not isinstance(target_language,str) or not target_language.strip():
            excluded.append({'id':r['id'],'reason':'alignment_language_unresolved'});continue
        source=r.get('source_audio');offset=r.get('audio_offset_seconds')
        if offset is None and source==provenance.get('source_audio'):
            offset=provenance.get('audio_offset_seconds')
        if not source or offset is None:
            excluded.append({'id':r['id'],'reason':'source_audio_or_time_offset_missing'});continue
        offset=float(offset);a=float(r['start_seconds'])-offset;b=float(r['end_seconds'])-offset
        with wave.open(str(source)) as wav:
            duration=wav.getnframes()/wav.getframerate()
            if (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())!=(16000,1,2):raise ValueError('alignment_requires_pcm16_mono_16k')
        if not all(math.isfinite(x) for x in (offset,a,b)) or not 0<=a<b<=duration:
            excluded.append({'id':r['id'],'reason':'invalid_source_interval'});continue
        if str(source) not in inputs:inputs[str(source)]=digest_file(source)
        jobs.append({'id':r['id'],'source_audio':source,'interval':[a,b],'offset':offset,'text':r['observed_text'],
                     'language':target_language})
    plan={'records':str(records),'inputs':inputs,'jobs':jobs,'excluded':excluded,'language':language,
          'model':model,'implementation':digest_file(__file__),'purpose':'word_timing_only_no_text_or_selection_changes'}
    path=output/'plan.json'
    if path.exists() and read(path)!=plan:raise ValueError('alignment_inputs_changed_choose_new_output')
    save(path,plan);publish(output,plan)
    return plan


def publish(output,plan):
    for source,h in plan.get('inputs',{}).items():
        if digest_file(source)!=h:raise ValueError('alignment_source_changed')
    rows=[json.loads(l) for l in Path(plan['records']).read_text().splitlines() if l.strip()]
    receipts={};pending=list(plan['excluded'])
    for job in plan['jobs']:
        path=output/'results'/(signature(job['id'])[:24]+'.json')
        if not path.exists():pending.append({'id':job['id'],'reason':'alignment_not_run'});continue
        r=read(path)
        if r['binding']!=signature({'plan':plan,'job':job}):raise ValueError('alignment_receipt_changed')
        if inspect_alignment(job['text'],[0,job['interval'][1]-job['interval'][0]],r['raw'],set(r['supported_chars']))!=r['gate']:
            raise ValueError('alignment_gate_changed')
        receipts[job['id']]=(job,r)
        if not r['gate']['passed']:pending.append({'id':job['id'],'reason':r['gate']['reasons']})
    waiting={job['id'] for job in plan['jobs']}|{x['id'] for x in plan['excluded']}
    for row in rows:
        if row['id'] in waiting:
            row['previous_words']=copy.deepcopy(row.get('words',[]));row['words']=[]
            row['word_timing_status']='alignment_pending'
            row['eligible_for_word_timed_use']=False;row['word_timestamps_verified']=False
        if row['id'] not in receipts:continue
        job,r=receipts[row['id']]
        row['alignment_review']=r['gate'];row['word_timestamps_verified']=False
        # 'verified' is reserved for a source-reviewed timing reference. A model
        # estimate passing geometry checks is explicitly not that reference.
        row['word_timing_status']='model_aligned_checks_passed' if r['gate']['passed'] else 'alignment_needs_review'
        row['eligible_for_word_timed_use']=r['gate']['passed']
        if r['gate']['passed']:
            base=job['interval'][0]+job['offset']
            row['words']=[{'word':w['word'],'start_seconds':w['start']+base,'end_seconds':w['end']+base,
                           'alignment_score':w['score']} for w in r['raw']['word_segments']]
            row['word_alignment_required']=False
    output.mkdir(parents=True,exist_ok=True)
    revision=signature({'plan':plan,'receipts':receipts,'pending':pending})[:24]
    dest=output/'revisions'/revision;dest.mkdir(parents=True,exist_ok=True)
    jsonl(dest/'records.aligned.jsonl',rows);jsonl(dest/'timing-review.jsonl',pending)
    summary={'targets':len(plan['jobs']),'aligned_checks_passed':sum(r['gate']['passed'] for _,r in receipts.values()),
             'pending_or_unresolved':len(pending),'text_changes':0,'selection_changes':0,'api_calls':0,
             'actual_accuracy':None}
    save(output/'summary.json',summary);save(output/'latest.json',{'records':str(dest/'records.aligned.jsonl'),'timing_review':str(dest/'timing-review.jsonl')})
    return summary


def run(output,allow_download=False):
    output=Path(output).resolve();plan=read(output/'plan.json')
    if plan['implementation']!=digest_file(__file__):raise ValueError('alignment_code_changed_prepare_new_output')
    for path,h in plan['inputs'].items():
        if digest_file(path)!=h:raise ValueError('alignment_source_changed')
    if not allow_download:
        os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    # Imports/model execution happen only in the user's run command.
    import nltk
    try:nltk.data.find('tokenizers/punkt_tab')
    except LookupError:
        if not allow_download:raise ValueError('nltk_punkt_tab_not_installed')
        if not nltk.download('punkt_tab',quiet=True):raise ValueError('nltk_punkt_download_failed')
    import numpy as np
    from whisperx.alignment import load_align_model,align
    models={}
    try:
        for job in plan['jobs']:
            path=output/'results'/(signature(job['id'])[:24]+'.json')
            if path.exists():continue
            language=job.get('language') or plan['language']
            if language not in models:
                models[language]=load_align_model(language,'cpu',model_name=plan['model'],model_cache_only=not allow_download)
            model,metadata=models[language];supported=sorted(metadata['dictionary'])
            a,b=job['interval']
            with wave.open(job['source_audio']) as wav:
                wav.setpos(round(a*16000));pcm=wav.readframes(round((b-a)*16000))
            audio=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
            raw=align([{'start':0.,'end':len(audio)/16000,'text':job['text']}],model,metadata,audio,'cpu',return_char_alignments=True)
            gate=inspect_alignment(job['text'],[0,b-a],raw,set(supported))
            save(path,{'binding':signature({'plan':plan,'job':job}),'raw':raw,'gate':gate,'supported_chars':supported,
                       'model':plan['model'] or metadata['language'],'whisperx_version':importlib.metadata.version('whisperx')})
            print(json.dumps({'id':job['id'],'timing_checks_passed':gate['passed']},ensure_ascii=False),flush=True)
    finally:publish(output,plan)
    return publish(output,plan)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('mode',choices=['prepare','run','report'])
    ap.add_argument('--records',type=Path);ap.add_argument('--source-plan',type=Path);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--language',default='ko');ap.add_argument('--model');ap.add_argument('--allow-download',action='store_true')
    a=ap.parse_args()
    if a.mode=='prepare':
        if a.records is None:ap.error('--records required')
        prepare(a.records,a.output,a.language,a.source_plan,a.model);summary=read(a.output/'summary.json')
    elif a.mode=='run':summary=run(a.output,a.allow_download)
    else:summary=publish(a.output,read(a.output/'plan.json'))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
