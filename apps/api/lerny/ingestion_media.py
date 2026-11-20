"""Owned media subprocess; selected text/checkpoints survive, scratch images do not."""

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from lerny.config import settings
from lerny.ingestion_engine import PacedTransport
from lerny.ingestion_store import IngestionError, SupabaseIngestion


def run(path, out, job_id, token):
    from video_extraction.pipeline import connected
    from video_extraction.shared.common import read, save
    if not settings().gemini_calls_enabled:
        raise IngestionError("GEMINI_CALLS_DISABLED")
    poppler = Path(os.environ.get("LERNY_INGESTION_POPPLER_BIN", str(
        Path.home() / "LernyData/tools/poppler-26.09.0/poppler-26.09.0/Library/bin")))
    if (poppler / "pdftotext.exe").is_file():
        os.environ["PATH"] = str(poppler) + os.pathsep + os.environ.get("PATH", "")
    store = SupabaseIngestion()
    def check():
        rows = store.rows("ingestion_jobs", id=job_id)
        if (not rows or rows[0]["status"] != "PROCESSING" or rows[0]["lease_token"] != token
                or datetime.fromisoformat(rows[0]["lease_until"]) <= datetime.now(UTC)):
            raise IngestionError("STALE_LEASE")
        store.source(rows[0])
    options = {name: os.environ.get("LERNY_INGESTION_" + name.upper()) for name in
               ("whisper_model", "ocr_models", "ocr_python", "alignment_python", "alignment_model")}
    local_whisper = Path.home() / "LernyData/models/huggingface/faster-whisper-small"
    if not options["whisper_model"] and (local_whisper / "model.bin").is_file():
        options["whisper_model"] = str(local_whisper)
    try:
        check()
        connected.prepare(out, inputs=[path], model=settings().gemini_answer_model,
                          native_python=sys.executable, code_python=sys.executable,
                          alignment_allow_download=False, **options)
        summary = connected.run(out, None, maximum=settings().gemini_max_calls_per_job, delay=4.5,
                                transport=PacedTransport(store, check, time.sleep))
        if not summary["all_tasks_processed"]:
            raise IngestionError("MEDIA_TASKS_INCOMPLETE")
        latest = read(out / "latest.json")
        def lines(path):
            return [json.loads(s) for s in Path(path).read_text(encoding="utf-8").splitlines() if s.strip()]
        revision = Path(latest["manifest"]).parent
        save(out / "extracted.json", {"bundles": lines(latest["multimodal_bundles"]),
                                     "review_items": lines(revision / "review-required.jsonl"),
                                     "records": lines(latest["records"]), "summary": summary})
    finally:
        store.close()


if __name__ == "__main__":
    run(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4])
