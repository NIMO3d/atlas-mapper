"""Small reusable widgets shared by the Atlas Mapper panels.

Pure PySide6. Painter's own icons (close cross, drop-down arrow) are not
reachable from a plugin, so the symbols used here are painted with thin
lines in the widget text color, to match Painter's look.
"""

import html
import os
import re
import textwrap

from PySide6 import QtCore, QtGui, QtWidgets

PLUGIN_NAME = "Atlas Mapper"
# Shown in the "About" window (ui/about_dialog.py). Raise it at each release.
PLUGIN_VERSION = "1.0.0"
# Dark grey (#333333) version of the plugin icon, for the light title bar of
# every window the plugin opens (the panel itself keeps the light icon).
_WINDOW_ICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "resources", "atlas_mapper_icon_window.png")

# Painter UI colors, sampled from the native "Texture Set Settings" panel.
_PAINTER_SEPARATOR = "#262626"
_PAINTER_TITLE = "#e5e5e5"
_PAINTER_TITLE_DISABLED = "#999999"  # greyed title while no project is open
PAINTER_ACCENT = "#378ef0"  # blue frame of Painter's active panel
_PAINTER_BACKGROUND = "#333333"

# Section titles (bold, light grey), as in native Painter panels.
SECTION_TITLE_STYLE = (f"QLabel {{ color: {_PAINTER_TITLE}; font-weight: bold; }}"
                       f"QLabel:disabled {{ color: {_PAINTER_TITLE_DISABLED}; }}")

# Painter's button style adds a minimum width and outer margins, which made
# square buttons narrow and far from their neighbour: both are cancelled.
SQUARE_BUTTON_STYLE = "QPushButton { margin: 0px; padding: 0px; min-width: 0px; }"


def _symbol_pen(widget):
    """Thin pen in the widget text color (greyed when the widget is disabled)."""
    group = QtGui.QPalette.Active if widget.isEnabled() else QtGui.QPalette.Disabled
    return QtGui.QPen(widget.palette().color(group, QtGui.QPalette.ButtonText), 1.0)


class SquareButton(QtWidgets.QPushButton):
    """Button as high as its row (the neighbouring field), and as wide as high."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(SQUARE_BUTTON_STYLE)
        # Height follows the row instead of the button's own default height.
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Width = height once the real height is known (after Painter's style
        # is applied and the panel is laid out).
        if self.width() != self.height():
            self.setFixedWidth(self.height())


class CrossButton(SquareButton):
    """Square button with a thin cross, like Painter's panel close cross."""

    CROSS_SIZE = 5  # pixels

    def __init__(self, parent=None):
        super().__init__("", parent)

    def paintEvent(self, event):
        super().paintEvent(event)  # button frame and background
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(_symbol_pen(self))
        half = self.CROSS_SIZE / 2.0
        center = QtCore.QRectF(self.rect()).center()
        painter.drawLine(center + QtCore.QPointF(-half, -half), center + QtCore.QPointF(half, half))
        painter.drawLine(center + QtCore.QPointF(-half, half), center + QtCore.QPointF(half, -half))


_ITALIC_STYLE = "QLineEdit { font-style: italic; }"


def set_italic_placeholder(field):
    """Show the grey hint text of an empty field in italics; the text typed
    or pasted by the artist stays upright."""
    def update(text):
        field.setStyleSheet("" if text else _ITALIC_STYLE)
    field.textChanged.connect(update)
    update(field.text())


class PathField(QtWidgets.QLineEdit):
    """Path field that keeps the full path but, when it does not fit, shows
    its start + "…" + its end ("C:/Users/…/PluginTest"). While the artist
    edits it (the field has the focus), the full path is shown.

    Use path() / set_path() and the path_changed signal, never text() /
    setText(): text() may be the shortened display."""

    path_changed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        # Typed or pasted by the artist (not called by setText).
        self.textEdited.connect(self._on_edited)

    def path(self):
        return self._path

    def set_path(self, path):
        if path == self._path:
            return
        self._path = path
        self._show()
        self.path_changed.emit(path)

    def _on_edited(self, text):
        self._path = text
        self.setToolTip(text)
        self.path_changed.emit(text)

    def _show(self):
        """Full path while editing, shortened otherwise. Signals are blocked:
        changing the display is not a change of path."""
        self.setToolTip(self._path)
        if self.hasFocus():
            shown = self._path
        else:
            # Room for the text: the field minus its inner margins and frame.
            room = self.contentsRect().width() - 12
            shown = self.fontMetrics().elidedText(self._path, QtCore.Qt.ElideMiddle, room)
        if shown != self.text():
            self.blockSignals(True)
            self.setText(shown)
            self.setCursorPosition(0)  # show the start, not the end
            self.blockSignals(False)
            # The italic hint style (set_italic_placeholder) follows textChanged,
            # blocked here: refresh it by hand.
            self.setStyleSheet("" if shown else _ITALIC_STYLE)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._show()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._show()


def set_window_icon(window):
    """Give a window opened by the plugin the dark icon. Without it, a window
    takes the light icon of the panel that opens it."""
    window.setWindowIcon(QtGui.QIcon(_WINDOW_ICON_PATH))


_BULLET = "• "
_BULLET_GAP = 6  # pixels between a bullet and its text


def bold_markup(text):
    """Plain text with **bold** marks -> rich text for a message window
    (show_message(..., rich=True)): special characters escaped, line breaks kept.

    Lines starting with "• " become a two-column table (bullet | text): a
    long line wraps under its text, never under the bullet."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(text, quote=False))
    blocks = []    # html of the text runs and bullet tables, in order
    run = []       # plain lines waiting to be written
    bullets = []   # bullet lines waiting to be written

    def flush_run():
        if run:
            blocks.append("<div>" + "<br>".join(run) + "</div>")
            run.clear()

    def flush_bullets():
        if bullets:
            rows = "".join(
                f'<tr><td valign="top">•</td>'
                f'<td style="padding-left: {_BULLET_GAP}px;">{line}</td></tr>'
                for line in bullets)
            blocks.append(f'<table border="0" cellspacing="0" cellpadding="0">{rows}</table>')
            bullets.clear()

    for line in text.split("\n"):
        if line.startswith(_BULLET):
            flush_run()
            bullets.append(line[len(_BULLET):])
        else:
            flush_bullets()
            run.append(line)
    flush_run()
    flush_bullets()
    return "".join(blocks)


def message_box(parent, text, warning=False, rich=False):
    """Message window of the plugin (title "Atlas Mapper", dark icon).
    rich=True: text is rich text (see bold_markup).
    Buttons can be added before exec(); without any, an OK button is shown."""
    box = QtWidgets.QMessageBox(parent)
    box.setIcon(QtWidgets.QMessageBox.Warning if warning else QtWidgets.QMessageBox.Information)
    box.setWindowTitle(PLUGIN_NAME)
    if rich:
        box.setTextFormat(QtCore.Qt.RichText)
    box.setText(text)
    set_window_icon(box)
    return box


def show_message(parent, text, warning=False, rich=False):
    """Show a message window of the plugin and wait until it is closed."""
    message_box(parent, text, warning, rich).exec()


# Longest line of an explanation (characters), like Painter's info tooltips.
TOOLTIP_LINE_LENGTH = 50
# Short drop-down lists ("DirectX", "3x3"): same fixed width everywhere in
# the panel (CONFIGURATION, "Source normal map format" of MAPPING).
SHORT_FIELD_WIDTH = 120
# Note addressed to the artist ("Please note: ..."), in the yellow of
# Painter's own notes (Project configuration window, measured on a
# screenshot), upright; greyed with the panel while no project is open.
NOTE_STYLE = "QLabel:enabled { color: #ffb91a; }"
# French punctuation kept with its word: never alone at the start or end of a line.
_NO_BREAK = (("« ", "« "), (" »", " »"), (" :", " :"), (" ;", " ;"),
             (" ?", " ?"), (" !", " !"))


def wrap_tooltip(text):
    """Cut an explanation into lines of at most TOOLTIP_LINE_LENGTH characters,
    between words. A line break written in the text ("\\n") starts a new
    paragraph; a bullet line ("  • ...") keeps its indent when it wraps."""
    for space, kept in _NO_BREAK:
        text = text.replace(space, kept)
    lines = []
    for paragraph in text.split("\n"):
        indent = paragraph[:len(paragraph) - len(paragraph.lstrip())]
        bullet = paragraph.lstrip().startswith("• ")
        lines.append(textwrap.fill(
            paragraph, TOOLTIP_LINE_LENGTH, break_on_hyphens=False,  # hyphenated words stay whole
            subsequent_indent=indent + ("   " if bullet else "")) or "")
    return "\n".join(lines)


class InfoIcon(QtWidgets.QWidget):
    """Round "i" icon, like Painter's: hovering it shows the explanation of
    its line at once. Placed at the far right of the line.
    Grey at rest, light while the mouse is over it.

    The explanation is wrapped automatically (wrap_tooltip): write it without
    line breaks inside a sentence, only between paragraphs."""

    SIZE = 14     # pixels, diameter of the circle
    MARGIN = 1    # pixels around the circle: its smoothed edge is not cut
    REST_COLOR = "#808080"
    HOVER_COLOR = _PAINTER_TITLE
    DISABLED_COLOR = "#555555"

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE + 2 * self.MARGIN, self.SIZE + 2 * self.MARGIN)
        # Not a Qt tooltip: Qt waits ~0.7 s of still mouse before showing it,
        # too long (and often missed) on such a small icon. Shown at once instead.
        self._text = wrap_tooltip(text)
        self._hovered = False

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        # Just below the icon; hidden as soon as the mouse leaves it.
        QtWidgets.QToolTip.showText(
            self.mapToGlobal(self.rect().bottomLeft() + QtCore.QPoint(0, 4)),
            self._text, self, self.rect())
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        QtWidgets.QToolTip.hideText()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtCore.Qt.NoPen)
        if not self.isEnabled():
            color = self.DISABLED_COLOR
        else:
            color = self.HOVER_COLOR if self._hovered else self.REST_COLOR
        # Filled circle...
        painter.setBrush(QtGui.QColor(color))
        circle = QtCore.QRectF(self.MARGIN, self.MARGIN, self.SIZE, self.SIZE)
        painter.drawEllipse(circle)
        # ... with the "i" cut out in the panel background color.
        painter.setBrush(QtGui.QColor(_PAINTER_BACKGROUND))
        center = circle.center()
        painter.drawEllipse(center + QtCore.QPointF(0.0, -3.5), 1.3, 1.3)  # dot
        painter.drawRect(QtCore.QRectF(center.x() - 1.0, center.y() - 1.0, 2.0, 5.0))  # stem


class PencilButton(SquareButton):
    """Square "modify" button: pencil going down to the left. Body and tip
    are one filled shape; the cap (top right) is a separate filled block,
    with a small gap between them."""

    CAP_LENGTH = 2.5  # pixels
    GAP = 2  # the 1-pixel outline eats half a pixel on each side: 1 pixel stays visible
    BODY_LENGTH = 6
    TIP_LENGTH = 3.5
    WIDTH = 4

    def __init__(self, parent=None):
        super().__init__("", parent)

    def paintEvent(self, event):
        super().paintEvent(event)  # button frame and background
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = _symbol_pen(self)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)  # slightly rounded tip, like Painter's icons
        painter.setPen(pen)
        painter.setBrush(pen.color())
        # Drawn pointing right around the button center, then turned so the
        # tip points to the bottom left.
        painter.translate(QtCore.QRectF(self.rect()).center())
        painter.rotate(135)
        half_total = (self.CAP_LENGTH + self.GAP + self.BODY_LENGTH + self.TIP_LENGTH) / 2.0
        half_w = self.WIDTH / 2.0
        cap_end = -half_total + self.CAP_LENGTH
        body_start = cap_end + self.GAP
        body_end = body_start + self.BODY_LENGTH
        painter.drawRect(QtCore.QRectF(-half_total, -half_w, self.CAP_LENGTH, self.WIDTH))
        painter.drawPolygon(QtGui.QPolygonF([
            QtCore.QPointF(body_start, -half_w), QtCore.QPointF(body_end, -half_w),
            QtCore.QPointF(half_total, 0.0),
            QtCore.QPointF(body_end, half_w), QtCore.QPointF(body_start, half_w)]))


class _TitleBarIcon(QtWidgets.QWidget):
    """Plugin icon drawn in the color of the dock title text: only the shape
    of the icon (its alpha) is kept, filled with that color.

    Shown only while the title text is: when the dock is grouped in tabs,
    Painter hides the title text (the tab shows the name) and keeps a thin
    bar, where the icon must not stay alone."""

    SIZE = 14         # pixels, about the height of the title capitals
    LEFT_MARGIN = 8   # pixels, like the title text of Painter's own panels

    def __init__(self, icon, title_label, parent=None):
        super().__init__(parent)
        self._icon = icon
        self._title_label = title_label
        self.setFixedSize(self.LEFT_MARGIN + self.SIZE, self.SIZE)
        self.setVisible(not title_label.isHidden())
        title_label.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self._title_label and event.type() in (QtCore.QEvent.Show,
                                                              QtCore.QEvent.Hide):
            self.setVisible(not self._title_label.isHidden())
        return False   # the title label handles the event as usual

    def paintEvent(self, _event):
        # Read at each paint: the title color follows Painter (active, greyed...).
        color = self._title_label.palette().color(self._title_label.foregroundRole())
        ratio = self.devicePixelRatioF()
        tinted = self._icon.pixmap(QtCore.QSize(self.SIZE, self.SIZE), ratio)
        painter = QtGui.QPainter(tinted)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), color)
        painter.end()
        QtGui.QPainter(self).drawPixmap(self.LEFT_MARGIN, 0, tinted)


def add_title_bar_icon(dock, icon):
    """Put the plugin icon left of the title of a Painter dock.

    Painter gives its docks its own title bar (checked in Painter
    2026-10-06): a widget with a horizontal layout holding the title QLabel,
    then the undock and close buttons. The icon is inserted before the title.
    Returns False, without changing anything, if the bar is not built that way.
    """
    bar = dock.titleBarWidget()
    layout = bar.layout() if bar is not None else None
    title = bar.findChild(QtWidgets.QLabel) if bar is not None else None
    if not isinstance(layout, QtWidgets.QHBoxLayout) or title is None or icon.isNull():
        return False
    layout.insertWidget(0, _TitleBarIcon(icon, title, bar), 0, QtCore.Qt.AlignVCenter)
    return True


class Separator(QtWidgets.QWidget):
    """Horizontal line exactly 1 screen pixel high, as in native Painter panels.

    A plain 1-pixel widget would be drawn thicker when Windows display
    scaling is above 100 %, so the line is painted at 1 / scaling instead.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        height = 1.0 / self.devicePixelRatioF()
        painter.fillRect(QtCore.QRectF(0, 0, self.width(), height),
                         QtGui.QColor(_PAINTER_SEPARATOR))


class FallbackScroll(QtWidgets.QScrollArea):
    """Vertical scroll that only shows when its content does not fit: at a
    normal height nothing changes; in a too short window the content scrolls
    instead of being cut. Never scrolls sideways.

    A plain scroll area does not pass its content's width on to the window
    (the end of the lines would be cut): the content's minimum width is asked
    each time its layout changes, plus the bar while it shows."""

    MIN_HEIGHT = 80  # pixels: the window can shrink down to this

    def __init__(self, content, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)  # content as tall as the visible area when it fits
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        # Transparent: the panel background shows through. Scoped by
        # objectName so the style does not leak into the content.
        self.setObjectName("FallbackScroll")
        self.viewport().setObjectName("FallbackScrollViewport")
        content.setObjectName("FallbackScrollContent")
        self.setStyleSheet("#FallbackScroll, #FallbackScrollViewport, #FallbackScrollContent"
                           " { background: transparent; }")
        self.setWidget(content)
        content.installEventFilter(self)
        # The bar appears / disappears: its width is added / removed.
        self.verticalScrollBar().rangeChanged.connect(lambda *_: self.updateGeometry())

    def eventFilter(self, watched, event):
        if watched is self.widget() and event.type() == QtCore.QEvent.LayoutRequest:
            self.updateGeometry()  # the window asks minimumSizeHint again
        return super().eventFilter(watched, event)

    def minimumSizeHint(self):
        width = self.widget().minimumSizeHint().width()
        if self.verticalScrollBar().maximum() > 0:  # the bar shows
            width += self.verticalScrollBar().sizeHint().width()
        return QtCore.QSize(width, self.MIN_HEIGHT)

    def sizeHint(self):
        return QtCore.QSize(self.minimumSizeHint().width(),
                            self.widget().sizeHint().height())


class ChevronButton(QtWidgets.QToolButton):
    """Frameless fold/unfold button with a chevron like Painter's drop-down arrow.

    Checkable: chevron pointing down when closed (like a drop-down list),
    pointing up when open. sideways=True: pointing right when closed and down
    when open, like Painter's foldable groups ("Depth of field").
    """

    CHEVRON_WIDTH = 9   # pixels
    CHEVRON_HEIGHT = 5  # pixels
    BUTTON_SIZE = 20    # pixels, clickable area

    def __init__(self, parent=None, sideways=False):
        super().__init__(parent)
        self._sideways = sideways
        self.setCheckable(True)
        self.setAutoRaise(True)
        self.setFixedSize(self.BUTTON_SIZE, self.BUTTON_SIZE)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(_symbol_pen(self))
        half_w = self.CHEVRON_WIDTH / 2.0
        half_h = self.CHEVRON_HEIGHT / 2.0
        center = QtCore.QRectF(self.rect()).center()
        if self._sideways:
            # Drawn pointing down; turned to point right while closed.
            sign = 1.0
            if not self.isChecked():
                painter.translate(center)
                painter.rotate(-90)
                painter.translate(-center)
        else:
            # Open: the tip points up (sign flips the vertical direction).
            sign = -1.0 if self.isChecked() else 1.0
        tip = center + QtCore.QPointF(0.0, sign * half_h)
        painter.drawLine(center + QtCore.QPointF(-half_w, -sign * half_h), tip)
        painter.drawLine(tip, center + QtCore.QPointF(half_w, -sign * half_h))


class _NoFocusLineDelegate(QtWidgets.QStyledItemDelegate):
    """Draws the entries of a drop-down list with its original drawer, but
    without the "has focus" state: the native style draws the dotted focus
    line straight from that state, which a style sheet (outline: none)
    cannot reach. The hover rectangle stays."""

    def __init__(self, original, parent):
        super().__init__(parent)
        self._original = original  # Qt's own drawer of the list entries

    def paint(self, painter, option, index):
        option = QtWidgets.QStyleOptionViewItem(option)
        option.state &= ~QtWidgets.QStyle.StateFlag.State_HasFocus
        self._original.paint(painter, option, index)

    def sizeHint(self, option, index):
        return self._original.sizeHint(option, index)


class ComboBox(QtWidgets.QComboBox):
    """Drop-down list of the plugin: no dotted focus line on its entries.
    General rule: every drop-down list of Atlas Mapper uses this class
    instead of QtWidgets.QComboBox."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(_NoFocusLineDelegate(self.itemDelegate(), self))


class RefreshingComboBox(ComboBox):
    """Drop-down list that announces when it is about to open, so its entries
    can be refreshed first (e.g. preset files added while Painter runs)."""

    about_to_open = QtCore.Signal()

    def showPopup(self):
        self.about_to_open.emit()  # handled right away, before the list opens
        super().showPopup()
