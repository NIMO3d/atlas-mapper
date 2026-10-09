"""Guess the format (OpenGL / DirectX) of a normal map from its pixels.

A normal map describes a relief. Read with the right green convention, the
slopes it gives fit together (the relief can be rebuilt); read with the green
inverted, they do not. For every pixel the test compares both readings
(curl of the slopes, docs/project/workflow.md §20.1.1) and each block of the
image votes for the reading that fits best, its vote weighted by how
clearly it decides.

Mirrored UV islands invert the red channel, which inverts their vote: a map
whose votes stay mixed is reported as uncertain instead of guessed. The
artist always validates.

Pure Python (Painter's Python has no numpy): the image is reduced to
ANALYSIS_SIZE pixels with Qt before the analysis. classify() has no Qt and
can be tested outside Painter.
"""

import os

from ..core.atlas_assignment import (NORMAL_DIRECTX, NORMAL_OPENGL, NORMAL_TEXTURE_FORMAT,
                                     NORMAL_UNCERTAIN)
from .scanner import ScanCancelled

ANALYSIS_SIZE = 256     # pixels: largest side of the reduced image
_BLOCK = 16             # pixels: side of a voting block
_MIN_BLOCK_PIXELS = 40  # pixels usable in a block for it to vote
# Share of the (weighted) votes that must agree for a sure answer. Checked
# on 49 maps on 2026-10-08 (workflow.md §20.1.1): none between 0.3 and 0.7.
SURE_SHARE = 0.7
_MAX_JUMP = 0.5         # slope change above this: UV seam or empty area, ignored
_MIN_JUMP = 1e-3        # flat area: says nothing
_MIN_NZ = 0.3           # normals too tilted (borders, padding): ignored

# Results already computed in this Painter session: {path: (file signature,
# NormalDetection or None)}. A rescan (other grid, other preset) does not
# analyse again a file that did not change.
_cache = {}


class NormalDetection:
    """Result for one file: verdict (NORMAL_OPENGL, NORMAL_DIRECTX or
    NORMAL_UNCERTAIN) and share of the weighted votes that read as OpenGL."""

    def __init__(self, verdict, opengl_share):
        self.verdict = verdict
        self.opengl_share = opengl_share


def detect_normal_maps(assets, progress=None):
    """{file path: NormalDetection} of every normal map file of the scanned
    assets (processing/scanner.py); files that cannot be analysed are left out.

    progress(done, total, relative_path), optional: called before each file;
    it returns False to stop: ScanCancelled is then raised, like the scan.
    A file already analysed in this session and not modified since (same
    date and size) is not analysed again.
    """
    textures = [texture for asset in assets for texture in asset.textures
                if texture.texture_format == NORMAL_TEXTURE_FORMAT]
    results = {}
    for done, texture in enumerate(textures):
        if progress is not None and progress(done, len(textures), texture.relative_path) is False:
            raise ScanCancelled()
        try:
            status = os.stat(texture.path)
            signature = (status.st_mtime_ns, status.st_size)
        except OSError:
            signature = None   # unreadable now: analysed (and failing) every time
        cached = _cache.get(texture.path)
        if signature is not None and cached is not None and cached[0] == signature:
            detection = cached[1]
        else:
            detection = detect_normal_format(texture.path)
            if signature is not None:
                _cache[texture.path] = (signature, detection)
        if detection is not None:
            results[texture.path] = detection
    return results


def detect_normal_format(path):
    """NormalDetection of an image file, or None when it cannot be read or
    has no usable relief (flat map)."""
    # Qt only here: classify() stays testable without it.
    from PySide6 import QtCore, QtGui

    image = QtGui.QImage(path)
    if image.isNull():
        return None
    if max(image.width(), image.height()) > ANALYSIS_SIZE:
        image = image.scaled(ANALYSIS_SIZE, ANALYSIS_SIZE, QtCore.Qt.KeepAspectRatio,
                             QtCore.Qt.SmoothTransformation)   # averages the pixels
    image = image.convertToFormat(QtGui.QImage.Format_RGB888)
    width, height, line = image.width(), image.height(), image.bytesPerLine()
    data = bytes(image.constBits())[:line * height]
    # QImage rows go top to bottom; the test needs V going up (row 0 = bottom).
    rows = [data[(height - 1 - y) * line:(height - 1 - y) * line + width * 3]
            for y in range(height)]
    return classify(width, height, rows)


def classify(width, height, rows):
    """rows: one bytes object per pixel row, bottom row first, 3 bytes (R, G,
    B) per pixel. Returns a NormalDetection, or None without enough relief."""
    # Slopes of the relief, read as OpenGL (green = up): hx = dh/dx, hy = dh/dy.
    hx, hy, usable = [], [], []
    for row in rows:
        row_hx, row_hy, row_usable = [], [], []
        for x in range(width):
            nx = row[3 * x] / 127.5 - 1.0
            ny = row[3 * x + 1] / 127.5 - 1.0
            nz = row[3 * x + 2] / 127.5 - 1.0
            row_usable.append(nz > _MIN_NZ)
            nz = max(nz, 0.05)
            row_hx.append(-nx / nz)
            row_hy.append(-ny / nz)
        hx.append(row_hx)
        hy.append(row_hy)
        usable.append(row_usable)

    # For a real relief d(hx)/dy = d(hy)/dx. With the green inverted, hy
    # changes sign: the "+" difference becomes the small one.
    # Each block's vote weighs how clearly it decides: nearly flat blocks
    # (smooth objects) vote almost at random and must not drown the blocks
    # with a real relief (workflow.md §20.1.1).
    total_weight = opengl_weight = 0.0
    for block_y in range(0, height - _BLOCK, _BLOCK):
        for block_x in range(0, width - _BLOCK, _BLOCK):
            fits_opengl = fits_directx = 0.0
            count = 0
            for y in range(block_y, block_y + _BLOCK):
                hx_row, hx_up, hy_row, usable_row = hx[y], hx[y + 1], hy[y], usable[y]
                for x in range(block_x, block_x + _BLOCK):
                    if not usable_row[x]:
                        continue
                    a = hx_up[x] - hx_row[x]        # d(hx)/dy
                    b = hy_row[x + 1] - hy_row[x]   # d(hy)/dx
                    jump = max(abs(a), abs(b))
                    if jump >= _MAX_JUMP or jump <= _MIN_JUMP:
                        continue
                    fits_opengl += abs(a - b)
                    fits_directx += abs(a + b)
                    count += 1
            if count >= _MIN_BLOCK_PIXELS:
                weight = abs(fits_directx - fits_opengl)
                total_weight += weight
                if fits_opengl < fits_directx:
                    opengl_weight += weight
    if not total_weight:
        return None
    share = opengl_weight / total_weight
    if share >= SURE_SHARE:
        verdict = NORMAL_OPENGL
    elif share <= 1 - SURE_SHARE:
        verdict = NORMAL_DIRECTX
    else:
        verdict = NORMAL_UNCERTAIN
    return NormalDetection(verdict, share)
