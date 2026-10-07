"""Scan report: a one-line summary, with problem details on demand.

Pure PySide6: receives a ScanResult already computed by processing/scanner.py
and only displays it. Correctly identified textures are not listed here:
they appear in the MAPPING section (ui/mapping.py).
"""

import html
import os

from PySide6 import QtCore, QtWidgets

from .widgets import ChevronButton

_SECTION_STYLE = "font-weight: bold;"
_HEADER_STYLE = "font-style: italic;"  # the summary line reads as a status, not a setting
_INDENT = 12  # pixels, explanation and file lines under their heading
_HEADER_TITLE = "Scan report"
_NO_ASSET_SUMMARY = "No asset found"
_SCAN_FAILED = "Scan failed"
_SCAN_CANCELLED = "Scan cancelled"
_NO_ASSET_HINT = ("Check that the file names end with a suffix defined in the naming preset "
                  "(e.g. _basecolor, _normal).")
# Duplicates and accented names in the summary: the orange of the plugin's
# warnings (the artist must choose or rename a file). Unrecognized files stay
# neutral: often not a problem.
_WARNING_COLOR = "#e6a23c"


def build_message(text):
    """Simple text block (errors, information)."""
    label = QtWidgets.QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    return label


def build_scan_error(text):
    """A failed scan, shown like the scan report: "Scan report" and an orange
    "⚠ Scan failed" on the same line, the reason in italics below."""
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)  # like ScanReportWidget
    header, _layout, _title = _header(
        f"<span style=\"color: {_WARNING_COLOR};\">⚠ {_SCAN_FAILED}</span>")
    layout.addWidget(header)
    layout.addWidget(_hint(text))
    return widget


def build_scan_cancelled():
    """The artist stopped the scan: "Scan report   Scan cancelled", neutral
    (not a problem), nothing below."""
    return _header(_SCAN_CANCELLED)[0]


def _header(summary_text):
    """'Scan report          <summary>' line: (widget, its layout, title label).
    Title in bold, like Painter's foldable sub-titles ("Base Surface"); the
    summary (rich text, numbers and fixed words only) in italics at the far right."""
    header = QtWidgets.QWidget()
    header_layout = QtWidgets.QHBoxLayout(header)
    header_layout.setContentsMargins(0, 0, 0, 0)
    title = QtWidgets.QLabel(_HEADER_TITLE)
    title.setStyleSheet(_SECTION_STYLE)
    header_layout.addWidget(title)
    summary = QtWidgets.QLabel(summary_text)
    summary.setTextFormat(QtCore.Qt.RichText)  # orange warnings
    summary.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
    summary.setStyleSheet(_HEADER_STYLE)
    header_layout.addWidget(summary, 1)
    return header, header_layout, title


def _hint(text):
    """Italic text under the header line: what happened, what to check."""
    hint = build_message(text)
    hint.setStyleSheet(_HEADER_STYLE)  # italics, like a status
    return hint


class ScanReportWidget(QtWidgets.QWidget):
    """'› Scan report        3 assets · 1 unrecognized' + foldable details.

    The arrow sits on the left, like the fold arrows of the asset list:
    pointing right when closed, down when open. Clicking anywhere on the
    line opens or closes the details.
    """

    def __init__(self, result, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        duplicates = _duplicates(result)
        self._details = self._build_details(result, duplicates)

        # Header line: fold arrow on the left (only when there are details to
        # show), title, summary.
        header, header_layout, self._title = _header(_summary(result, duplicates))
        layout.addWidget(header)
        if not result.assets:
            # The summary says "No asset found": what to check, just below.
            layout.addWidget(_hint(_NO_ASSET_HINT))
        if self._details is None:
            return

        self._toggle = ChevronButton(sideways=True)
        self._toggle.setToolTip("Show / hide the details")
        self._toggle.toggled.connect(self._show_details)
        header_layout.insertWidget(0, self._toggle)  # just before "Scan report"
        # The whole line is clickable, not only the chevron.
        header.setCursor(QtCore.Qt.PointingHandCursor)
        header.mousePressEvent = lambda _event: self._toggle.toggle()

        self._details.setVisible(False)
        layout.addWidget(self._details)

    def _show_details(self, shown):
        """Open / close the details. Their headings ("Duplicates"...) start
        where the "Scan report" text starts, right of the chevron, like the
        content of Painter's foldable sub-titles. Measured on the laid-out
        line, so it follows the chevron size and spacing of Painter's style."""
        if shown:
            self._details.layout().setContentsMargins(self._title.x(), 0, 0, 0)
        self._details.setVisible(shown)

    @staticmethod
    def _build_details(result, duplicates):
        """Details widget, or None when there is no problem to show."""
        # (title, explanation, lines, lines shown before the list scrolls)
        sections = [
            # A duplicate line is long (several files): fewer lines shown.
            ("Duplicates", "Several files for the same map:", duplicates,
             _MAX_VISIBLE_DUPLICATES),
            # Like the unrecognized files: name in italics, path on hover
            # (the accent may be in a folder name only).
            ("Accented names", "Ignored: accented or special characters in the file or "
             "folder name:",
             [(f"<i>{html.escape(os.path.basename(path))}</i>", path)
              for path in result.not_allowed],
             _MAX_VISIBLE_LINES),
            # File name only, in italics; the path inside the root folder on hover.
            ("Unrecognized files", "No suffix of the naming preset matches:",
             [(f"<i>{html.escape(os.path.basename(path))}</i>", path)
              for path in result.unrecognized],
             _MAX_VISIBLE_LINES),
            ("Unreadable folders", "These folders could not be read:",
             [(html.escape(path), path) for path in result.unreadable], _MAX_VISIBLE_LINES),
        ]
        sections = [s for s in sections if s[2]]
        if not sections:
            return None

        details = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(details)
        layout.setContentsMargins(0, 0, 0, 0)  # left: set when opened (_show_details)
        layout.setSpacing(2)
        for title, explanation, lines, max_visible in sections:
            title_label = QtWidgets.QLabel(f"{title} ({len(lines)})")  # full count
            title_label.setStyleSheet(_SECTION_STYLE)
            layout.addWidget(title_label)
            # Heading, then its explanation one step right, then the lines
            # one more step right.
            explanation_label = build_message(explanation)
            explanation_label.setContentsMargins(_INDENT, 0, 0, 0)
            layout.addWidget(explanation_label)
            # A folder chosen too high (a whole drive: 4,000+ unrecognized
            # files, tested 2026-10-07) froze Painter while one line per
            # file was built: only the first lines are listed.
            if len(lines) > _MAX_LISTED_LINES:
                lines = lines[:_MAX_LISTED_LINES] + [
                    (f"<i>… and {len(lines) - _MAX_LISTED_LINES} more</i>", "")]
            layout.addWidget(_line_list(lines, max_visible))
            layout.addSpacing(6)
        return details


# A list of the report (unrecognized files...) shows at most this many
# lines; longer lists scroll inside this height. Duplicates: 2 lines.
_MAX_VISIBLE_LINES = 3
_MAX_VISIBLE_DUPLICATES = 2
# Lines built per list at most, then "… and N more": building thousands of
# lines freezes Painter.
_MAX_LISTED_LINES = 100
_LINE_SPACING = 2
# A bullet starts each entry; the text has its own column, so a line cut by
# the panel width goes on under the text, not under the bullet: each entry
# stands out from the end of the previous one. Same height: no extra scroll.
_BULLET = "•"
_BULLET_GAP = 6  # pixels between the bullet and its text


def _line_list(lines, max_visible):
    """lines: [(text shown, as rich text, escaped; tooltip)]. One "• text"
    row per line, indented; scrolls when there are more than max_visible lines, so a
    big folder does not stretch the panel.

    A line never widens the panel: a long line wraps between its words
    (between the files of a duplicate), a single too long word is cut; the
    full text stays in the tooltip."""
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(widget)
    layout.setContentsMargins(2 * _INDENT, 0, 0, 0)  # under the explanation
    layout.setSpacing(_LINE_SPACING)
    labels = []
    bullet_width = 0
    for text, tooltip in lines:
        row = QtWidgets.QWidget()
        row.setToolTip(tooltip)
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(_BULLET_GAP)
        bullet = QtWidgets.QLabel(_BULLET)
        bullet_width = bullet.sizeHint().width()
        row_layout.addWidget(bullet, 0, QtCore.Qt.AlignTop)  # on the first text line
        label = QtWidgets.QLabel(text)
        label.setTextFormat(QtCore.Qt.RichText)  # italics of the duplicates
        label.setWordWrap(True)
        # Ignored width: the label takes the width it is given, never more.
        label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        row_layout.addWidget(label, 1)
        layout.addWidget(row)
        labels.append(label)
    if len(lines) <= max_visible:
        return widget

    # Width taken left of the text: list indent + bullet + gap.
    scroll = _LimitedScroll(labels, max_visible, 2 * _INDENT + bullet_width + _BULLET_GAP)
    widget.setAutoFillBackground(False)
    scroll.setWidget(widget)
    return scroll


class _LimitedScroll(QtWidgets.QScrollArea):
    """Scroll area exactly as high as its first max_visible lines. A long
    line wraps onto several text lines depending on the panel width, so the
    height is computed again each time the width changes."""

    def __init__(self, labels, max_visible, left_width):
        super().__init__()
        self._labels = labels[:max_visible]
        self._left_width = left_width  # pixels left of the text (indent, bullet)
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.viewport().setAutoFillBackground(False)  # panel background shows through

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Width given to the text: the visible area minus what is left of it.
        width = self.viewport().width() - self._left_width
        if width <= 0:
            return
        height = (sum(label.heightForWidth(width) for label in self._labels)
                  + (len(self._labels) - 1) * _LINE_SPACING)
        if height != self.height():  # only when it changes: no endless resizing
            self.setFixedHeight(height)


def _duplicates(result):
    """[('Asset – <i>Base Color: a.png, b.png</i>', paths)] for every map
    with several files: file names shown (in italics after the dash), their
    paths in the root folder on hover."""
    lines = []
    for asset in result.assets:
        for texture_format, textures in asset.textures_by_format().items():
            if len(textures) > 1:
                files = ", ".join(os.path.basename(t.relative_path) for t in textures)
                details = html.escape(f"{texture_format.title()}: {files}")
                lines.append((f"{html.escape(asset.name)} – <i>{details}</i>",
                              "\n".join(t.relative_path for t in textures)))
    return lines


def _summary(result, duplicates):
    """Summary line, as rich text (numbers and fixed words only, nothing to escape)."""
    count = len(result.assets)
    parts = [f"{count} asset{'' if count == 1 else 's'}" if count else _NO_ASSET_SUMMARY]
    if duplicates:
        parts.append(f"<span style=\"color: {_WARNING_COLOR};\">⚠ {len(duplicates)} "
                     f"duplicate{'' if len(duplicates) == 1 else 's'}</span>")
    if result.not_allowed:
        # Orange: these files are ignored, the artist must rename them.
        parts.append(f"<span style=\"color: {_WARNING_COLOR};\">⚠ "
                     f"{len(result.not_allowed)} with accents</span>")
    if result.unrecognized:
        parts.append(f"{len(result.unrecognized)} unrecognized")
    if result.unreadable:
        n = len(result.unreadable)
        parts.append(f"{n} unreadable folder{'' if n == 1 else 's'}")
    return " · ".join(parts)
