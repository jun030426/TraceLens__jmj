"""User-terminal-only setup, shared by common and standalone alignment launchers.

No Gemini client, key access, audio upload, extraction or content mutation here.
Unlike the offline doctor, this explicit entry point can install local tools and
download alignment assets. It must finish before the common launcher asks for keys.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path
from video_extraction.pipeline import runtime_tools as rt
from video_extraction.shared.common import read, save, digest_file
from video_extraction._layout import PROJECT_ROOT


WARMUP = r'''
import os,sys,socket
offline=sys.argv[3]=='offline'
os.environ['HF_HUB_OFFLINE']='1' if offline else '0'
os.environ['TRANSFORMERS_OFFLINE']='1' if offline else '0'
if offline:
 def deny(*a,**k):raise OSError('network_disabled_for_alignment_probe')
 socket.socket.connect=deny;socket.create_connection=deny
import nltk
try:nltk.data.find('tokenizers/punkt_tab')
except LookupError:
 if offline:raise
 if not nltk.download('punkt_tab',quiet=True):raise RuntimeError('nltk_punkt_download_failed')
from whisperx.alignment import load_align_model
model,metadata=load_align_model(sys.argv[1],'cpu',model_name=sys.argv[2] or None,model_cache_only=offline)
if not metadata.get('dictionary'):raise RuntimeError('alignment_dictionary_empty')
print('ALIGNMENT_MODEL_READY')
'''


def ensure_alignment(python, language, model=None):
    python=rt.executable(python)
    modules=[('whisperx.alignment','whisperx'),('nltk','nltk')]
    check=rt.imports(python,modules)
    installed=False
    if not check['ok']:
        if not Path(python).is_file():
            env=Path(python).parent.parent
            if Path(python).parent.name!='bin':
                raise ValueError('alignment_python_must_be_venv_bin_python')
            print('기존 Whisper·OCR 환경과 분리한 WhisperX 환경을 준비합니다.',flush=True)
            subprocess.run([sys.executable,'-m','venv',str(env)],check=True)
        # Never install packages into a non-venv interpreter supplied by mistake.
        subprocess.run([python,'-c','import sys; sys.exit(0 if sys.prefix!=sys.base_prefix else 2)'],check=True)
        subprocess.run([python,'-m','pip','install','--upgrade','-r',
                        str(PROJECT_ROOT/'video_extraction/requirements-alignment.txt')],check=True)
        installed=True
        check=rt.imports(python,modules)
        if not check['ok']:
            raise ValueError('whisperx_setup_import_check_failed')
    # Automatic ASR language detection has not run at setup time. Install the
    # engine now; prepare the language-specific model after detection in run().
    if language is None:
        return {'python':python,'imports':check,'installed':installed,
                'download_attempted':False,'model_cache_ready':False,
                'state':'awaiting_source_language','language':None,'audio_processed':False}
    if not isinstance(language,str) or not language.strip():
        raise ValueError('invalid_alignment_language')
    args=[python,'-c',WARMUP,language,model or '']
    probe=subprocess.run([*args,'offline'],capture_output=True,text=True,check=False)
    downloaded=False
    if probe.returncode:
        print('WhisperX 정렬 모델·문장 분리 자료를 준비합니다. 유료 API 호출이나 음원 업로드는 없습니다.',flush=True)
        subprocess.run([*args,'download'],check=True)
        downloaded=True
        # Ensure the later offline alignment worker really can use this cache.
        subprocess.run([*args,'offline'],check=True)
    return {'python':python,'imports':check,'installed':installed,'download_attempted':downloaded,
            'model_cache_ready':True,'language':language,'model':model,'audio_processed':False}


def prepare_common(output):
    from video_extraction.pipeline.connected import verify
    output=Path(output).resolve()
    status={'state':'preparing','api_calls':0,'setup_implementation':digest_file(__file__)}
    try:
        plan=verify(output)  # Invalid/stale plans stop before installation or keys.
        report=rt.audit(plan,output);rt.require_core(report)
        status['alignment']={'state':'not_required'}
        if any(t['kind']=='audio' for t in plan['tasks']):
            cfg=plan['tool_runtime']
            status['alignment']=ensure_alignment(cfg['alignment_python'],
                plan['source_plan'].get('config',{}).get('language','ko'),cfg.get('alignment_model'))
            report=rt.audit(plan,output);rt.require_core(report)
            if any(c['tool']=='WhisperX' and not c['ok'] for c in report['checks']):
                raise ValueError('whisperx_environment_not_ready_after_setup')
        status.update(state='ready',runtime=report)
    except Exception as exc:
        status.update(state='blocked_before_api',error_type=type(exc).__name__)
        save(output/'tool-setup.json',status)
        raise
    save(output/'tool-setup.json',status)
    print('유형별 실행 도구 준비 확인 완료. 추출·검증·수정·선별로 이어갑니다.',flush=True)
    return status


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    target=ap.add_mutually_exclusive_group(required=True)
    target.add_argument('--output',type=Path)
    target.add_argument('--alignment-output',type=Path)
    ap.add_argument('--alignment-python')
    a=ap.parse_args()
    if a.output:
        prepare_common(a.output)
    else:
        p=read(a.alignment_output/'plan.json')
        ensure_alignment(a.alignment_python or os.environ.get('ALIGNMENT_PYTHON') or rt.defaults()['alignment_python'],
                         p['language'],p.get('model'))
    return 0


if __name__=='__main__':raise SystemExit(main())
