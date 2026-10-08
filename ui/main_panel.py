"""Atlas Mapper main panel.

Pure PySide6 widget: it contains no Substance 3D Painter API call, so it can
be opened and tested outside Painter. Docking into Painter is done by the
plugin entry point (atlas_mapper/__init__.py).

The panel does not scan or build anything itself (the preset editor window
it opens reads and writes preset files through core/naming_config.py). It emits signals
(scan_requested, build_requested) that the plugin connects to the actual logic.
"""

import os

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.atlas_assignment import NORMAL_FORMATS, NORMAL_OPENGL
from ..core.naming_config import (
    DEFAULT_PRESET, PROTECTED_PRESET, NamingConfigError, delete_preset, is_protected_preset)
from .about_dialog import AboutDialog
from .mapping import NORMAL_LABELS
from .preset_editor import PresetEditorDialog
from .widgets import (
    NOTE_STYLE, PAINTER_ACCENT, SECTION_TITLE_STYLE, SHORT_FIELD_WIDTH, SQUARE_BUTTON_STYLE,
    PLUGIN_VERSION, ComboBox, CrossButton, FallbackScroll, InfoIcon,
    PathField, PencilButton, RefreshingComboBox, Separator, SquareButton, bold_markup,
    message_box, set_italic_placeholder, show_message, wrap_tooltip)

# Supported atlas grids: always square, 2x2 to 4x4 (no 5x5: decided 2026-10-05)
# (docs/project/project-overview.md, Step 3).
GRID_SIZES = (2, 3, 4)
DEFAULT_GRID_SIZE = 2

_PRESET_TOOLTIP = ("Rules used by the scan to recognize the textures:\n"
                   "  • the file suffix gives the map (Drill_N.png → Normal);\n"
                   "  • a packed map (_ORM…) is split according to its R / G / B / A channels;\n"
                   "  • a prefix (TX_…) is removed from the asset name.\n"
                   "Create a preset with +, modify it with the pencil, delete it with -.")

# Above "Build Atlas" while assets placed in the grid still have a warning.
_BUILD_NOTE = "Please note: Fix the ⚠ of the assets that have an ID before \"Build Atlas\"."

_PROJECT_NORMAL_TOOLTIP = ("Set here the normal map format chosen when the Painter project was "
                           "created.\n"
                           "Painter does not let the plugin read it.\n\n"  # blank line
                           "If it differs from the format of the normal maps found by the scan, "
                           "their Green channel is inverted at Build.")

# Above the greyed panel when the project uses UV Tiles (workflow.md §5.1).
# Names of Painter's "New project" window: "UV Tile settings (UDIMs)",
# "Use UV Tile workflow". No ⚠: the red is enough.
_UDIM_NOTE = ("This project uses the UV Tile workflow (UDIMs): not supported by Atlas Mapper. "
              "The plugin works with a single 0-1 UV atlas per Texture Set.\n"
              "Please set up a new project with \"Use UV Tile workflow\" disabled.")

_ICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "resources", "atlas_mapper_icon.svg")

# Painter UI colors, sampled from the native "Texture Set Settings" panel.
_PAINTER_BACKGROUND = "#333333"

# Styles are scoped by objectName (#...) so they do not leak into child widgets.
_CONTENT_STYLE = f"#AtlasMapperContent {{ background-color: {_PAINTER_BACKGROUND}; }}"
# UDIM note: same background as the content; red, an error rather than a
# warning (the red of Painter's Log errors, measured on a screenshot); its
# padding aligns it with the section titles.
_UDIM_NOTE_STYLE = (f"#AtlasMapperUdimNote {{ background-color: {_PAINTER_BACKGROUND};"
                    f" color: #ef4e35; padding: 20px 20px 0px 20px; }}")
# Blue border on the button of the next step: "..." (no valid folder), then
# "Scan folder" (not scanned yet), then "Build Atlas" (ready).
_NEXT_STEP_STYLE = f"QPushButton:enabled {{ border: 1px solid {PAINTER_ACCENT}; }}"

# "About" link under "Build Atlas": small grey text, lighter on hover, like a
# signature rather than a button (it must not compete with "Build Atlas").
_ABOUT_STYLE = ("QPushButton { border: none; background: transparent; padding: 0px;"
                " min-width: 0px; color: #808080; }"
                "QPushButton:hover { color: #e5e5e5; }"
                "QPushButton:disabled { color: #555555; }")

# Spacing (pixels).
_CONTENT_MARGIN = 20      # between the panel content and its border
_TITLE_SPACING = 20       # below each title, and between blocks
_BELOW_SEPARATOR = 10     # between a separator and the block below it
_PATH_BUTTON_GAP = 4      # between the path field and the "..." button
_REPORT_SPACING = 6       # between the scan button and the scan report
_ROW_SPACING = 8          # between two settings rows of a section
_CONTENT_INDENT = 10      # content shifted right of its title (as in the preset editor)
# Short drop-down lists ("DirectX", "3x3"): fixed width (SHORT_FIELD_WIDTH),
# on the right of their column (preset list too, followed by its buttons).


def _grid_tooltip(size):
    """Warning for grids whose cells do not fall on whole pixels of a
    power-of-two texture (3x3), or "" (2x2, 4x4)."""
    if size & (size - 1) == 0:  # power of two: 4096 / size is a whole number
        return ""
    cell = f"{4096 / size:.2f}"
    # Line breaks only between ideas: wrap_tooltip cuts the lines (a break
    # inside a sentence made Qt cut again and leave single words alone).
    # The formula is joined by no-break spaces: never cut in the middle.
    formula = f"(4096 / {size} = {cell} px)".replace(" ", " ")
    return wrap_tooltip(
        f"{size}x{size}: on a 2048 or 4096 px texture, the cell borders do not fall between "
        f"two pixels {formula}.\n"
        f"The seam pixels are shared by two assets: slight color bleeding is possible, "
        f"worse with mipmaps.\n"
        f"Pixel-aligned grids: 2x2 and 4x4.")


def _build_summary_text(placed, ignored, deleted=0, hidden=0, updated=0):
    """'2 assets will be created · 2 updated · 1 without ID ignored · 1 folder deleted'.
    updated: placed assets whose folder already exists (rebuilt, not created);
    deleted / hidden: folders of assets withdrawn from the Build
    (painter/layer_builder.py, folder_changes)."""
    created = placed - updated
    if created or not updated:
        text = f"{created} {_plural(created, 'asset')} will be created"
    if updated:
        if created:
            text += f" · {updated} updated"
        else:  # nothing new: the line starts with the updated assets
            text = f"{updated} {_plural(updated, 'asset')} will be updated"
    if ignored:
        text += f" · {ignored} without ID ignored"
    if deleted:
        text += f" · {deleted} {_plural(deleted, 'folder')} deleted"
    if hidden:
        text += f" · {hidden} {_plural(hidden, 'folder')} hidden"
    return text


def _plural(count, word):
    """'asset' / 'assets': English plural, also for 0."""
    return word if count == 1 else word + "s"


class AtlasMapperPanel(QtWidgets.QWidget):
    """Main Atlas Mapper window, docked in Painter."""

    # Emitted with (root_folder, grid_size) when the artist clicks "Scan folder".
    scan_requested = QtCore.Signal(str, int)
    # Emitted with (root_folder, grid_size) when the artist clicks "Build Atlas".
    build_requested = QtCore.Signal(str, int)
    # Emitted with the new format ("opengl" / "directx") when the artist changes
    # "Project normal map format". No rescan: only the Build's green flip changes.
    project_normal_changed = QtCore.Signal(str)
    # Emitted with (old name, new name) when the artist renames a naming
    # preset in the editor (✎), before the rescan.
    preset_renamed = QtCore.Signal(str, str)

    def __init__(self, list_presets, parent=None):
        """list_presets: function returning the naming preset names (the panel
        itself does not read files)."""
        super().__init__(parent)
        self._list_presets = list_presets
        # Unique objectName: lets Painter save/restore the dock position and size.
        self.setObjectName("AtlasMapperPanel")
        self.setWindowTitle("Atlas Mapper")
        # With a window icon, Painter adds a quick button to reopen the panel
        # after it has been closed (see add_dock_widget in api_source/substance_painter/ui.py).
        self.setWindowIcon(QtGui.QIcon(_ICON_PATH))

        # A single container fills the whole panel (no outer margin), so the
        # Painter dock frame surrounds the window instead of each block.
        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # Outside the content: stays readable while the content is greyed.
        self._udim_note = QtWidgets.QLabel(_UDIM_NOTE)
        self._udim_note.setObjectName("AtlasMapperUdimNote")
        self._udim_note.setStyleSheet(_UDIM_NOTE_STYLE)
        self._udim_note.setWordWrap(True)
        self._udim_note.setVisible(False)
        outer_layout.addWidget(self._udim_note)

        content = QtWidgets.QFrame()
        self._content = content  # greyed as a whole while no project is open
        content.setObjectName("AtlasMapperContent")
        content.setStyleSheet(_CONTENT_STYLE)
        outer_layout.addWidget(content)

        panel_layout = QtWidgets.QVBoxLayout(content)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # The three sections scroll only when the panel is too short for them
        # (4x4 grid, Scan report details open, small screen): "Build Atlas"
        # below stays visible. At a normal height nothing scrolls. The bar
        # sits at the panel edge, in the content margin.
        sections = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(sections)
        layout.setContentsMargins(_CONTENT_MARGIN, _CONTENT_MARGIN, _CONTENT_MARGIN, 0)
        # No automatic gap: every vertical gap is set explicitly below.
        layout.setSpacing(0)
        # Artist order: choose the atlas format, then the source and scan,
        # then assign the Atlas IDs.
        layout.addWidget(self._build_configuration_section())
        self._add_separator(layout)
        layout.addWidget(self._build_source_section())
        self._add_separator(layout)
        layout.addWidget(self._build_mapping_section(), 1)
        panel_layout.addWidget(FallbackScroll(sections), 1)

        # What the build will create, right above "Build Atlas": never scrolls.
        build_block = QtWidgets.QVBoxLayout()
        build_block.setContentsMargins(
            _CONTENT_MARGIN, _TITLE_SPACING, _CONTENT_MARGIN, _CONTENT_MARGIN)
        build_block.setSpacing(_REPORT_SPACING)
        panel_layout.addLayout(build_block)

        # Assets placed in the grid still have a warning: what blocks the
        # Build. Left-aligned with the section titles. Only placed assets
        # count (AtlasAssignment.can_build): an asset without ID is not created.
        self.build_note = QtWidgets.QLabel(_BUILD_NOTE)
        self.build_note.setStyleSheet(NOTE_STYLE)
        self.build_note.setWordWrap(True)
        self.build_note.setVisible(False)
        build_block.addWidget(self.build_note)

        self.build_summary = QtWidgets.QLabel()
        self.build_summary.setAlignment(QtCore.Qt.AlignCenter)
        # Italic like the scan report summary: a status, not a setting.
        self.build_summary.setStyleSheet("font-style: italic;")
        self.build_summary.setWordWrap(True)  # longer with folders to remove: never widens the panel
        self.build_summary.setVisible(False)
        build_block.addWidget(self.build_summary)

        self.build_button = QtWidgets.QPushButton("Build Atlas")
        self.build_button.setStyleSheet(_NEXT_STEP_STYLE)
        self._disable_focus_frame(self.build_button)
        self.build_button.clicked.connect(self._on_build_clicked)
        build_block.addWidget(self.build_button)

        # Opens the About window (author, version, links), bottom right.
        about_button = QtWidgets.QPushButton(f"About · v{PLUGIN_VERSION}")
        about_button.setStyleSheet(_ABOUT_STYLE)
        about_button.setCursor(QtCore.Qt.PointingHandCursor)
        self._disable_focus_frame(about_button)
        about_button.clicked.connect(lambda: AboutDialog(self).exec())
        build_block.addWidget(about_button, 0, QtCore.Qt.AlignRight)

        self._update_buttons()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_section(title):
        """Section with a Painter-style title (bold, uppercase, light grey).

        Returns (section_widget, section_layout): the caller adds the content
        below the title, in section_layout, shifted right of the title.
        """
        section = QtWidgets.QWidget()
        outer_layout = QtWidgets.QVBoxLayout(section)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(_TITLE_SPACING)  # space below the title

        title_label = QtWidgets.QLabel(title.upper())
        title_label.setStyleSheet(SECTION_TITLE_STYLE)
        outer_layout.addWidget(title_label)

        section_layout = QtWidgets.QVBoxLayout()
        section_layout.setContentsMargins(_CONTENT_INDENT, 0, 0, 0)
        section_layout.setSpacing(_TITLE_SPACING)  # between blocks of the section
        outer_layout.addLayout(section_layout, 1)  # MAPPING: its list takes the height
        return section, section_layout

    @staticmethod
    def _add_separator(layout):
        """Add a separator line: normal gap above it, half gap below it."""
        layout.addSpacing(_TITLE_SPACING)
        layout.addWidget(Separator())
        layout.addSpacing(_BELOW_SEPARATOR)

    def _build_source_section(self):
        section, section_layout = self._build_section("Source")
        # How to start, like Painter's italic notes ("You can't change UV Tile
        # settings..."): normal text color, italics. Hidden once a scan is shown.
        self.source_hint = QtWidgets.QLabel(
            "Choose a folder, then click \"Scan folder\" to list the assets.")
        self.source_hint.setStyleSheet("font-style: italic;")
        self.source_hint.setWordWrap(True)
        # Hint and "Folder" line grouped: only the gap between two settings
        # lines, not the gap between the blocks of the section.
        folder_block = QtWidgets.QVBoxLayout()
        folder_block.setSpacing(_ROW_SPACING)
        section_layout.addLayout(folder_block)
        folder_block.addWidget(self.source_hint)
        row = QtWidgets.QHBoxLayout()
        folder_block.addLayout(row)

        row.addWidget(QtWidgets.QLabel("Folder"))

        # Takes all the width left by the label and the buttons: "..." and
        # the cross stay at the far right. A path that does not fit is
        # shortened in the middle (PathField).
        self.root_folder_field = PathField()
        # Editable: the artist can type or paste a path, or use "...".
        self.root_folder_field.setPlaceholderText("Paste a path or click ...")
        set_italic_placeholder(self.root_folder_field)
        # Any change of folder makes a previous scan obsolete.
        self.root_folder_field.path_changed.connect(self.clear_results)
        # Path field and "..." button grouped with a small gap between them.
        path_row = QtWidgets.QHBoxLayout()
        path_row.setSpacing(_PATH_BUTTON_GAP)
        row.addLayout(path_row, 1)
        path_row.addWidget(self.root_folder_field, 1)

        self.browse_button = SquareButton("...")
        self.browse_button.setToolTip("Choose the folder of the textures to scan")
        self._disable_focus_frame(self.browse_button)
        self.browse_button.clicked.connect(self._on_browse_clicked)
        path_row.addWidget(self.browse_button)

        # Empties the path field (enabled only when there is a path to remove).
        self.clear_path_button = CrossButton()
        self.clear_path_button.setToolTip("Clear the path")
        self._disable_focus_frame(self.clear_path_button)
        self.clear_path_button.clicked.connect(self._on_clear_path_clicked)
        path_row.addWidget(self.clear_path_button)

        # Scan button with the one-line scan report right below it.
        scan_block = QtWidgets.QVBoxLayout()
        scan_block.setSpacing(_REPORT_SPACING)
        section_layout.addLayout(scan_block)

        self.scan_button = QtWidgets.QPushButton("Scan folder")
        self._disable_focus_frame(self.scan_button)
        self.scan_button.clicked.connect(self._on_scan_clicked)
        scan_block.addWidget(self.scan_button)

        self.report_layout = QtWidgets.QVBoxLayout()
        self.report_layout.setContentsMargins(0, 0, 0, 0)
        scan_block.addLayout(self.report_layout)

        return section

    def _build_configuration_section(self):
        section, section_layout = self._build_section("Configuration")
        # Labels in one column, drop-down lists aligned in the next one.
        rows = QtWidgets.QGridLayout()
        rows.setVerticalSpacing(_ROW_SPACING)
        rows.setColumnStretch(1, 1)
        section_layout.addLayout(rows)

        # Drop-down list, like Painter's "Size" field. Each entry stores N.
        self.grid_combo = ComboBox()
        for size in GRID_SIZES:
            self.grid_combo.addItem(f"{size}x{size}", size)
            self.grid_combo.setItemData(
                self.grid_combo.count() - 1, _grid_tooltip(size) or None, QtCore.Qt.ToolTipRole)
        self.grid_combo.setCurrentIndex(GRID_SIZES.index(DEFAULT_GRID_SIZE))
        self._disable_focus_frame(self.grid_combo)  # no blue current entry after use
        # A previous scan was made for another grid: it is redone automatically.
        self.grid_combo.currentIndexChanged.connect(self._on_scan_setting_changed)
        # The warning also shows on the closed list while 3x3 is chosen.
        self.grid_combo.currentIndexChanged.connect(
            lambda _index: self.grid_combo.setToolTip(_grid_tooltip(self.grid_size())))
        rows.addWidget(QtWidgets.QLabel("Grid format"), 1, 0)
        self.grid_combo.setFixedWidth(SHORT_FIELD_WIDTH)
        rows.addWidget(self.grid_combo, 1, 1, QtCore.Qt.AlignRight)

        # Setting of the Painter project, chosen at its creation: first line.
        self.project_normal_combo = ComboBox()
        for normal_format in NORMAL_FORMATS:
            self.project_normal_combo.addItem(NORMAL_LABELS[normal_format], normal_format)
        self._disable_focus_frame(self.project_normal_combo)
        self.project_normal_combo.setCurrentIndex(
            self.project_normal_combo.findData(NORMAL_OPENGL))  # Painter's default
        self.project_normal_combo.currentIndexChanged.connect(
            lambda _index: self.project_normal_changed.emit(self.project_normal_format()))
        rows.addWidget(QtWidgets.QLabel("Project normal map format"), 0, 0)
        self.project_normal_combo.setFixedWidth(SHORT_FIELD_WIDTH)
        rows.addWidget(self.project_normal_combo, 0, 1, QtCore.Qt.AlignRight)
        # Explanation behind the "i" icon at the far right, like Painter.
        rows.addWidget(InfoIcon(_PROJECT_NORMAL_TOOLTIP), 0, 2)

        # Naming preset = one JSON file of naming_presets. The list is read
        # again each time it opens: a preset file added meanwhile appears.
        self.preset_combo = RefreshingComboBox()
        self.preset_combo.setPlaceholderText("No preset in naming_presets")
        self._disable_focus_frame(self.preset_combo)
        self._refresh_presets()
        self.preset_combo.about_to_open.connect(self._refresh_presets)
        # Same as the grid: a scan made with another preset is redone.
        self.preset_combo.currentIndexChanged.connect(self._on_scan_setting_changed)
        rows.addWidget(QtWidgets.QLabel("Naming convention"), 2, 0)
        # Create / modify a preset without editing its JSON file by hand.
        preset_row = QtWidgets.QHBoxLayout()
        preset_row.setSpacing(_PATH_BUTTON_GAP)
        # List and buttons on the right, like the lists above: the pencil ends
        # where they end, whatever the panel width.
        preset_row.addStretch(1)
        self.preset_combo.setFixedWidth(SHORT_FIELD_WIDTH)
        # A long preset name may be cut in the short list: full name on hover.
        self.preset_combo.currentTextChanged.connect(self.preset_combo.setToolTip)
        preset_row.addWidget(self.preset_combo)
        self.delete_preset_button = SquareButton("-")
        self._disable_focus_frame(self.delete_preset_button)
        self.delete_preset_button.clicked.connect(self._on_delete_preset_clicked)
        preset_row.addWidget(self.delete_preset_button)
        self.new_preset_button = SquareButton("+")
        self.new_preset_button.setToolTip("Create a naming preset")
        self._disable_focus_frame(self.new_preset_button)
        self.new_preset_button.clicked.connect(self._on_new_preset_clicked)
        preset_row.addWidget(self.new_preset_button)
        self.edit_preset_button = PencilButton()
        self._disable_focus_frame(self.edit_preset_button)
        self.edit_preset_button.clicked.connect(self._on_edit_preset_clicked)
        preset_row.addWidget(self.edit_preset_button)
        self.preset_combo.currentIndexChanged.connect(self._update_buttons)
        rows.addLayout(preset_row, 2, 1)
        rows.addWidget(InfoIcon(_PRESET_TOOLTIP), 2, 2)  # far right, like the line above

        return section

    def _refresh_presets(self, renamed_to=None):
        """Fill the preset list from the files, keeping the current choice
        (Default, otherwise the first preset, if its file no longer exists).
        renamed_to: the current preset was just renamed from the editor: its
        new name is selected, and the caller redoes the scan."""
        current = self.preset_name()
        wanted = renamed_to or current
        names = self._list_presets()
        self.preset_combo.blockSignals(True)  # not a choice of the artist
        self.preset_combo.clear()
        self.preset_combo.addItems(names)
        if wanted in names:
            self.preset_combo.setCurrentIndex(names.index(wanted))
        else:
            self.preset_combo.setCurrentIndex(
                names.index(DEFAULT_PRESET) if DEFAULT_PRESET in names else 0)
        self.preset_combo.blockSignals(False)
        # Its file was removed or renamed by other means.
        if renamed_to is None and current and self.preset_name() != current:
            self._on_scan_setting_changed()

    def _build_mapping_section(self):
        section, section_layout = self._build_section("Mapping")

        # Grid + asset list after a scan, a hint before. Not scrollable as a
        # whole: only the asset list scrolls (inside MappingWidget), the
        # grid stays visible.
        container = QtWidgets.QWidget()
        self.mapping_layout = QtWidgets.QVBoxLayout(container)
        self.mapping_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.addWidget(container, 1)

        return section

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    # ------------------------------------------------------------------
    # Public API (used by the plugin logic)
    # ------------------------------------------------------------------

    def root_folder(self):
        # Strip spaces and the quotes added by Windows "Copy as path".
        return self.root_folder_field.path().strip().strip('"')

    def grid_size(self):
        """Selected grid size N (the atlas is N x N)."""
        return self.grid_combo.currentData()

    def preset_name(self):
        """Selected naming preset, or "" when there is none."""
        return self.preset_combo.currentText()

    def select_preset(self, name):
        """Select a naming preset by name. Returns False (current preset kept)
        when no preset file has this name."""
        self._refresh_presets()
        # Upper / lower case ignored (MatchFixedString without MatchCaseSensitive):
        # a project built with "studio" finds "Studio" after a case-only rename.
        index = self.preset_combo.findText(name, QtCore.Qt.MatchFixedString)
        if index < 0:
            return False
        self.preset_combo.setCurrentIndex(index)
        return True

    def project_normal_format(self):
        """"opengl" or "directx": normal format of the Painter project."""
        return self.project_normal_combo.currentData()

    def set_project_normal_format(self, normal_format):
        """Select the project normal format (unknown value: kept unchanged)."""
        index = self.project_normal_combo.findData(normal_format)
        if index >= 0:
            self.project_normal_combo.setCurrentIndex(index)

    def set_source(self, root_folder, grid_size, preset_name=None):
        """Fill the root folder, the grid and the naming preset (e.g. from the
        last Build of the opened project). Like a manual change, it clears a
        previous scan. A missing preset keeps the current one."""
        if grid_size in GRID_SIZES:  # None / unknown: keep the current grid
            self.grid_combo.setCurrentIndex(GRID_SIZES.index(grid_size))
        if preset_name:
            self.select_preset(preset_name)
        self.root_folder_field.set_path(root_folder)

    def set_project_open(self, is_open, uses_uv_tiles=False):
        """Grey the whole panel while no Painter project is open, like native
        panels (Shader Settings): nothing can be configured without a project.
        A project with UV Tiles (UDIM) is refused: greyed too, with a note."""
        self._udim_note.setVisible(is_open and uses_uv_tiles)
        self._content.setEnabled(is_open and not uses_uv_tiles)

    def clear_results(self):
        """Remove the scan report and the mapping, disable "Build Atlas"."""
        self._clear_layout(self.report_layout)
        self._clear_layout(self.mapping_layout)
        self._scanned = False
        self._build_ready = False
        self._build_counts = (0, 0, 0, 0, 0)
        self._update_buttons()

    def set_scan_report(self, widget, succeeded=True):
        """Show the scan report (or a scan error) under the scan button.

        After a failed scan, "Scan folder" keeps its blue border:
        the scan has to be run again.
        """
        self._clear_layout(self.report_layout)
        self.report_layout.addWidget(widget)
        self._scanned = succeeded
        self._update_buttons()

    def set_mapping(self, widget):
        """Show the grid + asset list in the MAPPING section."""
        self._clear_layout(self.mapping_layout)
        self.mapping_layout.addWidget(widget, 1)  # takes the height: its list scrolls

    def set_build_ready(self, ready, placed=0, ignored=0, deleted=0, hidden=0, updated=0,
                        texture_set=""):
        """Enable "Build Atlas" (decided by AtlasAssignment.can_build).

        placed / ignored: assets with / without an Atlas ID; updated: placed
        assets whose folder already exists; deleted / hidden: folders of
        withdrawn assets; texture_set: where the Build goes (the active one).
        When the build is possible, a line above the button says where, and
        what will be created, updated and removed.
        """
        self._build_ready = ready
        self._build_counts = (placed, ignored, deleted, hidden, updated)
        self._build_target = texture_set
        self._update_buttons()

    def confirm_build_target(self, scanned, active):
        """The active Texture Set changed since the scan: build into the
        active one anyway? True = build."""
        box = message_box(self, f"Build into the Texture Set \"{active}\"?", warning=True)
        box.setInformativeText(
            f"The scan was made with the Texture Set \"{scanned}\" active, and the choices "
            f"shown come from its last Build. \"{active}\" is active now: the Build goes "
            f"there, and these choices are remembered for it.\n\n"
            f"To build \"{scanned}\", select it again in Painter. To load the choices "
            f"remembered for \"{active}\", click Cancel, then \"Scan folder\".")
        build_button = box.addButton("Build", QtWidgets.QMessageBox.AcceptRole)
        box.setDefaultButton(box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole))
        box.exec()
        return box.clickedButton() is build_button

    def show_build_result(self, message, succeeded):
        """Tell the artist how the build went (message written for the artist,
        **text** shown in bold)."""
        show_message(self, bold_markup(message), warning=not succeeded, rich=True)

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    _scanned = False
    _build_ready = False
    # (assets with an ID, assets without ID, folders to delete, folders to hide)
    _build_counts = (0, 0, 0, 0, 0)
    _build_target = ""  # Texture Set the Build goes into

    @staticmethod
    def _disable_focus_frame(button):
        # Without keyboard focus, Painter no longer draws its blue focus border
        # on the last clicked button: blue only means "next step".
        button.setFocusPolicy(QtCore.Qt.NoFocus)

    def _update_buttons(self):
        # The path is typed by hand: scan only when it points to an existing folder.
        folder_ok = os.path.isdir(self.root_folder())
        # No preset file at all: nothing to recognize the textures with.
        self.scan_button.setEnabled(folder_ok and bool(self.preset_name()))
        self.clear_path_button.setEnabled(bool(self.root_folder_field.path()))
        # Default is protected: it can be copied (+), never modified or deleted.
        preset = self.preset_name()
        protected = is_protected_preset(preset)
        for button, action in ((self.edit_preset_button, "Modify"),
                               (self.delete_preset_button, "Delete")):
            button.setEnabled(bool(preset) and not protected)
            button.setToolTip(f"\"{PROTECTED_PRESET}\" is protected: create a copy with +"
                              if protected else f"{action} the selected preset")
        self.build_button.setEnabled(self._build_ready)
        self.build_summary.setVisible(self._build_ready)
        summary = _build_summary_text(*self._build_counts)
        if self._build_target:  # where the Build goes: a project can hold several atlases
            summary = f"Texture Set \"{self._build_target}\" · {summary}"
        self.build_summary.setText(summary)
        placed = self._build_counts[0]
        self.build_note.setVisible(not self._build_ready and placed > 0)
        self.source_hint.setVisible(not self._scanned)

        # Blue border on the next step only ("Build Atlas" has it whenever enabled).
        self.browse_button.setStyleSheet(
            SQUARE_BUTTON_STYLE + ("" if folder_ok else _NEXT_STEP_STYLE))
        self.scan_button.setStyleSheet(
            _NEXT_STEP_STYLE if folder_ok and not self._scanned else "")

    def _on_browse_clicked(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose the root folder", self.root_folder())
        if folder:
            # set_path triggers path_changed, which clears a previous scan.
            self.root_folder_field.set_path(folder)

    def _on_clear_path_clicked(self):
        # path_changed too: the previous scan is removed.
        self.root_folder_field.set_path("")

    def _on_scan_setting_changed(self):
        # The scan shown was made for the old grid (IDs depend on the grid) or
        # the old naming preset (files recognized differently): it is cleared,
        # and redone with the new setting if there was one.
        was_scanned = self._scanned
        self.clear_results()
        if was_scanned and os.path.isdir(self.root_folder()):
            self._on_scan_clicked()

    def _on_new_preset_clicked(self):
        dialog = PresetEditorDialog(self.preset_name(), parent=self)
        if dialog.exec() and dialog.saved_name():
            # Selecting the new preset redoes a scan shown (like a manual choice).
            self.select_preset(dialog.saved_name())

    def _on_edit_preset_clicked(self):
        name = self.preset_name()
        dialog = PresetEditorDialog(name, edited_preset=name, parent=self)
        if not (dialog.exec() and dialog.saved_name()):
            return
        new_name = dialog.saved_name()
        if new_name == name:
            self._on_scan_setting_changed()  # same preset, new rules: rescan
            return
        # Renamed: the open project's Build memory is updated first, so the
        # rescan below does not warn about a changed preset.
        self.preset_renamed.emit(name, new_name)
        # The list goes straight to the new name (never through Default),
        # then a scan shown is redone once.
        self._refresh_presets(renamed_to=new_name)
        self._on_scan_setting_changed()

    def _on_delete_preset_clicked(self):
        name = self.preset_name()
        box = message_box(self, f"Delete the preset \"{name}\"?", warning=True)
        box.setInformativeText(f"The file {name}.json will be permanently deleted "
                               f"from the naming_presets folder.")
        delete_button = box.addButton("Delete", QtWidgets.QMessageBox.DestructiveRole)
        box.setDefaultButton(box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole))
        box.exec()
        if box.clickedButton() is not delete_button:
            return
        try:
            delete_preset(name)
        except NamingConfigError as error:
            show_message(self, str(error), warning=True)
            return
        # The deleted preset is gone from the list: Default is selected, and a
        # scan shown is redone with it.
        self._refresh_presets()

    def _on_scan_clicked(self):
        self.scan_requested.emit(self.root_folder(), self.grid_size())

    def _on_build_clicked(self):
        self.build_requested.emit(self.root_folder(), self.grid_size())
