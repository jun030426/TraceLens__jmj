"""Conservative admission units, separate from serialized inline-media bytes.

Text retains the existing UTF-8 byte upper estimate. Inline PCM WAV uses duration
at 32 tokens/s (above Gemini 3's documented 25); PNG/JPEG uses at least 2240
tokens, covering Gemini 3 ultra_high, and the older tiled-image upper estimate.
These are admission estimates, not billing measurements. Shared RPM/TPM/RPD
coordination is unchanged. Unsupported media fails closed, never costs zero.
References: https://ai.google.dev/gemini-api/docs/media-resolution
            https://ai.google.dev/gemini-api/docs/tokens
"""
import base64
import binascii
import io
import json
import math
import wave

MAX_INLINE_BYTES = 20 * 1024 * 1024

def input_units(payload):
    inline_bytes = 0
    media_units = 0
    def visit(value):
        nonlocal inline_bytes, media_units
        if isinstance(value, list):
            return [visit(v) for v in value]
        if not isinstance(value, dict):
            return value
        if value.get('type') not in {'audio','image','video','document'}:
            return {k:visit(v) for k,v in value.items()}
        encoded = value.get('data')
        if not isinstance(encoded, str) or value.get('uri'):
            raise ValueError('GEMINI_MEDIA_INPUT_UNSUPPORTED')
        if len(encoded) > (MAX_INLINE_BYTES + 2)//3*4:
            raise ValueError('GEMINI_MEDIA_PAYLOAD_TOO_LARGE')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError('GEMINI_MEDIA_INPUT_INVALID') from None
        inline_bytes += len(raw)
        if inline_bytes > MAX_INLINE_BYTES:
            raise ValueError('GEMINI_MEDIA_PAYLOAD_TOO_LARGE')
        try:
            if value['type']=='audio' and value.get('mime_type')=='audio/wav':
                with wave.open(io.BytesIO(raw)) as wav:
                    if wav.getcomptype()!='NONE' or wav.getnframes()<=0:
                        raise ValueError('invalid PCM')
                    # Validate declared sample length against actual bytes.
                    expected=wav.getnframes()*wav.getnchannels()*wav.getsampwidth()
                    if len(wav.readframes(wav.getnframes())) != expected:
                        raise ValueError('truncated PCM')
                    duration=wav.getnframes()/wav.getframerate()
                media_units += math.ceil(duration*32)
            elif value['type']=='image' and value.get('mime_type') in {'image/png','image/jpeg'}:
                from PIL import Image
                with Image.open(io.BytesIO(raw)) as image:
                    width,height=image.size
                    if image.format not in {'PNG','JPEG'} or width*height>50_000_000:
                        raise ValueError('invalid image')
                    image.verify()
                media_units += max(2240,258*math.ceil(width/768)*math.ceil(height/768))
            else:
                raise ValueError('GEMINI_MEDIA_INPUT_UNSUPPORTED')
        except (OSError, EOFError, ValueError, wave.Error) as exc:
            if str(exc)=='GEMINI_MEDIA_INPUT_UNSUPPORTED':raise
            raise ValueError('GEMINI_MEDIA_INPUT_INVALID') from None
        # Copy metadata; do not mutate the original request or its cache key.
        return {k:visit(v) for k,v in value.items() if k!='data'}
    text_payload=visit(payload)
    return len(json.dumps(text_payload,ensure_ascii=False,allow_nan=False).encode('utf-8')) + media_units
