import importlib.util
import json
import os
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from lerny.config import Settings

AWS = Path(__file__).resolve().parents[3] / "deploy/aws"
spec = importlib.util.spec_from_file_location("worker_policy_manager", AWS / "manage.py")
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)

POLICY = {"LERNY_GEMINI_REVIEW_QUOTA_PROJECT": "lerny-paid-embedding",
          "LERNY_GEMINI_REVIEW_COURSE_ID": "course", "LERNY_GEMINI_REVIEW_WEEK": "4",
          "LERNY_INSTRUCTOR_REVIEW_FROM_WEEK": "5", "LERNY_GEMINI_PAID_FROM_WEEK": "5",
          "LERNY_GEMINI_PAID_UPLOADS_SINCE": "2026-11-22T03:07:10+00:00",
          "LERNY_GEMINI_REVIEW_REQUESTS_PER_MINUTE": "60", "LERNY_GEMINI_EMBEDDING_REQUESTS_PER_MINUTE": "120"}


@pytest.mark.parametrize("role", ["embedding", "interactive"])
def test_configuration_and_clean_ssm_only_launcher(tmp_path, monkeypatch, role):
    base = {k:"fixture" for k in ("DATABASE_URL","SUPABASE_URL","SUPABASE_SECRET_KEY",
                                  "GEMINI_EMBEDDING_API_KEY","GEMINI_CONTENT_API_KEY")}
    env = tmp_path / "test.env"
    env.write_text("\n".join(f"{k}={v}" for k,v in {**base,**POLICY}.items()), encoding="utf-8")
    configured = manage.configuration(env, tmp_path)
    assert {k:configured[k] for k in POLICY} == POLICY
    assert not POLICY.keys() & manage.configuration(env,tmp_path,worker=False).keys()
    worker_json = tmp_path / "worker.json"
    worker_json.write_text(json.dumps(configured))
    original_read = Path.read_text
    def read(path, *args, **kwargs):
        return original_read(worker_json if path.as_posix() == "/etc/lerny/worker.json" else path, *args, **kwargs)
    monkeypatch.setattr(Path,"read_text",read)
    monkeypatch.setattr(os,"environ",{})
    monkeypatch.setattr(sys,"argv",["start_worker.py",role])
    monkeypatch.setitem(sys.modules,"pwd",SimpleNamespace(getpwnam=lambda _:SimpleNamespace(
        pw_name="fixture",pw_uid=12,pw_gid=12,pw_dir=str(tmp_path))))
    for name in ("setuid","setgid","initgroups","chdir"):
        monkeypatch.setattr(os,name,lambda *_:None,raising=False)
    captured = []
    monkeypatch.setattr(os,"execv",lambda _,argv:captured.append(argv))
    runpy.run_path(str(AWS/"start_worker.py"))
    assert captured[0][-2:] == ["lerny.material_daemon",role]
    config = Settings(**{k.removeprefix("LERNY_").lower():os.environ[k] for k in POLICY})
    assert config.paid_upload_week("course",5) and not config.paid_upload_week("course",4)
    assert config.gemini_review_requests_per_minute == 60 and config.gemini_embedding_requests_per_minute == 120
    assert config.gemini_content_requests_per_minute == 12


def test_policy_plan_preserves_unrelated_values_and_kms_metadata(capsys):
    old = {"unrelated":"sensitive-fixture","LERNY_GEMINI_CALLS_ENABLED":"false"}
    writes = []
    fake = SimpleNamespace(
        get_parameter=lambda **k:{"Parameter":{"Value":json.dumps(old),"Type":"SecureString","Version":11}},
        describe_parameters=lambda **k:{"Parameters":[{"Version":11,"Tier":"Standard","KeyId":"test-key"}]},
        put_parameter=lambda **k:writes.append(k) or {"Version":12})
    manage.update_worker_policy(fake,POLICY,11)
    assert writes == []
    for patch,version in [(POLICY,12),({"UNRELATED":"x"},11)]:
        with pytest.raises(ValueError):
            manage.update_worker_policy(fake,patch,version,apply=True)
    manage.update_worker_policy(fake,POLICY,11,apply=True)
    assert len(writes)==1 and writes[0]["KeyId"]=="test-key"
    assert json.loads(writes[0]["Value"]) == {**old,**POLICY}
    assert "sensitive-fixture" not in capsys.readouterr().out


def test_windows_release_matches_linux_engine_bytes(tmp_path):
    import io
    import tarfile
    source = tmp_path / "apps/api/video_extraction/shared/gemini.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"# fixture\r\n")
    binary = source.with_suffix(".png")
    binary.write_bytes(b"fixture\r\n")
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as out:
        for path in (source, binary):
            manage.add_release_file(out, path, tmp_path)
    archive.seek(0)
    with tarfile.open(fileobj=archive) as out:
        assert out.extractfile(source.relative_to(tmp_path).as_posix()).read() == b"# fixture\n"
        assert out.extractfile(binary.relative_to(tmp_path).as_posix()).read() == b"fixture\r\n"
