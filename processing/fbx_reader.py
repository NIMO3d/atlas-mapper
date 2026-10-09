"""Where is each mesh of the project? Read from the project's FBX file.

The Painter API gives the path of the imported mesh
(substance_painter.project.last_imported_mesh_path) but not the position of
each mesh in the scene. The FBX file holds it: this module reads, for every
mesh object, its name, its box in the scene and the area of its UVs. Used by
the viewport framing (docs/project/workflow.md §11.1) and the Atlas ID
pre-fill (§12.1). The file is only read, never written.

Pure Python (struct + zlib, Painter's Python has no FBX library): binary FBX
only, ASCII FBX is refused. Checked on 2026-10-08 against Painter's own scene
box (get_scene_bounding_box) on Maya and Blender exports, Y-up and Z-up,
centimetres and metres, groups and parented meshes:
    - the full FBX transform chain is applied (pivots, offsets, pre / post
      rotation, rotation order, geometric transform, parents);
    - Painter converts the file's axes to Y up: scene X = file CoordAxis,
      scene Y = file UpAxis, scene Z = file FrontAxis (only "+" signs checked);
    - Painter ignores UnitScaleFactor: a file in metres stays in metres.
"""

import math
import struct
import zlib
from dataclasses import dataclass

_BINARY_MAGIC = b"Kaydara FBX Binary  "
_ASCII_MAGIC = b"; FBX"


class FbxReadError(Exception):
    """The FBX cannot be read. The message is written for the artist."""


@dataclass(frozen=True)
class MeshInfo:
    """One mesh object of the FBX, in Painter's scene space."""
    name: str          # object name, as in Painter's Geometry mask list
    box_min: tuple     # (x, y, z)
    box_max: tuple     # (x, y, z)
    uv_center: tuple   # (u, v): center of the area of its first UV set, None without UVs
    uv_min: tuple = None   # (u, v): lower corner of that area, None without UVs
    uv_max: tuple = None   # (u, v): upper corner of that area, None without UVs


def read_meshes(path):
    """[MeshInfo] of every mesh object of a binary FBX. Raises FbxReadError."""
    try:
        with open(path, "rb") as handle:
            data = memoryview(handle.read())
    except OSError as error:
        raise FbxReadError(f"The mesh file cannot be opened: {path}") from error
    if bytes(data[:len(_BINARY_MAGIC)]) != _BINARY_MAGIC:
        if bytes(data[:len(_ASCII_MAGIC)]) == _ASCII_MAGIC:
            raise FbxReadError("The mesh is an ASCII FBX: only binary FBX files are supported.")
        raise FbxReadError("The mesh file is not a binary FBX.")
    try:
        root = _read_document(data)
        return _scene_meshes(root)
    except (struct.error, zlib.error, ValueError, IndexError, KeyError, TypeError) as error:
        raise FbxReadError(f"The mesh file could not be read ({error}).") from error


# ---------------------------------------------------------------------------
# Binary FBX structure: a tree of nodes, each with typed properties.
# ---------------------------------------------------------------------------

class _Node:
    def __init__(self, name, props, children):
        self.name = name
        self.props = props
        self.children = children

    def find(self, name):
        return next((child for child in self.children if child.name == name), None)

    def find_all(self, name):
        return [child for child in self.children if child.name == name]


_SCALARS = {"Y": "<h", "C": "<?", "I": "<i", "F": "<f", "D": "<d", "L": "<q"}
_ARRAYS = {"f": "f", "d": "d", "l": "q", "i": "i", "b": "?"}


def _read_document(data):
    version = struct.unpack_from("<I", data, 23)[0]
    wide = version >= 7500   # 64-bit offsets since FBX 7.5
    pos = 27
    roots = []
    while pos < len(data):
        node, pos = _read_node(data, pos, wide)
        if node is None:
            break
        roots.append(node)
    return _Node("", [], roots)


def _read_node(data, pos, wide):
    if wide:
        end, count, _length = struct.unpack_from("<QQQ", data, pos)
        pos += 24
    else:
        end, count, _length = struct.unpack_from("<III", data, pos)
        pos += 12
    name_length = data[pos]
    pos += 1
    if end == 0:   # null record: end of a list of nodes
        return None, pos + name_length
    name = bytes(data[pos:pos + name_length]).decode("ascii", "replace")
    pos += name_length
    props = []
    for _ in range(count):
        value, pos = _read_property(data, pos)
        props.append(value)
    children = []
    while pos < end:
        child, pos = _read_node(data, pos, wide)
        if child is None:
            break
        children.append(child)
    return _Node(name, props, children), end


def _read_property(data, pos):
    code = chr(data[pos])
    pos += 1
    if code in _SCALARS:
        fmt = _SCALARS[code]
        return struct.unpack_from(fmt, data, pos)[0], pos + struct.calcsize(fmt)
    if code in _ARRAYS:
        count, encoding, length = struct.unpack_from("<III", data, pos)
        pos += 12
        raw = bytes(data[pos:pos + length])
        if encoding == 1:
            raw = zlib.decompress(raw)
        return list(struct.unpack(f"<{count}{_ARRAYS[code]}", raw)), pos + length
    if code in ("S", "R"):
        length = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        raw = bytes(data[pos:pos + length])
        return (raw.decode("utf-8", "replace") if code == "S" else raw), pos + length
    raise ValueError(f"unknown property type {code!r}")


def _properties70(node):
    """{property name: [values]} of a node's Properties70 block."""
    block = node.find("Properties70") if node is not None else None
    if block is None:
        return {}
    return {p.props[0]: p.props[4:] for p in block.find_all("P")}


# ---------------------------------------------------------------------------
# Scene: objects, their transforms and their UVs.
# ---------------------------------------------------------------------------

def _scene_meshes(root):
    objects = root.find("Objects")
    connections = root.find("Connections")
    if objects is None or connections is None:
        return []
    models = {n.props[0]: n for n in objects.find_all("Model")}
    geometries = {n.props[0]: n for n in objects.find_all("Geometry")
                  if n.find("Vertices") is not None}

    parent_of, geometry_of = {}, {}
    for link in connections.find_all("C"):
        if link.props[0] != "OO":
            continue
        child, parent = link.props[1], link.props[2]
        if child in models and parent in models:
            parent_of[child] = parent
        elif child in geometries and parent in models:
            geometry_of[parent] = child

    def world_matrix(model_id):
        matrix = _local_matrix(_properties70(models[model_id]))
        parent = parent_of.get(model_id)
        return _mul(world_matrix(parent), matrix) if parent is not None else matrix

    axes = _painter_axes(_properties70(root.find("GlobalSettings")))
    meshes = []
    for model_id, geometry_id in geometry_of.items():
        model = models[model_id]
        geometry = geometries[geometry_id]
        matrix = _mul(world_matrix(model_id), _geometric_matrix(_properties70(model)))
        vertices = geometry.find("Vertices").props[0]
        low, high = [math.inf] * 3, [-math.inf] * 3
        for i in range(0, len(vertices) - 2, 3):
            point = _apply(matrix, vertices[i:i + 3])
            point = [point[source] * sign for source, sign in axes]
            for k in range(3):
                low[k] = min(low[k], point[k])
                high[k] = max(high[k], point[k])
        if low[0] == math.inf:
            continue   # mesh without vertices
        uv_min, uv_max = _uv_box(geometry)
        uv_center = (None if uv_min is None
                     else ((uv_min[0] + uv_max[0]) / 2, (uv_min[1] + uv_max[1]) / 2))
        meshes.append(MeshInfo(model.props[1].split("\x00\x01")[0], tuple(low), tuple(high),
                               uv_center, uv_min, uv_max))
    return meshes


def _painter_axes(settings):
    """[(file axis, sign)] giving Painter's X, Y, Z (see the module docstring)."""
    def value(name, default):
        return int(settings.get(name, [default])[0])
    return [(value("CoordAxis", 0), value("CoordAxisSign", 1)),
            (value("UpAxis", 1), value("UpAxisSign", 1)),
            (value("FrontAxis", 2), value("FrontAxisSign", 1))]


def _uv_box(geometry):
    """((u, v) min, (u, v) max) of the area covered by the first UV set, or
    (None, None)."""
    layers = geometry.find_all("LayerElementUV")
    if not layers:
        return None, None
    first = min(layers, key=lambda layer: layer.props[0] if layer.props else 0)
    uv_node = first.find("UV")
    uvs = uv_node.props[0] if uv_node is not None else []
    if len(uvs) < 2:
        return None, None
    us, vs = uvs[0::2], uvs[1::2]
    return (min(us), min(vs)), (max(us), max(vs))


# ---------------------------------------------------------------------------
# FBX transform chain (4 x 4 matrices, column vectors: p' = M * p).
# ---------------------------------------------------------------------------

def _identity():
    return [[1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]


def _mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def _apply(m, p):
    return [m[r][0] * p[0] + m[r][1] * p[1] + m[r][2] * p[2] + m[r][3] for r in range(3)]


def _translation(v):
    m = _identity()
    m[0][3], m[1][3], m[2][3] = v
    return m


def _scaling(v):
    m = _identity()
    m[0][0], m[1][1], m[2][2] = v
    return m


def _axis_rotation(axis, degrees):
    angle = math.radians(degrees)
    c, s = math.cos(angle), math.sin(angle)
    i, j = {"x": (1, 2), "y": (2, 0), "z": (0, 1)}[axis]
    m = _identity()
    m[i][i], m[i][j], m[j][i], m[j][j] = c, -s, s, c
    return m


_ROTATION_ORDERS = ("xyz", "xzy", "yzx", "yxz", "zxy", "zyx")


def _euler(v, order=0):
    """FBX Euler angles: order "xyz" rotates around X first, then Y, then Z."""
    m = _identity()
    angles = dict(zip("xyz", v))
    for axis in _ROTATION_ORDERS[order]:
        m = _mul(_axis_rotation(axis, angles[axis]), m)
    return m


def _inverse(m):
    """Inverse of an affine 4 x 4 matrix."""
    a = [row[:3] for row in m[:3]]
    det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
           - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
           + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    inverse3 = [[0.0] * 3 for _ in range(3)]
    for r in range(3):
        for c in range(3):
            minor = [[a[i][j] for j in range(3) if j != r] for i in range(3) if i != c]
            cofactor = minor[0][0] * minor[1][1] - minor[0][1] * minor[1][0]
            inverse3[r][c] = (-1) ** (r + c) * cofactor / det
    out = _identity()
    for r in range(3):
        out[r][:3] = inverse3[r]
        out[r][3] = -sum(inverse3[r][k] * m[k][3] for k in range(3))
    return out


def _vector(props, name, default):
    values = props.get(name)
    return list(values[:3]) if values else default


def _local_matrix(props):
    """T * Roff * Rp * Rpre * R * Rpost^-1 * Rp^-1 * Soff * Sp * S * Sp^-1."""
    zero, one = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
    rotation_pivot = _translation(_vector(props, "RotationPivot", zero))
    scaling_pivot = _translation(_vector(props, "ScalingPivot", zero))
    parts = (
        _translation(_vector(props, "Lcl Translation", zero)),
        _translation(_vector(props, "RotationOffset", zero)),
        rotation_pivot,
        _euler(_vector(props, "PreRotation", zero)),
        _euler(_vector(props, "Lcl Rotation", zero), int(props.get("RotationOrder", [0])[0])),
        _inverse(_euler(_vector(props, "PostRotation", zero))),
        _inverse(rotation_pivot),
        _translation(_vector(props, "ScalingOffset", zero)),
        scaling_pivot,
        _scaling(_vector(props, "Lcl Scaling", one)),
        _inverse(scaling_pivot),
    )
    m = _identity()
    for part in parts:
        m = _mul(m, part)
    return m


def _geometric_matrix(props):
    """Transform of the geometry only (not inherited by children)."""
    zero, one = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
    m = _mul(_translation(_vector(props, "GeometricTranslation", zero)),
             _euler(_vector(props, "GeometricRotation", zero)))
    return _mul(m, _scaling(_vector(props, "GeometricScaling", one)))
