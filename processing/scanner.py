"""Folder scan: finds the assets and their texture files.

Reads file names only: nothing is opened, moved or modified, and no
Painter API is used (analysis phase, docs/project/workflow.md §7).

The root folder and all its subfolders (any depth) are scanned. The asset
always comes from the file name without its texture suffix, wherever the
file is:  Root/ElectricDrill_BaseColor.png and
          Root/Meshes/ElectricDrill_Normal.png  -> asset "ElectricDrill".
Only a file with nothing before its suffix (Root/Drill/_BC.png) takes the
name of the root subfolder it is in. A known asset prefix (e.g. "TX_") is
then removed. Files of one asset spread over several folders are merged.
"""

import os
from dataclasses import dataclass, field

from ..core.atlas_assignment import BASE_COLOR_TEXTURE_FORMAT
from .image_alpha import has_alpha


class ScanError(Exception):
    """The folder cannot be scanned. The message is written for the artist."""


class ScanCancelled(Exception):
    """The artist stopped the scan (progress returned False): no result."""


@dataclass
class TextureFile:
    path: str             # absolute path
    relative_path: str    # path relative to the scanned root, for display
    texture_format: str   # e.g. "base color", from the naming preset
    keyword: str          # suffix that identified it, e.g. "_bc"
    # Alpha channel in the file (header only, image_alpha.py). Read for Base
    # Color files only: the only map whose alpha is used (opacity, workflow.md
    # §20.3); False for the others.
    has_alpha: bool = False


@dataclass
class Asset:
    name: str
    textures: list = field(default_factory=list)   # [TextureFile]

    def textures_by_format(self):
        """{texture format: [TextureFile]}. More than one file means a duplicate."""
        grouped = {}
        for texture in self.textures:
            grouped.setdefault(texture.texture_format, []).append(texture)
        return grouped


@dataclass
class ScanResult:
    root_folder: str
    assets: list = field(default_factory=list)        # [Asset], sorted by name
    unrecognized: list = field(default_factory=list)  # relative paths of image files without known suffix
    unreadable: list = field(default_factory=list)    # relative paths of folders that could not be read
    # Relative paths of image files ignored because their name or one of
    # their folders has accented or special characters (workflow.md §7).
    not_allowed: list = field(default_factory=list)


def _special_characters(text):
    """Accented or special characters of text (anything outside plain ASCII:
    é, ç, ü, ß...), in order, each once. Spaces are allowed."""
    return "".join(dict.fromkeys(c for c in text if not c.isascii()))


def scan_folder(root_folder, attributes, progress=None):
    """Scan root_folder with the rules of a TextureAttributes. Raises ScanError.

    progress(folders, files, relative_folder), optional: called for every
    folder entered and every image file read (a big folder or a network
    drive can take long), with the counts so far and the folder being read.
    It returns False to stop the scan: ScanCancelled is then raised.
    """
    # Accents are not allowed anywhere in a path (artist's rule, 2026-10-07).
    special = _special_characters(root_folder)
    if special:
        raise ScanError(f"The folder path contains accented or special characters "
                        f"({' '.join(special)}), which Atlas Mapper does not accept:\n"
                        f"{root_folder}\n"
                        f"Rename these folders, or move the textures to a path without them.")
    if not os.path.isdir(root_folder):
        raise ScanError(f"The folder does not exist or cannot be accessed:\n{root_folder}")
    try:
        os.listdir(root_folder)   # the root itself must be readable
    except OSError:
        raise ScanError(f"The content of the folder cannot be read:\n{root_folder}\n"
                        f"Check the access rights.")

    result = ScanResult(root_folder)
    assets = {}  # lowercase name -> Asset, so "Drill" and "drill" are one asset

    def asset_named(name):
        # Same prefix rule for every name, so "TX_Drill_BC.png" and
        # "Drill_N.png" give the same asset "Drill".
        name = attributes.strip_asset_prefix(name)
        return assets.setdefault(name.lower(), Asset(name))

    def on_error(error):
        result.unreadable.append(os.path.relpath(error.filename, root_folder))

    folder_count = file_count = 0

    def report_progress(relative_folder):
        if progress is not None and progress(folder_count, file_count, relative_folder) is False:
            raise ScanCancelled()

    for current, dirs, files in os.walk(root_folder, onerror=on_error):
        dirs.sort(key=str.lower)   # same order at every scan
        relative_folder = os.path.relpath(current, root_folder)
        folder_count += 1
        file_count += len(files)
        report_progress(relative_folder)
        # Fallback name: the subfolder of the root this file is in (None at the root).
        folder_asset = None if relative_folder == "." else relative_folder.split(os.sep)[0]
        for file_name in sorted(files, key=str.lower):
            if not attributes.is_supported_file(file_name):
                continue
            # Reading an image header (Base Color alpha) can be slow on a network drive.
            report_progress(relative_folder)
            path = os.path.join(current, file_name)
            # In the file name or in a subfolder name: the file is ignored.
            if _special_characters(os.path.relpath(path, root_folder)):
                result.not_allowed.append(os.path.relpath(path, root_folder))
                continue
            match = attributes.match_suffix(file_name)
            asset_name = _asset_name_from_file(file_name, match) or (match and folder_asset)
            if asset_name:
                asset_named(asset_name).textures.append(_texture(path, match, root_folder))
            else:
                result.unrecognized.append(os.path.relpath(path, root_folder))

    result.assets = sorted(assets.values(), key=lambda a: a.name.lower())
    return result


def _asset_name_from_file(file_name, match):
    """'ElectricDrill_BaseColor.png' -> 'ElectricDrill' (original case kept), or None."""
    if match is None:
        return None
    stem = os.path.splitext(file_name)[0]
    # The keyword was matched on the lowercase name: same length, so cut the original.
    name = stem[:len(stem) - len(match.keyword)].rstrip("_-. ")
    return name or None


def _texture(path, match, root_folder):
    # Opening every file was 70 % of the scan time (2026-10-06): only the Base
    # Color needs it. Unreadable header (None) = no alpha.
    alpha = match.texture_format == BASE_COLOR_TEXTURE_FORMAT and bool(has_alpha(path))
    return TextureFile(path, os.path.relpath(path, root_folder), match.texture_format, match.keyword,
                       alpha)
