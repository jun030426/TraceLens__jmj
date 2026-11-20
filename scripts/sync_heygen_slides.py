"""Sync a staff-selected Google Slides deck to HeyGen assets and prepare request.json.

Use a 16:9 studio background without a presenter. Each visible slide's speaker notes
are its spoken script. GOOGLE_SLIDES_ACCESS_TOKEN needs presentations.readonly.
Sync uploads images only. Submit the prepared file with scripts/heygen_video_agent.py.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import TypeAdapter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from lerny.heygen_pilot import PilotError, job_lock, load_credentials
from lerny.heygen_slides import AssetId, Script, compile_studio

SLIDES = "https://slides.googleapis.com/v1/presentations/"
ASSETS = "https://api.heygen.com/v3/assets"


def atomic_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(path)


def notes(page):
    notes_page = page["slideProperties"]["notesPage"]
    speaker_id = notes_page["notesProperties"]["speakerNotesObjectId"]
    speaker = next(
        (e for e in notes_page["pageElements"] if e["objectId"] == speaker_id), {}
    )
    runs = speaker.get("shape", {}).get("text", {}).get("textElements", [])
    script = "".join(run.get("textRun", {}).get("content", "") for run in runs).strip()
    return TypeAdapter(Script).validate_python(script)


def read_slides(google, media, presentation_id):
    if not re.fullmatch(r"[\w-]{1,150}", presentation_id, re.ASCII):
        raise ValueError("Invalid presentation ID")
    url = SLIDES + presentation_id
    response = google.get(url)
    response.raise_for_status()
    deck = response.json()
    size = deck["pageSize"]
    if (
        size["width"]["unit"] != size["height"]["unit"]
        or abs(size["width"]["magnitude"] / size["height"]["magnitude"] - 16 / 9) > 0.01
    ):
        raise ValueError("A landscape 16:9 deck is required")
    pages = [
        s for s in deck["slides"] if not s.get("slideProperties", {}).get("isSkipped")
    ]
    if not 1 <= len(pages) <= 50:
        raise ValueError("Studio accepts 1 to 50 visible slides")
    scripts = [notes(s) for s in pages]
    images = []
    for page in pages:
        thumbnail = google.get(
            url + "/pages/" + page["objectId"] + "/thumbnail",
            params={
                "thumbnailProperties.thumbnailSize": "LARGE",
                "thumbnailProperties.mimeType": "PNG",
            },
        )
        thumbnail.raise_for_status()
        source = thumbnail.json()["contentUrl"]
        parsed = urlsplit(source)
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(
            ".googleusercontent.com"
        ):
            raise ValueError("Unexpected Google thumbnail origin")
        # This separate client never receives any provider credentials.
        image = media.get(source)
        image.raise_for_status()
        if (
            not image.content.startswith(b"\x89PNG\r\n\x1a\n")
            or len(image.content) > 32 * 1024 * 1024
        ):
            raise ValueError("Invalid slide thumbnail")
        images.append(image.content)
    if deck.get("revisionId"):
        revision = google.get(url, params={"fields": "revisionId"})
        revision.raise_for_status()
        if revision.json().get("revisionId") != deck["revisionId"]:
            raise ValueError("The deck changed during synchronization")
    return deck["title"], scripts, images


def sync_assets(api, cache_path, title, scripts, images):
    # Validate all narration and the scene count before the first upload.
    compile_studio(title, ["pending"] * len(images), scripts)
    cache = (
        json.loads(cache_path.read_text(encoding="utf-8"))
        if cache_path.exists()
        else {}
    )
    ids = []
    for index, data in enumerate(images, start=1):
        digest = hashlib.sha256(data).hexdigest()
        if digest not in cache:
            response = api.post(
                ASSETS, files={"file": (f"lesson-{index}.png", data, "image/png")}
            )
            response.raise_for_status()
            asset = TypeAdapter(AssetId).validate_python(
                response.json()["data"]["asset_id"]
            )
            cache[digest] = asset
            atomic_json(cache_path, cache)
        ids.append(cache[digest])
    return compile_studio(title, ids, scripts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--presentation-id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--env-file", type=Path, default=Path.home() / "LernyData/secrets/heygen.env"
    )
    args = parser.parse_args()
    try:
        token = os.environ.get("GOOGLE_SLIDES_ACCESS_TOKEN")
        if not token:
            parser.error("Set GOOGLE_SLIDES_ACCESS_TOKEN in the process environment")
        key = load_credentials(args.env_file)["HEYGEN_API_KEY"]
        with (
            job_lock(args.output_dir),
            httpx.Client(
                headers={"Authorization": "Bearer " + token},
                timeout=40,
                trust_env=False,
            ) as google,
            httpx.Client(timeout=40, trust_env=False) as media,
            httpx.Client(
                headers={"X-Api-Key": key}, timeout=60, trust_env=False
            ) as heygen,
        ):
            title, scripts, images = read_slides(google, media, args.presentation_id)
            namespace = hashlib.sha256(key.encode()).hexdigest()[:16]
            body = sync_assets(
                heygen,
                args.output_dir / f"assets-{namespace}.json",
                title,
                scripts,
                images,
            )
            atomic_json(
                args.output_dir / "slide-map.json",
                {
                    "slides": [
                        {
                            "asset_id": s["input"]["background"]["source"]["asset_id"],
                            "script": s["input"]["script"],
                        }
                        for s in body["scenes"]
                    ]
                },
            )
            atomic_json(args.output_dir / "request.json", body)
        print(json.dumps({"submitted": False, "scenes": len(images)}))
    except (
        httpx.HTTPError,
        PilotError,
        ValueError,
        OSError,
        KeyError,
        TypeError,
    ) as exc:
        code = (
            exc.response.status_code
            if isinstance(exc, httpx.HTTPStatusError)
            else type(exc).__name__
        )
        parser.exit(
            1, f"Sync failed ({code}). Check access, slide format and narration.\n"
        )


if __name__ == "__main__":
    main()
