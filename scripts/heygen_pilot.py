"""Run from repo root: python scripts/heygen_pilot.py check|catalog|generate|resume."""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from lerny.config import settings
from lerny.heygen_pilot import Pilot, PilotError, job_lock, load_credentials


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "catalog", "generate", "resume"])
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--video-id", help="Recover a known ID after an ambiguous submission")
    parser.add_argument("--wait-seconds", type=int, default=900)
    args = parser.parse_args()
    if args.wait_seconds < 0 or args.wait_seconds > 3600:
        parser.error("--wait-seconds must be between 0 and 3600")
    if args.video_id and args.action != "resume":
        parser.error("--video-id is only accepted with resume")
    try:
        config = settings()
        if config.deployment != "local":
            raise PilotError("이 샘플 도구는 로컬 환경에서만 실행합니다.")
        credentials = load_credentials(args.env_file)
        with (
            httpx.Client(
                base_url="https://api.heygen.com",
                timeout=60,
                trust_env=False,
                headers={"X-Api-Key": credentials["HEYGEN_API_KEY"]},
            ) as client,
            httpx.Client(timeout=120, trust_env=False) as media,
        ):
            if args.action == "check":
                response = client.get("/v3/users/me")
                response.raise_for_status()
                account = response.json()["data"]
                print(
                    json.dumps(
                        {
                            "authenticated": True,
                            "billing_type": account.get("billing_type"),
                            "wallet_balance": (account.get("wallet") or {}).get(
                                "remaining_balance"
                            ),
                            "avatar_configured": bool(credentials.get("HEYGEN_AVATAR_ID")),
                            "voice_configured": bool(credentials.get("HEYGEN_VOICE_ID")),
                        }
                    )
                )
                return 0
            if args.action == "catalog":
                # First page only, read-only. Keep names/IDs; omit account and raw response data.
                for label, endpoint, params in [
                    (
                        "voices",
                        "/v3/voices",
                        {"language": "Korean", "gender": "female", "limit": 100},
                    ),
                    (
                        "avatars",
                        "/v3/avatars/looks",
                        {"avatar_type": "photo_avatar", "ownership": "public", "limit": 50},
                    ),
                ]:
                    response = client.get(endpoint, params=params)
                    response.raise_for_status()
                    body = response.json()
                    items = body["data"]
                    if not isinstance(items, list):
                        raise PilotError("카탈로그 응답 형식을 확인해 주세요.")
                    print(
                        json.dumps(
                            {
                                "catalog": label,
                                "has_more": body.get("has_more"),
                                "items": [
                                    {
                                        k: row.get(k)
                                        for k in (
                                            "voice_id" if label == "voices" else "id",
                                            "name",
                                            "language",
                                            "gender",
                                        )
                                    }
                                    for row in items
                                ],
                            },
                            ensure_ascii=False,
                        )
                    )
                return 0
            pilot = Pilot(config.runtime_root / "data" / "heygen-pilot")
            with job_lock(pilot.root):
                if args.action == "generate":
                    pilot.start(
                        client,
                        credentials.get("HEYGEN_AVATAR_ID", ""),
                        credentials.get("HEYGEN_VOICE_ID", ""),
                    )
                elif args.video_id:
                    pilot.attach_video(args.video_id)
                deadline = time.monotonic() + args.wait_seconds
                while True:
                    status = pilot.poll(client, media)
                    print(json.dumps({"status": status}), flush=True)
                    if status == "completed":
                        print("영상 저장 완료. Lerny 강의실의 AI 강의 화면에서 재생할 수 있습니다.")
                        return 0
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        print("아직 생성 중입니다. resume 명령으로 이어서 확인하세요.")
                        return 2
                    time.sleep(min(10, remaining))
    except PilotError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError):
        print(
            "연결 또는 설정을 확인해 주세요. 키와 외부 응답 본문은 출력하지 않았습니다.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("중단했습니다. 기록된 작업은 resume 명령으로 이어서 확인할 수 있습니다.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
