"""Progress window of a long scan, with a Cancel button.

Pure PySide6. The scan (processing/scanner.py) runs in Painter's main
thread: while it reads a big folder or a network drive, Painter cannot
redraw. ScanProgressDialog.report is given to scan_folder as its progress
function: after SHOW_DELAY the window appears and, a few times per second,
shows the counts and lets Painter process the clicks (Cancel). A normal
scan ends before SHOW_DELAY: no window at all.
"""

import os
import time

from PySide6 import QtCore, QtWidgets

from .widgets import PLUGIN_NAME, set_window_icon

SHOW_DELAY = 0.5        # seconds of scan before the window appears
_REFRESH_INTERVAL = 0.1  # seconds between two refreshes of the window
_WIDTH = 360            # pixels of the text column; a long folder path is cut in the middle
_MARGIN = 20
_MUTED_STYLE = "color: #999999;"  # current folder, like the About window's muted texts


class ScanProgressDialog(QtWidgets.QDialog):
    """'Scanning the folder...', counts, current folder, Cancel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(PLUGIN_NAME)
        set_window_icon(self)
        # The whole of Painter waits: no click elsewhere during the scan
        # (a second scan, a project closed...).
        self.setWindowModality(QtCore.Qt.ApplicationModal)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        layout.setSpacing(6)
        layout.addWidget(QtWidgets.QLabel("Scanning the folder..."))
        self._counts = QtWidgets.QLabel()
        layout.addWidget(self._counts)
        self._folder = QtWidgets.QLabel()
        self._folder.setStyleSheet(_MUTED_STYLE)
        self._folder.setFixedWidth(_WIDTH)
        layout.addWidget(self._folder)
        layout.addSpacing(_MARGIN // 2)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        layout.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)

        self._start = time.monotonic()
        self._last_refresh = 0.0
        self._cancelled = False

    def report(self, folders, files, relative_folder):
        """Progress function of scan_folder: False once the artist cancelled."""
        if self._cancelled:
            return False
        now = time.monotonic()
        if now - self._start < SHOW_DELAY or now - self._last_refresh < _REFRESH_INTERVAL:
            return True
        self._last_refresh = now
        self._counts.setText(f"{files:,} file{'' if files == 1 else 's'} · "
                             f"{folders:,} folder{'' if folders == 1 else 's'}")
        folder = "" if relative_folder == "." else relative_folder.replace(os.sep, "/")
        self._folder.setText(self._folder.fontMetrics().elidedText(
            folder, QtCore.Qt.ElideMiddle, _WIDTH))
        self._folder.setToolTip(folder)
        if not self.isVisible():
            self.show()
        # Draw the window and handle the clicks (Cancel) before reading on.
        QtWidgets.QApplication.processEvents()
        return not self._cancelled

    def reject(self):
        """Cancel button, Escape or the window's close button: the scan stops
        at its next file."""
        self._cancelled = True
        super().reject()

    def finish(self):
        """Scan over (finished, failed or cancelled): close the window."""
        self.hide()
        self.deleteLater()
