"""UVtransform.sbsar: what it exposes, and its import into the project.

The identifiers below were read from the .sbsar itself with
`sbsrender info` (2026-10-03; opacity: 2026-10-04). If the .sbsar changes in
Designer, update them.

The artist never imports the .sbsar: it is imported into the current project
the first time it is needed, then reused (docs/project/workflow.md §19).
"""

import os

import substance_painter.resource
from substance_painter.textureset import ChannelType

# In the resources folder of the plugin itself: copying the atlas_mapper
# folder is enough to install the plugin (since 2026-10-07).
SBSAR_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "resources", "UVtransform.sbsar"))

# Name given to the resource in the project; also used to find it again.
RESOURCE_NAME = "UVtransform"

# Parameters (uv-transformation.md §7).
PARAM_UV_TILING = "uv_tiling"
PARAM_U_OFFSET = "u_offset"

# Output used by the folder mask (uv-transformation.md §9-10).
OUTPUT_QUADRANT_MASK = "quadrantmask"


class MapRoute:
    """One texture format: .sbsar image input -> .sbsar output -> Painter channel.

    channel_param: .sbsar parameter choosing which channel of the input is
    used (None: the input takes the whole image, no packed map possible).
    invert_param: .sbsar parameter inverting the branch (None: no inversion
    possible); inverted: the value it gets for this map.
    """

    def __init__(self, image_input, output, channel, channel_param=None, invert_param=None,
                 inverted=False):
        self.image_input = image_input
        self.output = output
        self.channel = channel
        self.channel_param = channel_param
        self.invert_param = invert_param
        self.inverted = inverted


# Glossiness (= Smoothness) shares the Roughness branch, inverted
# (workflow.md §20.5). The Roughness sets it back to False, so a second
# Build of an asset that switched from Glossiness to Roughness is right.
PARAM_ROUGHNESS_INVERT = "roughness_invert"


# Keys = texture formats of the naming preset.
# Only the maps the .sbsar has an input for. Roughness, Metallic and AO can
# also come from a packed map; Opacity from the alpha of the Base Color.
# Without an image plugged in, an output is black (opacity 0 = transparent):
# the Fill only activates the channels that received a map.
MAP_ROUTES = {
    "base color":        MapRoute("input_Base_Color", "basecolor", ChannelType.BaseColor),
    "normal":            MapRoute("input_normalmap", "normal", ChannelType.Normal),
    "roughness":         MapRoute("input_Roughness", "roughness", ChannelType.Roughness,
                                  "roughness_channel", PARAM_ROUGHNESS_INVERT),
    "glossiness":        MapRoute("input_Roughness", "roughness", ChannelType.Roughness,
                                  "roughness_channel", PARAM_ROUGHNESS_INVERT, inverted=True),
    "metallic":          MapRoute("input_Metallic", "metallic", ChannelType.Metallic,
                                  "metallic_channel"),
    "ambient occlusion": MapRoute("input_Ambient_Occlusion", "ambientocclusion", ChannelType.AO,
                                  "ao_channel"),
    "opacity":           MapRoute("input_Opacity", "opacity", ChannelType.Opacity,
                                  "opacity_channel"),
    # Height and Emissive: 2026-10-06 (workflow.md §20.4). emissive_channel 0
    # keeps the file's color; 1-4 give the channel as gray.
    "height":            MapRoute("input_Height", "height", ChannelType.Height,
                                  "height_channel"),
    "emissive":          MapRoute("input_Emissive", "emissive", ChannelType.Emissive,
                                  "emissive_channel"),
}

# Values of the *_channel parameters (drop-down list of the .sbsar).
# None = separate grayscale file (Grayscale Conversion branch).
# Checked with sbsrender: 1 -> R, 2 -> G, 3 -> B (2026-10-03);
# 4 -> A (opacity_channel 2026-10-04, workflow.md §20.3; roughness_channel,
# metallic_channel and ao_channel 2026-10-06; height_channel and
# emissive_channel 2026-10-06, 0 = color for emissive).
CHANNEL_VALUES = {None: 0, "R": 1, "G": 2, "B": 3, "A": 4}
# Maps whose .sbsar branch reads the A channel (value 4). A map declared in A
# that is not listed here is ignored at Build with a note.
ALPHA_READY_MAPS = ("opacity", "roughness", "glossiness", "metallic", "ambient occlusion", "height",
                    "emissive")


class SbsarError(Exception):
    """The .sbsar cannot be used. The message is written for the artist."""


def describe(resource_id):
    """URL, type and usages of the resource, for the log (diagnostic)."""
    text = resource_id.url()
    try:
        for resource in substance_painter.resource.Resource.retrieve(resource_id):
            text += f" type={resource.type()} usages={resource.usages()}"
    except Exception as error:  # diagnostic only: never block the build
        text += f" (retrieve impossible : {error!r})"
    return text


def get_or_import():
    """ResourceID of the UVtransform GRAPH in the current project.

    Importing a .sbsar creates a "Substance package" resource (tested in
    Painter 2026-10-03: type SUBSTANCE_PACKAGE, no usage); it cannot be put
    in a Fill. The graph it contains (Resource.children()) is what the Fills use.
    """
    package = _project_package() or _import_package()
    graphs = [child for child in package.children()
              if child.type() == substance_painter.resource.Type.SUBSTANCE]
    if not graphs:
        raise SbsarError("UVtransform.sbsar was imported but Painter finds no usable graph "
                         "in it. Check the .sbsar in Substance Designer.")
    return graphs[0].identifier()


def _project_package():
    """UVtransform already imported in this project, or None.

    Resource.retrieve also finds a package imported but not used yet
    (list_project_resources only lists resources used by the project).
    """
    try:
        found = substance_painter.resource.Resource.retrieve(
            substance_painter.resource.ResourceID.from_project(RESOURCE_NAME))
    except ValueError:
        return None
    # Most up to date first (documented).
    return found[0] if found else None


def _import_package():
    if not os.path.isfile(SBSAR_PATH):
        raise SbsarError(f"The material UVtransform.sbsar cannot be found:\n{SBSAR_PATH}\n"
                         f"It must be in the \"resources\" folder of the atlas_mapper plugin "
                         f"folder. Reinstall the plugin (copy the whole atlas_mapper folder).")
    try:
        return substance_painter.resource.import_project_resource(
            SBSAR_PATH, substance_painter.resource.Usage.BASE_MATERIAL, name=RESOURCE_NAME)
    except (ValueError, RuntimeError) as error:
        raise SbsarError("Painter could not import UVtransform.sbsar into the project.") from error
