"""Development follow-up on the same frozen sample; not a held-out evaluation.

Reuse the completed broad-hint experiment's two blind ASR arms. Decode ONLY the
bounded-hint arm, retaining broad outputs so its regressions cannot disappear.
"""
from video_extraction._layout import source_path
import argparse
import shutil
import time
from pathlib import Path

from video_extraction.shared.common import digest_file, read, save, signature
from video_extraction.audio.speech_rules import apply
from video_extraction.audio.speech_experiment import ROOT, decode, render


def hints(row, terms, all_rows):
    targets={p['term'] for p in row['proposals']}
    context=row['context']
    ranked=sorted(terms,key=lambda t:(
        -(3*(t['term'] in targets)+2*(t['term'] in context)+t['importance']/3),t['term']))
    hotwords=', '.join(t['term'] for t in ranked[:8])
    s=row['segment']
    previous=[r['segment']['text'] for r in all_rows
              if r['segment']['end_seconds']<=s['start_seconds'] and r['segment']['end_seconds']>=s['start_seconds']-15]
    # initial_prompt is an ASR context hint, not an instruction-following prompt.
    prompt=' '.join(previous)[-100:]
    return prompt,hotwords


def run(source,out):
    from faster_whisper import WhisperModel
    manifest=read(source/'manifest.json')
    for row in manifest['selected']:
        if not (source/'samples'/row['segment']['id']/'result.json').exists():
            raise ValueError('The broad experiment must finish before the bounded comparison.')
    out.mkdir(parents=True,exist_ok=True)
    manifest={**manifest,'follow_up':'Development iteration on SAME sample; not held out.',
              'broad_source':str(source),'bounded_code_sha256':digest_file(Path(__file__)),
              'follow_up_rule_sha256':digest_file(source_path('speech_rules.py')),
              'gate_change':'Exact liaison-equivalent spelling accepted; full clip word times used with original-time bounds.'}
    save(out/'manifest.json',manifest)
    start=time.monotonic()
    model=WhisperModel('turbo',device='cpu',compute_type='int8',cpu_threads=4,
        local_files_only=True,download_root=str(ROOT/'work/extraction-compare/models'))
    for i,row in enumerate(manifest['selected']):
        s=row['segment'];old=read(source/'samples'/s['id']/'result.json')
        folder=out/'samples'/s['id'];folder.mkdir(parents=True,exist_ok=True)
        clip=folder/'audio.wav'
        if not clip.exists():shutil.copyfile(source/old['clip'],clip)
        prompt,hotwords=hints(row,manifest['lexicon'],manifest['all_proposals'])
        params={'model':'turbo','audio_sha256':digest_file(clip),'prompt':prompt,'hotwords':hotwords,
                'beam_size':5,'language':'ko','version':1}
        sig=signature(params);cached=folder/'bounded.json'
        if cached.exists() and read(cached).get('signature')==sig:new=read(cached)['result']
        else:
            new=decode(model,clip,old['clip_left_seconds'],s,prompt,hotwords)
            save(cached,{'signature':sig,'parameters':params,'result':new})
        final,accepted,held=apply(s,row['proposals'],old['plain'],new,old['witness'])
        # Re-evaluate the broad arm with the SAME updated gate for fair policy comparison.
        broad_final,broad_accepted,broad_held=apply(s,row['proposals'],old['plain'],old['hinted'],old['witness'])
        result={**old,'broad_hinted':old['hinted'],'hinted':new,'hint_policy':'8 ranked terms; previous 15s, max 100 characters',
                'broad_same_gate':{'corrected_candidate':broad_final,'accepted':broad_accepted,'held':broad_held},
                'corrected_candidate':final,'accepted':accepted,'held':held,
                'clip':str(clip.relative_to(out))}
        save(folder/'result.json',result)
        print(f'{i+1}/{len(manifest["selected"])} {s["id"]}: {new["seconds"]:.2f}s; {len(accepted)} supported',flush=True)
    save(out/'runtime.json',{'run_wall_seconds':time.monotonic()-start,
        'note':'Only bounded hinted arm newly decoded. Blind turbo/small arms reused from source experiment.'})
    metrics=render(out,manifest)
    print(metrics,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=ROOT/'outputs/speech-context-test/v2')
    p.add_argument('--out',type=Path,default=ROOT/'outputs/speech-context-test/bounded')
    a=p.parse_args();run(a.source,a.out)
