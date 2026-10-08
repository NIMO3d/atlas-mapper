"""Atlas Mapper "About" window: plugin name, version, author and links.

Pure PySide6, opened by the "?" button of the main panel (ui/main_panel.py).
"""

import os

from PySide6 import QtCore, QtGui, QtWidgets

from .widgets import PAINTER_ACCENT, PLUGIN_NAME, PLUGIN_VERSION, set_window_icon

_ICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "resources", "atlas_mapper_icon.svg")

_DESCRIPTION = "Non-destructive texture atlasing for Substance 3D Painter."
_AUTHOR = "Nicolas Morlet"
_CREDITS = "Developed with Claude (Anthropic)"
_COPYRIGHT = "© 2026 Nicolas Morlet"
_FREE_NOTE = "Free plugin."
# (label, url), shown as clickable links that open in the web browser.
_LINKS = (
    ("ArtStation", "https://www.artstation.com/nicolasmorlet"),
    ("LinkedIn", "https://www.linkedin.com/in/nicolas-morlet-9b8ab763/"),
)

_ICON_SIZE = 64       # pixels
_TEXT_GAP = 16        # between the icon and the text column
_BLOCK_SPACING = 12   # between the text blocks
_MARGIN = 20          # around the window content
# Muted text (version, copyright), lighter than the panel's disabled grey.
_MUTED_STYLE = "color: #999999;"


class AboutDialog(QtWidgets.QDialog):
    """Small fixed window: icon on the left, texts on the right, Close button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {PLUGIN_NAME}")
        set_window_icon(self)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        layout.setSpacing(_MARGIN)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(_TEXT_GAP)
        layout.addLayout(top)

        icon = QtWidgets.QLabel()
        icon.setPixmap(QtGui.QIcon(_ICON_PATH).pixmap(_ICON_SIZE, _ICON_SIZE))
        top.addWidget(icon, 0, QtCore.Qt.AlignTop)

        texts = QtWidgets.QVBoxLayout()
        texts.setSpacing(_BLOCK_SPACING)
        top.addLayout(texts, 1)

        # Name in bold and larger, version just below it.
        title_block = QtWidgets.QVBoxLayout()
        title_block.setSpacing(2)
        name = QtWidgets.QLabel(PLUGIN_NAME)
        font = name.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.4)
        name.setFont(font)
        title_block.addWidget(name)
        version = QtWidgets.QLabel(f"Version {PLUGIN_VERSION}")
        version.setStyleSheet(_MUTED_STYLE)
        title_block.addWidget(version)
        texts.addLayout(title_block)

        texts.addWidget(QtWidgets.QLabel(_DESCRIPTION))
        texts.addWidget(QtWidgets.QLabel(f"Created by <b>{_AUTHOR}</b><br>{_CREDITS}"))

        # Painter's default link color is hard to read on its dark background:
        # links take Painter's accent blue.
        links = QtWidgets.QLabel("  ·  ".join(
            f'<a href="{url}" style="color: {PAINTER_ACCENT};">{label}</a>'
            for label, url in _LINKS))
        links.setTextFormat(QtCore.Qt.RichText)
        links.setOpenExternalLinks(True)
        texts.addWidget(links)

        footer = QtWidgets.QLabel(f"{_COPYRIGHT}  ·  {_FREE_NOTE}")
        footer.setStyleSheet(_MUTED_STYLE)
        texts.addWidget(footer)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Fixed size: the window is as small as its content.
        layout.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
