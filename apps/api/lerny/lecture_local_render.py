"""Offline, explicitly demo-only MP4 compositor. No provider/client/credential imports."""

import hashlib
import html
import json
import subprocess
from pathlib import Path

from lerny.lecture_contract import validate_spec
from lerny.lecture_presentation import legacy_panel_profile

WIDTH, HEIGHT, FPS = 1920, 1080, 24
CONTENT = (60, 245, 1860, 850)
INSTRUCTOR_WIDTH = 540  # 30% of the 1800-pixel content width; remaining 1260 = 70%.


def build_timeline(data, context):
    spec, validation = validate_spec(data, context)
    if not validation["structure_valid"] or validation["status"] != "needs_content_review":
        raise ValueError("A structurally valid draft without blocking issues is required")
    count = sum(len(s.utterances) for s in spec.scenes)
    total_frames = spec.target_duration_seconds * FPS
    if total_frames < count * FPS:
        raise ValueError("Demo needs at least one second per utterance")
    weights = [max(1, len(u.text)) for s in spec.scenes for u in s.utterances]
    remaining = total_frames - count * FPS
    denominator = sum(weights)
    elapsed_weight = 0
    cursor = 0
    entries = []
    for scene in spec.scenes:
        visual = scene.visual.model_dump()
        is_stack = visual["type"] == "stack_diagram"
        stack = list(visual["initial_state"]["items_bottom_to_top"]) if is_stack else []
        values = {e["element_id"]: e["value"] for e in visual.get("elements", [])}

        def apply(utterance_id, boundary, scene=scene, stack=stack):
            removed = []
            for event in scene.visual_events:
                if (event.trigger.utterance_id, event.trigger.boundary) == (utterance_id, boundary):
                    if event.action == "push":
                        stack.append(event.element_id)
                    else:
                        removed.append(stack.pop())
            if len(stack) > 6:
                raise ValueError("This demo layout supports at most six visible stack blocks")
            return removed

        for utterance in scene.utterances:
            removed = apply(utterance.utterance_id, "start")
            weight = weights[len(entries)]
            duration = FPS + (
                (elapsed_weight + weight) * remaining // denominator
                - elapsed_weight * remaining // denominator
            )
            elapsed_weight += weight
            entry = {
                "scene_id": scene.scene_id,
                "utterance_id": utterance.utterance_id,
                "text": utterance.text,
                "start_frame": cursor,
                "end_frame": cursor + duration,
                "start_seconds": cursor / FPS,
                "end_seconds": (cursor + duration) / FPS,
                "visual": visual,
                "stack": [{"id": k, "value": values[k]} for k in stack],
                "removed": [values[k] for k in removed],
                "gesture_cues": [
                    g.model_dump()
                    for g in scene.gesture_cues
                    if g.utterance_id == utterance.utterance_id
                ],
            }
            # End-boundary events affect the next utterance, not the current caption.
            apply(utterance.utterance_id, "end")
            entry["stack_after"] = [{"id": k, "value": values[k]} for k in stack]
            entries.append(entry)
            cursor += duration
    return {
        "artifact_kind": "local_composition_demo",
        "timing_kind": "synthetic_character_weighted",
        "audio_present": False,
        "instructor_motion": "static_image",
        "gesture_rendering": "not_applied",
        "heygen_submitted": False,
        "publication_allowed": False,
        "validation": validation,
        "presentation_profile": legacy_panel_profile(),
        "canvas": {"width": WIDTH, "height": HEIGHT},
        "content_bounds": list(CONTENT),
        "instructor_width_pixels": INSTRUCTOR_WIDTH,
        "material_width_pixels": CONTENT[2] - CONTENT[0] - INSTRUCTOR_WIDTH,
        "fps": FPS,
        "duration_frames": cursor,
        "duration_seconds": cursor / FPS,
        "entries": entries,
    }


def srt_time(frame):
    ms = round(frame * 1000 / FPS)
    seconds, ms = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def subtitles(timeline):
    return (
        "\n\n".join(
            f"{i}\n{srt_time(e['start_frame'])} --> {srt_time(e['end_frame'])}\n{e['text']}"
            for i, e in enumerate(timeline["entries"], 1)
        )
        + "\n"
    )


def render_frame(entry, portrait, font_path, number, total):
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    image = Image.new("RGB", (WIDTH, HEIGHT), "#faf8fc")
    draw = ImageDraw.Draw(image)
    ink, muted, purple = "#382d42", "#897a96", "#73548c"

    def font(size):
        return ImageFont.truetype(str(font_path), size)

    def text(x, y, value, size=30, fill=ink):
        draw.text((x, y), str(value), font=font(size), fill=fill)

    def paragraph(value, box, size, min_size=24):
        # Wrap by glyph width (works for Korean and long tokens); never silently truncate.
        x, y, width, height = box
        for chosen in range(size, min_size - 1, -2):
            f = font(chosen)
            lines, line = [], ""
            for char in value:
                if char == "\n" or (line and draw.textlength(line + char, font=f) > width):
                    lines.append(line)
                    line = "" if char == "\n" else char
                else:
                    line += char
            if line:
                lines.append(line)
            step = int(chosen * 1.5)
            if len(lines) * step <= height:
                for i, line in enumerate(lines):
                    draw.text((x, y + i * step), line, font=f, fill=ink)
                return
        raise ValueError(f"Text does not fit the demo layout: {entry['utterance_id']}")

    text(64, 37, "Lerny", 42, purple)
    text(1435, 52, "합성 시안 · 가상 시간 · 무음", 24, muted)
    text(64, 113, "개념 강의", 23, muted)
    paragraph(entry["visual"]["heading"], (60, 151, 1800, 88), 46, 32)
    draw.rounded_rectangle(CONTENT, radius=20, fill="#ffffff", outline="#e5ddeb", width=2)
    divider = CONTENT[0] + INSTRUCTOR_WIDTH
    draw.line((divider, CONTENT[1], divider, CONTENT[3]), fill="#e5ddeb", width=2)
    # Contain preserves the complete original portrait and its proportions; no face edits.
    fitted = ImageOps.contain(portrait, (INSTRUCTOR_WIDTH - 32, 535))
    px = CONTENT[0] + (INSTRUCTOR_WIDTH - fitted.width) // 2
    image.paste(fitted, (px, CONTENT[1] + 17))
    text(174, 801, "임시 강사 · 정지 이미지", 24, muted)
    visual = entry["visual"]
    if visual["type"] == "stack_diagram":
        blocks = entry["stack"]
        left, right, bottom = 720, 1100, 785
        draw.line(
            [
                (left - 12, 342),
                (left - 12, bottom + 8),
                (right + 12, bottom + 8),
                (right + 12, 342),
            ],
            fill="#b5a4c4",
            width=4,
        )
        step = min(116, 388 // max(1, len(blocks)))
        for i, block in enumerate(blocks):
            y = bottom - (i + 1) * step
            draw.rounded_rectangle(
                (left, y, right, y + step - 12),
                radius=12,
                fill="#eee6f5",
                outline="#c7b5d6",
                width=2,
            )
            label = str(block["value"])
            f = font(min(48, step - 24))
            draw.text(
                ((left + right - draw.textlength(label, font=f)) / 2, y + 13),
                label,
                font=f,
                fill="#59406f",
            )
        if blocks:
            text(870, bottom - len(blocks) * step - 40, "TOP", 25, muted)
        else:
            text(844, 591, "빈 스택", 28, muted)
        if entry["removed"]:
            text(744, 275, ", ".join(map(str, entry["removed"])) + " 꺼냄 ↑", 30, "#a87843")
        text(1220, 367, "현재 스택", 27, muted)
        paragraph(
            " → ".join(str(b["value"]) for b in blocks) or "비어 있음",
            (1220, 420, 550, 146),
            43,
            26,
        )
        text(1220, 573, "아래 → 위 순서", 24, muted)
        draw.line((1220, 640, 1780, 640), fill="#e5ddeb", width=2)
        text(1220, 671, "원소 수", 24, muted)
        text(1520, 671, "맨 위 (TOP)", 24, muted)
        text(1220, 718, f"{len(blocks)}개", 38, purple)
        text(1520, 718, blocks[-1]["value"] if blocks else "없음", 38, purple)
    else:
        points = visual["key_points"]
        if points:
            paragraph("\n".join(points), (730, 365, 1020, 360), 52, 28)
        else:
            text(750, 371, "이번 개념", 30, muted)
            paragraph(visual["heading"], (750, 455, 990, 250), 64, 32)
    draw.rounded_rectangle((60, 885, 1860, 1034), radius=18, fill="#eee8f4")
    paragraph(entry["text"], (92, 902, 1736, 116), 34, 26)
    text(64, 1041, "16:9  ·  강사 30% / 설명 자료 70%", 19, muted)
    text(1720, 1041, f"{number:02} / {total:02}", 19, muted)
    return image


def render_demo(data, context, portrait_path, output_dir, ffmpeg_path, font_path):
    from PIL import Image, ImageOps

    timeline = build_timeline(data, context)
    output_dir = Path(output_dir)
    ffmpeg_path, font_path, portrait_path = map(Path, (ffmpeg_path, font_path, portrait_path))
    if not all(p.is_file() for p in (ffmpeg_path, font_path, portrait_path)):
        raise ValueError("Image, font and local ffmpeg executable must exist")
    if portrait_path.stat().st_size > 30 * 1024 * 1024:
        raise ValueError("Portrait exceeds 30 MiB")
    with Image.open(portrait_path) as source:
        if source.width * source.height > 30_000_000:
            raise ValueError("Portrait exceeds 30 megapixels")
        portrait = ImageOps.exif_transpose(source).convert("RGB")
    # A fresh directory avoids accidentally replacing a previous preview or final video.
    output_dir.mkdir(parents=True, exist_ok=False)
    timeline["portrait_sha256"] = hashlib.sha256(portrait_path.read_bytes()).hexdigest()
    concat = ["ffconcat version 1.0"]
    for i, entry in enumerate(timeline["entries"], 1):
        name = f"frame-{i:02}.png"
        render_frame(entry, portrait, font_path, i, len(timeline["entries"])).save(
            output_dir / name
        )
        concat.extend(
            [f"file '{name}'", f"duration {(entry['end_frame'] - entry['start_frame']) / FPS:.9f}"]
        )
    concat.append(f"file '{name}'")
    (output_dir / "frames.ffconcat").write_text("\n".join(concat) + "\n", encoding="utf-8")
    (output_dir / "timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "subtitles.srt").write_text(subtitles(timeline), encoding="utf-8")
    command = [
        str(ffmpeg_path.resolve()),
        "-hide_banner",
        "-nostdin",
        "-n",
        "-f",
        "concat",
        "-safe",
        "1",
        "-i",
        "frames.ffconcat",
        "-vf",
        f"fps={FPS}",
        "-frames:v",
        str(timeline["duration_frames"]),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        "lecture-preview.mp4",
    ]
    with (output_dir / "encode.log").open("w", encoding="utf-8") as log:
        subprocess.run(command, cwd=output_dir, stdout=log, stderr=log, check=True, timeout=240)
    buttons = "".join(
        f'<button data-time="{e["start_seconds"]:.6f}">{html.escape(e["utterance_id"])}'
        f" · {e['start_seconds']:.2f}s — {html.escape(e['text'])}</button>"
        for e in timeline["entries"]
    )
    player = """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lerny · 로컬 MP4 합성 시안</title><style>
body{font-family:'Malgun Gothic',sans-serif;background:#f7f4fa;color:#392e43;margin:0;padding:24px}
main{max-width:1200px;margin:auto}h1{font-size:24px}p{line-height:1.7;color:#7a6b87}
video{display:block;width:100%;aspect-ratio:16/9;background:#eee;border-radius:14px}
nav{display:grid;gap:8px;margin:22px 0}button{padding:12px;text-align:left;border:1px solid #ded3e8;
border-radius:8px;background:white;color:#503e60;cursor:pointer}a{color:#70528a}
</style><main><h1>16:9 강의 · MP4 합성 시안</h1>
<p>첨부 강사 이미지 · 본문 30:70 · 가상 발화 시간표 · 무음<br>
인물과 손은 움직이지 않습니다. HeyGen 호출 없이 로컬에서 합성한 검토용 파일입니다.</p>
<video controls preload="metadata" poster="frame-05.png" src="lecture-preview.mp4"></video>
<p><a href="lecture-preview.mp4" download>MP4 다운로드</a> ·
<a href="subtitles.srt" download>가상 자막 SRT</a> · <a href="timeline.json">시간표 JSON</a></p>
<nav>BUTTONS</nav></main><script>
const video=document.querySelector('video');
document.querySelectorAll('button[data-time]').forEach(b=>b.onclick=()=>{
video.pause();video.currentTime=Number(b.dataset.time)+0.08;
});</script></html>""".replace("BUTTONS", buttons)
    # Use an existing frame even for short custom specs.
    player = player.replace("frame-05.png", f"frame-{min(5, len(timeline['entries'])):02}.png")
    (output_dir / "index.html").write_text(player, encoding="utf-8")
    return timeline
