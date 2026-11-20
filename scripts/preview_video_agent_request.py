"""Export an offline request preview. This script never submits anything to HeyGen."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))

from lerny.heygen_request_preview import PreviewOptions, compile_preview


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=ROOT / "docs/contracts/lecture.example.json")
    parser.add_argument(
        "--context", type=Path, default=ROOT / "docs/contracts/generation-input.example.json"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8-sig"))
    context = json.loads(args.context.read_text(encoding="utf-8-sig"))
    try:
        result = compile_preview(spec, context.get("generation_input", context), PreviewOptions())
    except ValueError as exc:
        parser.error(str(exc))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "video-agent-preview.json": json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        "video-agent-request.json": json.dumps(
            result["requests"][0]["body"], ensure_ascii=False, indent=2
        )
        + "\n",
        "video-agent-prompt.txt": result["requests"][0]["body"]["prompt"] + "\n",
    }
    for name, content in outputs.items():
        (args.output_dir / name).write_text(content, encoding="utf-8")
    print(
        json.dumps(
            {
                "request_count": result["request_count"],
                "prompt_characters": result["prompt_characters"],
                "submitted": result["submitted"],
                "unresolved_fields": result["unresolved_fields"],
                "output_dir": str(args.output_dir.resolve()),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
