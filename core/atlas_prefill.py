"""Atlas ID pre-fill from the mesh names and UVs (docs/project/workflow.md §12.1),
and grid of the atlas suggested by the mesh UVs (§12.2).

Pure logic: no UI, no Painter API call. From the meshes read in the FBX
or OBJ (processing/fbx_reader.py, obj_reader.py) and the scanned asset names, it proposes an Atlas
ID for the assets whose cell is sure. The artist still validates every ID
before the Build.

Rules (decided 2026-10-09):
    - names are compared by their BASE NAME: lower case, prefixes of the
      naming preset removed (several: "TX_SM_Drill" -> "drill"), cut before
      the first part holding a digit, separators removed
      ("TX_HardHat_01_Blue" -> "hardhat", "SM_WheelBarrel_Wheel_01a" ->
      "wheelbarrelwheel"): variant numbers and letters often differ between
      the textures and the meshes of one pack;
    - a mesh belongs to the asset whose base name starts its own base name,
      the longest one when several do ("canister" does not take
      "tallgascanister"; "canisterbig" wins over "canister" for
      "SM_CanisterBig");
    - the cell of a mesh is read from its UVs (inverse of
      uv-transformation.md §5); they must lie inside that cell (small
      tolerance). If one recognized mesh lies over several cells, the grid
      is not the atlas's: nothing at all is pre-filled. A grid coarser than
      the atlas (2x2 on a 4x4) is not caught this way: its cells then hold
      several assets, which stops them (next rule);
    - an asset is pre-filled only when all its meshes lie in ONE cell, no
      other asset claims that cell, the cell is not already taken and the
      asset has no validated choice (Build memory). Otherwise nothing:
      the artist chooses.
"""

import re
from dataclasses import dataclass

from ..uv.transformations import atlas_id_at

# Share of a cell the UVs of a mesh may pass its edges by (UV islands placed
# by hand touch the edge: 0.1 % on the demo atlas).
UV_TOLERANCE = 0.02

_SEPARATORS = re.compile(r"[_\-\s.]+")


@dataclass(frozen=True)
class Prefill:
    """Atlas ID proposed for one asset, and the meshes it was found from."""
    atlas_id: int
    mesh_names: tuple


def base_name(name, prefixes=()):
    """Base name used to compare an asset and a mesh (see the module
    docstring). prefixes: lower case, as in the naming preset."""
    lowered = name.lower()
    stripped = True
    while stripped:
        stripped = False
        for prefix in sorted(prefixes, key=len, reverse=True):
            if lowered.startswith(prefix) and len(lowered) > len(prefix):
                lowered = lowered[len(prefix):]
                stripped = True
                break
    parts = []
    for part in _SEPARATORS.split(lowered):
        if any(character.isdigit() for character in part):
            break
        parts.append(part)
    return "".join(parts)


def mesh_cell(mesh, grid_size):
    """Atlas ID of the cell holding all the UVs of a mesh, or None (no UVs,
    outside 0-1, or spread over several cells)."""
    if mesh.uv_center is None or mesh.uv_min is None:
        return None
    atlas_id = atlas_id_at(mesh.uv_center[0], mesh.uv_center[1], grid_size)
    if atlas_id is None:
        return None
    column = min(int(mesh.uv_center[0] * grid_size), grid_size - 1)
    row = min(int(mesh.uv_center[1] * grid_size), grid_size - 1)
    tolerance = UV_TOLERANCE / grid_size
    low = (column / grid_size - tolerance, row / grid_size - tolerance)
    high = ((column + 1) / grid_size + tolerance, (row + 1) / grid_size + tolerance)
    inside = all(low[k] <= mesh.uv_min[k] and mesh.uv_max[k] <= high[k] for k in range(2))
    return atlas_id if inside else None


def suggested_grid_size(meshes, grid_sizes):
    """Grid of the atlas, read from the mesh UVs (workflow.md §12.2): the
    finest of grid_sizes in which the UVs of every mesh lie inside one cell
    (a 4x4 atlas also fits a 2x2 grid; a 2x2 atlas does not fit 4x4: its
    meshes spread over several cells). None when no mesh has UVs, or when
    no grid fits every mesh. Meshes without UVs are left out."""
    with_uvs = [mesh for mesh in meshes if mesh.uv_center is not None]
    if not with_uvs:
        return None
    for size in sorted(grid_sizes, reverse=True):
        if all(mesh_cell(mesh, size) is not None for mesh in with_uvs):
            return size
    return None


def prefill_atlas_ids(asset_names, meshes, grid_size, prefixes=(), validated=(), taken_ids=()):
    """Atlas IDs to pre-fill.

    asset_names: every scanned asset; meshes: [MeshInfo]; validated: names of
    the assets whose choices are validated (never changed, but they still
    own their meshes); taken_ids: cells already used.
    Returns ({asset name: Prefill}, {asset name: reason not pre-filled}),
    the reasons only for the assets with a base name, for the Log.
    """
    cores = {name: base_name(name, prefixes) for name in asset_names}
    meshes_of = {name: [] for name in asset_names}
    for mesh in meshes:
        if mesh.uv_center is None:
            continue   # no UVs: nothing to place
        # An OBJ from Maya names a mesh with its groups ("Asset_grp
        # SM_Drill_01a"): each name of the line is compared too.
        mesh_cores = {base_name(part, prefixes) for part in [mesh.name] + mesh.name.split()}
        matching = [name for name, core in cores.items()
                    if core and any(mesh_core.startswith(core) for mesh_core in mesh_cores)]
        if not matching:
            continue
        longest = max(len(cores[name]) for name in matching)
        # Same longest base name (two color variants): the mesh goes to both,
        # the shared cell then stops both.
        for name in matching:
            if len(cores[name]) == longest:
                meshes_of[name].append(mesh)

    validated_keys = {name.lower() for name in validated}
    # One recognized mesh over several cells: the grid is not the atlas's
    # (a 3x3 grid on a 4x4 atlas still holds the corner meshes): no pre-fill.
    for name in asset_names:
        spread = [mesh.name for mesh in meshes_of[name] if mesh_cell(mesh, grid_size) is None]
        if spread:
            reason = (f"the {grid_size}x{grid_size} grid does not match the UVs "
                      f"({spread[0]} lies over several cells)")
            return {}, {other: reason for other in asset_names
                        if cores[other] and other.lower() not in validated_keys}

    taken = set(taken_ids)
    candidates, skipped = {}, {}
    for name in asset_names:
        if not cores[name]:
            continue
        found = meshes_of[name]
        if not found:
            skipped[name] = "no mesh with a matching name"
            continue
        cells = {mesh_cell(mesh, grid_size) for mesh in found}
        mesh_names = tuple(sorted((mesh.name for mesh in found), key=str.lower))
        if len(cells) > 1:
            skipped[name] = f"meshes in several cells ({', '.join(mesh_names)})"
        else:
            candidates[name] = Prefill(cells.pop(), mesh_names)

    claims = {}
    for name, prefill in candidates.items():
        claims.setdefault(prefill.atlas_id, []).append(name)
    prefills = {}
    for name, prefill in candidates.items():
        others = [other for other in claims[prefill.atlas_id] if other != name]
        if name.lower() in validated_keys:
            continue   # choices of the last Build: kept, nothing to report
        if others:
            skipped[name] = f"cell {prefill.atlas_id} also matches {', '.join(others)}"
        elif prefill.atlas_id in taken:
            skipped[name] = f"cell {prefill.atlas_id} already used"
        else:
            prefills[name] = prefill
    for name in list(skipped):
        if name.lower() in validated_keys:
            del skipped[name]
    return prefills, skipped
