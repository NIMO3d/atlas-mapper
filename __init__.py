"""Atlas Mapper - Substance 3D Painter plugin entry point.

Painter calls start_plugin() when the plugin is enabled and close_plugin()
when it is disabled or Painter closes (see api_source/substance_painter_plugins.py).

Development install: set the environment variable
    SUBSTANCE_PAINTER_PLUGINS_PATH = Z:\\Atlas Builder\\src
then restart Painter. Painter looks for plugins in its "plugins" subfolder,
i.e. src/plugins/atlas_mapper.
"""

import os
import time

from PySide6 import QtCore, QtWidgets

import substance_painter.event
import substance_painter.logging
import substance_painter.project
import substance_painter.ui

from .core import build_memory
from .core.atlas_assignment import NORMAL_OPENGL, AtlasAssignment
from .core.atlas_prefill import prefill_atlas_ids, suggested_grid_size
from .core.naming_config import (DEFAULT_PRESET, NamingConfigError, list_presets,
                                 load_texture_attributes)
from .painter.layer_builder import AssetToBuild, BuildError, build_atlas, folder_changes
from .painter.project_memory import (MEMORY_ERRORS, active_texture_set, load_builds,
                                     load_memory, project_uses_uv_tiles, save_builds,
                                     save_memory)
from .painter.uvtransform_sbsar import SbsarError
from .painter.viewport_camera import FramingError, ViewportFramer
from .processing.normal_detection import detect_normal_maps
from .processing.scanner import ScanCancelled, ScanError, scan_folder
from .ui.build_progress import BuildProgressDialog
from .ui.mapping import MappingWidget
from .ui.main_panel import DEFAULT_GRID_SIZE, GRID_SIZES, AtlasMapperPanel
from .ui.scan_progress import ScanProgressDialog
from .ui.scan_results import ScanReportWidget, build_scan_cancelled, build_scan_error
from .ui.widgets import add_title_bar_icon, show_message

_LOG_CHANNEL = "Atlas Mapper"

# Widgets created by the plugin, kept so they can be removed in close_plugin().
_plugin_widgets = []

# Atlas ID assignment of the last successful scan (validated data for the build).
# texture_set: Texture Set active at that scan, whose memory was restored.
# normal_confirmed: Texture Sets whose project normal format the artist
# confirmed since the project opened (asked once, workflow.md §20.1).
_current = {"assignment": None, "texture_set": None, "normal_confirmed": set()}

# Viewport framing (workflow.md §11.1): the meshes of the open project, the
# MappingWidget shown, the target framed in each cell (index, for repeated
# clicks) and the framing errors already shown to the artist (once each).
# enabled: "Frame viewport on click", kept on this computer like the preset.
_framing = {"framer": ViewportFramer(), "mapping": None, "index": {}, "errors_shown": set(),
            "enabled": True}

# Project events followed by the plugin: (event class, callback), disconnected
# in close_plugin().
_event_callbacks = []

# Last naming preset used, kept on this computer between Painter sessions
# (Windows registry, via Qt): a new project starts with it.
_SETTINGS = ("Atlas Mapper", "Atlas Mapper")
_LAST_PRESET_KEY = "naming_preset"
_FRAME_VIEWPORT_KEY = "frame_viewport"


def start_plugin():
    panel = AtlasMapperPanel(list_presets)
    if not panel.select_preset(QtCore.QSettings(*_SETTINGS).value(_LAST_PRESET_KEY, "")):
        panel.select_preset(DEFAULT_PRESET)  # otherwise the first preset stays selected
    # Qt stores booleans as text in the registry: "false" when unchecked.
    _framing["enabled"] = (
        str(QtCore.QSettings(*_SETTINGS).value(_FRAME_VIEWPORT_KEY, True)).lower() != "false")
    panel.scan_requested.connect(lambda folder, n: _on_scan_requested(panel, folder, n))
    panel.build_requested.connect(lambda folder, n: _on_build_requested(panel, n))
    panel.project_normal_changed.connect(lambda fmt: _on_project_normal_changed(panel, fmt))
    # "Rebuild all" changes what the line above "Build Atlas" announces.
    panel.rebuild_all_changed.connect(
        lambda: _current["assignment"] is not None
        and _update_build_state(panel, _current["assignment"]))
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


def _restore_source(panel, suggested_grid):
    """Fill the root folder and the grid of the last Build of this project,
    then scan it right away so the remembered choices are shown at once.
    The memory is the one of the active Texture Set (one atlas per Texture Set).
    Never built: the grid suggested by the mesh UVs is selected (workflow.md §12.2)."""
    memory = _read_memory(active_texture_set())
    if not (isinstance(memory, dict) and memory.get("root_folder")):
        if suggested_grid is not None:
            panel.set_grid_size(suggested_grid)
        return
    project_normal = build_memory.restore_project_normal_format(memory)
    if project_normal:
        panel.set_project_normal_format(project_normal)
    grid_size = memory.get("grid_size")
    if suggested_grid is not None and grid_size in GRID_SIZES and grid_size != suggested_grid:
        # Atlas reorganized in the DCC since the last Build? The artist chooses.
        grid_size = panel.confirm_remembered_grid(grid_size, suggested_grid)
    panel.set_source(memory["root_folder"], grid_size, memory.get("naming_preset"))
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
    # New project: no memory yet, only the grid suggested by the mesh is set.
    _restore_source(panel, _suggest_grid(panel, log=True))


def _suggest_grid(panel, log=False):
    """Grid suggested by the mesh UVs of the project (workflow.md §12.2), given
    to the panel; None when the mesh cannot be read or no grid fits."""
    try:
        meshes = _framing["framer"].meshes()
    except FramingError as error:
        if log:
            _log(f"No grid suggested from the mesh UVs: {error}")
        panel.set_suggested_grid(None)
        return None
    size = suggested_grid_size(meshes, GRID_SIZES)
    panel.set_suggested_grid(size)
    if log:
        _log(f"Grid suggested by the mesh UVs: {size}x{size}" if size else
             "No grid suggested: the UVs of the meshes do not lie in the cells of a "
             + ", ".join(f"{n}x{n}" for n in GRID_SIZES) + " grid.")
    return size


def _forget_project(panel):
    _current["assignment"] = None
    _current["texture_set"] = None
    _current["normal_confirmed"].clear()
    _framing["framer"].forget()
    _framing["mapping"] = None
    _framing["index"].clear()
    _framing["errors_shown"].clear()
    panel.set_suggested_grid(None)
    # Empty field, grid back to the first one of the list: the next project
    # starts from the defaults (or its own Build / mesh).
    panel.set_source("", DEFAULT_GRID_SIZE)  # the scan results are cleared too
    panel.set_project_normal_format(NORMAL_OPENGL)  # Painter's default for a new project
    panel.set_project_open(False)


def _confirm_project_normal(panel):
    """First scan of a Texture Set never built: the artist confirms the
    project normal format, which no API can read (workflow.md §20.1).
    Returns False when the artist cancels (no scan)."""
    texture_set = active_texture_set()
    if not texture_set or texture_set in _current["normal_confirmed"]:
        return True
    memory = _read_memory(texture_set)
    if build_memory.restore_project_normal_format(memory):
        return True   # built before: the format of that Build is kept
    normal_format = panel.confirm_project_normal_format()
    if normal_format is None:
        return False
    panel.set_project_normal_format(normal_format)
    _current["normal_confirmed"].add(texture_set)
    return True


def _on_scan_requested(panel, folder, grid_size):
    if not _confirm_project_normal(panel):
        return   # cancelled: the previous scan stays shown
    preset = panel.preset_name()
    panel.clear_results()
    _current["assignment"] = None
    _current["texture_set"] = None
    _framing["mapping"] = None   # its grid is deleted with the previous results
    try:
        # Read at every scan: edits to the preset file apply without
        # restarting Painter.
        attributes = load_texture_attributes(preset)
        # A long scan (big folder, network drive) shows a window with Cancel.
        progress = ScanProgressDialog(panel)
        try:
            result = scan_folder(folder, attributes, progress.report)
            # Format of every normal map, read from its pixels (workflow.md §20.1.1).
            detections = detect_normal_maps(result.assets, progress.report_normal_maps)
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
    if detections:
        _log("Normal maps detected: " + ", ".join(
            f"{os.path.basename(path)} {detection.verdict} "
            f"({detection.opengl_share:.0%} OpenGL)"
            for path, detection in sorted(detections.items())))
    panel.set_scan_report(ScanReportWidget(result))
    if result.assets:
        # Assets start without an Atlas ID: restored or pre-filled below,
        # the artist validates and assigns the others.
        assignment = AtlasAssignment(grid_size, result.assets, attributes.packed_channels)
        assignment.set_project_normal_format(panel.project_normal_format())
        # Choices of the last Build in the active Texture Set come back (still
        # editable). Another Texture Set = another atlas: rescan to load its own.
        texture_set = active_texture_set()
        restore_report = build_memory.restore(assignment, _read_memory(texture_set), preset)
        # Sure detections pre-fill the normal format, except for the assets
        # whose choices come back from the last Build (validated by the artist).
        assignment.normal_detections = {path: detection.verdict
                                        for path, detection in detections.items()}
        prefilled = assignment.apply_normal_detections(
            restore_report.restored if restore_report else ())
        if prefilled:
            _log(f"Normal format pre-filled from the detection: {', '.join(prefilled)}")
        # Sure Atlas IDs from the mesh names and UVs, after the Build memory
        # (whose choices are kept): the artist checks them (workflow.md §12.1).
        _prefill_atlas_ids(assignment, attributes, restore_report)
        # Mesh reimported since the project opened: the suggested grid follows.
        _suggest_grid(panel)
        mapping = MappingWidget(assignment, list(attributes.texture_formats), restore_report,
                                frame_viewport=_framing["enabled"])
        # "Build Atlas" follows every ID / file choice of the artist.
        mapping.assignment_changed.connect(
            lambda: _update_build_state(panel, assignment))
        mapping.frame_viewport_changed.connect(
            lambda checked: _on_frame_viewport_changed(panel, checked))
        mapping.cell_framing_requested.connect(
            lambda atlas_id, again: _on_cell_framing(panel, grid_size, atlas_id, again))
        panel.set_mapping(mapping)
        _update_build_state(panel, assignment)  # not ready: no ID yet
        _current["assignment"] = assignment
        _current["texture_set"] = texture_set
        _framing["mapping"] = mapping
        # The grid is deleted when the results are cleared (other folder, grid...).
        mapping.destroyed.connect(
            lambda _object=None, m=mapping: _framing["mapping"] is m and _framing.update(mapping=None))
        _framing["index"].clear()
        _refresh_framing(panel, grid_size)


def _prefill_atlas_ids(assignment, attributes, restore_report):
    """Pre-fill the sure Atlas IDs from the meshes of the project (read in its
    FBX or OBJ, as for the viewport framing). Assets restored from the last Build,
    and the cells they use, are left alone. Problems are only logged: the
    artist assigns the IDs by hand, as without pre-fill."""
    try:
        meshes = _framing["framer"].meshes()
    except FramingError as error:
        _log(f"Atlas IDs not pre-filled: {error}")
        return
    validated = restore_report.restored if restore_report else ()
    taken = {assignment.atlas_id(asset) for asset in assignment.assets} - {None}
    prefills, skipped = prefill_atlas_ids(
        [asset.name for asset in assignment.assets], meshes, assignment.grid_size,
        attributes.asset_prefixes, validated, taken)
    changed = assignment.apply_prefill(prefills)
    if changed:
        _log("Atlas IDs pre-filled from the mesh names and UVs: " + ", ".join(
            f"{name} {prefills[name].atlas_id} ({' + '.join(prefills[name].mesh_names)})"
            for name in changed))
    if skipped:
        _log("Atlas IDs not pre-filled: " + "; ".join(
            f"{name} ({reason})" for name, reason in skipped.items()))


def _on_frame_viewport_changed(panel, checked):
    _framing["enabled"] = checked
    QtCore.QSettings(*_SETTINGS).setValue(_FRAME_VIEWPORT_KEY, checked)
    if _framing["mapping"] is not None:
        _refresh_framing(panel, _framing["mapping"].assignment.grid_size)


def _refresh_framing(panel, grid_size):
    """After a scan or a change of the option: errors are only logged here,
    they are shown when the artist clicks a cell."""
    try:
        _update_framing_targets(panel, grid_size)
    except FramingError as error:
        _log(f"Viewport framing not possible: {error}", substance_painter.logging.WARNING)


def _update_framing_targets(panel, grid_size):
    """Tell the grid which cells have meshes to frame (read from the mesh
    file of the project, again after it changed). Returns the targets
    {Atlas ID: [Target]}; raises FramingError when they cannot be read."""
    mapping = _framing["mapping"]
    if not _framing["enabled"]:
        mapping.set_framing_targets({}, enabled=False)
        return {}
    try:
        targets = _framing["framer"].targets(grid_size)
    except FramingError:
        mapping.set_framing_targets({})   # asset cells still ask: the error is shown then
        raise
    mapping.set_framing_targets({atlas_id: [" + ".join(target.mesh_names) for target in cell]
                                 for atlas_id, cell in targets.items()})
    return targets


def _on_cell_framing(panel, grid_size, atlas_id, again):
    """Click on a grid cell with "Frame viewport on click": frame its meshes;
    clicked again, the next one (workflow.md §11.1)."""
    try:
        targets = _update_framing_targets(panel, grid_size).get(atlas_id, [])
        if not targets:
            return   # no mesh with its UVs in this cell
        index = (_framing["index"].get(atlas_id, -1) + 1) if again else 0
        index %= len(targets)
        _framing["index"][atlas_id] = index
        _framing["framer"].frame(targets[index])
    except FramingError as error:
        _log(f"Viewport framing not possible: {error}", substance_painter.logging.WARNING)
        message = str(error)
        if message not in _framing["errors_shown"]:   # once per problem, not at every click
            _framing["errors_shown"].add(message)
            show_message(panel, message, warning=True)


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


def _on_project_normal_changed(panel, normal_format):
    """CONFIGURATION > Project normal map format changed: the scan shown is kept,
    only the green flip decided at Build changes (so do the assets to update)."""
    if _current["assignment"] is not None:
        _current["assignment"].set_project_normal_format(normal_format)
        _update_build_state(panel, _current["assignment"])


def _assets_to_build(assignment):
    """Validated data only: assets with an Atlas ID, maps resolved one by one
    (own file, or one channel of a packed file)."""
    assets = []
    for asset in assignment.placed_assets():
        maps = assignment.resolved_maps(asset)
        assets.append(AssetToBuild(
            asset.name, assignment.atlas_id(asset),
            {fmt: src.texture.path for fmt, src in maps.items() if src.channel is None},
            assignment.flip_normal_green(asset),
            {fmt: (src.texture.path, src.channel, assignment.format_label(src.packed_format))
             for fmt, src in maps.items() if src.channel is not None}))
    return assets


def _unchanged_assets(panel, assets, grid_size):
    """Assets the Build can leave as is: same choices as at the last Build in
    the active Texture Set (workflow.md §22.3). Empty when "Rebuild all" is
    checked."""
    if panel.rebuild_all():
        return frozenset()
    return build_memory.unchanged_assets(assets, grid_size, _read_memory(active_texture_set()))


def _update_build_state(panel, assignment):
    """Enable "Build Atlas" and tell how many assets will be created / updated /
    left unchanged / ignored, and how many folders of withdrawn assets will be
    deleted / hidden."""
    assets = _assets_to_build(assignment)
    placed = len(assets)
    try:
        updated, unchanged, deleted, hidden = folder_changes(
            assets, _unchanged_assets(panel, assets, assignment.grid_size))
    except Exception as error:  # only an announcement: never block the panel for it
        _log(f"Could not read the asset folders of the layer stack: {error!r}",
             substance_painter.logging.WARNING)
        updated = unchanged = deleted = hidden = 0
    # The Build goes into the active Texture Set: named above the button.
    panel.set_build_ready(assignment.can_build(), placed, len(assignment.assets) - placed,
                          deleted, hidden, updated, unchanged,
                          texture_set=active_texture_set() or "")


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
    assets = _assets_to_build(assignment)
    unchanged = _unchanged_assets(panel, assets, grid_size)
    # A Build can take a while (4x4 grid): a window with a turning icon and
    # the busy cursor show that it is working.
    progress = BuildProgressDialog(panel)
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    start = time.monotonic()
    ended = []

    def end_progress():
        """Close the progress window and the busy cursor (once)."""
        if not ended:
            ended.append(True)
            progress.finish()
            QtWidgets.QApplication.restoreOverrideCursor()

    try:
        report = build_atlas(grid_size, assets, unchanged, progress.report)
    except (BuildError, SbsarError) as error:
        end_progress()
        _log(f"Build failed: {error}", substance_painter.logging.ERROR)
        panel.show_build_result(str(error), succeeded=False)
        return
    except Exception as error:  # unexpected Painter error: keep details in the log
        end_progress()
        _log(f"Build failed (unexpected): {error!r}", substance_painter.logging.ERROR)
        panel.show_build_result("The Build failed unexpectedly.\n"
                                "The details are in Painter's Log window "
                                "(Atlas Mapper channel). Ctrl+Z undoes what was created.",
                                succeeded=False)
        return
    build_end = time.monotonic()
    _log(f"Build time: {build_end - start:.1f} s")   # the plugin's own work
    # Painter then recomputes the layers, and no API tells when it is done:
    # the window stays (icon still) until the result window shows.
    progress.set_finishing()
    try:
        _finish_build(panel, assignment, assets, grid_size, report, build_end, end_progress)
    finally:
        end_progress()   # already done if the result window showed


def _finish_build(panel, assignment, assets, grid_size, report, build_end, end_progress):
    """After a successful Build: Build memory, log, result window, panel."""
    # Remember the choices in the project (kept once the project is saved),
    # for the Texture Set just built.
    _current["texture_set"] = report.texture_set
    # Fingerprints of the assets up to date: the next Build skips them if
    # nothing changed (workflow.md §22.3).
    fingerprints = {asset.name.lower(): build_memory.asset_fingerprint(asset, grid_size)
                    for asset in assets if asset.name.lower() in report.up_to_date}
    try:
        save_memory(report.texture_set,
                    build_memory.to_memory(assignment, panel.root_folder(), panel.preset_name(),
                                           fingerprints))
    except MEMORY_ERRORS as error:
        _log(f"Could not store the Build memory in the project: {error!r}",
             substance_painter.logging.WARNING)
        report.notes.append("The choices of this Build could not be saved in the project.")

    for note in report.notes:
        _log(note.replace("**", ""), substance_painter.logging.WARNING)  # no bold marks in the log
    _log(f"Build in '{report.texture_set}' - created: {', '.join(report.created) or '-'}"
         f" | updated: {', '.join(report.updated) or '-'}"
         f" | unchanged: {', '.join(report.unchanged) or '-'}")
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
    if report.unchanged:
        # A count only: the list would hide the assets that did change.
        count = len(report.unchanged)
        lines.append(f"{count} asset{'' if count == 1 else 's'} unchanged since the last "
                     f"Build, left as is.")
    if not report.created and not report.updated:
        lines.insert(0, "Nothing to rebuild.")
    message = (f"Texture Set \"{report.texture_set}\"\n"
               f"Layer Stack folder \"Atlas Mapper\"\n\n"
               + "\n".join(lines))
    if report.notes:
        message += "\n\nNotes:\n• " + "\n• ".join(report.notes)

    def on_result_shown():
        # Runs when Painter is free again: its layer update is over.
        _log(f"Painter layer update: {time.monotonic() - build_end:.1f} s")
        end_progress()

    QtCore.QTimer.singleShot(0, on_result_shown)
    panel.show_build_result(message, succeeded=True)
    panel.set_rebuild_all(False)  # one Build only: never left checked by mistake
    _update_build_state(panel, assignment)   # the layer stack changed: folders to remove too
