"""Exact cosine retrieval; PostgreSQL JSON storage pending native pgvector build."""

import math
import re

import httpx
from sqlalchemy import select

from lerny.config import settings
from lerny.models import Chunk, Material, MaterialVersion

EMBED_MODEL = "qwen3-embedding:0.6b"


def embed(texts):
    with httpx.Client(timeout=120, trust_env=False) as client:
        result = client.post(
            settings().model_url + "/api/embed",
            json={
                "model": EMBED_MODEL,
                "input": texts,
                "truncate": False,
            },
        )
        result.raise_for_status()
        vectors = result.json()["embeddings"]
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


def search_public(session, course_id, question):
    rows = session.execute(
        select(Chunk, Material, MaterialVersion)
        .join(MaterialVersion, Chunk.version_id == MaterialVersion.id)
        .join(Material, MaterialVersion.material_id == Material.id)
        .where(
            Material.course_id == course_id,
            Material.visibility == "public",
            Material.deleted.is_(False),
            Material.active_version_id == MaterialVersion.id,
            MaterialVersion.status == "ready",
            Chunk.embedding_model == EMBED_MODEL,
        )
    ).all()
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
    return [lookup[key] for key in sorted(scores, key=scores.get, reverse=True)[:4]]


def internal_validation_context(session, course_id, question):
    """Private opt-in material is usable only inside validation/grading tasks."""
    rows = session.execute(
        select(Chunk, Material, MaterialVersion)
        .join(MaterialVersion, Chunk.version_id == MaterialVersion.id)
        .join(Material, MaterialVersion.material_id == Material.id)
        .where(
            Material.course_id == course_id,
            Material.visibility == "private",
            Material.internal_use == "validation_grading",
            Material.deleted.is_(False),
            Material.active_version_id == MaterialVersion.id,
            MaterialVersion.status == "ready",
            Chunk.embedding_model == EMBED_MODEL,
        )
    ).all()
    if not rows:
        return []
    vector = embed(["Instruct: Retrieve assessment reference material.\nQuery: " + question])[0]
    ranked = sorted(rows, key=lambda row: cosine(vector, row[0].embedding or []), reverse=True)
    return [row[0].content for row in ranked[:2]]
