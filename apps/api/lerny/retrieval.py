"""Exact cosine retrieval; PostgreSQL JSON storage pending native pgvector build."""

import math
import re

from sqlalchemy import select
from sqlalchemy.orm import defer

from lerny.config import settings
from lerny.inference import perform
from lerny.models import Chunk, Material, MaterialVersion

EMBED_MODEL = "qwen3-embedding:0.6b"


def embed(texts):
    from lerny.gemini_provider import EMBED_MODEL as GEMINI_EMBED_MODEL
    result = perform("embed", {
                "model": GEMINI_EMBED_MODEL if settings().ai_provider == "gemini" else EMBED_MODEL,
                "input": texts,
                "truncate": False,
            })
    vectors = result["embeddings"]
    if len(vectors) != len(texts) or any(
        not v or any(not math.isfinite(x) for x in v) for v in vectors
    ):
        raise ValueError("INVALID_EMBEDDING")
    return vectors


def cosine(a, b):
    if len(a) != len(b):
        return -1
    norm = math.sqrt(sum(x * x for x in a) * sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else -1


def search_public(session, course_id, question, *, version_id=None, version_ids=None, max_week=None, published_only=False, limit=4):
    if type(limit) is not int or not 1 <= limit <= 12:
        raise ValueError("INVALID_RETRIEVAL_LIMIT")
    if settings().ai_provider == "gemini":
        return search_gemini(session, course_id, question, version_id=version_id, version_ids=version_ids, max_week=max_week, published_only=published_only, limit=limit)
    rows = [r for r in public_rows(session,course_id,version_ids=version_ids,published_only=published_only)
            if r[0].embedding_model == EMBED_MODEL]
    rows = [r for r in rows if (version_id is None or r[2].id == version_id)
            and (max_week is None or r[1].week <= max_week)]
    if not rows:
        return []
    vector = embed(
        [
            "Instruct: Retrieve passages from lecture notes that answer the question.\nQuery: "
            + question
        ]
    )[0]
    terms = set(re.findall(r"\w+", question.lower()))
    semantic = sorted(rows, key=lambda r: cosine(vector, r[0].embedding or []), reverse=True)[:20]
    keyword = sorted(
        rows,
        key=lambda r: sum(r[0].content.lower().count(t) for t in terms if len(t) > 1),
        reverse=True,
    )
    keyword = [r for r in keyword if any(t in r[0].content.lower() for t in terms if len(t) > 1)][
        :20
    ]
    scores = {}
    lookup = {r[0].id: r for r in rows}
    for ranking in (semantic, keyword):
        for index, row in enumerate(ranking):
            scores[row[0].id] = scores.get(row[0].id, 0) + 1 / (60 + index + 1)
    return [lookup[key] for key in sorted(scores, key=scores.get, reverse=True)[:limit]]


def internal_validation_context(session, course_id, question, source_ids=None):
    """Locally select bounded answer-key excerpts; never embed them or expose as citations.

    Callers are validation/grading handlers, never student content generators.
    Restrict to the weeks of the public evidence when provided. Selection itself is offline;
    the actual model call still goes through the provider's disabled-call guard.
    """
    query = (
        select(Chunk, Material, MaterialVersion)
        .options(defer(MaterialVersion.extraction_report), defer(MaterialVersion.extracted_text))
        .join(MaterialVersion, Chunk.version_id == MaterialVersion.id)
        .join(Material, MaterialVersion.material_id == Material.id)
        .where(
            Material.course_id == course_id,
            Material.kind == "answer",
            Material.internal_use == "validation_grading",
            Material.deleted.is_(False),
            Material.active_version_id == MaterialVersion.id,
            MaterialVersion.status == "ready",
        )
    )
    if source_ids is not None:
        weeks = session.scalars(
            select(Material.week)
            .join(MaterialVersion, Material.active_version_id == MaterialVersion.id)
            .join(Chunk, Chunk.version_id == MaterialVersion.id)
            .where(Material.course_id == course_id, Chunk.id.in_(source_ids),
                   Material.visibility == "public", Material.internal_use == "none",
                   Material.kind != "answer", Material.deleted.is_(False),
                   MaterialVersion.status == "ready")
        ).all()
        if not weeks:
            return []
        query = query.where(Material.week.in_(weeks))
    # Positive keyword overlap only: do not fall back to unrelated answer sheets.
    stop = {"the", "and", "for", "are", "자료", "정답", "해설", "채점", "기준", "설명"}
    terms = {t for t in re.findall(r"\w+", question.lower()) if len(t) > 1 and t not in stop}
    ranked = []
    for chunk, material, _ in session.execute(query.order_by(Chunk.id)):
        content = (material.title + " " + chunk.content).lower()
        score = sum(1 for term in terms if term in content)
        if score:
            ranked.append((score, chunk.id, chunk.content[:1800]))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [content for _, _, content in ranked[:4]]


def public_rows(session, course_id, *, version_ids=None, published_only=False):
    if published_only:
        from lerny.weekly_content import published_version_ids
        published = published_version_ids(session, course_id)
        version_ids = published if version_ids is None else published & set(version_ids)
    query = (select(Chunk, Material, MaterialVersion)
        # OCR reports belong to a whole version. Joining them once per chunk can
        # expand a 1 MB report into hundreds of MB before ORM deduplication.
        .options(defer(MaterialVersion.extraction_report), defer(MaterialVersion.extracted_text))
        .join(MaterialVersion, Chunk.version_id == MaterialVersion.id)
        .join(Material, MaterialVersion.material_id == Material.id)
        .where(Material.course_id == course_id, Material.visibility == "public",
               Material.internal_use == "none", Material.kind != "answer", Material.deleted.is_(False),
               MaterialVersion.status == "ready"))
    query = query.where(Material.active_version_id == MaterialVersion.id) if version_ids is None else query.where(MaterialVersion.id.in_(version_ids))
    return session.execute(query.order_by(Chunk.id)).all()


def search_gemini(session, course_id, question, *, version_id=None, version_ids=None, max_week=None, published_only=False, limit=4):
    from lerny.rag_index import indexed_ids, load_vector, shared_semantic
    from lerny.team_engine import make_engine

    rows = public_rows(session, course_id, version_ids=version_ids, published_only=published_only)
    rows = [r for r in rows if (version_id is None or r[2].id == version_id)
            and (max_week is None or r[1].week <= max_week)]
    if not rows:
        return []
    semantic_search = None
    vector_map = None
    if settings().rag_storage == "supabase":
        if len(indexed_ids(row[0] for row in rows)) != len(rows):
            raise ValueError("GEMINI_INDEX_REQUIRED")
        semantic_search = shared_semantic
    else:
        vectors = [load_vector(row[0]) for row in rows]
        # Do not silently answer from a partial or stale index.
        if any(vector is None for vector in vectors):
            raise ValueError("GEMINI_INDEX_REQUIRED")
        vector_map = {row[0].id: vector for row, vector in zip(rows, vectors, strict=True)}
    engine = make_engine(rows, course_id, vectors=vector_map, semantic_search=semantic_search,
                         query_embed=lambda query: perform("embed", {"input": [query], "task": "query"})["embeddings"][0])
    lookup = {row[0].id: row for row in rows}
    return [lookup[hit["id"]] for hit in engine.retrieve(question, top_k=limit)]
