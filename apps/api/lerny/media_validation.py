"""Bounded MP4 container validation; decoding happens only on the worker."""
import struct


def validate_mp4(content):
    view = memoryview(content)
    offset, boxes, found = 0, 0, set()
    while offset < len(view):
        if len(view) - offset < 8 or boxes >= 10000:
            raise ValueError("INVALID_MP4")
        size, kind = struct.unpack_from(">I4s", view, offset)
        header = 8
        if size == 1:
            if len(view) - offset < 16:
                raise ValueError("INVALID_MP4")
            size = struct.unpack_from(">Q", view, offset + 8)[0]
            header = 16
        elif size == 0:
            size = len(view) - offset
        if size < header or size > len(view) - offset:
            raise ValueError("INVALID_MP4")
        if kind == b"ftyp":
            if size < header + 8 or (size - header) % 4:
                raise ValueError("INVALID_MP4")
            brands = {bytes(view[i:i + 4]) for i in range(offset + header, offset + size, 4)}
            if not brands.intersection({b"isom", b"iso2", b"iso3", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"dash", b"M4V "}):
                raise ValueError("INVALID_MP4")
        if kind in {b"moov", b"mdat"} and size <= header:
            raise ValueError("INVALID_MP4")
        found.add(kind)
        offset += size
        boxes += 1
    if not {b"ftyp", b"moov", b"mdat"} <= found:
        raise ValueError("INVALID_MP4")
