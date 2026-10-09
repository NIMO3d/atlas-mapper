"""Atlas ID -> UVtransform.sbsar parameters, and UV point -> Atlas ID.

Pure math: no UI, no Painter API. The formulas are defined in
docs/project/uv-transformation.md (§5 grid coordinates and its inverse,
§7 .sbsar parameters):
do not change them here without updating that document.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CellTransform:
    """Values applied to the texture Fill Layer AND to the quadrant mask."""
    uv_tiling: float
    u_offset: tuple   # (X, Y): center of the cell from the atlas center, X right, Y up


def grid_coordinates(atlas_id, grid_size):
    """(x_grid, y_grid) of a cell, uv-transformation.md §5.

    y_grid counts from the bottom row: ID 1 (top left) of a 2 x 2 is (0, 1).
    """
    if not 1 <= atlas_id <= grid_size * grid_size:
        raise ValueError(f"Atlas ID {atlas_id} is outside 1-{grid_size ** 2}")
    x_grid = (atlas_id - 1) % grid_size
    y_grid = grid_size - 1 - ((atlas_id - 1) // grid_size)
    return x_grid, y_grid


def atlas_id_at(u, v, grid_size):
    """Atlas ID of the cell holding the UV point (u, v), or None outside 0-1.

    Inverse of grid_coordinates (uv-transformation.md §5): x_grid = floor(u * N),
    y_grid = floor(v * N) counted from the bottom, V up. A point on the
    upper edge (u or v = 1) belongs to the last cell.
    """
    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        return None
    x_grid = min(int(u * grid_size), grid_size - 1)
    y_grid = min(int(v * grid_size), grid_size - 1)
    return (grid_size - 1 - y_grid) * grid_size + x_grid + 1


def cell_transform(atlas_id, grid_size):
    """.sbsar parameters of a cell, uv-transformation.md §7."""
    x_grid, y_grid = grid_coordinates(atlas_id, grid_size)
    return CellTransform(
        uv_tiling=float(grid_size),
        u_offset=((x_grid + 0.5) / grid_size - 0.5,
                  (y_grid + 0.5) / grid_size - 0.5),
    )
