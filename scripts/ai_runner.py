"""Inference-only PC/GPU runner. HTTPS worker token + local Ollama; no database access."""

import argparse
import json
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx


def run(config_path):
    config = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    cloud_url = config["cloud_url"].rstrip("/")
    model_url = config.get("model_url", "http://127.0.0.1:11434").rstrip("/")
    if urlparse(cloud_url).scheme != "https" or urlparse(cloud_url).username:
        raise SystemExit("cloud_url must be an HTTPS service URL")
    if urlparse(model_url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("The runner uses a model on the same machine only")
    allowed_models = set(
        config.get("allowed_models", ["qwen3:4b-instruct", "qwen3-embedding:0.6b"])
    )
    identity = {"worker_id": config.get("worker_id", "test-pc"), "models_ready": True}
    headers = {"Authorization": "Bearer " + config["worker_token"]}
    if config.get("vercel_protection_bypass"):
        headers["x-vercel-protection-bypass"] = config["vercel_protection_bypass"]
    with httpx.Client(
        base_url=cloud_url + "/api/internal/", headers=headers, timeout=30, trust_env=False
    ) as cloud, httpx.Client(base_url=model_url, timeout=150, trust_env=False) as model:
        print(
            "Inference runner started. Stop with Ctrl+C. No DB or document processing.",
            flush=True,
        )
        while True:
            try:
                try:
                    tags = model.get("/api/tags")
                    tags.raise_for_status()
                    installed = {item["name"] for item in tags.json().get("models", [])}
                    identity["models_ready"] = allowed_models <= installed
                except (httpx.HTTPError, ValueError, KeyError):
                    identity["models_ready"] = False
                response = cloud.post("ai/claim", json=identity)
                response.raise_for_status()
                task = response.json()["task"]
                if not task:
                    time.sleep(10)
                    continue
                lease = {**identity, "lease_token": task["lease_token"]}
                stopped = threading.Event()

                def heartbeat(stopped=stopped, task_id=task["id"], lease=lease):
                    with httpx.Client(
                        base_url=cloud_url + "/api/internal/",
                        headers=headers,
                        timeout=20,
                        trust_env=False,
                    ) as pulse:
                        while not stopped.wait(30):
                            try:
                                r = pulse.post(f"ai/tasks/{task_id}/heartbeat", json=lease)
                                r.raise_for_status()
                            except httpx.HTTPError:
                                return

                thread = threading.Thread(target=heartbeat, daemon=True)
                thread.start()
                result = {**lease, "error": True}
                try:
                    if (
                        task["operation"] not in {"chat", "embed"}
                        or task["body"].get("model") not in allowed_models
                    ):
                        raise ValueError("Unsupported model request")
                    output = model.post("/api/" + task["operation"], json=task["body"])
                    output.raise_for_status()
                    raw = output.json()
                    result = {
                        **lease,
                        "response": {"embeddings": raw["embeddings"]}
                        if task["operation"] == "embed"
                        else {"message": {"content": raw["message"]["content"]}},
                    }
                except (httpx.HTTPError, ValueError, KeyError):
                    print(
                        "Model inference failed; reporting failure without request contents.",
                        flush=True,
                    )
                finally:
                    stopped.set()
                    thread.join(timeout=21)
                for attempt in range(3):
                    try:
                        saved = cloud.post(f"ai/tasks/{task['id']}/result", json=result)
                        if saved.status_code == 422 and not result.get("error"):
                            result = {**lease, "error": True}
                            continue
                        saved.raise_for_status()
                        break
                    except httpx.HTTPError:
                        if attempt == 2:
                            print(
                                "Could not acknowledge result; the cloud lease will recover it.",
                                flush=True,
                            )
                        else:
                            time.sleep(2)
            except (httpx.HTTPError, ValueError, KeyError):
                print(
                    "Cloud connection unavailable. Retrying; general service runs independently.",
                    flush=True,
                )
                time.sleep(10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(Path.home() / "LernyData/secrets/ai-runner.json"))
    args = parser.parse_args()
    try:
        run(args.config)
    except KeyboardInterrupt:
        print("Inference runner stopped.")
