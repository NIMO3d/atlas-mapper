"""Creation phase: generates or updates the Atlas Mapper Layer Stack.

Only module that modifies the Painter project. It receives validated data
(asset name, Atlas ID, chosen texture files) and, in the active Texture Set:

    Atlas Mapper                         <- folder, found by name or created
     ├─ 01_ElectricDrill                  <- folder "<ID>_<asset>", black mask
     │   ├─ Mask: [AM] Mask_Quadrant_Limiter   (Fill -> UVtransform, output quadrantmask)
     │   ├─ (artist's layers)                  <- never touched
     │   └─ [AM] ElectricDrill_Textures        (Fill -> UVtransform in material mode)
     │        └─ [AM] Levels - Normal (Flip G) <- only when the normal must be flipped
     └─ 02_...

First and second Build follow the same path (docs/project/workflow.md §22.2):
every generated element is looked up by its name, created if missing, then
set to the validated values. An asset unchanged since the last Build (same
fingerprint, folder still there with the same ID) is skipped, unless the
artist asks to rebuild everything (§22.3). Everything else (the artist's layers and
effects, folders of assets not built this time) is left as is. Painter's
Python API cannot move a layer: an existing folder keeps its place.

Texture Fill and mask use the same uv_tiling / u_offset
(docs/project/uv-transformation.md §11). The UVs are never touched.
"""

import re
from dataclasses import dataclass, field

import substance_painter.layerstack as layerstack
import substance_painter.logging
from substance_painter.levels import LevelsParamsRGB
import substance_painter.project
import substance_painter.resource
import substance_painter.source
import substance_painter.textureset as textureset

from ..core.atlas_assignment import NORMAL_TEXTURE_FORMAT
from ..uv.transformations import cell_transform
from . import uvtransform_sbsar as sbsar

# Names of the generated elements: the plugin finds them again by these names.
ROOT_FOLDER_NAME = "Atlas Mapper"
_LOG_CHANNEL = "Atlas Mapper"   # same channel as the plugin's messages (__init__.py)
# "[AM] " marks what every Build overwrites: the artist must not edit it
# (docs/project/workflow.md §22.2). Names without it (projects built before
# the marker) are still recognized, then renamed.
GENERATED_PREFIX = "[AM] "
MASK_FILL_NAME = "Mask_Quadrant_Limiter"
LEVELS_NAME = "Levels - Normal (Flip G)"
_FOLDER_NAME_PATTERN = re.compile(r"^(\d+)_(.+)$")   # "<ID>_<asset>"

# Green channel inverted, red and blue unchanged: output min/max swapped on
# green only (method 02 of docs/artistic/tutorials/
# how-to-fix-imported-normals-map-nicolas-morlet-3d-artist.jpg).
# Method 01 (color space) is not possible: tested 2026-10-03, a bitmap plugged
# into a .sbsar input only accepts Raw / Data / DataSigned.
_FLIP_GREEN = LevelsParamsRGB(output_min=(0.0, 1.0, 0.0), output_max=(1.0, 0.0, 1.0))


def _generated_name(base_name):
    """Name given to a generated element: 'Mask_Quadrant_Limiter' -> '[AM] Mask_Quadrant_Limiter'."""
    return GENERATED_PREFIX + base_name


def _is_generated(node, base_name):
    """True if the node carries this generated name, with or without the marker
    (any case)."""
    name = node.get_name().lower()
    return name in (base_name.lower(), _generated_name(base_name).lower())


class BuildError(Exception):
    """The build cannot start or failed. The message is written for the artist."""


@dataclass
class AssetToBuild:
    """Validated data of one asset (from AtlasAssignment)."""
    name: str
    atlas_id: int
    textures: dict   # {texture format: file path}
    flip_normal_green: bool = False   # source normal format differs from the project's
    # Maps read from one channel of a packed file: {map: (path, "R"/"G"/"B", "ORM")}.
    packed_maps: dict = field(default_factory=dict)


@dataclass
class BuildReport:
    texture_set: str = ""
    created: list = field(default_factory=list)    # folder names, new this Build
    updated: list = field(default_factory=list)    # folder names, already there
    unchanged: list = field(default_factory=list)  # folder names, left as is (§22.3)
    # Asset names (lower case) whose folder is up to date after this Build:
    # built or left unchanged. Their fingerprints go into the Build memory.
    up_to_date: set = field(default_factory=set)
    # Readable sentences for the artist; **text** = bold in the Build window.
    notes: list = field(default_factory=list)


def build_atlas(grid_size, assets, unchanged=frozenset(), progress=None):
    """Create or update the Layer Stack for the validated assets. Raises BuildError.
    unchanged: asset names (lower case) whose folder can be left as is
    (core/build_memory.unchanged_assets); empty = rebuild everything.
    progress(done, total, asset name), optional: called before each Painter
    call, so a progress window can show the Build is working
    (ui/build_progress.py)."""
    def report_progress(done=0, asset_name=""):
        if progress is not None:
            progress(done, len(assets), asset_name)

    if not substance_painter.project.is_open():
        raise BuildError("No project is open in Painter.\n"
                         "Open the project holding the atlas mesh, then run the Build again.")
    try:
        stack = textureset.get_active_stack()
    except RuntimeError as error:
        raise BuildError("No Texture Set is active.\n"
                         "Select the Texture Set of the atlas, then run the Build again.") from error

    report = BuildReport(texture_set=stack.material().name)
    report_progress()
    _ensure_channel(stack, assets, "ambient occlusion", textureset.ChannelType.AO, report)
    opacity_added = _ensure_channel(stack, assets, "opacity", textureset.ChannelType.Opacity,
                                    report)
    # 16 bits for the height (no stair steps in gradients); sRGB for the
    # emissive color, like Painter's own templates.
    _ensure_channel(stack, assets, "height", textureset.ChannelType.Height, report,
                    textureset.ChannelFormat.L16)
    _ensure_channel(stack, assets, "emissive", textureset.ChannelType.Emissive, report,
                    textureset.ChannelFormat.sRGB8)
    # After all the "Channel ... added" notes: they read as one group.
    if opacity_added:
        report.notes.append("To see the transparency, the shader must handle opacity "
                            "(Shader Settings in Painter, and the material in the engine).")
    report_progress()
    sbsar_id = sbsar.get_or_import()

    # One undo entry for the whole build; Painter recomputes once at the end.
    with layerstack.ScopedModification("Atlas Mapper - Build Atlas"):
        root = _find_or_create_root(stack, report)
        folders = _AssetFolders(root)
        built = {}   # asset key -> asset, for the notes about other folders
        for done, asset in enumerate(sorted(assets, key=lambda a: a.atlas_id)):
            report_progress(done, asset.name)
            entry = folders.find(asset.name)
            if _is_unchanged(entry, asset, unchanged):
                # Still in its cell: counts for the notes about other folders.
                entry.unchanged = True
                built[asset.name.lower()] = asset
                report.unchanged.append(entry.name)
                report.up_to_date.add(asset.name.lower())
                continue
            # Each new step (Painter call) also reports progress.
            step = _Step(lambda d=done, name=asset.name: report_progress(d, name))
            try:
                if _build_asset(folders, stack, asset, grid_size, sbsar_id, report, step):
                    built[asset.name.lower()] = asset
                    report.up_to_date.add(asset.name.lower())
            except BuildError:
                raise   # already written for the artist
            except Exception as error:
                # Tells which Painter call failed, for the log.
                raise RuntimeError(f"{asset.name}, step \"{step.name}\": {error!r} "
                                   f"| UVtransform = {sbsar.describe(sbsar_id)}") from error
        folders.remove_withdrawn(assets, report)
        folders.add_notes(built, report)
    return report


def _ensure_channel(stack, assets, texture_format, channel, report,
                    channel_format=textureset.ChannelFormat.L8):
    """Add a channel (AO, Opacity, Height, Emissive) if an asset has this map
    and it is missing. Returns True if the channel was added.
    channel_format: L8 = 8-bit grayscale, enough for an AO or opacity map."""
    needed = any(texture_format in asset.textures or texture_format in asset.packed_maps
                 for asset in assets)
    if not needed or stack.has_channel(channel):
        return False
    label = texture_format.title()
    try:
        stack.add_channel(channel, channel_format)
    except ValueError:
        # Documented case: not available with material layering.
        report.notes.append(f"The {label} channel could not be added to the Texture Set "
                            f"(material layering?). Add it in Texture Set Settings / "
                            f"Channels: the {label} maps are not plugged.")
        return False
    # Bold: a channel added to the project must not go unnoticed.
    report.notes.append(f"Channel **{label}** added to the **Texture Set**.")
    return True


def _is_unchanged(entry, asset, unchanged):
    """True if the Build can leave this asset's folder as is: same
    fingerprint as at the last Build, folder still there with the same ID."""
    return (asset.name.lower() in unchanged and entry is not None
            and entry.atlas_id == asset.atlas_id)


def folder_changes(assets, unchanged=frozenset()):
    """Read only, before the Build: (updated, unchanged, deleted, hidden).
    updated = how many assets already have their folder and will be rebuilt
    (see _AssetFolders.find); unchanged = how many folders will be left as
    is (_is_unchanged);
    deleted / hidden = how many asset folders the Build will delete / hide
    because their asset is not in assets (see
    _AssetFolders.remove_withdrawn). Folders already hidden are not counted.
    (0, 0, 0, 0) when there is nothing to look at (no project, no active
    Texture Set, no "Atlas Mapper" folder)."""
    if not substance_painter.project.is_open():
        return 0, 0, 0, 0
    try:
        stack = textureset.get_active_stack()
    except RuntimeError:
        return 0, 0, 0, 0
    roots = _roots(stack)
    if not roots:
        return 0, 0, 0, 0
    folders = _AssetFolders(roots[0])
    kept_assets = {asset.name.lower() for asset in assets}
    updated = same = 0
    for asset in assets:
        entry = folders.find(asset.name)
        if _is_unchanged(entry, asset, unchanged):
            same += 1
        elif entry is not None:
            updated += 1
    deleted = hidden = 0
    for entry in folders.entries:
        if entry.asset_key in kept_assets:
            continue
        if _holds_only_generated(entry):
            deleted += 1
        elif entry.node.is_visible():
            hidden += 1
    return updated, same, deleted, hidden


def _roots(stack):
    """The "Atlas Mapper" folders at the top level of the stack, top first."""
    return [node for node in layerstack.get_root_layer_nodes(stack)
            if isinstance(node, layerstack.GroupLayerNode)
            and node.get_name() == ROOT_FOLDER_NAME]


def _find_or_create_root(stack, report):
    """The "Atlas Mapper" folder at the top level of the stack (the first one)."""
    roots = _roots(stack)
    if len(roots) > 1:
        report.notes.append(f"{len(roots)} \"{ROOT_FOLDER_NAME}\" folders exist: only the top "
                            f"one is updated, the others are not touched.")
    if roots:
        return roots[0]
    root = layerstack.insert_group(layerstack.InsertPosition.from_textureset_stack(stack))
    root.set_name(ROOT_FOLDER_NAME)
    return root


class _AssetFolders:
    """Asset folders ("<ID>_<asset>") inside the root folder, top to bottom."""

    def __init__(self, root):
        self.root = root
        self.entries = []   # [_Folder], in layer stack order (top first)
        for node in root.sub_layers():
            match = _FOLDER_NAME_PATTERN.match(node.get_name())
            if isinstance(node, layerstack.GroupLayerNode) and match:
                self.entries.append(_Folder(node, int(match.group(1)), match.group(2)))

    def find(self, asset_name):
        """Folder of this asset (the first one if there are several), or None."""
        for entry in self.entries:
            if entry.asset_key == asset_name.lower():
                return entry
        return None

    def create(self, atlas_id, asset_name):
        """New folder, placed among the others in Atlas ID order (ID 1 at the top)."""
        index = next((i for i, e in enumerate(self.entries) if e.atlas_id > atlas_id),
                     len(self.entries))
        if index < len(self.entries):
            position = layerstack.InsertPosition.above_node(self.entries[index].node)
        elif self.entries:
            position = layerstack.InsertPosition.below_node(self.entries[-1].node)
        else:
            position = layerstack.InsertPosition.inside_node(self.root, layerstack.NodeStack.Substack)
        entry = _Folder(layerstack.insert_group(position), atlas_id, asset_name)
        self.entries.insert(index, entry)
        return entry

    def remove_withdrawn(self, assets, report):
        """Folders of assets withdrawn from the Build (no ID any more, or no
        longer in the scanned folder): deleted if they hold only generated
        elements, else hidden so the artist's layers are never lost
        (docs/project/workflow.md §22.2)."""
        kept_assets = {asset.name.lower() for asset in assets}
        for entry in list(self.entries):
            if entry.asset_key in kept_assets:
                continue
            if _holds_only_generated(entry):
                layerstack.delete_node(entry.node)
                self.entries.remove(entry)
                report.notes.append(f"Folder {entry.name_at_start} deleted (asset withdrawn from "
                                    f"the Build).")
            else:
                entry.node.set_visible(False)
                entry.withdrawn = True
                report.notes.append(
                    f"⚠ Folder {entry.name} hidden (asset withdrawn from the Build): it holds "
                    f"your own layers. Delete it in Layers if it is no longer needed.")

    def add_notes(self, built, report):
        """Folders not built this time, and folders out of Atlas ID order."""
        for entry in self.entries:
            if entry.built or entry.unchanged or entry.withdrawn:
                continue
            same_cell = [a.name for a in built.values() if a.atlas_id == entry.atlas_id]
            if same_cell:
                report.notes.append(
                    f"⚠ The folder {entry.name} (not built this Build) still covers "
                    f"cell {entry.atlas_id}, like {', '.join(same_cell)}: hide it or "
                    f"delete it in Layers.")
            else:
                report.notes.append(
                    f"Folder {entry.name} kept (not built this Build): it stays "
                    f"visible in cell {entry.atlas_id}.")
        ids = [entry.atlas_id for entry in self.entries]
        if ids != sorted(ids):
            report.notes.append(
                "The folders are no longer sorted by ID (current order: "
                f"{', '.join(e.name for e in self.entries)}). The render is not affected; "
                "you can drag them by hand in Layers.")


class _Folder:
    """One asset folder and what is known about it."""

    def __init__(self, node, atlas_id, asset_name):
        self.node = node
        self.atlas_id = atlas_id
        self.asset_key = asset_name.lower()
        self.built = False       # built (created or updated) by this Build
        self.unchanged = False   # left as is: unchanged since the last Build
        self.withdrawn = False   # asset withdrawn from the Build, folder hidden
        self.name_at_start = node.get_name()   # still readable once the node is deleted

    @property
    def name(self):
        return self.node.get_name()

    def set_id(self, atlas_id, asset_name):
        self.atlas_id = atlas_id
        self.node.set_name(f"{atlas_id:02d}_{asset_name}")


def _holds_only_generated(entry):
    """True if the asset folder holds nothing but what the Build creates: no
    layer, effect or mask paint added by the artist."""
    folder = entry.node
    if folder.content_effects():
        return False
    if any(not (isinstance(node, layerstack.FillEffectNode) and _is_generated(node, MASK_FILL_NAME))
           for node in folder.mask_effects()):
        return False
    layers = folder.sub_layers()
    if len(layers) > 1:
        return False
    if not layers:
        return True
    fill = layers[0]
    # The texture Fill of this asset (folder name "<ID>_<asset>"), without
    # mask or effect of the artist (the normal Levels is generated).
    match = _FOLDER_NAME_PATTERN.match(entry.name_at_start)
    if not (isinstance(fill, layerstack.FillLayerNode) and match
            and _is_generated(fill, f"{match.group(2)}_Textures")):
        return False
    if fill.has_mask():
        return False
    return all(isinstance(node, layerstack.LevelsEffectNode) and _is_generated(node, LEVELS_NAME)
               for node in fill.content_effects())


class _Step:
    """Name of the Painter call in progress (for the error message), and a
    progress report each time it changes (before each Painter call)."""

    def __init__(self, on_change=None):
        self._name = "preparation"
        self._on_change = on_change

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = value
        if self._on_change is not None:
            self._on_change()


def _routes(stack, asset, report):
    """{map: (route, path, packed channel or None)}: the maps the .sbsar can
    receive AND whose channel exists in the Texture Set."""
    wanted = [(fmt, path, None, None) for fmt, path in asset.textures.items()]
    wanted += [(fmt, path, channel, label)
               for fmt, (path, channel, label) in asset.packed_maps.items()]
    routes = {}
    for texture_format, path, packed_channel, packed_label in wanted:
        route = sbsar.MAP_ROUTES.get(texture_format)
        origin = f" ({packed_label} · {packed_channel})" if packed_channel else ""
        if route is None:
            report.notes.append(f"{asset.name}: map {texture_format.title()}{origin} not "
                                f"supported yet, ignored.")
        elif packed_channel and route.channel_param is None:
            report.notes.append(f"{asset.name}: the {texture_format.title()} map cannot be "
                                f"read from a packed texture{origin}, ignored.")
        elif packed_channel == "A" and texture_format not in sbsar.ALPHA_READY_MAPS:
            # Sending 4 to a branch that stops at B would give a wrong map silently.
            report.notes.append(f"{asset.name}: UVtransform cannot read the A channel yet for "
                                f"the {texture_format.title()} map{origin}, map ignored.")
        elif not stack.has_channel(route.channel):
            report.notes.append(f"{asset.name}: the Texture Set has no "
                                f"{texture_format.title()} channel, map ignored.")
        else:
            routes[texture_format] = (route, path, packed_channel)
    return routes


def _build_asset(folders, stack, asset, grid_size, sbsar_id, report, step):
    """Create or update the folder of one asset. Returns False if nothing was built."""
    routes = _routes(stack, asset, report)
    if not routes:
        report.notes.append(f"{asset.name}: no usable map, asset not built.")
        return False

    transform = cell_transform(asset.atlas_id, grid_size)
    parameters = {sbsar.PARAM_UV_TILING: transform.uv_tiling,
                  sbsar.PARAM_U_OFFSET: transform.u_offset}

    step.name = "asset folder"
    entry = folders.find(asset.name)
    if entry is None:
        entry = folders.create(asset.atlas_id, asset.name)
        report.created.append(f"{asset.atlas_id:02d}_{asset.name}")
    else:
        report.updated.append(f"{asset.atlas_id:02d}_{asset.name}")
    entry.set_id(asset.atlas_id, asset.name)   # renames the folder if the ID changed
    entry.built = True
    folder = entry.node
    folder.set_visible(True)   # hidden by an earlier Build that withdrew the asset

    _update_mask(folder, parameters, sbsar_id, step)
    _update_texture_fill(folder, asset, routes, parameters, sbsar_id, step)
    return True


def _update_mask(folder, parameters, sbsar_id, step):
    """Quadrant mask: everything outside the asset's cell is discarded."""
    step.name = "folder mask"
    if not folder.has_mask():
        folder.add_mask(layerstack.MaskBackground.Black)
    mask_fill = next((node for node in folder.mask_effects()
                      if isinstance(node, layerstack.FillEffectNode)
                      and _is_generated(node, MASK_FILL_NAME)), None)
    if mask_fill is None:
        mask_fill = layerstack.insert_fill(
            layerstack.InsertPosition.inside_node(folder, layerstack.NodeStack.Mask))
    mask_fill.set_name(_generated_name(MASK_FILL_NAME))   # also adds the marker to an old one
    step.name = "UVtransform in the mask"
    mask_source = mask_fill.get_source(None)   # mask = mono-channel: None
    if not isinstance(mask_source, substance_painter.source.SourceSubstance):
        mask_source = mask_fill.set_source(None, sbsar_id)
    step.name = "quadrantmask output"
    mask_source.active_output = sbsar.OUTPUT_QUADRANT_MASK
    step.name = "mask parameters"
    mask_source.set_parameters(parameters)


def _update_texture_fill(folder, asset, routes, parameters, sbsar_id, step):
    """Texture Fill Layer: one UVtransform in material mode for all the maps."""
    step.name = "texture Fill"
    fill_name = f"{asset.name}_Textures"
    layers = folder.sub_layers()
    fill = next((node for node in layers if isinstance(node, layerstack.FillLayerNode)
                 and _is_generated(node, fill_name)), None)
    if fill is None:
        # At the bottom of the folder: the artist's layers stay above it.
        position = (layerstack.InsertPosition.below_node(layers[-1]) if layers else
                    layerstack.InsertPosition.inside_node(folder, layerstack.NodeStack.Substack))
        fill = layerstack.insert_fill(position)
    fill.set_name(_generated_name(fill_name))

    step.name = "UVtransform in the Fill (material mode)"
    try:
        source = fill.get_material_source()
    except RuntimeError:   # new Fill, or not in material mode any more
        source = None
    if not isinstance(source, substance_painter.source.SourceSubstance):
        source = fill.set_material_source(sbsar_id)

    step.name = "UVtransform version"
    # Read once: each read is a call to Painter (the parameters do not change
    # while the maps are plugged).
    properties = source.get_properties()
    _check_sbsar_version(source, routes, parameters, properties)
    fill_parameters = dict(parameters)
    imported = {}   # path -> ResourceID: a packed file is imported once for its maps
    for route, path, packed_channel in routes.values():
        if path not in imported:
            step.name = f"import texture {path}"
            imported[path] = substance_painter.resource.import_project_resource(
                path, substance_painter.resource.Usage.TEXTURE).identifier()
        step.name = f"plugging {route.image_input}"
        source.set_source(route.image_input, imported[path])
        step.name = f"output {route.output}"
        source.output_mapping[route.channel] = route.output
        if route.channel_param:
            # 0 = separate grayscale file, 1/2/3 = R/G/B of a packed file,
            # 4 = A (opacity from the alpha of the Base Color).
            fill_parameters[route.channel_param] = sbsar.CHANNEL_VALUES[packed_channel]
        # Glossiness: Roughness branch inverted. A plain Roughness sets it back
        # off, if the project's UVtransform has the parameter (older versions
        # without it are never inverted; _check_sbsar_version stops a
        # Glossiness on them).
        if route.invert_param and route.invert_param in properties:
            # The .sbsar stores the toggle as INTEGER1 (sbsrender info); Painter
            # refuses a value of another type, so the current value's type is used.
            value_type = type(properties[route.invert_param].value())
            fill_parameters[route.invert_param] = value_type(route.inverted)
    step.name = "Fill parameters"
    source.set_parameters(fill_parameters)
    # Only the channels that received a map: a missing map does not
    # overwrite the channel with the .sbsar's empty input.
    step.name = "active channels of the Fill"
    fill.active_channels = {route.channel for route, _path, _ch in routes.values()}

    _update_normal_flip(fill, asset.flip_normal_green and NORMAL_TEXTURE_FORMAT in routes, step)


def _check_sbsar_version(source, routes, parameters, properties):
    """Stop before plugging anything if the project's UVtransform lacks an
    input, output or parameter needed by this asset.

    The project may still hold an older UVtransform (imported before the
    .sbsar got them, e.g. the opacity): the plugin reuses the project's copy.
    properties: source.get_properties(), read once by the caller.
    """
    used = list(routes.values())
    needed = set(parameters) | {route.channel_param for route, _p, _c in used if route.channel_param}
    needed |= {route.invert_param for route, _p, _c in used if route.inverted}
    missing = needed - set(properties)
    # Read once each: in the set below they would be read again for every map.
    image_inputs = set(source.image_inputs)
    image_outputs = set(source.image_outputs)
    missing |= {route.image_input for route, _p, _c in used if route.image_input not in image_inputs}
    missing |= {route.output for route, _p, _c in used if route.output not in image_outputs}
    if missing:
        raise BuildError(
            f"The UVtransform version in this project is old: it lacks "
            f"{', '.join(sorted(missing))}.\n"
            f"Update the project's UVtransform resource (Assets panel) or create a "
            f"new project, then run the Build again. Ctrl+Z undoes what was done.")
    _check_alpha_channel(properties, used)


def _check_alpha_channel(properties, used):
    """Stop if a map is read from the A channel (value 4) but the project's
    UVtransform is older than A in that branch (Roughness / Metallic / AO got
    it on 2026-10-06): the value would be clamped to B, a wrong map with no
    message. Checked on the drop-down list entries of the parameter."""
    for route, _path, packed_channel in used:
        if packed_channel != "A":
            continue
        prop = properties[route.channel_param]
        if prop.widget_type() != "Combobox":
            # Not a drop-down: its entries cannot be read, nothing to compare.
            substance_painter.logging.log(
                substance_painter.logging.WARNING, _LOG_CHANNEL,
                f"{route.channel_param}: widget {prop.widget_type()!r}, A channel not "
                f"checked. Properties: {prop.properties()}")
            continue
        if sbsar.CHANNEL_VALUES["A"] not in prop.enum_values().values():
            raise BuildError(
                f"The UVtransform version in this project is old: its "
                f"parameter {route.channel_param} does not offer the A channel.\n"
                f"Update the project's UVtransform resource (Assets panel) or create a "
                f"new project, then run the Build again. Ctrl+Z undoes what was done.")


def _update_normal_flip(fill, needed, step):
    """Levels effect inverting the normal's green channel: added, kept or removed."""
    step.name = "Levels - normal green inversion"
    levels = [node for node in fill.content_effects()
              if isinstance(node, layerstack.LevelsEffectNode) and _is_generated(node, LEVELS_NAME)]
    if not needed:
        for node in levels:
            layerstack.delete_node(node)
        return
    if levels:
        effect = levels[0]
    else:
        effect = layerstack.insert_levels_effect(
            layerstack.InsertPosition.inside_node(fill, layerstack.NodeStack.Content))
    effect.set_name(_generated_name(LEVELS_NAME))   # also adds the marker to an old one
    effect.affected_channel = textureset.ChannelType.Normal
    effect.set_parameters(_FLIP_GREEN)
