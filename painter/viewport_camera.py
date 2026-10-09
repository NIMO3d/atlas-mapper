"""Viewport framing: the Painter side (docs/project/workflow.md §11.1).

Finds the project's mesh file, reads it (processing/fbx_reader.py, or
processing/obj_reader.py for an OBJ), checks it
is the scene shown in the viewport, and moves Painter's camera. The rules
(cell of a mesh, targets, camera placement) are in core/viewport_framing.py.
Only the camera moves: the project, its mesh and its layers are untouched.
The meshes read are also given to the Atlas ID pre-fill (workflow.md §12.1).

Painter API used (api_source/substance_painter/):
    project.last_imported_mesh_path()   path of the mesh file of the project
    project.get_scene_bounding_box()    box of the whole scene (center, dimensions)
    display.Camera.get_default_camera() the viewport camera: field_of_view
                                        read; position, rotation and
                                        orthographic_height set
"""

import os

import substance_painter.display
import substance_painter.exception
import substance_painter.project

from ..core.viewport_framing import camera_view, matches_scene, targets_by_cell
from ..processing import fbx_reader, obj_reader

# Errors of the Painter API calls above (no project, Painter not ready, no camera).
_API_ERRORS = (substance_painter.exception.ProjectError,
               substance_painter.exception.ServiceNotFoundError, RuntimeError)


class FramingError(Exception):
    """The viewport cannot be framed. The message is written for the artist."""


class ViewportFramer:
    """Meshes of the open project, read once and read again when the mesh
    file changes (reimport, other file), and the camera moves."""

    def __init__(self):
        self._signature = None   # (path, modification time, size) of the file read
        self._meshes = None      # [MeshInfo] of that file
        self._targets = {}       # (grid size) -> {Atlas ID: [Target]}

    def forget(self):
        """The project closed: its meshes are no longer valid."""
        self.__init__()

    def targets(self, grid_size):
        """{Atlas ID: [Target]} of the open project. Reads the mesh file the
        first time and after it changed. Raises FramingError."""
        self._load()
        if grid_size not in self._targets:
            self._targets[grid_size] = targets_by_cell(self._meshes, grid_size)
        return self._targets[grid_size]

    def meshes(self):
        """[MeshInfo] of the open project, also used by the Atlas ID pre-fill
        (workflow.md §12.1). Same reading and checks as for framing. Raises
        FramingError."""
        self._load()
        return list(self._meshes)

    def frame(self, target):
        """Move the viewport camera onto a Target. Raises FramingError."""
        try:
            camera = substance_painter.display.Camera.get_default_camera()
            view = camera_view(target, camera.field_of_view)
            camera.position = view.position
            camera.rotation = view.rotation
            camera.orthographic_height = view.orthographic_height
        except _API_ERRORS as error:
            raise FramingError(f"The viewport camera could not be moved ({error}).") from error

    def _load(self):
        try:
            path = substance_painter.project.last_imported_mesh_path()
        except _API_ERRORS as error:
            raise FramingError(f"The mesh of the project could not be found ({error}).") from error
        if not path:
            raise FramingError("The project gives no mesh file.")
        try:
            stat = os.stat(path)
        except OSError as error:
            self._signature = None
            raise FramingError(
                f"The mesh file of the project was not found: {path}\n"
                "It was moved, renamed or deleted after the import. Put it back, or reimport "
                "the mesh (Edit > Project configuration).") from error
        signature = (os.path.normcase(path), stat.st_mtime, stat.st_size)
        if signature == self._signature:
            return
        reader = obj_reader if path.lower().endswith(".obj") else fbx_reader
        try:
            meshes = reader.read_meshes(path)
            box = substance_painter.project.get_scene_bounding_box()
        except (fbx_reader.FbxReadError, obj_reader.ObjReadError) as error:
            raise FramingError(f"{error}\nAtlas Mapper reads binary FBX and OBJ meshes only.") \
                from error
        except _API_ERRORS as error:
            raise FramingError(f"The scene of the project could not be read ({error}).") from error
        if not matches_scene(meshes, box.center, box.dimensions):
            raise FramingError(
                f"The mesh file no longer matches the scene in the viewport: {path}\n"
                "It was probably modified after the import. Reimport the mesh "
                "(Edit > Project configuration) to frame the assets again.")
        self._signature = signature
        self._meshes = meshes
        self._targets = {}
