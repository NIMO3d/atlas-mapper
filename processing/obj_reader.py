"""Where is each mesh of the project? Read from the project's OBJ file.

Same purpose and result as processing/fbx_reader.py (MeshInfo per mesh), for
meshes imported from an OBJ: viewport framing (docs/project/workflow.md
§11.1), Atlas ID pre-fill (§12.1), suggested grid (§12.2). The file is only
read, never written.

Checked on 2026-10-09 against Painter (get_scene_bounding_box,
TextureSet.all_mesh_names) on Maya and Blender exports, groups and
parented meshes:
    - Painter keeps the OBJ coordinates as they are (no axis conversion, no
      unit scaling): the box of all the meshes matched Painter's scene box;
    - a mesh is named by its whole "g" or "o" line, as Painter shows it:
      Maya writes the object with its groups on one line, in no fixed order
      ("Asset_grp pCone1", "pCube1 Asset_grp");
    - Maya writes the vertices under "g default" and the faces under the
      object's name: a mesh is made of the vertices and UVs its faces use.
"""

import math

from .fbx_reader import MeshInfo


class ObjReadError(Exception):
    """The OBJ cannot be read. The message is written for the artist."""


def read_meshes(path):
    """[MeshInfo] of every mesh (named group of faces) of an OBJ. Raises
    ObjReadError."""
    positions, uvs = [], []
    faces_of = {}   # mesh name -> ([vertex indices], [UV indices]) used by its faces
    name = "default"
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("v "):
                    positions.append(tuple(float(x) for x in line.split()[1:4]))
                elif line.startswith("vt "):
                    uvs.append(tuple(float(x) for x in line.split()[1:3]))
                elif line.startswith(("o ", "g ")):
                    name = line[2:].strip() or "default"
                elif line.startswith("f "):
                    vertex_ids, uv_ids = faces_of.setdefault(name, ([], []))
                    for corner in line.split()[1:]:
                        parts = corner.split("/")
                        vertex_ids.append(_index(parts[0], len(positions)))
                        if len(parts) > 1 and parts[1]:
                            uv_ids.append(_index(parts[1], len(uvs)))
    except OSError as error:
        raise ObjReadError(f"The mesh file cannot be opened: {path}") from error
    except (ValueError, IndexError) as error:
        raise ObjReadError(f"The mesh file could not be read ({error}).") from error

    meshes = []
    try:
        for mesh_name, (vertex_ids, uv_ids) in faces_of.items():
            points = [positions[i] for i in set(vertex_ids)]
            low = tuple(min(point[k] for point in points) for k in range(3))
            high = tuple(max(point[k] for point in points) for k in range(3))
            uv_min = uv_max = uv_center = None
            if uv_ids:
                used = [uvs[i] for i in set(uv_ids)]
                uv_min = (min(uv[0] for uv in used), min(uv[1] for uv in used))
                uv_max = (max(uv[0] for uv in used), max(uv[1] for uv in used))
                uv_center = ((uv_min[0] + uv_max[0]) / 2, (uv_min[1] + uv_max[1]) / 2)
            if math.inf not in low:
                meshes.append(MeshInfo(mesh_name, low, high, uv_center, uv_min, uv_max))
    except IndexError as error:   # a face uses a vertex or UV that does not exist
        raise ObjReadError(f"The mesh file could not be read ({error}).") from error
    return meshes


def _index(text, count):
    """0-based index of an OBJ index (1-based, or negative = from the end)."""
    value = int(text)
    return value - 1 if value > 0 else count + value
