"""Atlas ID assignment of the scanned assets (validation phase).

Pure logic: no UI, no Painter API call. Keeps which asset the artist placed
in which atlas cell and computes the status shown in the panel.

Rules (docs/project/workflow.md §12-14, docs/project/uv-transformation.md §3-4):
    - valid Atlas IDs go from 1 to N x N;
    - assets start WITHOUT an ID, except the IDs restored from the last
      Build and the sure IDs pre-filled from the mesh names and UVs
      (core/atlas_prefill.py, workflow.md §12.1); the artist validates,
      adds and removes IDs;
    - the Atlas ID is separate from the asset name (assigning never renames);
    - two assets cannot share the same Atlas ID;
    - a map found in several files (duplicate) needs the artist to choose
      the file to use; nothing is pre-selected;
    - assets without an Atlas ID are ignored at creation;
    - creation is possible when at least one asset has an ID and no asset
      with an ID needs attention;
    - normal maps: the artist declares the format of the Painter project and
      of the source files (one default for all assets, overridable per asset).
      When they differ, the green channel is flipped at creation
      (docs/project/workflow.md §20.1). It never blocks the build;
    - the format of each normal map file is also detected at scan
      (processing/normal_detection.py, workflow.md §20.1.1): a sure result
      pre-fills the asset's format when the artist has not validated one
      yet; an uncertain result, or a format that differs from the detected
      one, is a notice. Notices never block the build;
    - packed maps (ORM, RMA...): each map is resolved on its own. A map's own
      file wins; otherwise it comes from the channel of a packed file that
      declares it (docs/project/workflow.md §20.2);
    - glossiness (= smoothness) is an inverted roughness: when an asset has
      both, in any form, roughness wins (docs/project/workflow.md §20.5).
"""

from dataclasses import dataclass

# Asset / cell status.
STATUS_READY = "ready"        # has an ID, nothing to fix
STATUS_WARNING = "warning"    # needs the artist's attention
STATUS_NO_ID = "no_id"        # no Atlas ID yet (asset only)
STATUS_EMPTY = "empty"        # no asset in the cell (cell only)

# Texture format of the naming preset that holds normal maps.
NORMAL_TEXTURE_FORMAT = "normal"
# Opacity can come from the alpha channel of the Base Color (workflow.md §20.3).
BASE_COLOR_TEXTURE_FORMAT = "base color"
OPACITY_TEXTURE_FORMAT = "opacity"
ALPHA_CHANNEL = "A"
# Glossiness is read into the Roughness branch, inverted (workflow.md §20.5).
ROUGHNESS_TEXTURE_FORMAT = "roughness"
GLOSSINESS_TEXTURE_FORMAT = "glossiness"

# Normal map formats (of the Painter project or of a source file).
# The Painter API cannot read the project's format: the artist declares it.
NORMAL_OPENGL = "opengl"
NORMAL_DIRECTX = "directx"
NORMAL_FORMATS = (NORMAL_OPENGL, NORMAL_DIRECTX)
# Detection result when the image does not say clearly (workflow.md §20.1.1).
NORMAL_UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class MapSource:
    """Where one map comes from at creation."""
    texture: object              # TextureFile (processing/scanner.py)
    channel: str = None          # None = whole file; "R" / "G" / "B" = channel of a packed file
    packed_format: str = None    # e.g. "orm" when channel is set


@dataclass(frozen=True)
class AssetIssue:
    """A problem of one asset the artist has to fix."""
    short: str    # a few words for the asset line ("Duplicate", "ID 1 already used")
    detail: str   # full sentence, shown on hover


def cell_row_column(atlas_id, grid_size):
    """(row, column) of a cell in display order, both starting at 0.

    Atlas IDs follow the reading order: left to right, then top to bottom,
    ID 1 at the top left (uv-transformation.md §4). Display only: the UV
    transformation formulas are not computed here.
    """
    index = atlas_id - 1
    return index // grid_size, index % grid_size


class AtlasAssignment:
    """Atlas IDs of the assets of one scan, for one grid size."""

    def __init__(self, grid_size, assets, packed_channels=None):
        self.grid_size = grid_size
        self.assets = list(assets)
        # {packed format: {"R": map name, ...}} from the naming preset.
        self.packed_channels = packed_channels or {}
        self._ids = {}     # asset key -> Atlas ID
        # asset key -> Prefill (core/atlas_prefill.py) of an ID pre-filled at
        # scan and not touched by the artist since.
        self._prefilled = {}
        self._chosen = {}  # (asset key, texture format) -> TextureFile chosen among duplicates
        self.project_normal_format = NORMAL_OPENGL   # Painter's default for new projects
        self.default_normal_format = NORMAL_OPENGL   # source files, all assets
        self._normal_formats = {}  # asset key -> normal format chosen for this asset only
        # File path -> detected format (NORMAL_OPENGL / NORMAL_DIRECTX /
        # NORMAL_UNCERTAIN); files that could not be analysed are missing.
        self.normal_detections = {}

    @staticmethod
    def _key(asset):
        # Asset names are unique case-insensitively (see processing/scanner.py).
        return asset.name.lower()

    @staticmethod
    def asset_key(asset):
        """Identity of an asset from one scan to the next (its name, any case)."""
        return AtlasAssignment._key(asset)

    def format_label(self, texture_format):
        """'Base Color', 'ORM': display name of a texture or packed format."""
        if texture_format in self.packed_channels:
            return texture_format.upper()
        return texture_format.title()

    def valid_ids(self):
        return range(1, self.grid_size * self.grid_size + 1)

    def atlas_id(self, asset):
        """Atlas ID of an asset, or None."""
        return self._ids.get(self._key(asset))

    def set_atlas_id(self, asset, atlas_id):
        """Assign an Atlas ID (None removes it). The ID is no longer marked
        as pre-filled."""
        self._prefilled.pop(self._key(asset), None)
        if atlas_id is None:
            self._ids.pop(self._key(asset), None)
            return
        if atlas_id not in self.valid_ids():
            raise ValueError(f"Atlas ID {atlas_id} is outside 1-{self.grid_size ** 2}")
        self._ids[self._key(asset)] = atlas_id

    def apply_prefill(self, prefills):
        """Pre-fill Atlas IDs: {asset name: Prefill} (core/atlas_prefill.py).
        Returns the names of the assets changed."""
        changed = []
        for asset in self.assets:
            prefill = prefills.get(asset.name)
            if prefill is not None and prefill.atlas_id in self.valid_ids():
                self.set_atlas_id(asset, prefill.atlas_id)
                self._prefilled[self._key(asset)] = prefill
                changed.append(asset.name)
        return changed

    def prefill(self, asset):
        """Prefill of the asset's ID while the artist has not changed it, or None."""
        return self._prefilled.get(self._key(asset))

    def assets_at(self, atlas_id):
        """Assets placed in a cell (more than one is a conflict)."""
        return [asset for asset in self.assets if self.atlas_id(asset) == atlas_id]

    def chosen_texture(self, asset, texture_format):
        """File chosen by the artist for a duplicated map, or None."""
        return self._chosen.get((self._key(asset), texture_format))

    def set_chosen_texture(self, asset, texture_format, texture):
        """Choose the file to use for a duplicated map (None cancels the choice)."""
        key = (self._key(asset), texture_format)
        if texture is None:
            self._chosen.pop(key, None)
        else:
            self._chosen[key] = texture

    def normal_format_override(self, asset):
        """Normal format chosen for this asset only, or None (= default)."""
        return self._normal_formats.get(self._key(asset))

    def set_normal_format_override(self, asset, normal_format):
        """Choose the normal format of one asset (None = follow the default)."""
        if normal_format is None:
            self._normal_formats.pop(self._key(asset), None)
            return
        if normal_format not in NORMAL_FORMATS:
            raise ValueError(f"Unknown normal format {normal_format!r}")
        self._normal_formats[self._key(asset)] = normal_format

    def detected_normal_format(self, asset):
        """Detected format of the normal map used by this asset, or None (no
        normal map, file not chosen among duplicates, or not analysed)."""
        texture = self.resolved_textures(asset).get(NORMAL_TEXTURE_FORMAT)
        return None if texture is None else self.normal_detections.get(texture.path)

    def apply_normal_detections(self, validated_names=()):
        """Pre-fill the normal format of the assets from the detection (sure
        results only). An asset in validated_names (its choices were restored
        from the last Build) or with its own format is never changed.
        Returns the names of the assets changed."""
        validated = {name.lower() for name in validated_names}
        changed = []
        for asset in self.assets:
            if self._key(asset) in validated or self.normal_format_override(asset):
                continue
            detected = self.detected_normal_format(asset)
            if detected in NORMAL_FORMATS and detected != self.default_normal_format:
                self.set_normal_format_override(asset, detected)
                changed.append(asset.name)
        return changed

    def asset_notices(self, asset):
        """Points to check that never block the build: [AssetIssue]. Today
        only the normal map format (workflow.md §20.1.1)."""
        detected = self.detected_normal_format(asset)
        if detected == NORMAL_UNCERTAIN:
            return [AssetIssue(
                "Normal format uncertain",
                "The format of the normal map could not be detected for sure (mirrored or "
                "overlapping UVs?): check it visually after the Build.")]
        used = self.normal_format(asset)
        if detected in NORMAL_FORMATS and detected != used:
            labels = {NORMAL_OPENGL: "OpenGL", NORMAL_DIRECTX: "DirectX"}
            return [AssetIssue(
                f"Normal looks {labels[detected]}",
                f"The normal map looks {labels[detected]}, but {labels[used]} is used. "
                f"Check it visually after the Build, or change \"Source format\".")]
        return []

    def set_project_normal_format(self, normal_format):
        if normal_format not in NORMAL_FORMATS:
            raise ValueError(f"Unknown normal format {normal_format!r}")
        self.project_normal_format = normal_format

    def set_default_normal_format(self, normal_format):
        if normal_format not in NORMAL_FORMATS:
            raise ValueError(f"Unknown normal format {normal_format!r}")
        self.default_normal_format = normal_format

    def normal_format(self, asset):
        """Normal format used at creation: the asset's own choice, else the default."""
        return self.normal_format_override(asset) or self.default_normal_format

    def flip_normal_green(self, asset):
        """True when the source normal map and the project use different formats."""
        return self.normal_format(asset) != self.project_normal_format

    def resolved_textures(self, asset):
        """{texture format: TextureFile} used at creation.

        Single files are used as is; duplicated maps use the artist's choice
        and are left out while no file is chosen.
        """
        resolved = {}
        for texture_format, textures in asset.textures_by_format().items():
            if len(textures) == 1:
                resolved[texture_format] = textures[0]
            elif self.chosen_texture(asset, texture_format) is not None:
                resolved[texture_format] = self.chosen_texture(asset, texture_format)
        return resolved

    def resolved_maps(self, asset):
        """{map name: MapSource} used at creation, packed files split per map.

        A map's own file always wins, for that map only: the other maps of
        the packed file are still used. If two packed files declare the same
        map, the first packed format of the naming preset wins.
        Without any opacity source, a Base Color with an alpha channel gives
        the opacity (channel "A", workflow.md §20.3).
        A Roughness, own file or packed, replaces a Glossiness (§20.5).
        """
        maps = self._maps_found(asset)
        if self._roughness_wins(asset, maps):
            del maps[GLOSSINESS_TEXTURE_FORMAT]
        return maps

    def glossiness_replaced(self, asset):
        """True when the asset has a Glossiness that a Roughness replaces."""
        return self._roughness_wins(asset, self._maps_found(asset))

    @staticmethod
    def _roughness_wins(asset, maps):
        # An own Roughness file still waiting for a duplicate choice also wins.
        has_roughness = (ROUGHNESS_TEXTURE_FORMAT in maps
                         or ROUGHNESS_TEXTURE_FORMAT in asset.textures_by_format())
        return has_roughness and GLOSSINESS_TEXTURE_FORMAT in maps

    def _maps_found(self, asset):
        """{map name: MapSource} of every map found, before the Roughness /
        Glossiness rule."""
        files = self.resolved_textures(asset)
        own_files = asset.textures_by_format()
        maps = {fmt: MapSource(texture) for fmt, texture in files.items()
                if fmt not in self.packed_channels}
        for packed_format, channels in self.packed_channels.items():
            texture = files.get(packed_format)
            if texture is None:
                continue
            for channel, map_name in channels.items():
                # An own file still waiting for a duplicate choice also wins:
                # the asset is in warning until the artist chooses.
                if map_name not in own_files and map_name not in maps:
                    maps[map_name] = MapSource(texture, channel, packed_format)
        # No opacity file: the alpha channel of the Base Color gives the opacity.
        base_color = files.get(BASE_COLOR_TEXTURE_FORMAT)
        if (OPACITY_TEXTURE_FORMAT not in own_files and OPACITY_TEXTURE_FORMAT not in maps
                and base_color is not None and base_color.has_alpha):
            maps[OPACITY_TEXTURE_FORMAT] = MapSource(base_color, ALPHA_CHANNEL,
                                                     BASE_COLOR_TEXTURE_FORMAT)
        return maps

    def placed_assets(self):
        """Assets with an Atlas ID: the only ones used at creation."""
        return [asset for asset in self.assets if self.atlas_id(asset) is not None]

    def can_build(self):
        placed = self.placed_assets()
        return bool(placed) and all(self.asset_status(a) == STATUS_READY for a in placed)

    def asset_issues(self, asset):
        """Problems the artist has to look at: [AssetIssue], one per
        duplicated map without a chosen file, plus one for an ID shared with
        another asset."""
        issues = []
        for texture_format, textures in asset.textures_by_format().items():
            if len(textures) > 1 and self.chosen_texture(asset, texture_format) is None:
                issues.append(AssetIssue(
                    "Duplicate", f"Choose the {self.format_label(texture_format)} file "
                                 f"({len(textures)} files found)"))
        atlas_id = self.atlas_id(asset)
        if atlas_id is not None:
            others = [other.name for other in self.assets_at(atlas_id) if other is not asset]
            if others:
                issues.append(AssetIssue(f"ID {atlas_id} already used",
                                         f"ID {atlas_id} also used by {', '.join(others)}"))
        return issues

    def asset_status(self, asset):
        if self.asset_issues(asset):
            return STATUS_WARNING
        if self.atlas_id(asset) is None:
            return STATUS_NO_ID
        return STATUS_READY

    def cell_status(self, atlas_id):
        assets = self.assets_at(atlas_id)
        if not assets:
            return STATUS_EMPTY
        if len(assets) > 1 or any(self.asset_status(a) == STATUS_WARNING for a in assets):
            return STATUS_WARNING
        return STATUS_READY
