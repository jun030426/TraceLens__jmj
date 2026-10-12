"""Re-check the synthetic fixture without creating more demo classes."""
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from lerny.config import settings

root = settings().runtime_root
accounts = json.loads((root / "secrets/demo-accounts.json").read_text(encoding="utf-8"))
evidence_path = root / "evidence/local-learning-smoke.json"
evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
assert evidence["synthetic"] is True
with httpx.Client(base_url="http://127.0.0.1:8000/api/v1",timeout=30,trust_env=False) as c:
    def call(method,path,**kwargs):
        r=c.request(method,path,**kwargs)
        r.raise_for_status()
        return r.json()
    r=call("POST","/auth/login",json=accounts["student"])
    c.headers["X-CSRF-Token"]=r["csrf_token"]
    daily=call("POST",f"/sections/{evidence['section_id']}/daily",json={})
    for q in daily["items"]:
        a=q.get("attempt")
        if q["kind"] == "essay" and a and a["status"] == "held" and not a["appealed"]:
            job=call("POST",f"/attempts/{a['id']}/appeal",json={})
            started=time.monotonic()
            while time.monotonic()-started<300:
                state=call("GET","/jobs/"+job["job_id"])
                if state["status"] in ("succeeded","failed"):
                    print("assessment",state["status"],state.get("error"),flush=True)
                    evidence["assessment_recheck"]=state
                    break
                time.sleep(2)
    evidence["daily"]=call("POST",f"/sections/{evidence['section_id']}/daily",json={})
    r=call("POST","/auth/login",json=accounts["teacher"])
    c.headers["X-CSRF-Token"]=r["csrf_token"]
    evidence["analytics"]=call("GET",f"/sections/{evidence['section_id']}/analytics")
evidence_path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
print("Synthetic fixture rechecked.",flush=True)
