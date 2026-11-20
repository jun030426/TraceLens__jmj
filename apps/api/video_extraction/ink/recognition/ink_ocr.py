"""Optional offline PaddleOCR worker. Explicit local models; no downloads."""
import argparse
import json
import os
from pathlib import Path
import socket
import hashlib


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--models',required=True,type=Path)
    args=p.parse_args()
    det=args.models/'PP-OCRv5_mobile_det';rec=args.models/'korean_PP-OCRv5_mobile_rec'
    if not all((d/'inference.yml').exists() for d in (det,rec)):raise ValueError('local_ocr_models_missing')
    model_hashes={str(f.resolve()):hashlib.sha256(f.read_bytes()).hexdigest()
                  for d in (det,rec) for f in sorted(d.iterdir()) if f.is_file() and f.name!='README.md'}
    def deny(*a,**k):raise OSError('network_disabled_for_local_ocr')
    socket.socket.connect=deny;socket.create_connection=deny
    os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK']='True'
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['PADDLE_PDX_CACHE_HOME']=str(args.output.parent/'paddle-cache')
    os.environ['OMP_NUM_THREADS']='2'
    from paddleocr import PaddleOCR
    engine=PaddleOCR(text_detection_model_name='PP-OCRv5_mobile_det',text_recognition_model_name='korean_PP-OCRv5_mobile_rec',
        text_detection_model_dir=str(det.resolve()),text_recognition_model_dir=str(rec.resolve()),
        use_doc_orientation_classify=False,use_doc_unwarping=False,use_textline_orientation=False,
        device='cpu',cpu_threads=2,enable_mkldnn=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    # One durable receipt per image, so interruption does not discard finished OCR.
    for row in json.loads(args.manifest.read_text()):
        dest=args.output.parent/(row['id']+'.json')
        if dest.exists():
            existing=json.loads(dest.read_text())
            if existing.get('image_sha256')!=row['image_sha256'] or existing.get('model_hashes')!=model_hashes:
                raise ValueError('stale_ocr_receipt_prepare_new_output')
            continue
        try:
            result=list(engine.predict(row['path']))[0].json
            if isinstance(result,str):result=json.loads(result)
            body=result.get('res',result)
            words=[]
            for text,score,poly in zip(body.get('rec_texts',[]),body.get('rec_scores',[]),body.get('rec_polys',[])):
                xs=[float(pt[0]) for pt in poly];ys=[float(pt[1]) for pt in poly]
                words.append({'text':text,'score':float(score),'bbox_pixels':[min(xs),min(ys),max(xs),max(ys)]})
            record={'state':'candidate','words':words,'raw':result,'provider':'PaddleOCR','model_hashes':model_hashes,**row}
        except Exception as exc:
            record={'state':'failed','error':str(exc),'words':[],'provider':'PaddleOCR','model_hashes':model_hashes,**row}
        tmp=dest.with_suffix('.tmp');tmp.write_text(json.dumps(record,ensure_ascii=False));tmp.replace(dest)
        print(json.dumps({'ocr':row['id'],'state':record['state']},ensure_ascii=False),flush=True)
    args.output.write_text(json.dumps({'state':'finished','api_requests':0}))


if __name__=='__main__':main()
