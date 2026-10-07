"""Memory of the artist's choices of the last Build.

Pure Python (no Painter API): turns an AtlasAssignment into plain data that
can be stored in the Painter project (painter/project_memory.py), and applies
that data back to the assignment of a new scan (workflow.md §22.1).

Assets are recognized by name (any case), duplicate files by their path
relative to the scanned root. Restored choices stay editable.
"""

from dataclasses import dataclass, field

from .atlas_assignment import NORMAL_FORMATS, AtlasAssignment

MEMORY_VERSION = 1


@dataclass
class RestoreReport:
    """What a restore did, to tell the artist."""
    restored: list = field(default_factory=list)  # asset names with restored choices
    missing: list = field(default_factory=list)   # remembered with an ID, not found by the scan
    saved_grid_size: int = 0
    grid_changed: bool = False                     # IDs not restored (other grid)
    saved_preset: str = ""                         # naming preset of the last Build
    preset_changed: bool = False                   # scanned with another preset


def to_memory(assignment, root_folder, naming_preset):
    """Plain data (str / int / dict only, as Painter metadata requires)."""
    assets = {}
    for asset in assignment.assets:
        entry = {}
        atlas_id = assignment.atlas_id(asset)
        if atlas_id is not None:
            entry["atlas_id"] = atlas_id
        normal_format = assignment.normal_format_override(asset)
        if normal_format is not None:
            entry["normal_format"] = normal_format
        chosen = {}
        for texture_format, textures in asset.textures_by_format().items():
            texture = assignment.chosen_texture(asset, texture_format)
            if len(textures) > 1 and texture is not None:
                chosen[texture_format] = texture.relative_path
        if chosen:
            entry["chosen_files"] = chosen
        if entry:
            entry["name"] = asset.name
            assets[AtlasAssignment.asset_key(asset)] = entry
    return {
        "version": MEMORY_VERSION,
        "root_folder": root_folder,
        "grid_size": assignment.grid_size,
        "naming_preset": naming_preset,
        "project_normal_format": assignment.project_normal_format,
        "default_normal_format": assignment.default_normal_format,
        "assets": assets,
    }


def restore_project_normal_format(memory):
    """Project normal format of the last Build ("opengl" / "directx"), or None."""
    if not isinstance(memory, dict) or memory.get("version") != MEMORY_VERSION:
        return None
    value = memory.get("project_normal_format")
    return value if value in NORMAL_FORMATS else None


def restore(assignment, memory, naming_preset):
    """Apply remembered choices to a freshly scanned assignment.

    naming_preset: preset used by this scan. A different preset than the
    last Build's may recognize the files differently: the report says so.

    Returns a RestoreReport, or None when there is nothing usable to restore.
    Atlas IDs are only restored for the same grid size: ID 3 is not the same
    cell in a 2x2 and in a 3x3 atlas.
    """
    if not isinstance(memory, dict) or memory.get("version") != MEMORY_VERSION:
        return None

    # The project normal format is restored in the panel (CONFIGURATION),
    # before the scan: see restore_project_normal_format().
    if memory.get("default_normal_format") in NORMAL_FORMATS:
        assignment.set_default_normal_format(memory["default_normal_format"])

    report = RestoreReport(saved_grid_size=memory.get("grid_size", 0))
    report.grid_changed = report.saved_grid_size != assignment.grid_size
    # Memories written before the presets existed have no preset: no warning.
    report.saved_preset = memory.get("naming_preset", "")
    # Upper / lower case ignored: preset names are unique regardless of case.
    report.preset_changed = (bool(report.saved_preset)
                             and report.saved_preset.lower() != naming_preset.lower())
    saved_assets = memory.get("assets", {})
    scanned_keys = set()
    for asset in assignment.assets:
        key = AtlasAssignment.asset_key(asset)
        scanned_keys.add(key)
        entry = saved_assets.get(key)
        if not isinstance(entry, dict):
            continue
        atlas_id = entry.get("atlas_id")
        if not report.grid_changed and atlas_id in assignment.valid_ids():
            assignment.set_atlas_id(asset, atlas_id)
        if entry.get("normal_format") in NORMAL_FORMATS:
            assignment.set_normal_format_override(asset, entry["normal_format"])
        chosen = entry.get("chosen_files", {})
        for texture_format, textures in asset.textures_by_format().items():
            match = [t for t in textures if t.relative_path == chosen.get(texture_format)]
            if len(textures) > 1 and match:
                assignment.set_chosen_texture(asset, texture_format, match[0])
        report.restored.append(asset.name)

    report.missing = [entry.get("name", key) for key, entry in saved_assets.items()
                      if key not in scanned_keys and isinstance(entry, dict)
                      and entry.get("atlas_id") is not None]
    return report
