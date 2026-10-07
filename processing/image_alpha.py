"""Does an image file have an alpha channel? Read from the file header only.

Pure Python, no Painter API, no image library: only the first bytes that
describe the image are read (the pixels are never decoded), so it stays fast
on 4K textures. Used at scan to know whether a Base Color can give the
opacity (docs/project/workflow.md §20.3).

has_alpha(path) returns True / False, or None when the file cannot be read
or its format is not understood (the caller treats None as "no alpha").
"""

import os
import struct

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_EXR_MAGIC = b"\x76\x2f\x31\x01"


def has_alpha(path):
    extension = os.path.splitext(path)[1].lower()
    reader = _READERS.get(extension)
    if reader is None:
        return None
    try:
        with open(path, "rb") as file:
            return reader(file)
    except (OSError, struct.error, ValueError):
        return None


def _jpeg(_file):
    return False   # JPEG has no alpha channel


def _png(file):
    if file.read(8) != _PNG_SIGNATURE:
        return None
    # Chunks: length (4), type (4), data, CRC (4). IHDR comes first.
    while True:
        header = file.read(8)
        if len(header) < 8:
            return False
        length, chunk_type = struct.unpack(">I4s", header)
        if chunk_type == b"IHDR":
            data = file.read(length)
            color_type = data[9]
            if color_type in (4, 6):   # grey + alpha, RGB + alpha
                return True
            file.seek(4, os.SEEK_CUR)
            continue
        if chunk_type == b"tRNS":      # transparency of palette / single colour
            return True
        if chunk_type == b"IDAT":      # pixels start: no tRNS before them
            return False
        file.seek(length + 4, os.SEEK_CUR)


def _tga(file):
    header = file.read(18)
    if len(header) < 18:
        return None
    pixel_depth = header[16]
    alpha_bits = header[17] & 0x0F
    # Some tools write 32-bit pixels without filling the alpha-bits field.
    return alpha_bits > 0 or pixel_depth == 32


def _tiff(file):
    order = file.read(2)
    if order == b"II":
        endian = "<"
    elif order == b"MM":
        endian = ">"
    else:
        return None
    magic, ifd_offset = struct.unpack(endian + "HI", file.read(6))
    if magic != 42:   # 43 = BigTIFF, not handled
        return None
    file.seek(ifd_offset)
    (count,) = struct.unpack(endian + "H", file.read(2))
    samples, photometric, extra_samples = 1, None, False
    for _ in range(count):
        tag, field_type, _number, value = struct.unpack(endian + "HHI4s", file.read(12))
        # SHORT values sit in the first 2 bytes of the 4-byte value field.
        short = struct.unpack(endian + "H", value[:2])[0] if field_type == 3 else None
        if tag == 277:    # SamplesPerPixel
            samples = short or samples
        elif tag == 262:  # PhotometricInterpretation: 0/1 grey, 2 RGB
            photometric = short
        elif tag == 338:  # ExtraSamples: extra channel(s), in practice alpha
            extra_samples = True
    if extra_samples:
        return True
    if photometric == 2:
        return samples >= 4
    if photometric in (0, 1):
        return samples >= 2
    return False


def _exr(file):
    if file.read(4) != _EXR_MAGIC:
        return None
    file.read(4)   # version and flags
    # Header attributes: name\0 type\0 size(int32) value, ended by an empty name.
    while True:
        name = _read_cstring(file)
        if not name:
            return False
        attribute_type = _read_cstring(file)
        (size,) = struct.unpack("<i", file.read(4))
        value = file.read(size)
        if name == b"channels" and attribute_type == b"chlist":
            return any(channel == b"A" or channel.endswith(b".A")
                       for channel in _exr_channel_names(value))


def _exr_channel_names(value):
    """Channel list: name\0 + 16 bytes of settings, repeated, ended by \0."""
    names, position = [], 0
    while position < len(value) and value[position] != 0:
        end = value.index(b"\x00", position)
        names.append(value[position:end])
        position = end + 1 + 16
    return names


def _read_cstring(file, limit=256):
    data = b""
    while len(data) < limit:
        byte = file.read(1)
        if not byte or byte == b"\x00":
            return data
        data += byte
    raise ValueError("EXR header name too long")


_READERS = {
    ".png": _png,
    ".tga": _tga,
    ".jpg": _jpeg,
    ".jpeg": _jpeg,
    ".tif": _tiff,
    ".tiff": _tiff,
    ".exr": _exr,
}
