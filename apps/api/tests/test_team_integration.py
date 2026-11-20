"""Latest ZIP -> native extraction -> versioned service -> UI contract, without live APIs."""
import hashlib

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from lerny import worker
from lerny.config import settings
from lerny.models import Chunk, Job, MaterialVersion
from lerny.team_engine import native_document
from lerny.team_ingestion import report_path
from sqlalchemy import select
from test_gemini_integration import configured, integration  # noqa: F401
from test_lecture_specs import api  # noqa: F401


def test_native_upload_preserves_whole_code_and_holds_tables(integration, tmp_path):  # noqa: F811 -- pytest fixture
    client, session, _ = integration
    folder = settings().runtime_root / "data/files"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "team-source.docx"
    document = Document()
    code = document.styles.add_style("Code", WD_STYLE_TYPE.PARAGRAPH)
    code.font.name = "Courier New"
    original = "def push(stack, item):\n    stack.append(item)\n    return stack"
    document.add_paragraph(original, style="Code")
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "HELD_TABLE_NOT_FOR_GENERATION"
    document.save(path)
    version = session.get(MaterialVersion, "version")
    version.filename, version.object_key = path.name, path.name
    version.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    job = Job(owner_id="teacher", course_id="course", kind="extract", payload={"version_id": version.id})
    session.add(job)
    session.flush()
    result = worker.extract_job(session, job)
    assert result["engine"] == "team-20261115" and result["held_count"] > 0
    chunks = list(session.scalars(select(Chunk).where(Chunk.version_id == version.id)))
    assert len(chunks) == 1 and original in chunks[0].content
    assert chunks[0].locator["engine"]["code_text"].rstrip("\n") == original
    assert "HELD_TABLE_NOT_FOR_GENERATION" not in version.extracted_text
    assert report_path(version.id).is_file()
    review = client.get("/api/v1/materials/material/extraction-review")
    assert review.status_code == 200 and review.json()["held_count"] > 0
    processing=client.get('/api/v1/courses/course/processing')
    assert processing.status_code==200
    assert result["status"] == "extracted"
    assert session.scalar(select(Job).where(Job.kind == "embed")) is not None


def test_native_source_hash_is_checked_before_db_replacement(integration):  # noqa: F811 -- pytest fixture
    _, session, _ = integration
    path = settings().runtime_root / "data/files/bad.docx"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    doc.add_paragraph("Synthetic content")
    doc.save(path)
    version = session.get(MaterialVersion, "version")
    version.filename = version.object_key = path.name
    before = list(session.scalars(select(Chunk.id)))
    job = Job(owner_id="teacher", course_id="course", kind="extract", payload={"version_id": version.id})
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        worker.extract_job(session, job)
    assert list(session.scalars(select(Chunk.id))) == before


def test_python_structural_chunks_never_execute_source(tmp_path):
    marker = tmp_path / "must-not-exist"
    path = tmp_path / "source.py"
    path.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n\ndef push(stack, item):\n    stack.append(item)\n", encoding="utf-8")
    document, chunks, _, analysis = native_document(path)
    assert not marker.exists() and analysis["executed"] is False
    assert chunks and all(c["quality"] == "source_code_structure_checked" for c in chunks)
    assert document["source_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_engine_never_broadens_empty_course_or_concept_filter(tmp_path):
    from rag_mvp.unified_rag import UnifiedMultimodalRAG
    corpus = {"chunks": [{"id": "foreign", "course_id": "other", "text": "stack", "title": "stack"}]}
    engine = UnifiedMultimodalRAG(tmp_path, corpus=corpus, course_id="requested")
    assert engine.retrieve("stack") == []
    engine = UnifiedMultimodalRAG(tmp_path, corpus=corpus, course_id="other")
    assert engine.retrieve("stack", concept_id="missing") == []


def test_env_file_does_not_enable_network_or_override_process_key(tmp_path, monkeypatch):
    from lerny.config import settings
    env = tmp_path / "team.env"
    env.write_text("GEMINI_API_KEY=synthetic-private-key\nGEMINI_MODEL=synthetic-model\nLERNY_GEMINI_CALLS_ENABLED=true\n", encoding="utf-8")
    monkeypatch.setenv("LERNY_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setenv("LERNY_ENV_FILE", str(env))
    settings.cache_clear()
    try:
        config = settings()
        assert not config.gemini_calls_enabled
        assert config.gemini_api_key.get_secret_value() == "synthetic-private-key"
        assert config.gemini_answer_model == "synthetic-model"
        monkeypatch.setenv("LERNY_GEMINI_API_KEY", "process-test-key")
        settings.cache_clear()
        assert settings().gemini_api_key.get_secret_value() == "process-test-key"
    finally:
        settings.cache_clear()
