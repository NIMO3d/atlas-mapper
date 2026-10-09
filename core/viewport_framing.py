"""Frame the viewport on the meshes of an atlas cell (docs/project/workflow.md §11.1).

Pure logic: no UI, no Painter API call. From the meshes read in the FBX
or OBJ (processing/fbx_reader.py, obj_reader.py) it computes which meshes lie in which cell, and
where the camera goes to show them. Navigation only: nothing here changes
the Build.

Rules (decided 2026-10-08):
    - a mesh belongs to the cell holding the center of its UVs: the UV atlas
      is the source of truth, no naming convention is used;
    - in one cell, meshes whose boxes touch or overlap form ONE target,
      framed together (a wheelbarrow and its wheel); distant meshes are
      separate targets, the artist goes from one to the next by clicking
      the cell again (two propane tanks);
    - fixed, level 3/4 view (VIEW_YAW, VIEW_PITCH); the target fills the view
      with MARGIN around it, the artist can dolly back with Alt + Right.

Painter camera convention, found by tests in Painter on 2026-10-08 (not in
the API documentation): with rotation (0, 0, 0) the camera looks along -Z,
X right, Y up; the rotation matrix is Rx(a) * Ry(b) * Rz(c). Rotating the
view (Alt + Left) turns around the mesh point under the brush (mouse cursor)
when it starts; over empty space Painter keeps an earlier pivot. No API sets
this pivot: the artist puts the cursor on the framed mesh (workflow.md §11.1).
"""

import math
from dataclasses import dataclass

from ..uv.transformations import atlas_id_at

VIEW_YAW = 30.0      # degrees, around the vertical axis
VIEW_PITCH = -25.0   # degrees, negative = looking down
MARGIN = 1.3         # space around the target (1 = touching the frame)
# Meshes of one cell closer than this share of the larger one's size are one target.
TOUCH_TOLERANCE = 0.05
# Relative difference accepted between the mesh file's scene box and Painter's.
SCENE_TOLERANCE = 1e-3


@dataclass(frozen=True)
class Target:
    """What one click frames: one mesh, or meshes that touch."""
    mesh_names: tuple
    box_min: tuple
    box_max: tuple


@dataclass(frozen=True)
class CameraView:
    position: list      # (x, y, z)
    rotation: list      # Painter Euler angles, degrees
    orthographic_height: float


def targets_by_cell(meshes, grid_size):
    """{Atlas ID: [Target]} of the MeshInfo list; meshes without UVs or with
    UVs outside 0-1 are left out. Targets are in a stable order."""
    cells = {}
    for mesh in meshes:
        if mesh.uv_center is None:
            continue
        atlas_id = atlas_id_at(mesh.uv_center[0], mesh.uv_center[1], grid_size)
        if atlas_id is not None:
            cells.setdefault(atlas_id, []).append(
                Target((mesh.name,), tuple(mesh.box_min), tuple(mesh.box_max)))
    return {atlas_id: _merge_touching(targets) for atlas_id, targets in cells.items()}


def _merge_touching(targets):
    targets = list(targets)
    merged = True
    while merged:
        merged = False
        for i in range(len(targets)):
            for j in range(i + 1, len(targets)):
                if _touch(targets[i], targets[j]):
                    a, b = targets[i], targets.pop(j)
                    targets[i] = Target(
                        a.mesh_names + b.mesh_names,
                        tuple(min(a.box_min[k], b.box_min[k]) for k in range(3)),
                        tuple(max(a.box_max[k], b.box_max[k]) for k in range(3)))
                    merged = True
                    break
            if merged:
                break
    return sorted(targets, key=lambda target: sorted(name.lower() for name in target.mesh_names))


def _touch(a, b):
    tolerance = TOUCH_TOLERANCE * max(_diagonal(a), _diagonal(b))
    return all(a.box_min[k] - tolerance <= b.box_max[k] and b.box_min[k] - tolerance <= a.box_max[k]
               for k in range(3))


def _diagonal(target):
    return math.sqrt(sum((target.box_max[k] - target.box_min[k]) ** 2 for k in range(3)))


def matches_scene(meshes, scene_center, scene_dimensions):
    """True when the box of all the meshes is Painter's scene box: the file
    read is the one in the viewport, with the same axes."""
    if not meshes:
        return False
    low = [min(mesh.box_min[k] for mesh in meshes) for k in range(3)]
    high = [max(mesh.box_max[k] for mesh in meshes) for k in range(3)]
    tolerance = SCENE_TOLERANCE * max(max(scene_dimensions), 1e-6)
    return all(abs((low[k] + high[k]) / 2 - scene_center[k]) <= tolerance
               and abs((high[k] - low[k]) - scene_dimensions[k]) <= tolerance
               for k in range(3))


def camera_view(target, field_of_view):
    """Camera that shows the whole target, centered, in the fixed 3/4 view.
    field_of_view: the camera's current one, in degrees."""
    center = [(target.box_min[k] + target.box_max[k]) / 2 for k in range(3)]
    radius = max(_diagonal(target) / 2, 1e-3)
    view = _mul(_rotation_y(VIEW_YAW), _rotation_x(VIEW_PITCH))
    forward = [-view[0][2], -view[1][2], -view[2][2]]   # the camera looks along its -Z
    distance = radius * MARGIN / math.sin(math.radians(field_of_view) / 2)
    return CameraView(position=[center[k] - forward[k] * distance for k in range(3)],
                      rotation=_painter_angles(view),
                      orthographic_height=2 * radius * MARGIN)


# 3 x 3 rotations, column vectors.

def _rotation_x(degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]]


def _rotation_y(degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]]


def _mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(3)) for c in range(3)] for r in range(3)]


def _painter_angles(m):
    """(a, b, c) in degrees with Rx(a) * Ry(b) * Rz(c) = m."""
    b = math.asin(max(-1.0, min(1.0, m[0][2])))
    a = math.atan2(-m[1][2], m[2][2])
    c = math.atan2(-m[0][1], m[0][0])
    return [math.degrees(a), math.degrees(b), math.degrees(c)]
