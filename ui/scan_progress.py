"""Progress window of a long scan, with a turning icon (the one of the
Build window, ui/build_progress.py) and a Cancel button.

Pure PySide6. The scan (processing/scanner.py) runs in Painter's main
thread: while it reads a big folder or a network drive, Painter cannot
redraw. ScanProgressDialog.report is given to scan_folder as its progress
function: after SHOW_DELAY the window appears and, a few times per second,
shows the counts and lets Painter process the clicks (Cancel). A normal
scan ends before SHOW_DELAY: no window at all. report_normal_maps does the
same for the analysis of the normal maps that follows the scan
(processing/normal_detection.py).
"""

import os
import time

from PySide6 import QtCore, QtWidgets

from .build_progress import TurningIcon
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
        # Turning icon left of the texts, as in the Build window (2026-10-09).
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(_MARGIN // 2 + 4)
        layout.addLayout(top)
        self._icon = TurningIcon()
        top.addWidget(self._icon, 0, QtCore.Qt.AlignTop)
        texts = QtWidgets.QVBoxLayout()
        texts.setSpacing(6)
        top.addLayout(texts)
        self._title = QtWidgets.QLabel("Scanning the folder...")
        texts.addWidget(self._title)
        self._counts = QtWidgets.QLabel()
        texts.addWidget(self._counts)
        self._folder = QtWidgets.QLabel()
        self._folder.setStyleSheet(_MUTED_STYLE)
        self._folder.setFixedWidth(_WIDTH)
        texts.addWidget(self._folder)
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
        folder = "" if relative_folder == "." else relative_folder
        return self._report("Scanning the folder...",
                            f"{files:,} file{'' if files == 1 else 's'} · "
                            f"{folders:,} folder{'' if folders == 1 else 's'}", folder)

    def report_normal_maps(self, done, total, relative_path):
        """Progress function of detect_normal_maps: False once the artist cancelled."""
        return self._report("Analysing the normal maps...", f"{done + 1} / {total}",
                            relative_path)

    def _report(self, title, counts, path):
        if self._cancelled:
            return False
        now = time.monotonic()
        if now - self._start < SHOW_DELAY or now - self._last_refresh < _REFRESH_INTERVAL:
            return True
        self._last_refresh = now
        self._title.setText(title)
        self._counts.setText(counts)
        path = path.replace(os.sep, "/")
        self._folder.setText(self._folder.fontMetrics().elidedText(
            path, QtCore.Qt.ElideMiddle, _WIDTH))
        self._folder.setToolTip(path)
        self._icon.turn(now - self._start)
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
