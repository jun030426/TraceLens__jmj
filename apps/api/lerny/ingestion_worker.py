"""Five-stage ingestion queue worker. Start explicitly; model calls default to off."""

import argparse
import json
import logging
import socket
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

from lerny.config import settings
from lerny.ingestion_store import MODEL, PIPELINE, IngestionError, SupabaseIngestion

log = logging.getLogger(__name__)


class Lease:
    def __init__(self, store, job, interval=30):
        self.store, self.job, self.interval = store, job, interval
        self.stopped, self.lost = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self.run, name="ingestion-heartbeat", daemon=True)

    def run(self):
        while not self.stopped.wait(self.interval):
            try:
                if not self.store.heartbeat(self.job):
                    self.lost.set()
                    return
            except Exception:  # noqa: BLE001 -- a failed heartbeat invalidates this attempt
                # An unknown lease state cannot authorize further writes/model requests.
                self.lost.set()
                return

    def check(self):
        if self.lost.is_set():
            raise IngestionError("STALE_LEASE")

    def sleep(self, seconds):
        if self.lost.wait(seconds):
            self.check()

    def __enter__(self):
        if not self.store.heartbeat(self.job):
            raise IngestionError("STALE_LEASE")
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stopped.set()
        self.thread.join(timeout=95)


def process(store, job, engine_factory, scratch_root, heartbeat_seconds=30):
    """A failed/reclaimed attempt only resumes from durable, hash-checked stage data."""
    scratch_root = Path(scratch_root)
    scratch_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="ingestion-", dir=scratch_root) as directory:
        scratch = Path(directory)
        with Lease(store, job, heartbeat_seconds) as lease:
            if job["pipeline_version"] != PIPELINE or job["config"].get("embedding_model") != MODEL:
                raise IngestionError("PIPELINE_CONFIG_MISMATCH")
            source = store.source(job)
            engine = engine_factory(job, source, lease)
            saved = store.checkpoints(job)

            def checkpoint(stage, value, review=None, **extra):
                lease.check()
                pointer = store.save_artifact(job, stage, value)
                output = {"artifact": pointer, **extra}
                lease.check()
                store.checkpoint(job, stage, output, review or [])
                saved[stage] = output
                return value

            if 2 in saved:
                extracted = store.load_artifact(job, saved[2]["artifact"], scratch)
            else:
                suffix = Path(job["file_name"].replace("\\", "/")).suffix.lower()
                path = scratch / ("source" + suffix)
                digest = store.download(job["file_path"], path, 1024 * 1024 * 1024, lease.check)
                if digest != job["file_hash"]:
                    raise IngestionError("FILE_HASH_MISMATCH")
                if 1 not in saved:
                    checkpoint(1, {"file_hash": digest}, file_hash=digest)
                extracted = engine.extract(path, scratch)
                checkpoint(2, extracted, extracted.get("review_items", []))
            if 3 in saved:
                corpus = store.load_artifact(job, saved[3]["artifact"], scratch)
            else:
                corpus = engine.chunk(extracted)
                checkpoint(3, corpus, corpus.get("review_items", []))
            chunks = corpus["chunks"]
            if not chunks:
                raise IngestionError("NO_APPROVED_CHUNKS")
            if 4 not in saved:
                existing = {r["chunk_key"]: r for r in store.rows("course_vectors", job_id=job["id"])}
                for chunk in chunks:
                    lease.check()
                    old = existing.get(chunk["id"])
                    if old:
                        if old["content"] != chunk["text"] or old["embedding_model"] != MODEL:
                            raise IngestionError("RESULT_CONTENT_CONFLICT")
                        continue
                    vector = engine.embed(chunk)
                    lease.check()
                    store.upsert(job, "course_vectors", {
                        "chunk_key": chunk["id"], "content": chunk["text"],
                        "locator": {k: chunk.get(k) for k in
                                    ("source_locator", "source_sha256", "concept_ids", "page", "time_interval")},
                        "concept_label": chunk.get("title"), "embedding_model": MODEL,
                        "embedding": vector,
                    })
                checkpoint(4, {"vectors": len(chunks), "model": MODEL})
            if 5 not in saved:
                output = engine.generate(corpus)
                for table in ("concept_quizzes", "shorts_scripts"):
                    if not output.get(table):
                        raise IngestionError("CONTENT_RESULTS_REQUIRED")
                    for row in output[table]:
                        lease.check()
                        store.upsert(job, table, row)
                counts = store.counts(job)
                expected = {"course_vectors": len(chunks), "concept_quizzes": len(output["concept_quizzes"]),
                            "shorts_scripts": len(output["shorts_scripts"]), "lab_quizzes": 0}
                if counts != expected:
                    raise IngestionError("RESULT_COUNTS_MISMATCH")
                checkpoint(5, output, expected_counts=expected)
            lease.check()
            store.source(job)  # Recheck disclosure eligibility before publication.
            counts = store.counts(job)
            if counts != saved[5]["expected_counts"]:
                raise IngestionError("RESULT_COUNTS_MISMATCH")
            return store.publish(job, counts)


def run_once(store, engine_factory, scratch_root, worker_id):
    job = store.claim(worker_id)
    if not job:
        return False
    try:
        process(store, job, engine_factory, scratch_root)
        log.info("job=%s completed", job["id"])
    except (Exception, KeyboardInterrupt) as exc:
        # Never put a model response, source text, URL or credential into queue errors.
        code = str(exc) if isinstance(exc, IngestionError) else "PROCESSING_FAILED"
        retryable = code in {"PROCESSING_FAILED", "INGESTION_HTTP_FAILED", "INGESTION_CONNECTION_FAILED",
                             "INGESTION_DOWNLOAD_FAILED"}
        try:
            if code != "STALE_LEASE":
                store.fail(job, code, retryable)
        except IngestionError:
            log.warning("job=%s lease unavailable while recording failure", job["id"])
        log.warning("job=%s error=%s", job["id"], code)
        if isinstance(exc, KeyboardInterrupt):
            raise
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check", action="store_true", help="Readiness only; no claims or model calls")
    parser.add_argument("--worker-id", default=socket.gethostname()[:80] + "-ingestion")
    args = parser.parse_args()
    from lerny.ingestion_engine import TeamIngestionEngine
    config = settings()
    ready = config.gemini_calls_enabled and config.gemini_keys_ready()
    if args.check or not ready:
        print(json.dumps({"pipeline": PIPELINE, "embedding_model": MODEL,
                          "calls_enabled": config.gemini_calls_enabled,
                          "keys_configured": config.gemini_keys_ready(),
                          "ready_to_claim": ready, "live_verified": False}))
        return
    logging.basicConfig(level=logging.INFO)
    store = SupabaseIngestion()
    try:
        while True:
            worked = run_once(store, lambda j, s, lease: TeamIngestionEngine(j, s, lease, store),
                              config.runtime_root / "ingestion-scratch", args.worker_id)
            if args.once:
                return
            if not worked:
                threading.Event().wait(3)
    finally:
        store.close()


if __name__ == "__main__":
    main()
