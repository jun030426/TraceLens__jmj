"""Local lecture RAG MVP. Network calls are run from the user's Terminal."""
#공통 설정. 프로젝트 위치, 결과 저장 위치, 내부 버전을 정의해.
from pathlib import Path

import os
ROOT = Path(os.environ.get('LERNY_ENGINE_ROOT', Path(os.environ.get('LERNY_RUNTIME_ROOT', Path.home() / 'LernyData')) / 'team-engine'))
OUTPUT = ROOT / 'outputs/rag-mvp'
VERSION = 1
