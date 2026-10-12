"""Local synthetic E2E fixture; no real professor/student records or cloud calls."""

import json
import secrets
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from lerny.config import settings
from lerny.db import engine
from lerny.models import User
from lerny.security import hasher

root = settings().runtime_root
path = root / "secrets/demo-accounts.json"
if path.exists():
    accounts = json.loads(path.read_text(encoding="utf-8"))
else:
    accounts = {role: {"login_id": "demo_" + role, "password": secrets.token_urlsafe(24)} for role in ("teacher", "student")}
    path.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), encoding="utf-8")
with Session(engine()) as db:
    for role, account in accounts.items():
        if not db.scalar(select(User).where(User.login_id == account["login_id"])):
            db.add(User(login_id=account["login_id"], display_name="체험용 " + ("교수" if role == "teacher" else "학생"), role=role, password_hash=hasher.hash(account["password"])))
    db.commit()

client = httpx.Client(base_url="http://127.0.0.1:8000/api/v1", timeout=30, trust_env=False)
def call(method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json()
def login(role):
    result = call("POST", "/auth/login", json=accounts[role])
    client.headers["X-CSRF-Token"] = result["csrf_token"]
def wait_job(job_id):
    started = time.monotonic()
    while time.monotonic() - started < 600:
        job = call("GET", "/jobs/" + job_id)
        if job["status"] in ("succeeded", "failed", "cancelled"):
            print("job", job["kind"], job["status"], job.get("error"), flush=True)
            return job
        time.sleep(2)
    raise RuntimeError("job timeout")

login("teacher")
term = call("POST", "/terms", json={"name": "개발 검증용 학기", "starts_on": "2026-01-01", "ends_on": "2099-12-31"})
course = call("POST", "/courses", json={"term_id": term["id"], "title": "[체험] 자료구조 — 합성 강의 자료", "teaching_language": "python"})
section = call("POST", f"/courses/{course['id']}/sections", json={"title": "체험 1분반"})
concept = call("POST", f"/courses/{course['id']}/concepts", json={"name": "큐", "description": "선입선출과 삽입·삭제"})
call("PUT", f"/sections/{section['id']}/progress", headers={"If-Match": str(section["revision"])}, json={"concept_ids": [concept["id"]]})
lecture = """개발 검증용 합성 강의 자료 — 실제 교수의 강의가 아닙니다.
큐(queue)는 먼저 들어온 원소가 먼저 나오는 선입선출(FIFO) 자료구조입니다.
큐의 삽입 연산은 enqueue이고, 뒤쪽(rear)에 원소를 추가합니다.
큐의 삭제 연산은 dequeue이고, 앞쪽(front)의 원소를 꺼냅니다.
빈 큐에 A, B, C를 차례로 삽입한 뒤 한 번 삭제하면 A가 나옵니다. 남는 순서는 B, C입니다.
큐가 비었을 때 삭제를 시도하면 원소를 꺼낼 수 없으므로 빈 상태를 먼저 확인해야 합니다.
스택은 나중에 들어온 원소가 먼저 나오는 후입선출(LIFO) 자료구조입니다.
큐와 스택은 원소를 꺼내는 순서가 다릅니다.
"""
upload = call("POST", f"/courses/{course['id']}/materials", data={"kind":"lecture", "week":"1", "visibility":"public", "internal_use":"none"}, files={"file": ("sample-queue.txt", lecture.encode(), "text/plain")})
print("uploaded synthetic lecture", flush=True)
extraction = wait_job(upload["processing_job_id"])
assert extraction["status"] == "succeeded", extraction
code = call("POST", f"/sections/{section['id']}/join-code", json={})["join_code"]
generation = call("POST", f"/courses/{course['id']}/questions/generate", headers={"Idempotency-Key": secrets.token_hex(16)}, json={"concept_id":concept["id"]})
generated = wait_job(generation["job_id"])
login("student")
call("POST", "/enrollments", json={"join_code": code})
chat = call("POST", f"/sections/{section['id']}/chat/messages", headers={"Idempotency-Key":secrets.token_hex(16)}, json={"message":"큐에 A, B, C를 넣고 한 번 삭제하면 무엇이 나오나요?"})
answered = wait_job(chat["job_id"])
evidence = {"synthetic":True,"course_id":course["id"],"section_id":section["id"],"extraction":extraction,"generation":generated,"chat":answered}
if generated["status"] == "succeeded":
    daily = call("POST", f"/sections/{section['id']}/daily", json={})
    assert daily == call("POST", f"/sections/{section['id']}/daily", json={})
    for q in daily["items"]:
        result = call("POST", f"/learning-sessions/{daily['id']}/questions/{q['id']}/submit", headers={"Idempotency-Key":secrets.token_hex(16)}, json={"answer": "0" if q["kind"] == "mcq" else "큐는 선입선출로 먼저 들어온 원소가 먼저 나옵니다. enqueue는 rear에 삽입하고 dequeue는 front에서 삭제합니다. A, B, C를 삽입한 후 삭제하면 A가 나오고 B, C가 남습니다. 빈 큐에서는 원소를 꺼낼 수 없으므로 빈 상태를 먼저 확인합니다."})
        if result["job_id"]:
            wait_job(result["job_id"])
    evidence["daily"] = call("POST", f"/sections/{section['id']}/daily", json={})
login("teacher")
evidence["analytics"] = call("GET", f"/sections/{section['id']}/analytics")
out = root / "evidence/local-learning-smoke.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
print("Evidence saved:", out, flush=True)
