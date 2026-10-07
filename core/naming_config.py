"""Texture identification rules, read from a naming preset.

A naming preset is one JSON file of the plugin's naming_presets folder
(e.g. naming_presets/Default.json), so the artist can edit it without
touching the code. The preset name is the file name without ".json".
Each preset has separate sections:
    "extensions"      -> which image files the scan looks at;
    "texture_formats" -> texture format name -> list of suffix keywords;
    "packed_formats"  -> optional, packed format name -> suffixes + map stored in R / G / B / A;
    "asset_prefixes"  -> optional prefixes removed from the start of asset names.

Rules (see docs/project/project-overview.md, "Naming Convention System"):
    - names are compared in lowercase;
    - a keyword is a suffix: it must end the file name (extension excluded);
    - a prefix must start the asset name; only one prefix is removed;
    - when several keywords (or prefixes) match, the longest one wins;
    - packed formats follow the same suffix rules; their channels are
      declared, never guessed from the letters of the name
      (docs/project/workflow.md §20.2).
"""

import json
import os
from dataclasses import dataclass

PRESETS_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), "naming_presets")
DEFAULT_PRESET = "Default"
# Reference preset: can be copied, never modified from the panel.
PROTECTED_PRESET = DEFAULT_PRESET

# Maps of the preset editor, in this order: each has a route into
# UVtransform.sbsar (painter/uvtransform_sbsar.py, MAP_ROUTES).
# Glossiness (= Smoothness) is an inverted Roughness: it goes into the
# Roughness branch with roughness_invert on (workflow.md §20.5).
SINGLE_MAPS = ("base color", "normal", "roughness", "glossiness", "metallic", "ambient occlusion",
               "opacity", "height", "emissive")
# Maps a packed file can hold, in any channel R / G / B / A (workflow.md
# §20.2 and §20.3). Whether the .sbsar reads the A channel of a map is
# checked at Build (painter/uvtransform_sbsar.py, ALPHA_READY_MAPS).
PACKABLE_MAPS = ("ambient occlusion", "roughness", "glossiness", "metallic", "opacity", "height",
                 "emissive")


class NamingConfigError(Exception):
    """A naming preset is missing or invalid. The message is written for the artist."""


@dataclass(frozen=True)
class SuffixMatch:
    texture_format: str   # e.g. "base color"
    keyword: str          # e.g. "_basecolor"


# Channels a packed format can declare, in display order.
PACKED_CHANNELS = ("R", "G", "B", "A")


class TextureAttributes:
    """Validated content of a naming preset."""

    def __init__(self, extensions, texture_formats, asset_prefixes=(), packed_formats=None):
        self.extensions = extensions            # tuple of lowercase ".ext"
        self.texture_formats = texture_formats  # {format name: [keywords]}, file order kept
        packed_formats = packed_formats or {}   # {name: (keywords, {"R": map name, ...})}
        # {packed format name: {"R": map name, ...}}, file order kept.
        self.packed_channels = {name: channels for name, (_kw, channels) in packed_formats.items()}
        all_keywords = dict(texture_formats)
        all_keywords.update({name: keywords for name, (keywords, _ch) in packed_formats.items()})
        # Longest first: the first prefix found is the longest.
        self.asset_prefixes = tuple(sorted(asset_prefixes, key=len, reverse=True))
        # Every (keyword, format), longest keyword first: the first match is the longest.
        self._keywords = sorted(
            ((keyword, name) for name, keywords in all_keywords.items() for keyword in keywords),
            key=lambda item: len(item[0]), reverse=True)

    def is_supported_file(self, file_name):
        return os.path.splitext(file_name)[1].lower() in self.extensions

    def match_suffix(self, file_name):
        """Texture format of a file, from the suffix of its name, or None.

        The name is lowercased before comparison; the extension is ignored.
        """
        stem = os.path.splitext(file_name)[0].lower()
        for keyword, texture_format in self._keywords:
            if stem.endswith(keyword):
                return SuffixMatch(texture_format, keyword)
        return None

    def strip_asset_prefix(self, name):
        """'TX_ElectricDrill' -> 'ElectricDrill' (original case kept).

        The name is kept unchanged if no prefix matches, or if removing the
        prefix would leave nothing.
        """
        lowered = name.lower()
        for prefix in self.asset_prefixes:
            if lowered.startswith(prefix) and len(name) > len(prefix):
                return name[len(prefix):]
        return name


def list_presets():
    """Names of the naming presets (JSON files of naming_presets): Default
    first, then the others in alphabetical order (both lists of presets)."""
    try:
        names = [os.path.splitext(entry)[0] for entry in os.listdir(PRESETS_FOLDER)
                 if entry.lower().endswith(".json")]
    except OSError:  # folder missing: no preset, the scan explains it
        return []
    return sorted(names, key=lambda name: (name.lower() != DEFAULT_PRESET.lower(), name.lower()))


def preset_path(preset_name):
    return os.path.join(PRESETS_FOLDER, f"{preset_name}.json")


def read_preset_data(preset_name):
    """Raw content of a preset file (dict), for the preset editor.
    Raises NamingConfigError when it cannot be read."""
    path = preset_path(preset_name)
    try:
        with open(path, encoding="utf-8") as config_file:
            data = json.load(config_file)
    except (OSError, json.JSONDecodeError) as error:
        raise NamingConfigError(
            f"The naming preset \"{preset_name}\" cannot be read:\n{path}\n"
            f"({error})")
    if not isinstance(data, dict):
        raise NamingConfigError(
            f"The naming preset \"{preset_name}\" must hold an object {{ ... }}.")
    return data


def check_preset_data(data):
    """Check preset content with the same rules as the scan. Raises NamingConfigError."""
    _read_attributes(data)


def is_protected_preset(preset_name):
    return preset_name.lower() == PROTECTED_PRESET.lower()


# Characters Windows refuses in a file name.
_FORBIDDEN_NAME_CHARACTERS = '\\/:*?"<>|'


def check_new_preset_name(name, current=None):
    """Message for the artist if a preset cannot have this name, else "".
    current: name of the preset being renamed (it may keep its own name, or
    change only its upper / lower case)."""
    if not name:
        return "Give the preset a name."
    if any(character in _FORBIDDEN_NAME_CHARACTERS for character in name):
        return f"The name cannot contain these characters: {_FORBIDDEN_NAME_CHARACTERS}"
    if current is not None and name.lower() == current.lower():
        return ""
    if name.lower() in (existing.lower() for existing in list_presets()):
        return f"A preset \"{name}\" already exists: choose another name."
    return ""


def save_preset(preset_name, data):
    """Check then write a preset file. Default stays protected (never overwritten).
    Raises NamingConfigError."""
    if is_protected_preset(preset_name):
        raise NamingConfigError(
            f"The preset \"{PROTECTED_PRESET}\" is protected: it is the reference.")
    check_preset_data(data)
    try:
        os.makedirs(PRESETS_FOLDER, exist_ok=True)
        with open(preset_path(preset_name), "w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=4, ensure_ascii=False)
            config_file.write("\n")
    except OSError as error:
        raise NamingConfigError(
            f"The preset \"{preset_name}\" could not be saved:\n"
            f"{preset_path(preset_name)}\n({error})")


def rename_preset(old_name, new_name, data):
    """Save a modified preset under a new name: its content is written to the
    old file, which is then renamed (also works for a change of upper / lower
    case only, which Windows sees as the same file). Default stays protected.
    Raises NamingConfigError."""
    problem = check_new_preset_name(new_name, current=old_name)
    if problem:
        raise NamingConfigError(problem)
    if is_protected_preset(new_name):
        raise NamingConfigError(
            f"The name \"{PROTECTED_PRESET}\" is reserved for the reference preset.")
    save_preset(old_name, data)   # checked and written first: nothing renamed if it fails
    try:
        os.rename(preset_path(old_name), preset_path(new_name))
    except OSError as error:
        raise NamingConfigError(
            f"The preset \"{old_name}\" was saved but could not be renamed "
            f"to \"{new_name}\":\n{preset_path(old_name)}\n({error})")


def delete_preset(preset_name):
    """Delete a preset file. Default stays protected. Raises NamingConfigError."""
    if is_protected_preset(preset_name):
        raise NamingConfigError(
            f"The preset \"{PROTECTED_PRESET}\" is protected: it is the reference.")
    try:
        os.remove(preset_path(preset_name))
    except OSError as error:
        raise NamingConfigError(
            f"The preset \"{preset_name}\" could not be deleted:\n"
            f"{preset_path(preset_name)}\n({error})")


def load_texture_attributes(preset_name):
    """Read and check one naming preset. Raises NamingConfigError."""
    path = preset_path(preset_name)
    try:
        with open(path, encoding="utf-8") as config_file:
            data = json.load(config_file)
    except FileNotFoundError:
        raise NamingConfigError(
            f"The naming preset \"{preset_name}\" cannot be found:\n{path}\n"
            f"The presets are the .json files of the plugin's naming_presets folder.")
    except json.JSONDecodeError as error:
        raise NamingConfigError(
            f"The naming preset \"{preset_name}\" has a syntax error "
            f"on line {error.lineno} (missing comma, quote or bracket?).\n"
            f"Fix the file {path}, then run the scan again.")
    try:
        return _read_attributes(data)
    except NamingConfigError as error:
        raise NamingConfigError(f"Naming preset \"{preset_name}\": {error}\n"
                                f"Fix the file {path}, then run the scan again.") from None


def _read_attributes(data):
    if not isinstance(data, dict):
        raise NamingConfigError("the file must hold an object { ... }.")

    extensions = _read_extensions(data.get("extensions"))
    # Shared by both sections: a suffix belongs to one format only.
    owner_of_keyword = {}
    texture_formats = _read_texture_formats(data.get("texture_formats"), owner_of_keyword)
    packed_formats = _read_packed_formats(data.get("packed_formats", {}), texture_formats,
                                          owner_of_keyword)
    asset_prefixes = _read_asset_prefixes(data.get("asset_prefixes", []))
    return TextureAttributes(extensions, texture_formats, asset_prefixes, packed_formats)


def _read_asset_prefixes(raw):
    # Optional section: [] or missing means asset names are kept unchanged.
    if not isinstance(raw, list):
        raise NamingConfigError(
            f'the "asset_prefixes" section must be a list, '
            f'for example ["tx_", "sm_"], or [] to remove no prefix.')
    prefixes = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise NamingConfigError(
                f'invalid prefix in "asset_prefixes": {item!r}.')
        prefixes.append(item.strip().lower())
    return prefixes


def _read_extensions(raw):
    if not isinstance(raw, list) or not raw:
        raise NamingConfigError(
            f'the "extensions" section must be a non-empty list, '
            f'for example [".png", ".tga"].')
    extensions = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise NamingConfigError(
                f'invalid extension in "extensions": {item!r}.')
        extension = item.strip().lower()
        if not extension.startswith("."):
            extension = "." + extension
        extensions.append(extension)
    return tuple(extensions)


def _read_texture_formats(raw, owner_of_keyword):
    if not isinstance(raw, dict) or not raw:
        raise NamingConfigError(
            f'the "texture_formats" section must give each format '
            f'a list of suffixes, for example "normal": ["_normal", "_n"].')
    return {name: _read_suffixes(name, keywords, owner_of_keyword)
            for name, keywords in raw.items()}


def _read_suffixes(name, keywords, owner_of_keyword):
    """Cleaned suffix list of one format (texture or packed)."""
    if not isinstance(keywords, list) or not keywords:
        raise NamingConfigError(
            f'the format "{name}" must have a non-empty list of suffixes.')
    cleaned = []
    for keyword in keywords:
        if not isinstance(keyword, str) or not keyword.strip():
            raise NamingConfigError(
                f'invalid suffix for the format "{name}": {keyword!r}.')
        keyword = keyword.strip().lower()
        # A suffix shared by two formats would make the detection ambiguous.
        if keyword in owner_of_keyword and owner_of_keyword[keyword] != name:
            raise NamingConfigError(
                f'the suffix "{keyword}" is used by both '
                f'"{owner_of_keyword[keyword]}" and "{name}". A suffix can belong '
                f'to one format only.')
        owner_of_keyword[keyword] = name
        cleaned.append(keyword)
    return cleaned


_PACKED_EXAMPLE = ('"orm": { "suffixes": ["_orm"], "R": "ambient occlusion", '
                   '"G": "roughness", "B": "metallic" }')


def _read_packed_formats(raw, texture_formats, owner_of_keyword):
    """{name: (suffixes, {"R": map name, ...})}. Optional section: {} or missing = none."""
    if not isinstance(raw, dict):
        raise NamingConfigError(
            f'the "packed_formats" section must describe each packed '
            f'format, for example {_PACKED_EXAMPLE}.')
    packed_formats = {}
    for name, entry in raw.items():
        if name in texture_formats:
            raise NamingConfigError(
                f'"{name}" is both in "texture_formats" and in '
                f'"packed_formats". Keep it in one section only.')
        if not isinstance(entry, dict):
            raise NamingConfigError(
                f'the packed format "{name}" must be described like this: '
                f'{_PACKED_EXAMPLE}.')
        unknown = [key for key in entry if key not in ("suffixes",) + PACKED_CHANNELS]
        if unknown:
            raise NamingConfigError(
                f'packed format "{name}": unknown key "{unknown[0]}". '
                f'Possible keys: "suffixes", "R", "G", "B", "A" (upper case).')
        suffixes = _read_suffixes(name, entry.get("suffixes"), owner_of_keyword)
        channels = {}
        for channel in PACKED_CHANNELS:
            if channel not in entry:
                continue
            map_name = entry[channel]
            if not isinstance(map_name, str) or map_name.strip().lower() not in texture_formats:
                raise NamingConfigError(
                    f'packed format "{name}", channel {channel}: '
                    f'{map_name!r} is not a format of "texture_formats" '
                    f'({", ".join(texture_formats)}).')
            map_name = map_name.strip().lower()
            if map_name in channels.values():
                raise NamingConfigError(
                    f'packed format "{name}": the map "{map_name}" is '
                    f'declared in two channels.')
            channels[channel] = map_name
        if not channels:
            raise NamingConfigError(
                f'the packed format "{name}" declares no channel '
                f'(R, G, B or A).')
        packed_formats[name] = (suffixes, channels)
    return packed_formats
