"""Use the shared store without installing or writing a local LlamaIndex index."""

from video_extraction.shared.common import save

from .shared_vectors import DIMENSIONS, MODEL, PROFILE, document_key
from .source_context import search_text


def keys_for(corpus):
    return {c["id"]: document_key(search_text(c), c["title"]) for c in corpus["chunks"]}


def build_shared(out, corpus, client, store, signature):
    if client.embedding_model != MODEL or client.dimensions != DIMENSIONS:
        raise ValueError("SHARED_EMBEDDING_PROFILE_MISMATCH")
    keys = keys_for(corpus)
    found = store.fetch(keys.values(), include_vectors=False)
    reused = 0
    generated = 0
    for chunk in corpus["chunks"]:
        key = keys[chunk["id"]]
        if key in found:
            reused += 1
            continue
        text = search_text(chunk)
        vector = client.embed(text, title=chunk["title"])
        store.put(text, vector, title=chunk["title"])
        found[key] = True
        generated += 1
    folder = out / "indexes" / signature
    ready = {
        "signature": signature,
        "corpus_signature": corpus["signature"],
        "embedding_model": MODEL,
        "dimensions": DIMENSIONS,
        "profile": PROFILE,
        "nodes": len(keys),
        "storage": "supabase",
        "reused": reused,
        "generated": generated,
    }
    save(folder / "ready.json", ready)
    save(out / "index-ready.json", ready)
    return folder


def search_shared(corpus, client, store, question, limit):
    if client.embedding_model != MODEL or client.dimensions != DIMENSIONS:
        raise ValueError("SHARED_EMBEDDING_PROFILE_MISMATCH")
    keys = keys_for(corpus)
    if not keys:
        return []
    found = store.fetch(keys.values(), include_vectors=False)
    if any(key not in found for key in keys.values()):
        raise ValueError("GEMINI_INDEX_REQUIRED")
    vector = client.embed(question, query=True)
    scores = {
        row["input_hash"]: row["score"] for row in store.match(keys.values(), vector, limit=limit)
    }
    rows = [
        {"id": chunk_id, "vector_score": scores[key]}
        for chunk_id, key in keys.items()
        if key in scores
    ]
    return sorted(rows, key=lambda row: (-row["vector_score"], row["id"]))[:limit]
