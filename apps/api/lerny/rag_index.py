"""Selectable shared/local Gemini vectors; material permissions remain authoritative."""

import json
import math
import re
import unicodedata
from collections import Counter

from lerny.config import settings
from lerny.gemini_provider import PROFILE, fingerprint, normalized_vector, save_json


def source_hash(chunk):
    return fingerprint(
        {"text": chunk.content, "locator": chunk.locator, "version": chunk.version_id}
    )


def vector_path(chunk):
    return settings().runtime_root / "rag-indexes" / PROFILE / (fingerprint(chunk.id) + ".json")


def store_vector(chunk, vector):
    if settings().rag_storage == "supabase":
        shared_store().put(chunk.content, vector)
        return
    save_json(
        vector_path(chunk),
        {
            "profile": PROFILE,
            "source_hash": source_hash(chunk),
            "vector": normalized_vector(vector),
        },
    )


def load_local_vector(chunk):
    path = vector_path(chunk)
    if not path.is_file():
        return None
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry["profile"] != PROFILE or entry["source_hash"] != source_hash(chunk):
            return None
        return normalized_vector(entry["vector"])
    except (ValueError, KeyError, TypeError, OSError):
        return None


def shared_store():
    from rag_mvp.shared_vectors import SharedVectors
    config = settings()
    return SharedVectors(config.supabase_url, config.supabase_service_key.get_secret_value())


def load_vector(chunk):
    if settings().rag_storage == "local":
        return load_local_vector(chunk)
    from rag_mvp.shared_vectors import document_key
    key = document_key(chunk.content)
    return shared_store().fetch([key]).get(key)


def indexed_ids(chunks, *, validate_vectors=False):
    chunks = list(chunks)
    if settings().rag_storage == "local":
        return {chunk.id for chunk in chunks if load_local_vector(chunk) is not None}
    from rag_mvp.shared_vectors import document_key
    keys = {chunk.id: document_key(chunk.content) for chunk in chunks}
    found = shared_store().fetch(keys.values(), include_vectors=validate_vectors)
    return {key for key, value in keys.items() if value in found}


def shared_semantic(selected, query_vector, limit):
    from rag_mvp.shared_vectors import document_key
    keys = {item["id"]: document_key(item["text"]) for item in selected}
    hits = shared_store().match(keys.values(), query_vector, limit=limit)
    scores = {hit["input_hash"]: hit["score"] for hit in hits}
    rows = [{"id": key, "vector_score": scores[value]}
            for key, value in keys.items() if value in scores]
    return sorted(rows, key=lambda row: (-row["vector_score"], row["id"]))[:limit]


def tokens(value):
    # Preserve source text and operators; this normalization is for ranking only.
    words = re.findall(r"[a-z_]+|[가-힣]+|\d+", unicodedata.normalize("NFC", value).lower())
    result = []
    for word in words:
        result.append(word)
        if re.fullmatch("[가-힣]+", word) and len(word) > 2:
            result.extend(word[i : i + 2] for i in range(len(word) - 1))
    return result


def hybrid_rank(rows, vectors, query, query_vector):
    """Teammate BM25 + reciprocal rank fusion, scoped to pre-authorized DB rows."""
    counts = [Counter(tokens(row[1].title + "\n" + row[0].content)) for row in rows]
    average = sum(sum(c.values()) for c in counts) / max(1, len(counts))
    terms = set(tokens(query))
    frequencies = Counter(word for count in counts for word in terms if count[word])
    keyword = []
    for i, count in enumerate(counts):
        score = 0.0
        for word in terms:
            if count[word]:
                frequency = frequencies[word]
                idf = math.log(1 + (len(counts) - frequency + 0.5) / (frequency + 0.5))
                score += (
                    idf
                    * count[word]
                    * 2.5
                    / (count[word] + 1.5 * (0.25 + 0.75 * sum(count.values()) / max(1, average)))
                )
        if score > 0:
            keyword.append((i, score))
    semantic = sorted(
        range(len(rows)),
        key=lambda i: (
            -sum(a * b for a, b in zip(query_vector, vectors[i], strict=True)),
            rows[i][0].id,
        ),
    )[:8]
    lexical = [i for i, _ in sorted(keyword, key=lambda p: (-p[1], rows[p[0]][0].id))[:8]]
    scores = {}
    for ranking in (semantic, lexical):
        for rank, index in enumerate(ranking, 1):
            scores[index] = scores.get(index, 0) + 1 / (60 + rank)
    return [rows[i] for i in sorted(scores, key=lambda i: (-scores[i], rows[i][0].id))[:4]]
