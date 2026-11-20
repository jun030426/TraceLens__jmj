"""Server-only PostgREST RPCs and bounded private Storage for ingestion leases."""

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import httpx

from lerny.config import settings

PIPELINE = "ingestion-worker-v1"
MODEL = "gemini-embedding-2"
TABLES = {"course_vectors": "chunk_key", "concept_quizzes": "quiz_key",
          "shorts_scripts": "shorts_key"}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()


class IngestionError(RuntimeError):
    pass


class SupabaseIngestion:
    def __init__(self, client=None):
        self.config = settings()
        self.client = client or httpx.Client(timeout=90, trust_env=False, follow_redirects=False)
        key = self.config.supabase_service_key.get_secret_value()
        if not key or not self.config.supabase_url.startswith("https://"):
            raise IngestionError("SUPABASE_NOT_CONFIGURED")
        self.headers = {"apikey": key}
        if not key.startswith("sb_secret_"):
            self.headers["Authorization"] = "Bearer " + key

    def close(self):
        self.client.close()

    def request(self, method, path, **kwargs):
        headers = {**self.headers, **kwargs.pop("headers", {})}
        try:
            response = self.client.request(method, self.config.supabase_url.rstrip("/") + path,
                                           headers=headers, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            try:
                message = exc.response.json().get("message", "")
            except ValueError:
                message = ""
            known = {"STALE_LEASE", "RESULT_STAGE_NOT_OPEN", "RESULT_COUNTS_MISMATCH",
                     "CHECKPOINT_CONFLICT", "SOURCE_NOT_PUBLIC", "SHORTS_RESULTS_REQUIRED"}
            raise IngestionError(message if message in known else "INGESTION_HTTP_FAILED") from None
        except httpx.HTTPError:
            raise IngestionError("INGESTION_CONNECTION_FAILED") from None

    def rpc(self, name, **params):
        return self.request("POST", "/rest/v1/rpc/" + name, json=params).json()

    def rows(self, table, **filters):
        # Explicit paging avoids PostgREST's default result limit dropping later chunks.
        result = []
        for offset in range(0, 100_001, 500):
            params = {"select": "*", **{k: "eq." + str(v) for k, v in filters.items()},
                      "limit": 500, "offset": offset}
            params["order"] = "stage.asc" if table == "ingestion_checkpoints" else "id.asc"
            page = self.request("GET", "/rest/v1/" + table, params=params).json()
            result.extend(page)
            if len(page) < 500:
                return result
        raise IngestionError("INGESTION_ROW_LIMIT")

    def claim(self, worker):
        rows = self.rpc("ingestion_claim", p_worker_id=worker, p_lease_seconds=120,
                        p_pipeline_version=PIPELINE)
        return rows[0] if rows else None

    def heartbeat(self, job):
        return self.rpc("ingestion_heartbeat", p_job_id=job["id"],
                        p_lease_token=job["lease_token"], p_lease_seconds=120) is True

    def source(self, job):
        rows = self.rows("ingestion_sources", id=job["source_id"])
        if not rows or rows[0]["visibility"] != "public" or rows[0]["internal_use"] != "none":
            raise IngestionError("SOURCE_NOT_PUBLIC")
        return rows[0]

    def checkpoints(self, job):
        return {row["stage"]: row["output"] for row in
                self.rows("ingestion_checkpoints", job_id=job["id"])}

    def checkpoint(self, job, stage, output, review):
        self.rpc("ingestion_checkpoint", p_job_id=job["id"], p_lease_token=job["lease_token"],
                 p_stage=stage, p_output=output, p_review_items=review)

    def upsert(self, job, table, row):
        key = TABLES[table]
        self.request("POST", "/rest/v1/" + table,
                     params={"on_conflict": "job_id," + key},
                     headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                     json={**row, "job_id": job["id"], "lease_token": job["lease_token"]})

    def counts(self, job):
        result = {}
        for table in (*TABLES, "lab_quizzes"):
            response = self.request("GET", "/rest/v1/" + table,
                                    params={"select": "id", "job_id": "eq." + job["id"], "limit": 1},
                                    headers={"Prefer": "count=exact"})
            result[table] = int(response.headers["Content-Range"].rsplit("/", 1)[1])
        return result

    def publish(self, job, counts):
        return self.rpc("ingestion_publish", p_job_id=job["id"], p_lease_token=job["lease_token"],
                        p_expected_vectors=counts["course_vectors"],
                        p_expected_concept_quizzes=counts["concept_quizzes"],
                        p_expected_lab_quizzes=counts["lab_quizzes"])

    def fail(self, job, code, retryable):
        self.rpc("ingestion_fail", p_job_id=job["id"], p_lease_token=job["lease_token"],
                 p_error_code=code, p_error_message=code, p_retryable=retryable)

    def object_url(self, key):
        if not key.startswith("ingestion/") or ".." in key or "\\" in key:
            raise IngestionError("INVALID_STORAGE_PATH")
        return "/storage/v1/object/lerny-materials/" + quote(key, safe="/")

    def download(self, key, target, limit, check=lambda: None):
        target = Path(target)
        sha, size = hashlib.sha256(), 0
        try:
            with self.client.stream("GET", self.config.supabase_url.rstrip("/") + self.object_url(key),
                                    headers=self.headers) as response:
                response.raise_for_status()
                with target.open("wb") as stream:
                    for block in response.iter_bytes(1024 * 1024):
                        check()
                        size += len(block)
                        if size > limit:
                            raise IngestionError("FILE_TOO_LARGE")
                        stream.write(block)
                        sha.update(block)
        except httpx.HTTPError:
            raise IngestionError("INGESTION_DOWNLOAD_FAILED") from None
        if not size:
            raise IngestionError("EMPTY_SOURCE")
        return sha.hexdigest()

    def copy_original(self, source_key, raw_key):
        self.object_url(source_key)
        self.object_url(raw_key)
        try:
            response = self.client.post(self.config.supabase_url.rstrip("/") + "/storage/v1/object/copy",
                                        headers=self.headers, json={"bucketId": "lerny-materials",
                                            "sourceKey": source_key, "destinationKey": raw_key})
            if response.is_success:
                return
            # A previous attempt may have copied successfully before its response was lost.
            error = response.json()
            code = error.get("code", error.get("error"))
            if response.status_code in {400, 409} and code in {
                "ResourceAlreadyExists", "KeyAlreadyExists", "Duplicate", "already_exists"
            }:
                return
        except (httpx.HTTPError, ValueError):
            pass
        raise IngestionError("INGESTION_COPY_FAILED")

    def save_artifact(self, job, stage, value):
        content = encoded(value)
        if len(content) > 64 * 1024 * 1024:
            raise IngestionError("CHECKPOINT_TOO_LARGE")
        sha = hashlib.sha256(content).hexdigest()
        key = f"ingestion/checkpoints/{job['id']}/stage-{stage}-{sha}.json"
        # Content-addressed objects are immutable in meaning, including after a retry.
        self.request("POST", self.object_url(key), content=content,
                     headers={"Content-Type": "application/json", "x-upsert": "true"})
        return {"object_key": key, "sha256": sha, "bytes": len(content)}

    def load_artifact(self, job, pointer, scratch):
        prefix = f"ingestion/checkpoints/{job['id']}/"
        if not pointer["object_key"].startswith(prefix):
            raise IngestionError("CHECKPOINT_SCOPE_MISMATCH")
        path = scratch / "checkpoint.json"
        digest = self.download(pointer["object_key"], path, 64 * 1024 * 1024)
        if digest != pointer["sha256"]:
            raise IngestionError("CHECKPOINT_HASH_MISMATCH")
        return json.loads(path.read_text(encoding="utf-8"))
