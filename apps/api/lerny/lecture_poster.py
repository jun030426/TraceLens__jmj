"""Deterministic covers from reviewed slide copy; never calls an image/video model."""
import io

from PIL import Image, ImageDraw, ImageFont

from lerny.heygen_site_video import font_path
from lerny.lecture_theme import COLORS, POSTER_BACKGROUND, THEME_ID

WIDTH, HEIGHT = 1600, 900


def text_lines(text, font, width):
    """Measure actual glyphs, including Korean and long unbroken identifiers."""
    result, line = [], ''
    for char in text:
        if char == '\n':
            result.append(line); line = ''
        elif line and font.getlength(line + char) > width:
            boundary = line.rfind(' ')
            if boundary > 0:
                result.append(line[:boundary].rstrip()); line = line[boundary+1:] + char
            else:
                result.append(line.rstrip()); line = char.lstrip()
        else:
            line += char
    if line:
        result.append(line.rstrip())
    return result


def fit_text(text, box, *, size, minimum, max_lines):
    width, height = box
    for points in range(size, minimum - 1, -1):
        font = ImageFont.truetype(str(font_path()), points)
        lines = text_lines(text, font, width)
        spacing = round(points * 1.5)
        if len(lines) <= max_lines and len(lines) * spacing <= height:
            return font, lines, spacing
    raise ValueError('POSTER_TEXT_OVERFLOW')


def render_poster(lesson, plan):
    """Use only reviewed narration-plan text, without inventing a new summary."""
    first = plan.slides[0]
    with Image.open(POSTER_BACKGROUND) as picture:
        if abs(picture.width / picture.height - 16 / 9) > .01:
            raise ValueError('POSTER_BACKGROUND_INVALID')
        canvas = picture.convert('RGB').resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas)
    def block(text, x, y, w, h, size, minimum, lines, color='ink', bold=False):
        font, wrapped, spacing = fit_text(text, (w, h), size=size, minimum=minimum, max_lines=lines)
        for index, line in enumerate(wrapped):
            draw.text((x, y + index * spacing), line, font=font, fill='#' + COLORS[color],
                      stroke_width=1 if bold else 0, stroke_fill='#' + COLORS[color], anchor='lt')
    # Keep every glyph to the right of the approved portrait and above player controls.
    block('LERNY  /  개념 강의', 750, 110, 740, 50, 22, 22, 1, 'accent', True)
    block(first.heading, 750, 210, 740, 190, 52, 34, 3, bold=True)
    block(first.key_point, 750, 425, 740, 140, 30, 24, 3, 'muted')
    draw.line((750, 600, 1470, 600), fill='#' + COLORS['line'], width=2)
    block(lesson.title, 750, 635, 740, 125, 33, 14, 5, 'accent', True)
    block('개념을 보고, 직접 풀어보세요.', 750, 785, 740, 45, 22, 22, 1, 'muted')
    out = io.BytesIO()
    canvas.save(out, 'WEBP', quality=91, method=6)
    return out.getvalue()


def poster_receipt(session, video):
    """A receipt is only usable for this video's current accepted script."""
    if not video.script:
        return None
    from lerny.lecture_slides import latest, script_hash
    job = latest(session, video)
    receipt = (job.result or {}).get('poster') if job else None
    if (not receipt or receipt.get('script_hash') != script_hash(video)
            or receipt.get('theme') != THEME_ID or not (job.result or {}).get('model_reviewed')):
        return None
    digest = receipt.get('sha256', '')
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        return None
    if receipt.get('object_key') != f'lecture-posters/{video.id}/{digest}.webp':
        return None
    return receipt
