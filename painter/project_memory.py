"""Storage of the Build memory inside the Painter project.

Uses substance_painter.project.Metadata (api_source/substance_painter/project.py):
the data is saved in the .spp file with the project, so it is only kept once
the artist saves the project.

One memory per Texture Set (since 2026-10-07): a project can hold several
atlases, one per Texture Set, each with its own grid and Atlas IDs. Texture
Set names are unique in a project (api_source/substance_painter/textureset.py).

Also the two questions the plugin asks about the open project's Texture Sets:
which one is active, and whether the project uses UV Tiles (UDIM).
"""

import substance_painter.exception
import substance_painter.project
import substance_painter.textureset

_CONTEXT = "AtlasMapper"  # unique metadata context of the plugin
_KEY = "builds"           # {Texture Set name: memory of its last Build}
# Before 2026-10-07: one memory for the whole project. Still read while no
# Texture Set has a memory of its own; never written again.
_LEGACY_KEY = "last_build"


def active_texture_set():
    """Name of the active Texture Set (where the Build goes), or None."""
    if not substance_painter.project.is_open():
        return None
    try:
        return substance_painter.textureset.get_active_stack().material().name
    except (RuntimeError,  # no active stack
            substance_painter.exception.ProjectError,
            substance_painter.exception.ServiceNotFoundError):
        return None


def project_uses_uv_tiles():
    """True when a Texture Set of the open project uses UV Tiles (UDIM):
    Atlas Mapper refuses such a project (workflow.md §5.1). The UDIM choice
    is made when the project is created, so checking at opening is enough.

    TextureSet.has_uv_tiles() (api_source/substance_painter/textureset.py).
    Raises MEMORY_ERRORS when Painter is not ready.
    """
    if not substance_painter.project.is_open():
        return False
    return any(texture_set.has_uv_tiles()
               for texture_set in substance_painter.textureset.all_texture_sets())


def load_memory(texture_set):
    """Remembered data of the last Build in this Texture Set, or None."""
    if not substance_painter.project.is_open() or not texture_set:
        return None
    builds = load_builds()
    if texture_set in builds:
        return builds[texture_set]
    if builds:  # other Texture Sets have their memory: this one has none yet
        return None
    metadata = substance_painter.project.Metadata(_CONTEXT)
    # The doc does not say what get() does for a missing key: list() first.
    return metadata.get(_LEGACY_KEY) if _LEGACY_KEY in metadata.list() else None


def save_memory(texture_set, memory):
    """Store the Build memory of one Texture Set; the others are kept.

    Raises substance_painter.exception.ProjectError when no project is open.
    """
    builds = load_builds()
    builds[texture_set] = memory
    save_builds(builds)


def load_builds():
    """{Texture Set name: memory} of the open project ({} when none)."""
    metadata = substance_painter.project.Metadata(_CONTEXT)
    builds = metadata.get(_KEY) if _KEY in metadata.list() else None
    return dict(builds) if isinstance(builds, dict) else {}


def save_builds(builds):
    substance_painter.project.Metadata(_CONTEXT).set(_KEY, builds)


# Errors the callers may catch: no project, unsupported data, services not ready.
MEMORY_ERRORS = (substance_painter.exception.ProjectError,
                 substance_painter.exception.ServiceNotFoundError,
                 RuntimeError)
