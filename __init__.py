"""Atlas Mapper - Substance 3D Painter plugin entry point.

Painter calls start_plugin() when the plugin is enabled and close_plugin()
when it is disabled or Painter closes (see api_source/substance_painter_plugins.py).

Development install: set the environment variable
    SUBSTANCE_PAINTER_PLUGINS_PATH = Z:\\Atlas Builder\\src
then restart Painter. Painter looks for plugins in its "plugins" subfolder,
i.e. src/plugins/atlas_mapper.
"""

import os

from PySide6 import QtCore

import substance_painter.event
import substance_painter.logging
import substance_painter.project
import substance_painter.ui

from .core import build_memory
from .core.atlas_assignment import NORMAL_OPENGL, AtlasAssignment
from .core.naming_config import (DEFAULT_PRESET, NamingConfigError, list_presets,
                                 load_texture_attributes)
from .painter.layer_builder import AssetToBuild, BuildError, build_atlas, folder_changes
from .painter.project_memory import (MEMORY_ERRORS, active_texture_set, load_builds,
                                     load_memory, project_uses_uv_tiles, save_builds,
                                     save_memory)
from .painter.uvtransform_sbsar import SbsarError
from .processing.scanner import ScanCancelled, ScanError, scan_folder
from .ui.mapping import MappingWidget
from .ui.main_panel import AtlasMapperPanel
from .ui.scan_progress import ScanProgressDialog
from .ui.scan_results import ScanReportWidget, build_scan_cancelled, build_scan_error
from .ui.widgets import add_title_bar_icon

_LOG_CHANNEL = "Atlas Mapper"

# Widgets created by the plugin, kept so they can be removed in close_plugin().
_plugin_widgets = []

# Atlas ID assignment of the last successful scan (validated data for the build).
# texture_set: Texture Set active at that scan, whose memory was restored.
_current = {"assignment": None, "texture_set": None}

# Project events followed by the plugin: (event class, callback), disconnected
# in close_plugin().
_event_callbacks = []

# Last naming preset used, kept on this computer between Painter sessions
# (Windows registry, via Qt): a new project starts with it.
_SETTINGS = ("Atlas Mapper", "Atlas Mapper")
_LAST_PRESET_KEY = "naming_preset"


def start_plugin():
    panel = AtlasMapperPanel(list_presets)
    if not panel.select_preset(QtCore.QSettings(*_SETTINGS).value(_LAST_PRESET_KEY, "")):
        panel.select_preset(DEFAULT_PRESET)  # otherwise the first preset stays selected
    panel.scan_requested.connect(lambda folder, n: _on_scan_requested(panel, folder, n))
    panel.build_requested.connect(lambda folder, n: _on_build_requested(panel, n))
    panel.project_normal_changed.connect(_on_project_normal_changed)
    panel.preset_renamed.connect(_on_preset_renamed)

    # Turns the panel into a Painter dock: can be docked, undocked (floating)
    # and moved like native panels.
    dock = substance_painter.ui.add_dock_widget(panel)
    _plugin_widgets.append(dock)
    # Opened from Painter's side icons, the panel kept a height saved when
    # Painter was full screen and went past the bottom of a smaller Painter
    # window (native panels stop at it). Each time it shows, it is fitted;
    # after Painter has placed it (next event loop turn).
    dock.visibilityChanged.connect(
        lambda visible: visible and QtCore.QTimer.singleShot(0, lambda: _fit_in_main_window(dock)))
    # Plugin icon left of the title, in the title's color (ui/widgets.py).
    if not add_title_bar_icon(dock, panel.windowIcon()):
        _log("Dock title bar not recognized: no icon added to the title.")

    # The panel is greyed while no project is open. Each project remembers its
    # last Build: fill the panel when one opens, empty it when it closes (the
    # scan belongs to the closed project).
    for event_cls, callback in (
            (substance_painter.event.ProjectOpened, lambda _event: _open_project(panel)),
            (substance_painter.event.ProjectCreated, lambda _event: _open_project(panel)),
            (substance_painter.event.ProjectClosed, lambda _event: _forget_project(panel))):
        substance_painter.event.DISPATCHER.connect_strong(event_cls, callback)
        _event_callbacks.append((event_cls, callback))
    if substance_painter.project.is_open():  # plugin enabled with a project already open
        _open_project(panel)
    else:
        panel.set_project_open(False)


def close_plugin():
    for event_cls, callback in _event_callbacks:
        substance_painter.event.DISPATCHER.disconnect(event_cls, callback)
    _event_callbacks.clear()
    for widget in _plugin_widgets:
        substance_painter.ui.delete_ui_element(widget)
    _plugin_widgets.clear()


def _fit_in_main_window(dock):
    """Panel outside Painter's main window (floating, or opened from the
    side icons): shorten it so its bottom stays inside the main window, like
    Painter's own panels. Its content scrolls when needed (FallbackScroll).
    Docked inside the main window: nothing to do."""
    try:
        main = substance_painter.ui.get_main_window()
    except Exception as error:  # UI service not ready: keep Painter's size
        _log(f"Panel height not fitted: {error!r}", substance_painter.logging.WARNING)
        return
    window = dock.window()  # the top-level window that holds the panel
    if window is main or not window.isVisible():
        return
    main_bottom = main.mapToGlobal(main.rect().bottomLeft()).y()
    overflow = window.frameGeometry().bottom() - main_bottom
    if overflow > 0:
        window.resize(window.width(), max(window.minimumHeight(), window.height() - overflow))


def _log(message, severity=substance_painter.logging.INFO):
    substance_painter.logging.log(severity, _LOG_CHANNEL, message)


def _read_memory(texture_set):
    """Last Build memory of this Texture Set, or None (errors only logged)."""
    try:
        return load_memory(texture_set)
    except MEMORY_ERRORS as error:
        _log(f"Could not read the Build memory of the project: {error!r}",
             substance_painter.logging.WARNING)
        return None


def _restore_source(panel):
    """Fill the root folder and the grid of the last Build of this project,
    then scan it right away so the remembered choices are shown at once.
    The memory is the one of the active Texture Set (one atlas per Texture Set)."""
    memory = _read_memory(active_texture_set())
    if not (isinstance(memory, dict) and memory.get("root_folder")):
        return
    project_normal = build_memory.restore_project_normal_format(memory)
    if project_normal:
        panel.set_project_normal_format(project_normal)
    panel.set_source(memory["root_folder"], memory.get("grid_size"), memory.get("naming_preset"))
    # Folder moved or deleted: the field stays filled, the artist fixes the path.
    if os.path.isdir(panel.root_folder()):
        _on_scan_requested(panel, panel.root_folder(), panel.grid_size())


def _open_project(panel):
    try:
        uses_uv_tiles = project_uses_uv_tiles()
    except MEMORY_ERRORS as error:  # Painter not ready: the panel stays usable
        _log(f"Could not check whether the project uses UV Tiles: {error!r}",
             substance_painter.logging.WARNING)
        uses_uv_tiles = False
    if uses_uv_tiles:
        # UDIM project: refused, nothing restored or scanned (workflow.md §5.1).
        _log("Project with UV Tiles (UDIM): not supported, panel disabled.")
        panel.set_project_open(True, uses_uv_tiles=True)
        return
    panel.set_project_open(True)
    _restore_source(panel)  # new project: no memory yet, nothing restored


def _forget_project(panel):
    _current["assignment"] = None
    _current["texture_set"] = None
    panel.set_source("", None)  # empty field: the scan results are cleared too
    panel.set_project_normal_format(NORMAL_OPENGL)  # Painter's default for a new project
    panel.set_project_open(False)


def _on_scan_requested(panel, folder, grid_size):
    preset = panel.preset_name()
    panel.clear_results()
    _current["assignment"] = None
    _current["texture_set"] = None
    try:
        # Read at every scan: edits to the preset file apply without
        # restarting Painter.
        attributes = load_texture_attributes(preset)
        # A long scan (big folder, network drive) shows a window with Cancel.
        progress = ScanProgressDialog(panel)
        try:
            result = scan_folder(folder, attributes, progress.report)
        finally:
            progress.finish()
    except (NamingConfigError, ScanError) as error:
        _log(f"Scan failed: {folder} - {error}", substance_painter.logging.ERROR)
        panel.set_scan_report(build_scan_error(str(error)), succeeded=False)
        return
    except ScanCancelled:
        _log(f"Scan cancelled: {folder}")
        panel.set_scan_report(build_scan_cancelled(), succeeded=False)
        return

    QtCore.QSettings(*_SETTINGS).setValue(_LAST_PRESET_KEY, preset)
    _log(f"Scan: {folder} ({grid_size}x{grid_size}, preset {preset}) - {len(result.assets)} assets, "
         f"{len(result.unrecognized)} unrecognized files")
    panel.set_scan_report(ScanReportWidget(result))
    if result.assets:
        # Assets start without an Atlas ID: the artist assigns them.
        assignment = AtlasAssignment(grid_size, result.assets, attributes.packed_channels)
        assignment.set_project_normal_format(panel.project_normal_format())
        # Choices of the last Build in the active Texture Set come back (still
        # editable). Another Texture Set = another atlas: rescan to load its own.
        texture_set = active_texture_set()
        restore_report = build_memory.restore(assignment, _read_memory(texture_set), preset)
        mapping = MappingWidget(assignment, list(attributes.texture_formats), restore_report)
        # "Build Atlas" follows every ID / file choice of the artist.
        mapping.assignment_changed.connect(
            lambda: _update_build_state(panel, assignment))
        panel.set_mapping(mapping)
        _update_build_state(panel, assignment)  # not ready: no ID yet
        _current["assignment"] = assignment
        _current["texture_set"] = texture_set


def _on_preset_renamed(old_name, new_name):
    """A naming preset was renamed: the open project's Build memory follows
    it, so the project keeps finding its preset. Closed projects cannot be
    updated (project-overview.md §19.3)."""
    QtCore.QSettings(*_SETTINGS).setValue(_LAST_PRESET_KEY, new_name)
    try:
        builds = load_builds()  # the memories of every Texture Set
        renamed = [texture_set for texture_set, memory in builds.items()
                   if isinstance(memory, dict)
                   and str(memory.get("naming_preset", "")).lower() == old_name.lower()]
        if not renamed:
            return
        for texture_set in renamed:
            builds[texture_set]["naming_preset"] = new_name
        save_builds(builds)
    except MEMORY_ERRORS as error:
        _log(f"Could not update the Build memory after renaming preset {old_name} to "
             f"{new_name}: {error!r}", substance_painter.logging.WARNING)
        return
    _log(f"Naming preset renamed {old_name} -> {new_name}: Build memory updated for "
         f"{', '.join(renamed)}")


def _on_project_normal_changed(normal_format):
    """CONFIGURATION > Project normal map format changed: the scan shown is kept,
    only the green flip decided at Build changes."""
    if _current["assignment"] is not None:
        _current["assignment"].set_project_normal_format(normal_format)


def _update_build_state(panel, assignment):
    """Enable "Build Atlas" and tell how many assets will be created / updated /
    ignored, and how many folders of withdrawn assets will be deleted / hidden."""
    placed_assets = assignment.placed_assets()
    placed = len(placed_assets)
    try:
        updated, deleted, hidden = folder_changes([asset.name for asset in placed_assets])
    except Exception as error:  # only an announcement: never block the panel for it
        _log(f"Could not read the asset folders of the layer stack: {error!r}",
             substance_painter.logging.WARNING)
        updated = deleted = hidden = 0
    # The Build goes into the active Texture Set: named above the button.
    panel.set_build_ready(assignment.can_build(), placed, len(assignment.assets) - placed,
                          deleted, hidden, updated, texture_set=active_texture_set() or "")


def _on_build_requested(panel, grid_size):
    assignment = _current["assignment"]
    if assignment is None or not assignment.can_build():
        return  # the button is disabled in this case; safety only
    # Another Texture Set was selected since the scan: the choices shown
    # (restored from the memory of the scanned one) may belong to another atlas.
    scanned, active = _current["texture_set"], active_texture_set()
    if scanned and active and active != scanned:
        if not panel.confirm_build_target(scanned, active):
            _update_build_state(panel, assignment)  # summary names the active one
            return
    # Validated data only: assets with an Atlas ID, maps resolved one by one
    # (own file, or one channel of a packed file).
    assets = []
    for asset in assignment.placed_assets():
        maps = assignment.resolved_maps(asset)
        assets.append(AssetToBuild(
            asset.name, assignment.atlas_id(asset),
            {fmt: src.texture.path for fmt, src in maps.items() if src.channel is None},
            assignment.flip_normal_green(asset),
            {fmt: (src.texture.path, src.channel, assignment.format_label(src.packed_format))
             for fmt, src in maps.items() if src.channel is not None}))
    try:
        report = build_atlas(grid_size, assets)
    except (BuildError, SbsarError) as error:
        _log(f"Build failed: {error}", substance_painter.logging.ERROR)
        panel.show_build_result(str(error), succeeded=False)
        return
    except Exception as error:  # unexpected Painter error: keep details in the log
        _log(f"Build failed (unexpected): {error!r}", substance_painter.logging.ERROR)
        panel.show_build_result("The Build failed unexpectedly.\n"
                                "The details are in Painter's Log window "
                                "(Atlas Mapper channel). Ctrl+Z undoes what was created.",
                                succeeded=False)
        return

    # Remember the choices in the project (kept once the project is saved),
    # for the Texture Set just built.
    _current["texture_set"] = report.texture_set
    try:
        save_memory(report.texture_set,
                    build_memory.to_memory(assignment, panel.root_folder(), panel.preset_name()))
    except MEMORY_ERRORS as error:
        _log(f"Could not store the Build memory in the project: {error!r}",
             substance_painter.logging.WARNING)
        report.notes.append("The choices of this Build could not be saved in the project.")

    for note in report.notes:
        _log(note.replace("**", ""), substance_painter.logging.WARNING)  # no bold marks in the log
    _log(f"Build in '{report.texture_set}' - created: {', '.join(report.created) or '-'}"
         f" | updated: {', '.join(report.updated) or '-'}")
    # One asset per bulleted line: easier to read than a comma list.
    lines = []
    if report.created:
        count = len(report.created)
        lines.append(f"{count} asset{'' if count == 1 else 's'} created:")
        lines += [f"• {name}" for name in report.created]
    if report.updated:
        count = len(report.updated)
        lines.append(f"{count} asset{'' if count == 1 else 's'} updated:")
        lines += [f"• {name}" for name in report.updated]
    message = (f"Texture Set \"{report.texture_set}\"\n"
               f"Layer Stack folder \"Atlas Mapper\"\n\n"
               + "\n".join(lines))
    if report.notes:
        message += "\n\nNotes:\n• " + "\n• ".join(report.notes)
    panel.show_build_result(message, succeeded=True)
    _update_build_state(panel, assignment)   # the layer stack changed: folders to remove too
