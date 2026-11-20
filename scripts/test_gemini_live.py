"""Opt-in live Gemini smoke test using selected real PPTX pages and an isolated SQLite DB."""

import argparse
import hashlib
import json
import os
import secrets
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps/api"))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--slides", required=True, nargs="+", type=int)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--enable-api-calls", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    root = args.output_dir.resolve()
    if root.is_relative_to(REPO) or not args.source.is_file():
        parser.error("Use an existing source and an output directory outside the repository.")
    if not args.enable_api_calls or not os.environ.get("LERNY_GEMINI_API_KEY"):
        parser.error("A process key and --enable-api-calls are required.")
    if root.exists() and not args.resume:
        parser.error("Output already exists. Use --resume to reuse completed jobs and the index.")
    if not 1 <= len(set(args.slides)) <= 8:
        parser.error("Select between one and eight slides.")
    os.environ.update(
        LERNY_RUNTIME_ROOT=str(root / "runtime"),
        LERNY_AI_PROVIDER="gemini",
        LERNY_GEMINI_CALLS_ENABLED="true",
        LERNY_GEMINI_MAX_CALLS_PER_JOB="16",
        LERNY_DEPLOYMENT="local",
        LERNY_COOKIE_SECURE="false",
    )
    root.mkdir(parents=True, exist_ok=True)
    import httpx
    from fastapi.testclient import TestClient
    from lerny import db, worker
    from lerny.main import create_app
    from lerny.models import (
        Base,
        Chunk,
        Concept,
        Course,
        Enrollment,
        Job,
        Material,
        MaterialVersion,
        Section,
        Term,
        User,
    )
    from lerny.security import hasher
    from pptx import Presentation
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    deck = Presentation(args.source)
    pages = []
    for number in sorted(set(args.slides)):
        if not 1 <= number <= len(deck.slides):
            parser.error("Slide number outside the source deck.")
        text = "\n".join(s.text for s in deck.slides[number - 1].shapes if s.has_text_frame)
        if not text.strip():
            parser.error("Selected slide has no selectable text; visually review it separately.")
        pages.append({"slide": number, "text": text})
    source = {
        "path": str(args.source.resolve()),
        "sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "pages": pages,
        "question": args.question,
        "objective": args.objective,
        "title": args.title,
    }
    source_path = root / "source.json"
    if source_path.exists() and json.loads(source_path.read_text(encoding="utf-8")) != source:
        parser.error("The source or test inputs changed. Use a separate output directory.")
    save(source_path, source)
    sql_engine = create_engine(
        "sqlite:///" + (root / "test.sqlite3").as_posix(),
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(sql_engine, "connect")
    def sqlite_test_lock(connection, _):
        # The smoke test is strictly sequential. PostgreSQL concurrency is not tested here.
        connection.create_function("pg_advisory_xact_lock", 1, lambda _value: None)

    Base.metadata.create_all(sql_engine)
    password = secrets.token_urlsafe(32)
    with Session(sql_engine) as session:
        if session.get(Course, "live-course") is None:
            for role in ("teacher", "student"):
                session.add(
                    User(
                        id="live-" + role,
                        login_id="live-" + role,
                        display_name="Live test " + role,
                        password_hash=hasher.hash(password),
                        role=role,
                    )
                )
            session.add(
                Term(
                    id="live-term",
                    name="Isolated live test",
                    starts_on=date(2026, 1, 1),
                    ends_on=date(2026, 12, 31),
                )
            )
            session.flush()
            session.add(
                Course(
                    id="live-course",
                    term_id="live-term",
                    title="Gemini real-source test",
                    lead_teacher_id="live-teacher",
                    teaching_language="python",
                )
            )
            session.flush()
            session.add(Section(id="live-section", course_id="live-course", title="Isolated test"))
            session.add(Concept(id="live-concept", course_id="live-course", name=args.title))
            session.add(
                Material(
                    id="live-material",
                    course_id="live-course",
                    title=args.source.stem,
                    kind="pptx",
                    week=12,
                    visibility="public",
                    internal_use="none",
                    active_version_id="live-version",
                )
            )
            session.flush()
            session.add(
                Enrollment(
                    student_id="live-student",
                    course_id="live-course",
                    section_id="live-section",
                    status="active",
                )
            )
            session.add(
                MaterialVersion(
                    id="live-version",
                    material_id="live-material",
                    version_no=1,
                    filename=args.source.name,
                    object_key="external-read-only-original",
                    sha256=source["sha256"],
                    status="ready",
                )
            )
            session.flush()
            for page in pages:
                session.add(
                    Chunk(
                        id=f"real-slide-{page['slide']}",
                        version_id="live-version",
                        content=page["text"],
                        locator={"slide": page["slide"], "page": page["slide"]},
                    )
                )
        else:
            for role in ("teacher", "student"):
                session.get(User, "live-" + role).password_hash = hasher.hash(password)
        session.commit()
    db.engine = worker.engine = lambda: sql_engine

    calls_path = root / "calls.json"
    calls = json.loads(calls_path.read_text(encoding="utf-8")) if calls_path.exists() else []
    original_transport = httpx.HTTPTransport.handle_request

    def guarded_transport(transport, request):
        if request.url.host != "generativelanguage.googleapis.com" or request.url.scheme != "https":
            raise ValueError("LIVE_TEST_UNEXPECTED_EXTERNAL_ENDPOINT")
        if len(calls) >= 20:
            raise ValueError("LIVE_TEST_TOTAL_CALL_LIMIT")
        record = {"path": request.url.path, "state": "submitting"}
        calls.append(record)
        save(calls_path, calls)
        try:
            response = original_transport(transport, request)
            response.read()
            record.update(state="received", status=response.status_code)
            payload = response.json()
            record["usage"] = payload.get("usage", payload.get("usageMetadata"))
            if not response.is_success:
                record["error"] = json.dumps(payload.get("error", {}), ensure_ascii=False).replace(
                    os.environ["LERNY_GEMINI_API_KEY"], "[REDACTED]"
                )[:1200]
            save(calls_path, calls)
            return response
        except Exception as exc:
            record["exception"] = type(exc).__name__
            save(calls_path, calls)
            raise

    httpx.HTTPTransport.handle_request = guarded_transport
    report_path = root / "result.json"
    report = (
        json.loads(report_path.read_text(encoding="utf-8"))
        if report_path.exists()
        else {
            "source_file": str(args.source.resolve()),
            "slides": args.slides,
            "database": "isolated SQLite; existing PostgreSQL unchanged",
            "api_transport": "in-process FastAPI; external Gemini HTTP is live",
            "video_generated": False,
            "steps": {},
        }
    )

    def step(client, name, endpoint, body=None):
        previous = report["steps"].get(name)
        if previous:
            job_id = previous["job_id"]
        else:
            response = client.post(endpoint, json=body, headers={"Idempotency-Key": "live-" + name})
            if response.status_code != 202:
                raise RuntimeError(f"{name}: enqueue HTTP {response.status_code}")
            job_id = response.json()["job_id"]
            report["steps"][name] = {"job_id": job_id}
            save(report_path, report)
        with Session(sql_engine) as session:
            state = session.get(Job, job_id).status
        if state == "failed":
            raise RuntimeError(f"{name}: previous failed job requires explicit investigation")
        if state != "succeeded":
            worker.run_once(job_id)
        with Session(sql_engine) as session:
            job = session.get(Job, job_id)
            report["steps"][name].update(
                status=job.status, error_code=job.error_code, result=job.result
            )
            save(report_path, report)
            print(
                json.dumps({"step": name, "status": job.status, "error_code": job.error_code}),
                flush=True,
            )
            if job.status != "succeeded":
                raise RuntimeError(name + ": worker did not succeed")
            return job.result, job_id

    def login(client, role):
        response = client.post(
            "/api/v1/auth/login", json={"login_id": "live-" + role, "password": password}
        )
        if response.status_code != 200:
            raise RuntimeError("Isolated test login failed")
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]

    try:
        with TestClient(create_app()) as client:
            login(client, "teacher")
            result, _ = step(client, "index", "/api/v1/courses/live-course/rag/reindex")
            if not result["index_ready"]:
                raise RuntimeError("Index incomplete")
            login(client, "student")
            answer, _ = step(
                client,
                "answer",
                "/api/v1/sections/live-section/chat/messages",
                {"message": args.question},
            )
            login(client, "teacher")
            lesson, job_id = step(
                client,
                "lesson",
                "/api/v1/courses/live-course/narration-lessons",
                {
                    "concept_id": "live-concept",
                    "learning_objective": args.objective,
                    "target_duration_seconds": 65,
                },
            )
            preview = client.get("/api/v1/courses/live-course/narration-lessons/" + job_id)
            report["preview_status"] = preview.status_code
            report["request_prepared"] = "video_plan" in preview.json()
            report["answer_grounded"] = answer.get("answer_kind") == "grounded"
            report["lesson_reviewed"] = lesson.get("validation") == "model_reviewed"
            report["completed"] = report["answer_grounded"] and report["lesson_reviewed"]
    except Exception as exc:
        report["completed"] = False
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)[:300]}
        raise
    finally:
        report["api_calls"] = len(calls)
        save(report_path, report)
        httpx.HTTPTransport.handle_request = original_transport
        sql_engine.dispose()
    print(
        json.dumps(
            {"completed": report["completed"], "api_calls": len(calls), "video_generated": False}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()

