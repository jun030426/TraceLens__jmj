"""Exercise the real unpaid job handler on disposable localhost PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import hashlib

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from lerny.config import settings
from lerny.models import Base, Course, Job, Material, MaterialVersion, Term, User


def test_concurrent_preview_opens_and_worker_with_paid_calls_disabled(monkeypatch, tmp_path):
    from lerny import material_previews, worker
    url = settings().database_url
    engine = create_engine(url)
    assert engine.url.database == "lerny_test" and engine.url.host in {"127.0.0.1", "localhost"}
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    original = b"Offline handout\nOriginal stays unchanged."
    source = tmp_path / "data/files/lecture.txt"
    source.parent.mkdir(parents=True); source.write_bytes(original)
    monkeypatch.setenv("LERNY_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setenv("LERNY_AI_PROVIDER", "gemini")
    monkeypatch.setenv("LERNY_GEMINI_CALLS_ENABLED", "false")
    settings.cache_clear()
    monkeypatch.setattr(worker, "engine", lambda: engine)
    def no_model(*a, **k): raise AssertionError("No model call allowed")
    monkeypatch.setattr(worker, "model_json", no_model)
    try:
        with Session(engine) as db:
            db.add(User(id="teacher", login_id="teacher", display_name="test", role="teacher", password_hash="unused"))
            db.add(Term(id="term", name="test", starts_on=date(2026,1,1), ends_on=date(2026,12,31))); db.flush()
            db.add(Course(id="course", term_id="term", title="test", lead_teacher_id="teacher", teaching_language="python")); db.flush()
            db.add(Material(id="material", course_id="course", title="test", kind="lecture", week=1, visibility="public", active_version_id="version")); db.flush()
            db.add(MaterialVersion(id="version", material_id="material", version_no=1, filename="lecture.txt", object_key="lecture.txt", sha256=hashlib.sha256(original).hexdigest(), status="ready")); db.commit()
        def open_preview(_):
            with Session(engine) as db:
                return material_previews.ensure_preview(db, db.get(Material, "material"), db.get(MaterialVersion, "version")).id
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = list(pool.map(open_preview, range(2)))
        assert jobs[0] == jobs[1]
        assert worker.run_once(jobs[0])
        with Session(engine) as db:
            job = db.get(Job, jobs[0])
            assert job.status == "succeeded" and job.attempt == 1
            assert job.result["pages"][0]["text"] == original.decode()
            assert len(list(db.scalars(select(Job)))) == 1
            assert db.get(MaterialVersion, "version").status == "ready"
        assert source.read_bytes() == original
    finally:
        settings.cache_clear()
        engine.dispose()
