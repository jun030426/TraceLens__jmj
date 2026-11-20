"""Server-only, content-addressed Gemini vectors in Supabase.

Material authorization belongs to the caller. Only explicitly authorized document
keys may be fetched or searched. No model calls or local fallback happen here.
"""

import hashlib
import json
import math
from urllib.parse import urlsplit

import httpx

MODEL = "gemini-embedding-2"
DIMENSIONS = 768
PROFILE = "gemini-embedding-2-768-text-v1"
BATCH_SIZE = 200


class SharedIndexError(ValueError):
    pass


def document_key(text, title=None):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("EMPTY_EMBEDDING_DOCUMENT")
    title = title or "none"
    if not isinstance(title, str):
        raise TypeError("INVALID_EMBEDDING_TITLE")
    # Exactly the document input constructed by Google.embed, including its title.
    body = {"profile": PROFILE, "input": f"title: {title} | text: {text}"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def vector_values(value):
    if isinstance(value, str):
        value = json.loads(value)
    if (
        not isinstance(value, list)
        or len(value) != DIMENSIONS
        or any(type(x) not in (float, int) or not math.isfinite(x) for x in value)
    ):
        raise ValueError("INVALID_SHARED_EMBEDDING")
    norm = math.sqrt(sum(x * x for x in value))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("INVALID_SHARED_EMBEDDING")
    return [x / norm for x in value]


class SharedVectors:
    def __init__(self, url, secret, *, transport=None):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or not secret
        ):
            raise SharedIndexError("SUPABASE_VECTOR_CONFIG_REQUIRED")
        self.url = url.rstrip("/") + "/rest/v1"
        self.secret = secret
        self.transport = transport

    def request(self, method, path, **kwargs):
        headers = {"apikey": self.secret}
        if not self.secret.startswith("sb_secret_"):
            headers["Authorization"] = "Bearer " + self.secret
        headers.update(kwargs.pop("headers", {}))
        try:
            with httpx.Client(
                timeout=30, trust_env=False, follow_redirects=False, transport=self.transport
            ) as client:
                response = client.request(method, self.url + path, headers=headers, **kwargs)
                response.raise_for_status()
                return response.json() if response.content else None
        except (httpx.HTTPError, ValueError):
            # Do not log request bodies, credentials or source content.
            raise SharedIndexError("SUPABASE_VECTOR_REQUEST_FAILED") from None

    def put(self, text, vector, *, title=None):
        key = document_key(text, title)
        self.request(
            "POST",
            "/rag_shared_embeddings",
            params={"on_conflict": "profile,input_hash"},
            headers={"Prefer": "resolution=ignore-duplicates,return=minimal"},
            json={
                "profile": PROFILE,
                "input_hash": key,
                "document_text": text,
                "document_title": title or "none",
                "embedding_model": MODEL,
                "embedding": vector_values(vector),
            },
        )
        return key

    def fetch(self, keys, *, include_vectors=True):
        keys = list(dict.fromkeys(keys))
        found = {}
        for start in range(0, len(keys), BATCH_SIZE):
            batch = keys[start : start + BATCH_SIZE]
            result = self.request(
                "POST",
                "/rpc/lerny_rag_fetch",
                json={"p_profile": PROFILE, "p_keys": batch, "p_vectors": include_vectors},
            )
            if not isinstance(result, list):
                raise SharedIndexError("INVALID_SHARED_INDEX_RESPONSE")
            for row in result:
                if not isinstance(row, dict) or row.get("input_hash") not in batch:
                    raise SharedIndexError("INVALID_SHARED_INDEX_RESPONSE")
                found[row["input_hash"]] = (
                    vector_values(row["embedding"]) if include_vectors else True
                )
        return found

    def match(self, keys, query_vector, *, limit=8):
        keys = list(dict.fromkeys(keys))
        if not 1 <= limit <= 100:
            raise ValueError("INVALID_MATCH_LIMIT")
        query_vector = vector_values(query_vector)
        found = []
        for start in range(0, len(keys), BATCH_SIZE):
            batch = keys[start : start + BATCH_SIZE]
            result = self.request(
                "POST",
                "/rpc/lerny_rag_match",
                json={
                    "p_profile": PROFILE,
                    "p_keys": batch,
                    "p_query": query_vector,
                    "p_limit": limit,
                },
            )
            if not isinstance(result, list):
                raise SharedIndexError("INVALID_SHARED_INDEX_RESPONSE")
            for row in result:
                if (
                    not isinstance(row, dict)
                    or row.get("input_hash") not in batch
                    or type(row.get("score")) not in (int, float)
                    or not math.isfinite(row["score"])
                ):
                    raise SharedIndexError("INVALID_SHARED_INDEX_RESPONSE")
                found.append(row)
        return sorted(found, key=lambda row: (-row["score"], row["input_hash"]))[:limit]


def from_env(env_file=None):
    """Standalone teammate CLI uses the same private configuration as the service."""
    import os

    from lerny.environment import read_env

    values = {**read_env(env_file), **{k: v for k, v in os.environ.items() if v}}
    mode = values.get("LERNY_RAG_STORAGE", "local")
    if mode == "local":
        return None
    if mode != "supabase":
        raise SharedIndexError("INVALID_RAG_STORAGE")
    return SharedVectors(
        values.get("LERNY_SUPABASE_URL") or values.get("SUPABASE_URL", ""),
        values.get("LERNY_SUPABASE_SERVICE_KEY")
        or values.get("SUPABASE_SECRET_KEY")
        or values.get("SUPABASE_SERVICE_ROLE_KEY", ""),
    )
