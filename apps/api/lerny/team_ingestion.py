"""Connect teammate native extraction to versioned service materials and jobs."""

from sqlalchemy import delete

from lerny.config import settings
from lerny.gemini_provider import save_json
from lerny.models import Chunk, Job
from lerny.storage import source_file
from lerny.team_engine import ENGINE_VERSION, chunk_locator, native_document


def report_path(version_id):
    return settings().runtime_root / "team-engine" / "materials" / version_id / "extraction.json"


def native_extract_job(session, job, version, material):
    with source_file(version) as path:
        document, candidates, held, evidence = native_document(path)
        if path.suffix.lower() == '.pptx':
            from lerny.ppt_pictures import enrich
            candidates, held, evidence = enrich(path, settings().runtime_root/'picture-text',
                                                document, candidates, held, evidence)
    if document["source_sha256"] != version.sha256:
        raise ValueError("SOURCE_CHANGED")
    return publish_extraction(session, job, version, material, document, candidates, held, evidence)


def publish_extraction(session, job, version, material, document, candidates, held, evidence):
    from lerny.worker import activate_version
    if document["source_sha256"] != version.sha256:
        raise ValueError("SOURCE_CHANGED")
    content = "\n\n".join(c["text"] for c in candidates)
    if len(content) > 1_000_000:
        raise ValueError("TEXT_LIMIT")
    # Only the team's selected candidates feed concepts, embeddings and generation.
    # Held source content remains in this staff-only checkpoint, not extracted_text.
    report = {
        "engine": ENGINE_VERSION, "version_id": version.id,
        "source_sha256": document["source_sha256"],
        "usable_chunks": len(candidates), "held_count": len(held),
        "review_queue": held, "native_evidence": evidence,
    }
    version.extraction_report = report
    if settings().deployment == "local":
        save_json(report_path(version.id), report)
    session.execute(delete(Chunk).where(Chunk.version_id == version.id))
    version.extracted_text = content
    version.error_code = None
    if not candidates:
        version.status = "needs_review"
        return {"version_id": version.id, "status": "needs_review", "chunks": 0,
                "held_count": len(held), "engine": ENGINE_VERSION}
    session.add_all(Chunk(version_id=version.id, content=c["text"], locator=chunk_locator(c))
                    for c in candidates)
    if material.visibility != "public" or material.internal_use != "none" or material.kind == "answer":
        result = activate_version(session, job, version, len(candidates))
    else:
        version.status = "extracted"
        session.add(Job(owner_id=job.owner_id, course_id=job.course_id, kind="embed",
                        payload={"version_id": version.id}))
        result = {"version_id": version.id, "status": "extracted", "chunks": len(candidates)}
    return {**result, "held_count": len(held), "engine": ENGINE_VERSION}
