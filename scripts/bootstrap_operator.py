"""Issue the first local operator without printing its password to logs."""
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/api'))
from sqlalchemy import select
from sqlalchemy.orm import Session
from lerny.config import settings
from lerny.db import engine
from lerny.models import User
from lerny.security import hasher

with Session(engine()) as db:
    if not db.scalar(select(User).where(User.role == 'operator')):
        password = secrets.token_urlsafe(20)
        db.add(User(login_id='operator', display_name='운영 담당자', role='operator',
                    password_hash=hasher.hash(password), must_change_password=True))
        db.commit()
        filename = 'initial-cloud-operator.json' if settings().deployment == 'cloud' else 'initial-operator.json'
        path = settings().runtime_root / 'secrets' / filename
        path.write_text(json.dumps({'login_id': 'operator', 'password': password}, indent=2))
        print(f'Initial operator issued. See external secrets/{filename}; change at first login.')
    else:
        print('Operator already exists; credentials were not changed.')
