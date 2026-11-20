"""Local Video Agent runner. Defaults to offline status; network requires explicit flags."""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))

from lerny.heygen_pilot import PilotError, load_credentials
from lerny.heygen_video_agent import AgentError, VideoAgentRun


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["status", "generate", "resume", "recover"], default="status", nargs="?"
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--request-body", type=Path)
    parser.add_argument("--env-file", type=Path)
    recovery = parser.add_mutually_exclusive_group()
    recovery.add_argument("--session-id")
    recovery.add_argument("--video-id", help="Provider-verified Studio video ID for recovery")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--confirm-generate", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=0)
    args = parser.parse_args(argv)
    if not 0 <= args.wait_seconds <= 300:
        parser.error("--wait-seconds must be 0..300")
    if args.action in {"generate", "resume"} and not args.allow_network:
        parser.error("--allow-network is required; no network request was made")
    if args.action == "generate" and not (args.confirm_generate and args.request_body):
        parser.error("generate requires --confirm-generate and --request-body")
    if args.action == "recover" and not (args.session_id or args.video_id):
        parser.error("recover requires the provider-verified --session-id or --video-id")
    if args.action != "recover" and (args.session_id or args.video_id):
        parser.error("provider recovery IDs are only accepted with recover")
    run = VideoAgentRun(args.run_dir)
    try:
        if args.action == "status":
            print(json.dumps(run.status(), ensure_ascii=False))
            return 0
        if args.action == "recover":
            state = run.attach_video(args.video_id) if args.video_id else run.attach_session(args.session_id)
            print(json.dumps(state, ensure_ascii=False))
            return 0
        # Only these explicit actions load credentials or create HTTP clients.
        credentials = load_credentials(args.env_file)
        body = None
        if args.action == "generate":
            body = json.loads(args.request_body.read_text(encoding="utf-8-sig"))
        with (
            httpx.Client(
                headers={"X-Api-Key": credentials["HEYGEN_API_KEY"]},
                timeout=60,
                trust_env=False,
                follow_redirects=False,
            ) as api,
            httpx.Client(timeout=120, trust_env=False, follow_redirects=False) as media,
        ):
            if args.action == "generate":
                run.start(api, body, confirmed=True)
            deadline = time.monotonic() + args.wait_seconds
            while True:
                result = run.poll(api, media)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                if result["status"] == "completed":
                    return 0
                if result["status"] in {"failed", "cancelled", "needs_attention"}:
                    return 1
                delay = result.get("retry_after_seconds", 30)
                if time.monotonic() + delay > deadline:
                    return 2  # Pending: resume later, never POST again.
                next_poll = time.monotonic() + delay
                while time.monotonic() < next_poll:
                    time.sleep(min(1, next_poll - time.monotonic()))
    except (AgentError, PilotError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError):
        print("LOCAL_STATE_OR_INPUT_ERROR", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("INTERRUPTED_USE_RESUME", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
