"""MAPPING section: atlas grid + asset list with their Atlas ID.

Pure PySide6. All rules (statuses, conflicts) come from
core/atlas_assignment.py; this module only displays them and forwards the
artist's choices.

    grid        "Grid NxN" label, then one cell per Atlas ID (grid centered in the
                section width), in atlas reading order; its number
                shows the status (grey = empty, light = ready, orange = warning);
                clicking a cell selects the asset placed in it and scrolls the
                list to center its line; an empty cell has no hand cursor and
                explains at once, on hover, how to fill it;
                with "Frame viewport on click", a click also asks to frame the
                cell's meshes (cell_framing_requested), even in an empty cell,
                and a new click on a cell with several meshes goes to the next
                one without deselecting (workflow.md §11.1);
    framing     "Frame viewport on click" check box, under "Grid NxN", left of the grid;
    note        choices restored from the last Build, if any, and the number of
                Atlas IDs pre-filled from the mesh names and UVs (workflow.md §12.1);
    normal      default normal format of the source files; an asset can have its
                own ("Source format" in its details), then shown after its name;
                the Painter project format is in CONFIGURATION (main_panel.py);
    asset list  (the only part that scrolls) one line per asset: fold arrow, name,
                status, Atlas ID drop-down; "Pre-filled" after the name while its
                ID comes from the pre-fill and the artist has not changed it;
                an asset without ID is greyed: it is not created at Build;
                the arrow (or a click on the line) unfolds its map details, where
                the source normal format can be changed for this asset only.
                Several assets can be unfolded; choosing an ID never unfolds.
                Hovering a cell or a line outlines the cell (cross-hover).
                A map taken from a packed file shows its origin in italics ("ORM · B").
"""

import html

from PySide6 import QtCore, QtWidgets

from ..core.atlas_assignment import (
    GLOSSINESS_TEXTURE_FORMAT, NORMAL_DIRECTX, NORMAL_FORMATS, NORMAL_OPENGL, NORMAL_TEXTURE_FORMAT,
    NORMAL_UNCERTAIN, STATUS_EMPTY, STATUS_NO_ID, STATUS_READY, STATUS_WARNING, cell_row_column)
from .widgets import (
    SHORT_FIELD_WIDTH, ChevronButton, ComboBox, InfoIcon, wrap_tooltip)

# Status symbols of the asset list (the grid cells show the status by color).
STATUS_ICONS = {STATUS_READY: "✓", STATUS_WARNING: "⚠", STATUS_NO_ID: "○", STATUS_EMPTY: ""}

_NO_ID_TEXT = "—"

NORMAL_LABELS = {NORMAL_OPENGL: "OpenGL", NORMAL_DIRECTX: "DirectX"}
_SOURCE_TOOLTIP = ("Format of the SOURCE normal map (the file).\n"
                   "If it differs from the project, the Green channel is inverted at Build "
                   "(Levels effect under the asset's Fill).")
_DEFAULT_NORMAL_TOOLTIP = (
    "Format (OpenGL / DirectX) of the imported normal maps, used by every asset "
    "that has no setting of its own.\n"
    "An asset can have a different format: unfold it and change \"Source format\" "
    "under its Normal line. Its format is then shown after its name.")
# Format shown after the name of an asset that differs from the default.
_NORMAL_BADGE_STYLE = "color: #a0a0a0;"
# On the asset line, the format and "Pre-filled" get lighter under the mouse:
# they have a tooltip (2026-10-09).
_BADGE_HOVER_STYLE = "QLabel {{ color: #a0a0a0; {extra} }} QLabel:hover {{ color: #e5e5e5; }}"
_NORMAL_BADGE_TOOLTIP = "Normal format of this asset only (\"Source format\")."
# Between the format and "Pre-filled" when both show.
_BADGE_SEPARATOR = "|"
# Atlas ID pre-filled from the mesh names and UVs (workflow.md §12.1), shown
# after the name until the artist changes that ID.
_PREFILL_TEXT = "Pre-filled"
_PREFILL_TOOLTIP = ("ID {atlas_id} pre-filled from the mesh {meshes}: its name matches this "
                    "asset and its UVs lie in cell {atlas_id}.\nCheck it, or choose another ID.")
_PREFILL_NOTE = "{count} Atlas ID{s} pre-filled from the mesh names and UVs: check them before the Build."
# Under "Source format": what the scan read in the normal map (workflow.md §20.1.1).
_DETECTED_TEXTS = {NORMAL_OPENGL: "Detected: OpenGL", NORMAL_DIRECTX: "Detected: DirectX",
                   NORMAL_UNCERTAIN: "Detected: uncertain, check visually"}
_DETECTED_TOOLTIP = (
    "Read from the pixels of the normal map at scan. A sure result fills \"Source format\" "
    "for a new asset; an asset already built keeps your choice.\n"
    "Mirrored or overlapping UV islands make the result uncertain.")
_CHOOSE_TEXT = "Choose…"
_CELL_SIZE = 32     # pixels: the Atlas ID only (status shown by its color)
_CELL_SPACING = 2
_DETAIL_INDENT = 22
_SUB_INDENT = 10    # content under "Asset list", as under a section title
# Between the "Source normal map format" list and its "i" icon: the gap of
# the CONFIGURATION lines (measured on a Painter screenshot: 26 screen px
# at the 125 % display scale).
_INFO_ICON_GAP = 20

# Cell colors: (background, hover background, text). Empty cells are darker.
# The cell is too small for the status icon: the color of its number shows
# the status (orange = warning, as the ⚠ icon of the list).
_WARNING_COLOR = "#e6a23c"  # orange of the plugin's warnings (scan report, preset editor)
_CELL_COLORS = {
    STATUS_EMPTY: ("#2b2b2b", "#3a3a3a", "#777777"),
    STATUS_READY: ("#3e3e3e", "#4c4c4c", "#e5e5e5"),
    STATUS_WARNING: ("#3e3e3e", "#4c4c4c", _WARNING_COLOR),
}
_CELL_BORDER = "#262626"
# Selected cell: white, like Painter's titles. Not Painter's blue: in this
# panel blue means "next step to click" (Scan folder, Build Atlas).
_SELECTED_BORDER = "#e5e5e5"
# Hovered cell, or cell of the hovered asset line: visible, but quieter
# than the selection.
_HOVER_BORDER = "#808080"

# Cells: white border = selected, grey border = hovered.
# Asset lines: lighter background = hovered or selected (no border).
_ROW_HOVER = "#3e3e3e"
# Line of the selected asset: lighter than a hovered line, with a white bar
# on its left that echoes the white border of its cell.
_ROW_SELECTED = "#4a4a4a"
_SELECTED_BAR = 1  # pixels
_NAME_STYLE = "font-weight: bold;"
# Map details: the hovered line of a found map (✓, or ⚠ file to choose)
# gets a slightly lighter text (Painter's text is light grey). Missing maps
# (—) and "Source format" stay unchanged. Set once on the details block.
_DETAILS_STYLE = 'QLabel[hoverable="true"]:hover { color: #ffffff; }'


class _InstantTooltip(QtCore.QObject):
    """Shows the tooltip of a details line (file name, packed routing) as
    soon as the mouse enters it: a Qt tooltip waits ~0.7 s."""

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Enter and watched.toolTip():
            # Under the mouse, like a Qt tooltip; hidden when it leaves the line.
            QtWidgets.QToolTip.showText(
                event.globalPosition().toPoint(), watched.toolTip(), watched, watched.rect())
        elif event.type() == QtCore.QEvent.Leave:
            QtWidgets.QToolTip.hideText()
        elif event.type() == QtCore.QEvent.ToolTip:
            return True  # already shown: no second, delayed tooltip
        return False


def _hoverable(label):
    """Mark a details line that lights up on hover (_DETAILS_STYLE) and
    shows its tooltip at once."""
    label.setProperty("hoverable", True)
    label.installEventFilter(_InstantTooltip(label))  # kept alive by the label
    return label
# Asset without Atlas ID: greyed, it is ignored at Build (placed_assets()).
_UNUSED_COLOR = "#777777"
_UNUSED_TOOLTIP = "No ID: this asset will not be created."
# Shown at once when the mouse enters an empty cell.
_EMPTY_CELL_TOOLTIP = ("Empty cell. To fill it, choose ID {atlas_id} in the ID list of an asset. "
                       "It can also stay unused.")
# Viewport framing (workflow.md §11.1): an empty cell whose UVs hold a mesh.
_EMPTY_FRAMED_CELL_TOOLTIP = ("Empty cell. Click to frame its mesh in the viewport ({meshes}). "
                              "To fill it, choose ID {atlas_id} in the ID list of an asset.")
_NEXT_MESH_TOOLTIP = "{count} meshes in this cell: click it again to frame the next one."
_FRAME_VIEWPORT_TEXT = "Frame viewport on click"
_FRAME_VIEWPORT_TOOLTIP = (
    "Click a cell to frame, in the viewport, the mesh whose UVs lie in it.\n"
    "Several meshes in a cell: click again for the next one.\n\n"
    "To turn around the asset, put the cursor on it before Alt + Left.\n\n"
    "Binary FBX or OBJ meshes. Only the camera moves.")
# Between the "Frame viewport on click" text and its "i" icon.
_CHECK_INFO_GAP = 8
# Between "Grid NxN" and "Frame viewport on click", left of the grid.
_GRID_COLUMN_SPACING = 8
_MESH_SEPARATOR = " · "
# Vertical gap between two asset lines, kept small like Painter's foldable
# groups (Display Settings): the hover background tells the lines apart.
_ASSET_LINE_SPACING = 2
# Between the asset lines and the scroll bar, while it shows (as in the
# preset editor): a highlighted line does not touch the bar.
_SCROLLBAR_GAP = 8
# Smallest height of the asset list: about 4 asset lines (an asset line is
# ~32 px at 100 % display scale).
_MIN_LIST_HEIGHT = 130


def _cell_style(status, selected, linked_hover):
    """Painter's button style sets a minimum width and margins: replaced here.
    The size must be in the style sheet: style sheet sizes override setFixedSize().

    linked_hover: the asset line of this cell is hovered (cross-hover).
    A hovered cell gets a 1-pixel grey border; the selection border wins.
    """
    background, hover, text = _CELL_COLORS[status]
    if linked_hover:
        background = hover
    if selected:
        border = hover_border = _SELECTED_BORDER
    else:
        border = _HOVER_BORDER if linked_hover else _CELL_BORDER
        hover_border = _HOVER_BORDER
    return (f"QPushButton {{ margin: 0px; padding: 0px; "
            f"min-width: {_CELL_SIZE}px; max-width: {_CELL_SIZE}px; "
            f"min-height: {_CELL_SIZE}px; max-height: {_CELL_SIZE}px; "
            f"background-color: {background}; color: {text}; border: 1px solid {border}; }}"
            f"QPushButton:hover {{ background-color: {hover}; border-color: {hover_border}; }}")


def _row_style(selected, linked_hover):
    """selected: the asset is selected (white cell): lighter background and a
    white bar on the left, kept while the mouse is on the line.
    linked_hover: its grid cell is hovered (cross-hover): the hover
    background, even without the mouse on the line."""
    # The bar is always there (transparent when not selected): selecting a
    # line never shifts its content sideways.
    bar = _SELECTED_BORDER if selected else "transparent"
    if selected:
        background = hover = _ROW_SELECTED
    else:
        background = _ROW_HOVER if linked_hover else "transparent"
        hover = _ROW_HOVER
    # Scoped by objectName: the labels and drop-down inside are not affected.
    return (f"#AssetRow {{ border-radius: 2px; border-left: {_SELECTED_BAR}px solid {bar}; "
            f"background-color: {background}; }}"
            f"#AssetRow:hover {{ background-color: {hover}; }}")


def _panel_combo():
    """Drop-down list of the panel without keyboard focus: Painter's style
    draws the current entry of the last used list in blue, which reads as a
    selection or a next step. Mouse use is unchanged."""
    combo = ComboBox()
    combo.setFocusPolicy(QtCore.Qt.NoFocus)
    return combo


def _sub_title(text):
    """"Grid NxN" and "Asset list": bold, so the two parts of MAPPING stand
    apart (decided 2026-10-09)."""
    label = QtWidgets.QLabel(text)
    label.setStyleSheet("font-weight: bold;")
    return label


def _set_style(widget, style):
    """Apply a style sheet only if it changes. Applying one makes Qt recompute
    and redraw the widget and everything inside it (labels, drop-down lists):
    doing it for every cell and line on each hover made the panel lag."""
    if widget.styleSheet() != style:
        widget.setStyleSheet(style)


def _restore_note(report):
    """What was restored from the last Build (core/build_memory.py), as rich
    text, or "". The ⚠ lines are orange, the "restored" line keeps the
    normal color."""
    if report is None or not (report.restored or report.missing):
        return ""
    lines = []
    if report.restored:
        count = len(report.restored)
        lines.append(f"Choices of the last Build restored ({count} asset{'s' if count > 1 else ''}).")
    if report.grid_changed and report.restored:
        size = report.saved_grid_size
        lines.append(f"⚠ The last Build used a {size}x{size} grid: "
                     "the IDs are not restored for this grid.")
    if report.preset_changed:
        lines.append(f"⚠ The last Build used the naming preset \"{report.saved_preset}\": "
                     "some files may be recognized differently.")
    if report.missing:
        lines.append(f"⚠ Missing from the folder: {', '.join(report.missing)}")
    return "<br>".join(
        f'<span style="color: {_WARNING_COLOR};">{html.escape(line)}</span>'
        if line.startswith("⚠") else html.escape(line)
        for line in lines)


_ISSUES_SEPARATOR = " · "
_WARNING_TEXT_GAP = 4  # pixels between the ⚠ and its warning text


class _IssuesLabel(QtWidgets.QLabel):
    """Warnings of an asset on its line, next to the ⚠, in a few words
    ("Duplicate · ID 1 already used"), orange italics even when the asset
    has no ID. The full sentences (which map, which other asset) are in the
    tooltip of the whole asset line (_refresh), not here: a second tooltip
    competed with the line's. Never widens the panel: cut with "…" when the
    line is too narrow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._short = ""
        self.setStyleSheet(f"color: {_WARNING_COLOR}; font-style: italic;")
        # Takes the width it is given, never asks for more.
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)

    def set_issues(self, issues):
        """issues: [AssetIssue] (core/atlas_assignment.py)."""
        # "Duplicate" once, even for several duplicated maps.
        short = _ISSUES_SEPARATOR.join(dict.fromkeys(issue.short for issue in issues))
        if short != self._short:
            self._short = short
            self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(self._short, QtCore.Qt.ElideRight,
                                                   self.width()))


class _CellButton(QtWidgets.QPushButton):
    """Grid cell that reports when the mouse enters / leaves it."""

    hovered = QtCore.Signal(bool)

    def enterEvent(self, event):
        self.hovered.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit(False)
        super().leaveEvent(event)


class _ClickableRow(QtWidgets.QWidget):
    """Asset line: a click anywhere outside the drop-down selects the asset."""

    clicked = QtCore.Signal()
    hovered = QtCore.Signal(bool)

    def enterEvent(self, event):
        self.hovered.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit(False)
        super().leaveEvent(event)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AssetRow")
        # Needed for a plain QWidget to draw a style sheet background and :hover.
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setAttribute(QtCore.Qt.WA_Hover, True)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class MappingWidget(QtWidgets.QWidget):
    """Grid + asset list for one AtlasAssignment."""

    # Emitted after the artist changes an Atlas ID, a file or a normal map
    # format: the line above "Build Atlas" is recomputed.
    assignment_changed = QtCore.Signal()
    # Emitted with (Atlas ID, clicked again) when a click on a cell must frame
    # the viewport on its meshes; clicked again = go to the next mesh.
    cell_framing_requested = QtCore.Signal(int, bool)
    # Emitted with the new state when the artist checks / unchecks
    # "Frame viewport on click" (under the grid).
    frame_viewport_changed = QtCore.Signal(bool)

    def __init__(self, assignment, format_order, restore_report=None, frame_viewport=True,
                 parent=None):
        """frame_viewport: initial state of "Frame viewport on click" (kept by
        the plugin between scans and Painter sessions)."""
        super().__init__(parent)
        self.assignment = assignment
        self._format_order = format_order  # map order of the naming preset (packed excluded)
        self._selected = None              # selected asset, or None
        self._expanded = set()             # id() of the unfolded assets
        self._hovered_asset = None         # asset line under the mouse, or None
        self._hovered_cell = None          # Atlas ID of the cell under the mouse, or None
        self._cells = {}                   # Atlas ID -> cell button
        # [(asset, line, status label, name label, details widget, fold arrow)]
        self._rows = []
        self._scroll = None                # scroll area of the asset list
        self._normal_badges = {}           # id(asset) -> label of its own normal format
        self._issue_labels = {}            # id(asset) -> _IssuesLabel next to its ⚠
        self._prefill_labels = {}          # id(asset) -> "Pre-filled" label
        self._badge_separators = {}        # id(asset) -> "|" between format and "Pre-filled"
        # Viewport framing: {Atlas ID: [mesh names of each target]}, and the
        # cell framed by the last click (set_framing_targets).
        self._framing = {}
        self._framing_on = False
        self._framed_cell = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._build_grid_row(frame_viewport))
        # Title of the list, outside the scroll: it always stays visible.
        layout.addWidget(_sub_title("Asset list"))
        # Under "Asset list", shifted one step right: what was restored from
        # the last Build, the default normal format (both concern the listed
        # assets), then the list itself. The grid above never moves.
        assets_block = QtWidgets.QVBoxLayout()
        assets_block.setContentsMargins(_SUB_INDENT, 0, 0, 0)
        assets_block.setSpacing(layout.spacing())
        layout.addLayout(assets_block, 1)
        note = _restore_note(restore_report)
        if note:
            note_label = QtWidgets.QLabel(note)
            note_label.setTextFormat(QtCore.Qt.RichText)  # orange ⚠ lines
            note_label.setWordWrap(True)
            note_label.setStyleSheet("font-style: italic;")  # a status, not a setting
            assets_block.addWidget(note_label)
        prefilled = sum(1 for asset in assignment.assets if assignment.prefill(asset))
        if prefilled:
            prefill_label = QtWidgets.QLabel(
                _PREFILL_NOTE.format(count=prefilled, s="s" if prefilled > 1 else ""))
            prefill_label.setWordWrap(True)
            prefill_label.setStyleSheet("font-style: italic;")  # a status, like the note above
            assets_block.addWidget(prefill_label)
        assets_block.addWidget(self._build_normal_rows())

        # Only the asset list scrolls: the grid above always stays visible.
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        asset_list = QtWidgets.QWidget()
        list_layout = QtWidgets.QVBoxLayout(asset_list)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(_ASSET_LINE_SPACING)
        for asset in assignment.assets:
            list_layout.addWidget(self._build_asset_row(asset))
        list_layout.addStretch(1)
        scroll.setWidget(asset_list)
        # Never squeezed below a few lines: in a short panel, the whole panel
        # scrolls instead (FallbackScroll in ui/main_panel.py).
        scroll.setMinimumHeight(_MIN_LIST_HEIGHT)
        assets_block.addWidget(scroll, 1)
        self._scroll = scroll
        # The bar shows when the list is longer than the visible height
        # (range above 0): only then the lines leave a gap for it.
        scroll.verticalScrollBar().rangeChanged.connect(
            lambda _minimum, maximum: list_layout.setContentsMargins(
                0, 0, _SCROLLBAR_GAP if maximum > 0 else 0, 0))

        self._refresh()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_grid_row(self, frame_viewport):
        """'Grid NxN' on the left with "Frame viewport on click" under it (both
        belong to the grid, decided 2026-10-08), the grid centered in the
        width left on their right. Until then the grid was centered in the
        whole width, with an empty space as wide as the label on its right:
        the check box line is too wide for that."""
        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        column = QtWidgets.QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(_GRID_COLUMN_SPACING)
        # Follows the grid chosen in CONFIGURATION (a new grid rebuilds this widget).
        size = self.assignment.grid_size
        # Top of the label level with the top of the first row of cells.
        column.addWidget(_sub_title(f"Grid {size}x{size}"))
        column.addWidget(self._build_framing_row(frame_viewport))
        column.addStretch(1)
        row_layout.addLayout(column)
        row_layout.addStretch(1)
        row_layout.addWidget(self._build_grid())
        row_layout.addStretch(1)
        return row

    def _build_grid(self):
        grid_widget = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(_CELL_SPACING)
        for atlas_id in self.assignment.valid_ids():
            cell = _CellButton()  # size set by _cell_style(), cursor by _refresh()
            cell.clicked.connect(lambda _checked=False, i=atlas_id: self._on_cell_clicked(i))
            cell.hovered.connect(lambda inside, i=atlas_id: self._on_cell_hovered(i, inside))
            row, column = cell_row_column(atlas_id, self.assignment.grid_size)
            grid.addWidget(cell, row, column)
            self._cells[atlas_id] = cell
        return grid_widget

    def _build_framing_row(self, checked):
        """Check box before its text, like Painter's check boxes, then the
        "i" icon right after the text. Navigation only, never used by the
        Build (workflow.md §11.1)."""
        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        check = QtWidgets.QCheckBox(_FRAME_VIEWPORT_TEXT)
        check.setChecked(checked)
        check.setFocusPolicy(QtCore.Qt.NoFocus)  # no blue focus frame after a click
        check.toggled.connect(self.frame_viewport_changed.emit)
        row_layout.addWidget(check)
        row_layout.addSpacing(_CHECK_INFO_GAP)
        row_layout.addWidget(InfoIcon(_FRAME_VIEWPORT_TOOLTIP))
        row_layout.addStretch(1)
        return row

    def _build_normal_rows(self):
        """Default source format of the assets (the project format is in
        CONFIGURATION). Explanation behind the "i" icon at the far right."""
        rows = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(rows)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)  # every gap of the line is set below
        row_layout.addWidget(QtWidgets.QLabel("Source normal map format"))
        combo = _panel_combo()
        for normal_format in NORMAL_FORMATS:
            combo.addItem(NORMAL_LABELS[normal_format], normal_format)
        combo.setCurrentIndex(combo.findData(self.assignment.default_normal_format))
        combo.currentIndexChanged.connect(
            lambda _index: self._on_default_normal_chosen(combo.currentData()))
        # Short list at the right, next to the "i" icon, like the lists of
        # CONFIGURATION: a clear gap after the label.
        combo.setFixedWidth(SHORT_FIELD_WIDTH)
        row_layout.addStretch(1)
        row_layout.addWidget(combo)
        row_layout.addSpacing(_INFO_ICON_GAP)
        row_layout.addWidget(InfoIcon(_DEFAULT_NORMAL_TOOLTIP))
        return rows

    def _build_asset_row(self, asset):
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(4)

        line = _ClickableRow()
        # Like Painter's foldable groups: a click on the line folds / unfolds.
        line.clicked.connect(lambda a=asset: self._toggle_details(a))
        line.hovered.connect(lambda inside, a=asset: self._on_row_hovered(a, inside))
        line_layout = QtWidgets.QHBoxLayout(line)
        line_layout.setContentsMargins(0, 1, 4, 1)  # room for the hover background

        arrow = ChevronButton(sideways=True)
        arrow.setToolTip("Show / hide the map details")
        arrow.clicked.connect(lambda _checked=False, a=asset: self._toggle_details(a))
        line_layout.addWidget(arrow)

        name = QtWidgets.QLabel(asset.name)
        name.setStyleSheet(_NAME_STYLE)
        line_layout.addWidget(name)

        # Normal badge, "Pre-filled", status icon and warning text: grouped,
        # with a small gap. The badges come first so the ⚠ stays right
        # before its text, which reads as its explanation (2026-10-09).
        status_group = QtWidgets.QHBoxLayout()
        status_group.setSpacing(_WARNING_TEXT_GAP)
        line_layout.addLayout(status_group, 1)
        # "DirectX" / "OpenGL" when this asset differs from the default format
        # (hidden when empty: no extra gap).
        badge = QtWidgets.QLabel()
        badge.setStyleSheet(_BADGE_HOVER_STYLE.format(extra=""))
        badge.setToolTip(wrap_tooltip(_NORMAL_BADGE_TOOLTIP))
        badge.setVisible(False)
        status_group.addWidget(badge)
        self._normal_badges[id(asset)] = badge
        # "|" between the format and "Pre-filled", only when both show.
        separator = QtWidgets.QLabel(_BADGE_SEPARATOR)
        separator.setStyleSheet(_NORMAL_BADGE_STYLE)
        separator.setVisible(False)
        status_group.addWidget(separator)
        self._badge_separators[id(asset)] = separator
        # "Pre-filled" while the ID comes from the mesh names and UVs.
        prefill = QtWidgets.QLabel(_PREFILL_TEXT)
        prefill.setStyleSheet(_BADGE_HOVER_STYLE.format(extra="font-style: italic;"))
        prefill.setVisible(False)
        status_group.addWidget(prefill)
        self._prefill_labels[id(asset)] = prefill
        status = QtWidgets.QLabel()
        status_group.addWidget(status)
        # What the ⚠ means, readable without unfolding; takes the free room
        # up to "ID" (empty: just a gap), cut with "…" when too long.
        issues = _IssuesLabel()
        status_group.addWidget(issues, 1)
        self._issue_labels[id(asset)] = issues

        line_layout.addWidget(QtWidgets.QLabel("ID"))
        combo = _panel_combo()
        combo.addItem(_NO_ID_TEXT, None)  # entry 0 = no ID
        valid_ids = list(self.assignment.valid_ids())
        for atlas_id in valid_ids:
            combo.addItem(str(atlas_id), atlas_id)
        # Show the ID already assigned (restored from the last Build), set
        # before connecting so it is not taken as an artist's change.
        current_id = self.assignment.atlas_id(asset)
        if current_id in valid_ids:
            combo.setCurrentIndex(valid_ids.index(current_id) + 1)
        combo.currentIndexChanged.connect(
            lambda _index, a=asset, c=combo: self._on_id_chosen(a, c.currentData()))
        line_layout.addWidget(combo)
        container_layout.addWidget(line)

        details = QtWidgets.QWidget()
        details_layout = QtWidgets.QVBoxLayout(details)
        details_layout.setContentsMargins(_DETAIL_INDENT, 0, 0, 0)
        details_layout.setSpacing(2)
        details.setStyleSheet(_DETAILS_STYLE)
        container_layout.addWidget(details)

        self._rows.append((asset, line, status, name, details, arrow))
        return container

    def _fill_details(self, asset, details):
        """Map lines (✓ found, — missing, file choice for duplicates), packed
        files."""
        layout = details.layout()
        while layout.count():
            layout.takeAt(0).widget().deleteLater()

        grouped = asset.textures_by_format()
        maps = self.assignment.resolved_maps(asset)
        glossiness_replaced = self.assignment.glossiness_replaced(asset)
        for texture_format in self._format_order:
            textures = grouped.get(texture_format, [])
            source = maps.get(texture_format)
            if len(textures) > 1:
                layout.addWidget(self._duplicate_choice_row(asset, texture_format, textures))
            elif texture_format == GLOSSINESS_TEXTURE_FORMAT and glossiness_replaced:
                gap = "&nbsp;" * 3
                label = QtWidgets.QLabel(f"{html.escape(texture_format.title())}{gap}✓{gap}"
                                         f"<i>replaced by Roughness</i>")
                label.setTextFormat(QtCore.Qt.RichText)
                label.setToolTip(wrap_tooltip("This asset has a Roughness and a Glossiness: "
                                              "the Roughness is used, the Glossiness is ignored."))
                layout.addWidget(_hoverable(label))
            elif source is not None and source.channel is not None:
                # Map read from one channel of a packed file.
                origin = f"{self.assignment.format_label(source.packed_format)} · {source.channel}"
                # Rich text: the origin in italics; &nbsp; keeps the spaces
                # that HTML would otherwise merge into one.
                gap = "&nbsp;" * 3
                label = QtWidgets.QLabel(
                    f"{html.escape(texture_format.title())}{gap}✓{gap}<i>{html.escape(origin)}</i>")
                label.setTextFormat(QtCore.Qt.RichText)
                label.setToolTip(f"{source.texture.relative_path}\nchannel {source.channel}")
                layout.addWidget(_hoverable(label))
            else:
                mark = "✓" if textures else _NO_ID_TEXT
                label = QtWidgets.QLabel(f"{texture_format.title()}   {mark}")
                # File name only on hover, to keep the list light.
                if textures:
                    label.setToolTip(textures[0].relative_path)
                    _hoverable(label)  # missing map (—): no highlight
                layout.addWidget(label)
            if texture_format == NORMAL_TEXTURE_FORMAT and (textures or source is not None):
                layout.addWidget(self._normal_format_row(asset))

        for packed_format, channels in self.assignment.packed_channels.items():
            textures = grouped.get(packed_format, [])
            if len(textures) > 1:
                layout.addWidget(self._duplicate_choice_row(asset, packed_format, textures))
            elif textures:
                label = QtWidgets.QLabel(f"{self.assignment.format_label(packed_format)}   ✓")
                label.setToolTip(self._packed_tooltip(textures[0], channels, grouped))
                layout.addWidget(_hoverable(label))

        # The warnings themselves (ID used twice...) are written on the asset
        # line, next to its ⚠ (_refresh): readable without unfolding.

    @staticmethod
    def _packed_tooltip(texture, channels, grouped):
        """File + channel routing; a map that has its own file is marked as replaced."""
        lines = [texture.relative_path]
        for channel, map_name in channels.items():
            replaced = "   (replaced by its own file)" if map_name in grouped else ""
            lines.append(f"{channel} → {map_name.title()}{replaced}")
        return "\n".join(lines)

    def _normal_format_row(self, asset):
        """'Source format [Default (OpenGL) ▾]' under the Normal line of one asset."""
        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(_DETAIL_INDENT, 0, 0, 0)
        row_layout.addWidget(QtWidgets.QLabel("Source format"))
        combo = _panel_combo()
        combo.setToolTip(wrap_tooltip(_SOURCE_TOOLTIP))
        default_label = NORMAL_LABELS[self.assignment.default_normal_format]
        # "" = follow the default (None as item data is not reliable with findData).
        combo.addItem(f"Default ({default_label})", "")
        for normal_format in NORMAL_FORMATS:
            combo.addItem(NORMAL_LABELS[normal_format], normal_format)
        combo.setCurrentIndex(combo.findData(self.assignment.normal_format_override(asset) or ""))
        combo.currentIndexChanged.connect(
            lambda _index: self._on_normal_override_chosen(asset, combo.currentData() or None))
        row_layout.addWidget(combo)
        detected = self.assignment.detected_normal_format(asset)
        if detected is not None:
            label = QtWidgets.QLabel(_DETECTED_TEXTS[detected])
            label.setStyleSheet(_NORMAL_BADGE_STYLE)
            label.setToolTip(wrap_tooltip(_DETECTED_TOOLTIP))
            row_layout.addWidget(label)
        row_layout.addStretch(1)
        return row

    def _duplicate_choice_row(self, asset, texture_format, textures):
        """'Base Color ⚠ [Choose… ▾]': the artist picks the file to use."""
        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)

        chosen = self.assignment.chosen_texture(asset, texture_format)
        mark = "✓" if chosen is not None else "⚠"
        row_layout.addWidget(_hoverable(QtWidgets.QLabel(
            f"{self.assignment.format_label(texture_format)}   {mark}")))

        combo = _panel_combo()
        # Long file names must not widen the panel.
        combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(12)
        # Entry 0 = no choice (nothing pre-selected), entry i = textures[i - 1].
        combo.addItem(_CHOOSE_TEXT)
        for texture in textures:
            combo.addItem(texture.relative_path)
            combo.setItemData(combo.count() - 1, texture.path, QtCore.Qt.ToolTipRole)
        if chosen is not None:
            combo.setCurrentIndex(textures.index(chosen) + 1)
        combo.currentIndexChanged.connect(
            lambda index: self._on_file_chosen(
                asset, texture_format, textures[index - 1] if index > 0 else None))
        row_layout.addWidget(combo, 1)
        return row

    # ------------------------------------------------------------------
    # Refresh (after any change)
    # ------------------------------------------------------------------

    def _refresh(self):
        """Statuses, texts and details: after a selection or an assignment change."""
        for atlas_id, cell in self._cells.items():
            cell.setText(str(atlas_id))  # status shown by the color (_CELL_COLORS)
            assets = self.assignment.assets_at(atlas_id)
            targets = self._framing.get(atlas_id, [])
            tooltip = ", ".join(a.name for a in assets)  # empty: _on_cell_hovered
            if assets and len(targets) > 1:
                tooltip += "\n" + _NEXT_MESH_TOOLTIP.format(count=len(targets))
            cell.setToolTip(wrap_tooltip(tooltip))
            # A hand promises a click: an asset to select, or a mesh to frame.
            cell.setCursor(QtCore.Qt.PointingHandCursor if assets or targets
                           else QtCore.Qt.ArrowCursor)

        for asset, line, status, name, details, arrow in self._rows:
            status.setText(STATUS_ICONS[self.assignment.asset_status(asset)])
            unused = self.assignment.atlas_id(asset) is None
            color = f"color: {_UNUSED_COLOR};" if unused else ""
            _set_style(status, color)
            _set_style(name, _NAME_STYLE + color)
            # One tooltip for the whole line: "No ID..." then the details of
            # the warnings, separated by a blank line.
            # Notices (normal format to check) read like the warnings but never
            # block the Build: the status icon stays ✓.
            issues = (self.assignment.asset_issues(asset)
                      + self.assignment.asset_notices(asset))
            tooltip_blocks = [_UNUSED_TOOLTIP] if unused else []
            if issues:
                tooltip_blocks.append("\n".join(issue.detail for issue in issues))
            line.setToolTip(wrap_tooltip("\n\n".join(tooltip_blocks)))
            override = self.assignment.normal_format_override(asset)
            differs = override is not None and override != self.assignment.default_normal_format
            badge = self._normal_badges[id(asset)]
            badge.setText(NORMAL_LABELS[override] if differs else "")
            badge.setVisible(differs)
            prefill = self.assignment.prefill(asset)
            prefill_label = self._prefill_labels[id(asset)]
            prefill_label.setVisible(prefill is not None)
            self._badge_separators[id(asset)].setVisible(differs and prefill is not None)
            if prefill is not None:
                prefill_label.setToolTip(wrap_tooltip(_PREFILL_TOOLTIP.format(
                    atlas_id=prefill.atlas_id, meshes=" + ".join(prefill.mesh_names))))
            self._issue_labels[id(asset)].set_issues(issues)
            expanded = id(asset) in self._expanded
            arrow.setChecked(expanded)
            details.setVisible(expanded)
            if expanded:
                self._fill_details(asset, details)

        self._apply_styles()

    def _apply_styles(self):
        """Colors only (selection + cross-hover). Called on every hover: only
        the cells and lines whose look changes are touched (_set_style)."""
        hovered_asset_id = (self.assignment.atlas_id(self._hovered_asset)
                            if self._hovered_asset is not None else None)
        selected_id = (self.assignment.atlas_id(self._selected)
                       if self._selected is not None else None)
        for atlas_id, cell in self._cells.items():
            _set_style(cell, _cell_style(
                self.assignment.cell_status(atlas_id),
                selected=atlas_id == selected_id,
                linked_hover=atlas_id == hovered_asset_id))

        assets_in_hovered_cell = (self.assignment.assets_at(self._hovered_cell)
                                  if self._hovered_cell is not None else [])
        for asset, line, _status, _name, _details, _arrow in self._rows:
            _set_style(line, _row_style(
                selected=asset is self._selected,
                linked_hover=any(asset is a for a in assets_in_hovered_cell)))

    # ------------------------------------------------------------------
    # Cross-hover: a line lights up its cell, a cell lights up its line(s)
    # ------------------------------------------------------------------

    def _on_row_hovered(self, asset, inside):
        self._hovered_asset = asset if inside else None
        self._apply_styles()

    def _on_cell_hovered(self, atlas_id, inside):
        self._hovered_cell = atlas_id if inside else None
        self._apply_styles()
        if inside and not self.assignment.assets_at(atlas_id):
            # Empty cell: how to fill it, at once (a Qt tooltip waits ~0.7 s),
            # just below the cell; hidden as soon as the mouse leaves it.
            cell = self._cells[atlas_id]
            targets = self._framing.get(atlas_id, [])
            if targets:
                text = _EMPTY_FRAMED_CELL_TOOLTIP.format(
                    atlas_id=atlas_id, meshes=_MESH_SEPARATOR.join(targets))
                if len(targets) > 1:
                    text += " " + _NEXT_MESH_TOOLTIP.format(count=len(targets))
            else:
                text = _EMPTY_CELL_TOOLTIP.format(atlas_id=atlas_id)
            QtWidgets.QToolTip.showText(
                cell.mapToGlobal(cell.rect().bottomLeft() + QtCore.QPoint(0, 4)),
                wrap_tooltip(text), cell, cell.rect())

    # ------------------------------------------------------------------
    # Artist actions
    # ------------------------------------------------------------------

    def _select(self, asset, toggle=False):
        """Selection = white border on the asset's grid cell, white bar on its line. It never unfolds:
        unfolding is the artist's choice (arrow or click on the line)."""
        if toggle and asset is self._selected:
            asset = None  # second click on the same cell deselects
        self._selected = asset
        self._refresh()

    def _toggle_details(self, asset):
        """Fold / unfold the map details of one asset; it also becomes selected."""
        if id(asset) in self._expanded:
            self._expanded.discard(id(asset))
        else:
            self._expanded.add(id(asset))
        self._selected = asset
        self._framed_cell = None  # selected from the list: the next cell click starts over
        self._refresh()

    def _on_cell_clicked(self, atlas_id):
        assets = self.assignment.assets_at(atlas_id)
        targets = self._framing.get(atlas_id, [])
        # Clicked again: next mesh of the cell (workflow.md §11.1).
        again = atlas_id == self._framed_cell
        deselected = False
        if assets:
            # A cell with several meshes stays selected while the artist
            # goes from one mesh to the next; otherwise a second click deselects.
            self._select(assets[0], toggle=not (again and len(targets) > 1))
            deselected = self._selected is None
            if not deselected:
                self._center_on(self._selected)
        # An asset cell is sent even without a known mesh: the plugin then
        # explains why framing is not possible (mesh file missing, not FBX / OBJ...).
        # While no mesh at all is known (after such an error), every cell is
        # sent: the plugin reads the mesh file again once it is back or
        # reimported (Painter sends no event for a reimport).
        if (self._framing_on and (targets or assets or not self._framing)
                and not deselected):
            self._framed_cell = atlas_id
            self.cell_framing_requested.emit(atlas_id, again)
        else:
            self._framed_cell = None

    def set_framing_targets(self, targets, enabled=True):
        """{Atlas ID: [mesh names of each target]} that a click frames in the
        viewport. enabled False: "Frame viewport on click" is off, the grid
        behaves as without framing."""
        targets = dict(targets) if enabled else {}
        if targets == self._framing and enabled == self._framing_on:
            return   # unchanged: the mesh being framed by repeated clicks is kept
        self._framing = targets
        self._framing_on = enabled
        self._framed_cell = None
        self._refresh()

    def _center_on(self, asset):
        """Scroll the asset list so the line of this asset is in the middle
        (nothing happens when the whole list fits: no scroll bar)."""
        line = next(row[1] for row in self._rows if row[0] is asset)
        list_widget = self._scroll.widget()
        line_center = line.mapTo(list_widget, line.rect().center()).y()
        bar = self._scroll.verticalScrollBar()
        bar.setValue(line_center - self._scroll.viewport().height() // 2)

    def _on_id_chosen(self, asset, atlas_id):
        self.assignment.set_atlas_id(asset, atlas_id)
        self._selected = asset  # shows where it landed in the grid, without unfolding
        self._framed_cell = None
        self._refresh()
        self.assignment_changed.emit()

    def _on_default_normal_chosen(self, normal_format):
        self.assignment.set_default_normal_format(normal_format)
        self._refresh()  # the open details show "Default (...)"
        self.assignment_changed.emit()

    def _on_normal_override_chosen(self, asset, normal_format):
        """'Source format' of one asset: None = follow the default format."""
        self.assignment.set_normal_format_override(asset, normal_format)
        self._refresh()  # its format appears / disappears after its name
        self.assignment_changed.emit()

    def _on_file_chosen(self, asset, texture_format, texture):
        self.assignment.set_chosen_texture(asset, texture_format, texture)
        self._refresh()
        self.assignment_changed.emit()
