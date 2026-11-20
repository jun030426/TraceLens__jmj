import argparse
from pathlib import Path
from . import OUTPUT
from .server import serve

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--output',type=Path,default=OUTPUT)
    p.add_argument('--offline',action='store_true')
    args=p.parse_args()
    try:serve(args.output,args.port,args.offline)
    except KeyboardInterrupt:print('\n종료했습니다. 학습 기록은 유지됩니다.')
