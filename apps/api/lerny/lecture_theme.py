"""Approved Warm Grain teaching theme, shared by slides and video covers."""
from pathlib import Path
import io
from PIL import Image

THEME_ID = 'lerny-warm-grain-v1'
COLORS = {
    'background': 'F4E8D6', 'paper': 'FBF4E8', 'ink': '38271D',
    'accent': '8D4729', 'muted': '6D5645', 'code': '493629',
    'line': 'CBB59D',
}
POSTER_BACKGROUND = Path(__file__).with_name('assets') / 'lecture-poster-warm.png'


def scene_image(raw):
    """Place the editable native teaching panel over the approved empty studio.

    Google's left safe area is intentionally empty; the avatar is added by the
    existing video provider. Neither the portrait nor another avatar is baked in.
    """
    with Image.open(io.BytesIO(raw)) as native:
        if native.format!='PNG' or abs(native.width/native.height-16/9)>.01:
            raise ValueError('GOOGLE_SLIDES_INVALID_THUMBNAIL')
        native=native.convert('RGB').resize((1920,1080),Image.Resampling.LANCZOS)
    with Image.open(POSTER_BACKGROUND.with_name('lecture-ivory.png')) as background:
        if background.size!=(1920,1080):raise ValueError('VIDEO_BACKGROUND_SIZE_INVALID')
        canvas=background.convert('RGB')
    # Same 960x540 authoring coordinates as slide_requests, scaled exactly 2x.
    panel=(796,76,1848,920)
    canvas.paste(native.crop(panel),panel[:2])
    output=io.BytesIO();canvas.save(output,'PNG')
    return output.getvalue()
