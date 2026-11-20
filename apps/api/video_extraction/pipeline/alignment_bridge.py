"""Automatically hand approved changed speech to the existing WhisperX workflow.

Preparation/reporting are model-free. Only run (user CLI) executes alignment.
The derived file preserves text and selection, and marks unusable timing explicitly.
"""
from pathlib import Path
import subprocess
from video_extraction.shared.common import read,save,digest_file,signature
from video_extraction.audio import word_alignment
from video_extraction.pipeline import runtime_tools


def prepare(out,plan,records):
    out=Path(out);config=plan.get('tool_runtime',runtime_tools.defaults())
    binding={'records':digest_file(records),'language':plan['source_plan'].get('config',{}).get('language','ko'),
             'model':config.get('alignment_model'),'implementation':digest_file(word_alignment.__file__)}
    folder=out/'word-alignment'/signature(binding)[:24]
    ap=word_alignment.prepare(records,folder,binding['language'],model=binding['model'])
    summary=read(folder/'summary.json');latest=read(folder/'latest.json')
    status={'source_records':str(records),'source_sha256':binding['records'],'output':str(folder),
            'targets':len(ap['jobs']),'excluded':len(ap['excluded']),**summary,
            'state':'not_required' if not ap['jobs'] and not ap['excluded'] else 'pending',
            'text_usable_records':str(records),'records_with_timing':latest['records'],
            'word_timing_review':latest['timing_review'],'python':config['alignment_python']}
    done=all((folder/'results'/(signature(j['id'])[:24]+'.json')).exists() for j in ap['jobs'])
    if ap['jobs'] and done:status['state']='complete_with_review' if summary['pending_or_unresolved'] else 'complete'
    prior=out/'alignment-status.json'
    if prior.exists() and status['state']=='pending':
        old=read(prior)
        if old.get('source_sha256')==status['source_sha256'] and old.get('state') in ('environment_missing','execution_failed'):
            status.update({k:old[k] for k in ('state','reason','environment','log') if k in old})
    save(out/'alignment-status.json',status);return status


def run(out,plan):
    out=Path(out);latest=read(out/'latest.json');status=prepare(out,plan,latest['usable_records'])
    if status['state'] in ('not_required','complete','complete_with_review') or not status['targets']:return status
    config=plan.get('tool_runtime',runtime_tools.defaults());python=config['alignment_python']
    check=runtime_tools.imports(python,[('whisperx.alignment','whisperx'),('nltk','nltk')])
    if not check['ok']:
        status.update(state='environment_missing',reason='WhisperX 실행 환경 설치 필요',environment=check)
        save(out/'alignment-status.json',status);return status
    folder=Path(status['output']);args=[python,'-u','-m','video_extraction.audio.word_alignment','run','--output',str(folder)]
    # This function is called only by the user's run command, never report/prepare.
    from video_extraction.pipeline.runtime_setup import ensure_alignment
    ap=read(folder/'plan.json')
    for language in sorted({j.get('language') or ap['language'] for j in ap['jobs']}):
        ensure_alignment(python,language,config.get('alignment_model'))
    if config.get('alignment_allow_download'):args.append('--allow-download')
    with (folder/'worker.log').open('a') as log:
        result=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,check=False)
    status=prepare(out,plan,latest['usable_records'])
    if result.returncode:status.update(state='execution_failed',reason='정렬 로그 확인',log=str(folder/'worker.log'))
    save(out/'alignment-status.json',status);return status
