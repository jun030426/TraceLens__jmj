"""Offline executable/import/asset checks. Never loads an inference model or calls APIs."""
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from video_extraction.shared.common import save
from video_extraction._layout import PROJECT_ROOT


def executable(path=None):
    # A venv is selected by the invoked path, not its resolved symlink target.
    return str(Path(path or sys.executable).expanduser().absolute())


def defaults():
    native=PROJECT_ROOT/'work/extraction-compare/env/bin/python'
    return {'native_python':executable(native if native.exists() else sys.executable),
            'code_python':executable(PROJECT_ROOT/'.venv-rag/bin/python'),
            'alignment_python':executable(PROJECT_ROOT/'work/audio-alignment-env/bin/python')}


def imports(python,modules):
    python=executable(python)
    if not Path(python).is_file():return {'python':python,'ok':False,'checks':[], 'reason':'python_missing'}
    # Block import-time network probes; model constructors are never called.
    code='''import os,socket,json,sys,importlib,importlib.metadata
os.environ.update(PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True",HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1")
def deny(*a,**k): raise OSError("network_disabled_for_environment_check")
socket.socket.connect=deny;socket.create_connection=deny
checks=[]
for module,distribution in json.loads(sys.argv[1]):
 try:
  value=importlib.import_module(module)
  if module=="whisperx.alignment":
   import inspect
   if "model_cache_only" not in inspect.signature(value.load_align_model).parameters:
    raise RuntimeError("whisperx_offline_loading_api_incompatible")
  checks.append(dict(module=module,ok=True,file=getattr(value,"__file__",None),version=importlib.metadata.version(distribution)))
 except Exception as exc: checks.append(dict(module=module,ok=False,error_type=type(exc).__name__))
print("RUNTIME_CHECK="+json.dumps(dict(python=sys.executable,checks=checks,ok=all(c["ok"] for c in checks))))
'''
    try:
        with tempfile.TemporaryDirectory(prefix='pipeline-import-check-') as cache:
            p=subprocess.run([python,'-c',code,json.dumps(modules)],capture_output=True,text=True,timeout=60,
                env={**os.environ,'PADDLE_PDX_CACHE_HOME':cache,'PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK':'True',
                     'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'})
    except (OSError,subprocess.TimeoutExpired) as exc:
        return {'python':python,'ok':False,'checks':[],'reason':type(exc).__name__}
    lines=[l.partition('=')[2] for l in p.stdout.splitlines() if l.startswith('RUNTIME_CHECK=')]
    if p.returncode or not lines:return {'python':python,'ok':False,'checks':[],'reason':'import_process_failed','returncode':p.returncode}
    return json.loads(lines[-1])


def binary(name):
    from video_extraction.pipeline.adapters import binary_path
    from video_extraction.shared.media import ffmpeg
    try:
        path=ffmpeg() if name=='ffmpeg' else binary_path(name)
        if not path:return {'name':name,'ok':False,'reason':'binary_missing'}
        flag='--version' if name=='soffice' else '-version' if name=='ffmpeg' else '-v'
        p=subprocess.run([path,flag],capture_output=True,text=True,timeout=30)
        lines=(p.stdout+p.stderr).splitlines()
        return {'name':name,'path':path,'ok':p.returncode==0,'version':lines[0] if lines else '', 'returncode':p.returncode}
    except (OSError,subprocess.TimeoutExpired) as exc:return {'name':name,'ok':False,'reason':type(exc).__name__}


def assets(folder,names):
    root=Path(folder) if folder else None
    missing=[name for name in names if root is None or not (root/name).is_file() or (root/name).stat().st_size==0]
    return {'folder':str(root) if root else None,'ok':not missing,'missing':missing}


def audit(plan,output=None):
    source=plan['source_plan'];kinds={s['kind'] for s in source['sources']};config=plan.get('tool_runtime',defaults())
    checks=[];warnings=[]
    main=[('PIL','Pillow'),('numpy','numpy'),('cv2','opencv-python-headless')]
    # Installed OpenCV can be supplied by either wheel distribution.
    try:importlib.metadata.version('opencv-python-headless')
    except importlib.metadata.PackageNotFoundError:main[-1]=('cv2','opencv-python')
    if kinds & {'audio','video'}:main += [('av','av'),('imageio_ffmpeg','imageio-ffmpeg'),('faster_whisper','faster-whisper'),('ctranslate2','ctranslate2'),('onnxruntime','onnxruntime')]
    checks.append({'tool':'main_python','required':True,**imports(sys.executable,main)})
    if 'code' in kinds and any(s.get('language')=='java' for s in source['sources']):
        checks.append({'tool':'Tree-sitter Java','required':True,**imports(config.get('code_python',sys.executable),
            [('tree_sitter','tree-sitter'),('tree_sitter_java','tree-sitter-java')])})
    if 'ppt' in kinds:checks.append({'tool':'python-pptx','required':True,**imports(config['native_python'],[('pptx','python-pptx')])})
    for name in (['soffice'] if 'ppt' in kinds else [])+(['pdfinfo','pdftoppm','pdftotext'] if kinds & {'ppt','pdf'} else [])+(['ffmpeg'] if kinds & {'audio','video'} else []):
        checks.append({'tool':name,'required':True,**binary(name)})
    if kinds & {'ppt','pdf','image','video','ink'}:
        if plan.get('ocr_models'):
            checks.append({'tool':'PaddleOCR','required':plan.get('ocr_policy')!='selective_auxiliary_v1',**imports(plan['ocr_python'],[('paddle','paddlepaddle'),('paddleocr','paddleocr')])})
            names=[folder+'/'+name for folder in ('PP-OCRv5_mobile_det','korean_PP-OCRv5_mobile_rec') for name in ('inference.yml','inference.json','inference.pdiparams')]
            checks.append({'tool':'PaddleOCR_weights','required':plan.get('ocr_policy')!='selective_auxiliary_v1',**assets(plan['ocr_models'],names)})
        else:warnings.append({'tool':'PaddleOCR','reason':'not_configured_ink_text_cannot_be_selected'})
    if kinds & {'audio','video'} and source.get('local_whisper'):
        model=source['local_whisper']
        checks.append({'tool':'Whisper_weights','required':True,**assets(model['path'],list(model['files']))})
        spec=importlib.util.find_spec('faster_whisper')
        folder=Path(next(iter(spec.submodule_search_locations)))/'assets' if spec else None
        checks.append({'tool':'Silero_VAD_weights','required':True,**assets(folder,['silero_vad_v6.onnx'])})
    if kinds & {'audio','video'}:
        checks.append({'tool':'WhisperX','required':False,'required_for':'word_timed_audio',
            **imports(config['alignment_python'],[('whisperx.alignment','whisperx'),('nltk','nltk')])})
        warnings.append({'tool':'WhisperX_weights','reason':'checked_or_downloaded_only_during_user_alignment_run'})
    report={'checks':checks,'warnings':warnings,'core_ready':all(c['ok'] for c in checks if c['required']),
            'all_installed_tools_ready':all(c['ok'] for c in checks),'model_execution_tested':False,'api_called':False,
            'gemini':'connected_via_shared.gemini; authentication_and_model_response_not_tested',
            'alignment_connected':True,'comparison_only_not_required':['Docling','EasyOCR']}
    if output:save(Path(output)/'runtime-check.json',report)
    return report


def require_core(report):
    failed=[c['tool'] for c in report['checks'] if c['required'] and not c['ok']]
    if failed:raise ValueError('실행 도구 점검 실패: '+', '.join(failed)+' (runtime-check.json 확인)')
