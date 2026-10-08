# Atlas Mapper

Atlas Mapper is a free plugin for Adobe Substance 3D Painter. It builds a
non-destructive Layer Stack for a texture atlas: the UV layout of your mesh
is never modified.

It scans a folder of existing textures, matches them to your assets, lets
you validate each assignment on the atlas grid, then creates one organized,
editable folder per asset: every texture is placed in its atlas cell and
limited to it by a mask. Made for real-time production (XR, VR, AR, mobile,
PC), where many assets, often from external sources, are merged into one
atlas.

## Features

* Square atlas grids: 2x2, 3x3 and 4x4.
* Base Color, Normal (OpenGL / DirectX), Roughness, Metallic, Ambient
  Occlusion, Opacity, Height, Emissive.
* Packed textures (ORM, RMA...) routed channel by channel.
* Glossiness / Smoothness maps converted to Roughness.
* Naming presets, editable in the panel, for each studio's conventions.
* Build memory: build again after a change in the atlas without starting
  over.

## Download

Download `atlas_mapper.zip` from the latest release:
https://github.com/NIMO3d/atlas-mapper/releases

The zip contains the `atlas_mapper` folder, ready to install.

## Requirements

* Adobe Substance 3D Painter with Python plugins (tested with version 12.1.5).
* Windows (the plugin has only been tested on Windows).

## Install

1. Close Substance 3D Painter.
2. Open this folder (create the `plugins` folder if it does not exist):

   ```
   Documents\Adobe\Adobe Substance 3D Painter\python\plugins
   ```

3. Copy the whole `atlas_mapper` folder into it. Copy the folder itself, not
   only its content. The result must be:

   ```
   Documents\Adobe\Adobe Substance 3D Painter\python\plugins\atlas_mapper\__init__.py
   ```

   Do not rename the `atlas_mapper` folder: Painter loads the plugin by this
   name.

4. Start Substance 3D Painter.
5. In the **Python** menu, check **atlas_mapper**. Painter remembers it for
   the next sessions.

The **Atlas Mapper** panel opens docked in Painter. If you close it, its icon
in Painter's side toolbar opens it again.

## Check the installation

* The panel is greyed while no project is open: open a project.
* The version is shown under the "Build Atlas" button ("About · v1.0.1").
  Click it for the plugin information.

## Update to a new version

1. Close Substance 3D Painter.
2. Delete the old `atlas_mapper` folder, then copy the new one in its place.

   If you created your own naming presets, save them first: they are the
   `.json` files of `atlas_mapper\naming_presets` (keep `Default.json` from
   the new version). Copy them back into the new folder afterwards.

3. Start Substance 3D Painter.

Projects already built keep working: their Layer Stack and Atlas IDs are
saved in the project itself.

## Uninstall

1. Close Substance 3D Painter.
2. Delete the `atlas_mapper` folder from
   `Documents\Adobe\Adobe Substance 3D Painter\python\plugins`.

Projects already built keep their Layer Stack: it is made of standard
Painter layers.

## What the folder contains

| Item | Role |
| --- | --- |
| `__init__.py` and the `core`, `painter`, `processing`, `ui`, `uv` folders | The plugin code |
| `resources\UVtransform.sbsar` | The material that places each texture in its atlas cell. Imported automatically into the project at the first Build: never import it yourself |
| `resources\*.png` | Plugin icons |
| `naming_presets\*.json` | Naming conventions used by the scan (`Default` is always available) |
| `LICENSE` | The MIT License of the plugin |

Every file is needed: always copy the whole folder.

## Troubleshooting

**atlas_mapper is not in the Python menu**
The folder is not at the right place, or it is one level too deep
(`plugins\atlas_mapper\atlas_mapper\...`). Check the path of step 3, then
restart Painter.

**"The material UVtransform.sbsar cannot be found"**
The `resources` folder is incomplete. Copy the whole `atlas_mapper` folder
again.

**The plugin does not start, or behaves strangely**
Open Painter's **Log** window: Atlas Mapper writes its messages there, under
"Atlas Mapper". Send this log with your report.

## Advanced: install from another folder

Painter also loads plugins from the folders listed in the
`SUBSTANCE_PAINTER_PLUGINS_PATH` environment variable (each folder must
contain a `plugins` subfolder). Useful for a studio that shares one copy of
the plugin on a network drive. Do not install the plugin both ways at the
same time: Painter would find two `atlas_mapper` plugins.

## Author

Created by Nicolas Morlet, developed with Claude (Anthropic).

* ArtStation: https://www.artstation.com/nicolasmorlet
* LinkedIn: https://www.linkedin.com/in/nicolas-morlet-9b8ab763/

© 2026 Nicolas Morlet. Free plugin, released under the MIT License (see
`LICENSE`).
