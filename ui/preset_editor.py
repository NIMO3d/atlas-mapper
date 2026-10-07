"""Naming preset editor: create or modify a preset from the panel, without
editing JSON by hand (docs/project/project-overview.md §19.3).

The window only edits the asset prefixes, the suffixes of each single map
and the packed formats. Everything else of the starting preset (extensions,
_info, other formats) is copied unchanged. The checks are the ones of the
scan (core/naming_config.py): what can be saved can be scanned.
"""

import copy

from PySide6 import QtCore, QtWidgets

from ..core.naming_config import (
    PACKABLE_MAPS, PACKED_CHANNELS, PROTECTED_PRESET, SINGLE_MAPS, NamingConfigError,
    check_new_preset_name, check_preset_data, list_presets, read_preset_data, rename_preset,
    save_preset)
from .widgets import (
    SECTION_TITLE_STYLE, ChevronButton, ComboBox, CrossButton, InfoIcon, Separator, set_window_icon,
    show_message)

_UNUSED_CHANNEL = "—"
_START_TOOLTIP = ("The new preset is pre-filled with the prefixes and suffixes of the chosen "
                  "preset: modify only what changes. The chosen preset stays untouched.\n\n"  # blank line
                  "\"Blank page\" empties every field: each one shows an example of the "
                  "expected format.")
_BLANK_PAGE = "Blank page"
# Explanations of the "i" icons at the right of the section / sub-section titles.
_PREFIXES_TOOLTIP = ("Removed from the start of the asset names (taken from the file name).\n"
                     "Separated by commas. Upper and lower case are the same.")
_UNIQUE_TOOLTIP = ("One file per map. Each field lists the suffixes that end the file name, "
                   "just before the extension, separated by commas: e.g. _basecolor, _albedo, _d. "
                   "Upper and lower case are the same.\n"
                   "If several suffixes match, the longest one wins (_basecolor before _bc).")
_PACKED_TOOLTIP = ("One file holding several maps, one per channel R / G / B / A: e.g. ORM = "
                   "Ambient Occlusion in R, Roughness in G, Metallic in B. Its suffixes work like "
                   "those of the unique textures; \"—\" = channel not used.\n"
                   "A map found both as its own file and inside a packed file: its own file wins, "
                   "for that map only.")
# Example shown in an empty suffix field (grey italic placeholder).
_SUFFIX_EXAMPLES = {
    "base color": "_basecolor, _albedo",
    "normal": "_normal, _nrm",
    "roughness": "_roughness, _rough",
    "glossiness": "_glossiness, _smoothness",
    "metallic": "_metallic, _metal",
    "ambient occlusion": "_ao, _occlusion",
    "opacity": "_opacity, _alpha",
    "height": "_height, _disp",
    "emissive": "_emissive, _emit",
}
_WARNING_STYLE = "QLabel { color: #e6a23c; font-style: italic; }"  # same orange as the scan warnings
# Spacing (pixels).
_ROW_SPACING = 8
_LABEL_GAP = 12           # between a label and the field after it
_ABOVE_SEPARATOR = 20     # between a section and the separator line below it
_BELOW_SEPARATOR = 10     # between a separator and the next title
_BELOW_TITLE = 20         # between a title and its content
_CONTENT_INDENT = 10      # content shifted right of its title (also below a sub-title)
_BELOW_SUBTITLE = 10      # between a sub-title and its content
_BETWEEN_SUBSECTIONS = 20  # between two sub-sections of the same section
_MAX_VISIBLE_PACKED_ROWS = 5  # packed textures shown before their list scrolls
_SCROLLBAR_GAP = 8        # between the packed rows and their scroll bar
# Width of a closed R / G / B / A list, counted by Qt in "x" widths: 6 shows
# about 9 letters in Painter (9 showed about 14, measured on screenshots).
_CHANNEL_LIST_LENGTH = 6
_MIN_WINDOW_WIDTH = 560   # pixels; wider when the packed rows need it
_POPUP_MARGIN = 30        # open R / G / B / A list: room around the longest name


def _split_keywords(text):
    """'_D, _Albedo' -> ['_d', '_albedo'] (comma separated, lowercase)."""
    return [word.strip().lower() for word in text.split(",") if word.strip()]


def _format_problem(text, prefix=False):
    """Problem of a suffix (or prefix) field, for the artist, or "".

    Expected format: '_d, _albedo' for suffixes, 'tx_, sm_' for prefixes.
    """
    kind, example = ("prefix", "tx_, sm_") if prefix else ("suffix", "_d, _albedo")
    if not text.strip():
        return ""
    words = [word.strip().lower() for word in text.split(",")]
    if "" in words:
        return f"extra comma. Expected format: {example}"
    for word in words:
        if len(word.split()) > 1:
            return f"\"{word}\": separate each {kind} with a comma. Expected format: {example}"
    duplicate = _first_duplicate(words)
    if duplicate:
        return f"the {kind} \"{duplicate}\" is written twice."
    return ""


def _join_keywords(keywords):
    return ", ".join(keywords)


def _italic_when_empty(field):
    """Empty field: its example (placeholder, grey) is shown in italics.
    Qt has no separate style for the placeholder, so the field font is
    italic while the field is empty, upright as soon as something is typed."""
    def update(text):
        font = field.font()
        font.setItalic(not text)
        field.setFont(font)
    field.textChanged.connect(update)
    update(field.text())


def _first_duplicate(keywords):
    """First keyword written twice in the same field, or None."""
    seen = set()
    for keyword in keywords:
        if keyword in seen:
            return keyword
        seen.add(keyword)
    return None


def _packed_name(suffixes):
    """Packed format name from its first suffix: '_orm' -> 'orm' (shown 'ORM')."""
    if not suffixes:
        return ""
    return suffixes[0].strip("_-. ") or suffixes[0]


class _ChannelCombo(ComboBox):
    """R / G / B / A list: about 9 letters shown when the window is narrow
    ("Ambient O"), growing up to the longest map name when the window is
    widened, never wider (the suffix field takes the rest)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(_CHANNEL_LIST_LENGTH)
        # Maximum: never wider than sizeHint, can shrink to minimumSizeHint.
        self.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)

    def sizeHint(self):
        """Narrow width + what the longest name needs beyond it (Qt counts
        the narrow width in "x" widths)."""
        hint = super().sizeHint()
        metrics = self.fontMetrics()
        longest = max((metrics.horizontalAdvance(self.itemText(i)) for i in range(self.count())),
                      default=0)
        shown = self.minimumContentsLength() * metrics.horizontalAdvance("x")
        return QtCore.QSize(hint.width() + max(0, longest - shown), hint.height())


class _SuffixField(QtWidgets.QLineEdit):
    """Suffix field of a packed texture, often narrow: shows the start of its
    text ("_orm..."), not the end, and the full text on hover when it does
    not fit (like the full map name of the R / G / B / A lists)."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        # Qt puts the cursor at the end of a new text, scrolled into view:
        # brought back to the start, also when the artist leaves the field.
        self.setCursorPosition(0)
        self.editingFinished.connect(lambda: self.setCursorPosition(0))

    def event(self, event):
        if event.type() == QtCore.QEvent.ToolTip:
            # Room left for the text inside the frame (margins of the style).
            option = QtWidgets.QStyleOptionFrame()
            self.initStyleOption(option)
            room = self.style().subElementRect(
                QtWidgets.QStyle.SE_LineEditContents, option, self).width()
            if self.text() and self.fontMetrics().horizontalAdvance(self.text()) > room:
                QtWidgets.QToolTip.showText(event.globalPos(), self.text(), self)
            else:
                QtWidgets.QToolTip.hideText()
            return True
        return super().event(event)


class _PackedRow(QtWidgets.QWidget):
    """One packed format: its suffixes, then the map stored in R / G / B / A."""

    def __init__(self, suffixes, channels, on_change, on_remove, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.suffixes_field = _SuffixField(_join_keywords(suffixes))
        self.suffixes_field.setPlaceholderText("e.g. _orm")
        _italic_when_empty(self.suffixes_field)
        self.suffixes_field.textChanged.connect(on_change)
        layout.addWidget(self.suffixes_field, 1)

        self.channel_combos = {}
        for channel in PACKED_CHANNELS:
            layout.addWidget(QtWidgets.QLabel(f"{channel} :"))
            combo = _ChannelCombo()
            combo.addItem(_UNUSED_CHANNEL, None)
            for map_name in PACKABLE_MAPS:
                combo.addItem(map_name.title(), map_name)
            current = channels.get(channel)
            if current and combo.findData(current) < 0:  # written by hand in the file
                combo.addItem(current.title(), current)
            combo.setCurrentIndex(max(combo.findData(current), 0) if current else 0)
            # Full names in the open list and on hover.
            combo.view().setMinimumWidth(combo.view().sizeHintForColumn(0) + _POPUP_MARGIN)
            combo.setToolTip(combo.currentText())
            combo.currentTextChanged.connect(combo.setToolTip)
            combo.currentIndexChanged.connect(on_change)
            layout.addWidget(combo)
            self.channel_combos[channel] = combo

        remove_button = CrossButton()
        remove_button.setToolTip("Remove this packed texture")
        remove_button.setAutoDefault(False)  # Enter in a field must not remove the row
        remove_button.clicked.connect(lambda: on_remove(self))
        layout.addWidget(remove_button)

    def suffixes(self):
        return _split_keywords(self.suffixes_field.text())

    def channels(self):
        return {channel: combo.currentData() for channel, combo in self.channel_combos.items()
                if combo.currentData()}


class _RowsScroll(QtWidgets.QScrollArea):
    """Vertical-only scroll area as wide as its rows need.

    A plain scroll area does not pass that width on to the window, so the
    end of the rows (A list, cross) was cut. Here the minimum width is asked
    from the rows each time their layout changes (Painter's style widens the
    lists once the window shows)."""

    def __init__(self, content):
        super().__init__()
        self._scrolls = False
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setWidget(content)
        content.installEventFilter(self)

    def set_scrolls(self, scrolls):
        """True when the scroll bar shows: its width is added."""
        self._scrolls = scrolls
        self.updateGeometry()

    def eventFilter(self, watched, event):
        if watched is self.widget() and event.type() == QtCore.QEvent.LayoutRequest:
            self.updateGeometry()  # the window asks minimumSizeHint again
        return super().eventFilter(watched, event)

    def minimumSizeHint(self):
        width = self.widget().minimumSizeHint().width()
        if self._scrolls:
            width += self.verticalScrollBar().sizeHint().width()
        return QtCore.QSize(width, super().minimumSizeHint().height())

    def sizeHint(self):
        # The window opens at the narrow width; the lists grow when it is widened.
        return QtCore.QSize(self.minimumSizeHint().width(), super().sizeHint().height())


class PresetEditorDialog(QtWidgets.QDialog):
    """Create a preset (edited_preset=None) or modify an existing one.

    After exec(), saved_name() is the name of the saved preset, or "".
    """

    def __init__(self, start_preset, edited_preset=None, parent=None):
        super().__init__(parent)
        self._edited = edited_preset
        self._saved_name = ""
        self._data = {}
        self.setWindowTitle(f"Modify the preset \"{edited_preset}\"" if edited_preset
                            else "New naming preset")
        set_window_icon(self)

        layout =QtWidgets.QVBoxLayout(self)
        layout.setSpacing(0)  # every vertical gap is set explicitly
        # Inner padding of the window: twice Painter's default dialog margins.
        margins = layout.contentsMargins()
        layout.setContentsMargins(margins.left() * 2, margins.top() * 2,
                                  margins.right() * 2, margins.bottom() * 2)
        # Minimum width of the window through an invisible spacer, not with
        # setMinimumWidth: a fixed minimum would stop the window from growing
        # with its content (the packed rows would be cut).
        layout.addSpacerItem(QtWidgets.QSpacerItem(
            _MIN_WINDOW_WIDTH - margins.left() * 2 - margins.right() * 2, 0,
            QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed))

        # Name, and (creation only) the preset that pre-fills the window.
        top = QtWidgets.QGridLayout()
        top.setVerticalSpacing(_ROW_SPACING)
        top.setHorizontalSpacing(_LABEL_GAP)
        top.setColumnStretch(1, 1)
        self._add_section(layout, "Preset", first=True).addLayout(top)
        self.name_field = QtWidgets.QLineEdit(edited_preset or "")
        self.name_field.setPlaceholderText("e.g. Studio_X")
        _italic_when_empty(self.name_field)
        self.name_field.textChanged.connect(self._validate)
        top.addWidget(QtWidgets.QLabel("Name"), 0, 0)
        top.addWidget(self.name_field, 0, 1)
        self.start_combo = None
        self.rename_note = None
        if edited_preset:
            # Renaming is allowed; projects remember their preset by name, so
            # the closed ones built with it will not find it any more.
            self.rename_note = QtWidgets.QLabel(
                f"⚠ The other projects built with \"{edited_preset}\" will not find it "
                f"any more (the open project is updated).")
            self.rename_note.setWordWrap(True)
            self.rename_note.setStyleSheet(_WARNING_STYLE)
            self.rename_note.setVisible(False)
            top.addWidget(self.rename_note, 1, 1)
        else:
            self.start_combo = ComboBox()
            # Item data: the preset name, or None for the blank page (a preset
            # could be called "Blank page" too). The presets first, the blank
            # page last.
            for preset in list_presets():
                self.start_combo.addItem(preset, preset)
            self.start_combo.addItem(_BLANK_PAGE, None)
            self.start_combo.setCurrentIndex(max(self.start_combo.findData(start_preset), 0))
            self.start_combo.currentIndexChanged.connect(self._load_start)
            top.addWidget(QtWidgets.QLabel("Start from"), 1, 0)
            top.addWidget(self.start_combo, 1, 1)
            # Stays active while the fields are greyed: it can be read first.
            top.addWidget(InfoIcon(_START_TOOLTIP), 1, 2)

        # Everything below the name: greyed while the name is empty (_validate).
        # The message and the buttons below stay in the window, never greyed.
        window_layout = layout
        body = QtWidgets.QWidget()
        window_layout.addWidget(body)
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.body = body

        self.prefixes_field = QtWidgets.QLineEdit()
        self.prefixes_field.setPlaceholderText("e.g. TX_, SM_  (empty = names kept as they are)")
        _italic_when_empty(self.prefixes_field)
        self.prefixes_field.textChanged.connect(self._validate)
        # Label at the left, like the other fields of the window.
        prefixes_row = QtWidgets.QGridLayout()
        prefixes_row.setHorizontalSpacing(_LABEL_GAP)
        prefixes_row.setColumnStretch(1, 1)
        prefixes_row.addWidget(QtWidgets.QLabel("Prefixes"), 0, 0)
        prefixes_row.addWidget(self.prefixes_field, 0, 1)
        self._add_section(layout, "Asset prefixes", info=_PREFIXES_TOOLTIP).addLayout(prefixes_row)

        # One section, two sub-sections (like Painter's "Environment" /
        # "Shadows" inside "ENVIRONMENT SETTINGS"), no separator between them.
        suffixes_section = self._add_section(layout, "Asset suffixes")
        single = QtWidgets.QGridLayout()
        single.setVerticalSpacing(_ROW_SPACING)
        single.setHorizontalSpacing(_LABEL_GAP)
        single.setColumnStretch(1, 1)
        self._add_subsection(suffixes_section, "Unique textures",
                             info=_UNIQUE_TOOLTIP).addLayout(single)
        self.single_fields = {}
        for row, map_name in enumerate(SINGLE_MAPS):
            field = QtWidgets.QLineEdit()
            field.setPlaceholderText(f"e.g. {_SUFFIX_EXAMPLES.get(map_name, '_suffix')}")
            _italic_when_empty(field)
            field.textChanged.connect(self._validate)
            single.addWidget(QtWidgets.QLabel(map_name.title()), row, 0)
            single.addWidget(field, row, 1)
            self.single_fields[map_name] = field

        suffixes_section.addSpacing(_BETWEEN_SUBSECTIONS)
        packed_section = self._add_subsection(suffixes_section, "Packed textures",
                                              info=_PACKED_TOOLTIP)
        # The rows scroll beyond _MAX_VISIBLE_PACKED_ROWS (_fit_packed_scroll).
        packed_list = QtWidgets.QWidget()
        self.packed_layout = QtWidgets.QVBoxLayout(packed_list)
        self.packed_layout.setContentsMargins(0, 0, 0, 0)
        self.packed_layout.setSpacing(_ROW_SPACING)
        self.packed_scroll = _RowsScroll(packed_list)
        packed_section.addWidget(self.packed_scroll)
        self.packed_rows = []
        add_button = QtWidgets.QPushButton("+ Add a packed texture format")
        add_button.setAutoDefault(False)
        add_button.clicked.connect(lambda: self._add_packed_row([], {}, scroll_to=True))
        packed_section.addSpacing(_ROW_SPACING)
        packed_section.addWidget(add_button)

        layout.addSpacing(_ABOVE_SEPARATOR)
        window_layout.addStretch(1)
        # Error message on the same line as the buttons, at their left.
        bottom = QtWidgets.QHBoxLayout()
        bottom.setSpacing(_LABEL_GAP)
        window_layout.addLayout(bottom)
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        self.message.setStyleSheet(_WARNING_STYLE)
        bottom.addWidget(self.message, 1)

        buttons = QtWidgets.QDialogButtonBox()
        self.save_button = buttons.addButton("Save", QtWidgets.QDialogButtonBox.AcceptRole)
        self.save_button.setDefault(True)
        buttons.addButton("Cancel", QtWidgets.QDialogButtonBox.RejectRole).setAutoDefault(False)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        bottom.addWidget(buttons, 0, QtCore.Qt.AlignVCenter)

        if self.start_combo is not None:
            self._load_start()
        else:
            self._load(edited_preset)

    @staticmethod
    def _add_section(layout, title, first=False, info=None):
        """Separator line (except for the first section), title like the main
        panel (info: "i" icon at the far right of the title line), then an
        indented layout returned for the section content."""
        if not first:
            layout.addSpacing(_ABOVE_SEPARATOR)
            layout.addWidget(Separator())
            layout.addSpacing(_BELOW_SEPARATOR)
        label = QtWidgets.QLabel(title.upper())
        label.setStyleSheet(SECTION_TITLE_STYLE)
        title_row = QtWidgets.QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.addWidget(label, 1)
        if info:
            title_row.addWidget(InfoIcon(info))
        layout.addLayout(title_row)
        layout.addSpacing(_BELOW_TITLE)
        content = QtWidgets.QVBoxLayout()
        content.setContentsMargins(_CONTENT_INDENT, 0, 0, 0)
        content.setSpacing(0)
        layout.addLayout(content)
        return content

    def _add_subsection(self, layout, title, info=None):
        """Foldable sub-title (chevron at its left, then bold text, not
        uppercase; info: "i" icon at the far right of the line) inside a
        section, open by default, then an indented layout returned for its
        content."""
        header = QtWidgets.QWidget()
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        toggle = ChevronButton(sideways=True)
        toggle.setChecked(True)  # open: chevron pointing down
        toggle.setToolTip("Show / hide")
        header_layout.addWidget(toggle)
        title_label = QtWidgets.QLabel(title)
        title_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(title_label, 1)
        if info:
            icon = InfoIcon(info)
            # A click on the icon must not fold the sub-section (the line is clickable).
            icon.mousePressEvent = lambda event: event.accept()
            header_layout.addWidget(icon)
        # The whole line is clickable, not only the chevron (like the scan report).
        header.setCursor(QtCore.Qt.PointingHandCursor)
        header.mousePressEvent = lambda _event: toggle.toggle()
        layout.addWidget(header)

        # The gap below the sub-title folds with the content.
        body = QtWidgets.QWidget()
        body_layout = QtWidgets.QVBoxLayout(body)
        body_layout.setContentsMargins(0, _BELOW_SUBTITLE, 0, 0)
        layout.addWidget(body)
        toggle.toggled.connect(body.setVisible)
        toggle.toggled.connect(self._fit_height)
        content = QtWidgets.QVBoxLayout()
        content.setContentsMargins(_CONTENT_INDENT, 0, 0, 0)
        content.setSpacing(0)
        body_layout.addLayout(content)
        return content

    def _fit_height(self):
        """Window height back to its content (after a fold): no empty space
        left above the buttons. Width unchanged. Done once the layout has
        taken the change into account."""
        QtCore.QTimer.singleShot(0, lambda: self.resize(self.width(), self.sizeHint().height()))

    def saved_name(self):
        return self._saved_name

    # ------------------------------------------------------------------

    def _load_start(self):
        """Fill the window with the choice of "Start from"."""
        preset = self.start_combo.currentData()
        self._load(preset, blank=preset is None)

    def _load(self, preset_name, blank=False):
        """Fill the window with a preset (the starting one, or the edited one).

        blank: every field empty (their examples show). The rest of the file
        (_info, extensions) still comes from the protected preset, as for a
        preset started from it."""
        try:
            self._data = read_preset_data(PROTECTED_PRESET if blank else preset_name) \
                if (blank or preset_name) else {}
        except NamingConfigError as error:
            self._data = {}
            if not blank:  # a blank page works without the protected preset
                show_message(self, str(error), warning=True)
        if blank:
            for section in ("texture_formats", "packed_formats", "asset_prefixes"):
                self._data.pop(section, None)
        formats = self._data.get("texture_formats")
        formats = formats if isinstance(formats, dict) else {}
        prefixes = self._data.get("asset_prefixes")
        self.prefixes_field.setText(
            _join_keywords(prefixes) if isinstance(prefixes, list) else "")
        for map_name, field in self.single_fields.items():
            keywords = formats.get(map_name)
            field.setText(_join_keywords(keywords) if isinstance(keywords, list) else "")

        for row in list(self.packed_rows):
            self._remove_packed_row(row, validate=False)
        packed = self._data.get("packed_formats")
        for entry in (packed.values() if isinstance(packed, dict) else ()):
            if isinstance(entry, dict):
                suffixes = entry.get("suffixes")
                self._add_packed_row(suffixes if isinstance(suffixes, list) else [],
                                     {ch: entry[ch] for ch in PACKED_CHANNELS if ch in entry})
        self._validate()

    def _add_packed_row(self, suffixes, channels, scroll_to=False):
        row = _PackedRow(suffixes, channels, self._validate, self._remove_packed_row)
        self.packed_rows.append(row)
        self.packed_layout.addWidget(row)
        self._fit_packed_scroll()
        if scroll_to:  # added with the button: the new row is shown, even beyond 5
            # Bottom of the list (the new row is the last), never sideways.
            bar = self.packed_scroll.verticalScrollBar()
            QtCore.QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))
        self._validate()

    def _remove_packed_row(self, row, validate=True):
        self.packed_rows.remove(row)
        row.deleteLater()
        self._fit_packed_scroll()
        if validate:
            self._validate()

    def _fit_packed_scroll(self):
        """Packed rows area exactly as high as its rows, up to
        _MAX_VISIBLE_PACKED_ROWS; beyond, it scrolls. Empty: no height.
        When the scroll bar shows, a gap keeps it away from the crosses."""
        shown = min(len(self.packed_rows), _MAX_VISIBLE_PACKED_ROWS)
        if not shown:
            self.packed_scroll.setFixedHeight(0)
            return
        scrolls = len(self.packed_rows) > _MAX_VISIBLE_PACKED_ROWS
        self.packed_layout.setContentsMargins(0, 0, _SCROLLBAR_GAP if scrolls else 0, 0)
        self.packed_scroll.set_scrolls(scrolls)
        row_height = self.packed_rows[0].sizeHint().height()  # every row has the same widgets
        self.packed_scroll.setFixedHeight(shown * row_height + (shown - 1) * _ROW_SPACING)

    def _collect(self):
        """Preset content from the window: the edited sections replace those of
        the loaded preset, everything else is kept."""
        data = copy.deepcopy(self._data)
        formats = data.get("texture_formats")
        formats = dict(formats) if isinstance(formats, dict) else {}
        for map_name, field in self.single_fields.items():
            formats[map_name] = _split_keywords(field.text())
        data["texture_formats"] = formats
        data["packed_formats"] = {
            _packed_name(row.suffixes()): dict(suffixes=row.suffixes(), **row.channels())
            for row in self.packed_rows}
        data["asset_prefixes"] = _split_keywords(self.prefixes_field.text())
        data.setdefault("extensions", [".png", ".tga", ".jpg", ".jpeg", ".tif", ".tiff", ".exr"])
        return data

    def _problem(self):
        """First problem preventing the save, written for the artist, or ""."""
        problem = check_new_preset_name(self.name_field.text().strip(), current=self._edited)
        if problem:
            return problem
        problem = _format_problem(self.prefixes_field.text(), prefix=True)
        if problem:
            return f"Asset prefixes: {problem}"
        for map_name, field in self.single_fields.items():
            problem = _format_problem(field.text())
            if problem:
                return f"{map_name.title()}: {problem}"
            if not _split_keywords(field.text()):
                return f"{map_name.title()}: enter at least one suffix."
        names = []
        for number, row in enumerate(self.packed_rows, 1):
            problem = _format_problem(row.suffixes_field.text())
            if problem:
                return f"Packed texture {number}: {problem}"
            if not row.suffixes():
                return f"Packed texture {number}: enter at least one suffix."
            if not row.channels():
                return f"Packed texture {number}: choose the map of at least one channel."
            name = _packed_name(row.suffixes())
            if name in names:
                return (f"Two packed textures start with the same suffix "
                        f"\"{row.suffixes()[0]}\".")
            names.append(name)
        try:
            check_preset_data(self._collect())
        except NamingConfigError as error:
            return str(error)[:1].upper() + str(error)[1:]
        return ""

    def _validate(self):
        problem = self._problem()
        self.message.setText(f"⚠ {problem}" if problem else "")
        self.save_button.setEnabled(not problem)
        # A new preset is named first; an edited preset always has its name
        # (an emptied name only disables "Save").
        named = bool(self._edited or self.name_field.text().strip())
        self.body.setEnabled(named)
        if self.rename_note is not None:
            # A case-only change breaks no project (names compared without case).
            self.rename_note.setVisible(
                self.name_field.text().strip().lower() != self._edited.lower())
        if self.start_combo is not None:
            self.start_combo.setEnabled(named)

    def _renamed(self):
        """True when an edited preset gets another name (case included)."""
        return bool(self._edited) and self.name_field.text().strip() != self._edited

    def _on_save(self):
        name = self.name_field.text().strip()
        try:
            if self._renamed():
                rename_preset(self._edited, name, self._collect())
            else:
                save_preset(name, self._collect())
        except NamingConfigError as error:
            show_message(self, str(error), warning=True)
            return
        self._saved_name = name
        self.accept()
