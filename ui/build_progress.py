"""Progress window of the Build: "Building the atlas...", the asset being
built and a turning icon (circle of arrows, like Painter's refresh icon).

Pure PySide6. The Build (painter/layer_builder.py) runs in Painter's main
thread: nothing is redrawn while it works. BuildProgressDialog.report is
given to build_atlas as its progress function, which calls it several times
per asset (before each Painter call): after SHOW_DELAY the window appears,
then each call turns the icon and redraws the window. No Cancel: a Build
stopped halfway would leave a half-made layer stack (Ctrl+Z undoes a whole
Build).
"""

import math
import time

from PySide6 import QtCore, QtGui, QtWidgets

from .widgets import PLUGIN_NAME, set_window_icon

SHOW_DELAY = 0.3          # seconds of Build before the window appears
_REFRESH_INTERVAL = 0.05  # seconds between two redraws
_TURN_TIME = 1.0          # seconds per turn of the icon (from the clock: steady speed)
_ICON_SIZE = 22           # pixels
_ICON_COLOR = "#c8c8c8"   # light grey, like Painter's icons
_LINE_WIDTH = 1.2         # pixels: thin, like Painter's icons
_HEAD_LENGTH = 3.0        # pixels: arrow heads
_WIDTH = 300              # pixels of the text column; a long asset name is cut
_MARGIN = 20
_MUTED_STYLE = "color: #999999;"


class TurningIcon(QtWidgets.QWidget):
    """Circle made of two arrows, drawn at the current angle. Also used by
    the scan window (ui/scan_progress.py)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        self.angle = 0.0

    def turn(self, seconds):
        """Angle after this many seconds of work (steady speed), redrawn at
        the next processEvents."""
        self.angle = seconds / _TURN_TIME * 360 % 360
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        color = QtGui.QColor(_ICON_COLOR)
        painter.setPen(QtGui.QPen(color, _LINE_WIDTH, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        painter.translate(_ICON_SIZE / 2, _ICON_SIZE / 2)
        painter.rotate(-self.angle)   # counterclockwise, like the arrows
        radius = _ICON_SIZE / 2 - 4
        rect = QtCore.QRectF(-radius, -radius, 2 * radius, 2 * radius)
        head = _HEAD_LENGTH
        for start in (20, 200):   # two arcs of 140°, each ending in an arrow head
            painter.drawArc(rect, start * 16, 140 * 16)
            # End of the arc (Qt angles go counterclockwise, y goes down).
            end = math.radians(start + 140)
            tip = QtCore.QPointF(radius * math.cos(end), -radius * math.sin(end))
            # Tangent at the end, in the arc's direction.
            tangent = QtCore.QPointF(-math.sin(end), -math.cos(end))
            normal = QtCore.QPointF(math.cos(end), -math.sin(end))
            back = tip - tangent * head
            painter.setBrush(color)
            painter.drawPolygon(QtGui.QPolygonF(
                [tip, back + normal * (head * 0.7), back - normal * (head * 0.7)]))
        painter.end()


class BuildProgressDialog(QtWidgets.QDialog):
    """'Building the atlas...', turning icon, '7 / 16 · Ladder'."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(PLUGIN_NAME)
        set_window_icon(self)
        # The whole of Painter waits: no click elsewhere during the Build.
        self.setWindowModality(QtCore.Qt.ApplicationModal)
        # Windows shows the title bar icon only with the system menu; the
        # close button stays off (no WindowCloseButtonHint) and reject()
        # ignores Escape / Alt+F4: the Build cannot be stopped halfway.
        self.setWindowFlags(QtCore.Qt.Dialog | QtCore.Qt.CustomizeWindowHint
                            | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowSystemMenuHint)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        layout.setSpacing(_MARGIN // 2 + 4)
        self._icon = TurningIcon()
        layout.addWidget(self._icon, 0, QtCore.Qt.AlignTop)
        texts = QtWidgets.QVBoxLayout()
        texts.setSpacing(6)
        layout.addLayout(texts)
        self._title = QtWidgets.QLabel("Building the atlas...")
        texts.addWidget(self._title)
        self._asset = QtWidgets.QLabel()
        self._asset.setStyleSheet(_MUTED_STYLE)
        self._asset.setFixedWidth(_WIDTH)
        texts.addWidget(self._asset)
        layout.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)

        self._start = time.monotonic()
        self._last_refresh = 0.0

    def report(self, done, total, asset_name):
        """Progress function of build_atlas (done = assets finished so far)."""
        now = time.monotonic()
        if now - self._start < SHOW_DELAY or now - self._last_refresh < _REFRESH_INTERVAL:
            return
        self._last_refresh = now
        text = f"{min(done + 1, total)} / {total}"
        if asset_name:
            text += f" · {asset_name}"
        self._asset.setText(self._asset.fontMetrics().elidedText(
            text, QtCore.Qt.ElideRight, _WIDTH))
        self._icon.turn(now - self._start)
        if not self.isVisible():
            self.show()
        # Draw the window only: clicks and keys wait (the window is modal
        # anyway), so nothing can change the project during the Build.
        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents)

    def set_finishing(self):
        """The plugin's work is done; Painter recomputes the layers next and
        redraws nothing meanwhile (the icon stays still): say so."""
        if not self.isVisible():
            return   # short Build: no window at all
        self._title.setText("Updating the layers...")
        self._asset.setText("")
        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents)

    def reject(self):
        """Escape: ignored, the Build goes on."""

    def closeEvent(self, event):
        """Alt+F4 / close button: ignored, the Build goes on (finish() hides)."""
        event.ignore()

    def finish(self):
        """Build over (succeeded or failed): close the window."""
        self.hide()
        self.deleteLater()
