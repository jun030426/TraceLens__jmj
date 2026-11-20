"""Read-only shared-index check. Never generates embeddings or prints credentials."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))

from lerny.config import settings
from lerny.rag_index import shared_store
from rag_mvp.shared_vectors import DIMENSIONS, MODEL, SharedIndexError


def main():
    try:
        config = settings()
        result = {
            "storage": config.rag_storage,
            "model": MODEL,
            "dimensions": DIMENSIONS,
            "model_calls_performed": False,
        }
        if config.rag_storage == "supabase":
            shared_store().fetch(["0" * 64], include_vectors=False)
            result["read_access_verified"] = True
        print(json.dumps(result))
        return 0
    except SharedIndexError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    except (ValueError, OSError, TypeError):
        print(json.dumps({"error": "RAG_STORAGE_CONFIGURATION_INVALID"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
