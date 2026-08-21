"""Navigation icons — drawn in code, not shipped as files.

Two reasons for not using icon files: it's one less asset that can go
missing from packaging, and the stroke color can change instantly with
the theme (PNG icons would become unreadable in dark mode).

All of them are drawn on a 24x24 grid with the same stroke width; when
different widths sit side by side, some icons stand out and the eye
misreads the ordering.
"""

from ..qt import Qt, QtCore, QtGui

GRID = 24.0
STROKE = 1.7


def _pen(color, width=STROKE):
    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


# --- individual drawings ----------------------------------------------------
def _home(p):
    path = QtGui.QPainterPath()
    path.moveTo(3.5, 10.5)
    path.lineTo(12, 3.5)
    path.lineTo(20.5, 10.5)
    p.drawPath(path)
    p.drawRect(QtCore.QRectF(5.5, 10.5, 13, 10))
    p.drawRect(QtCore.QRectF(9.75, 14.5, 4.5, 6))


def _devices(p):
    # measurement instrument: body + screen + stand
    p.drawRoundedRect(QtCore.QRectF(3.5, 5.5, 17, 13), 2.5, 2.5)
    p.drawRoundedRect(QtCore.QRectF(6.5, 8.5, 11, 4.5), 1.0, 1.0)
    p.drawLine(QtCore.QPointF(7.5, 16.0), QtCore.QPointF(9.0, 16.0))
    p.drawLine(QtCore.QPointF(11.25, 16.0), QtCore.QPointF(12.75, 16.0))
    p.drawLine(QtCore.QPointF(15.0, 16.0), QtCore.QPointF(16.5, 16.0))


def _new(p):
    p.drawEllipse(QtCore.QRectF(3.5, 3.5, 17, 17))
    p.drawLine(QtCore.QPointF(12.0, 8.0), QtCore.QPointF(12.0, 16.0))
    p.drawLine(QtCore.QPointF(8.0, 12.0), QtCore.QPointF(16.0, 12.0))


def _acquire(p):
    # oscilloscope waveform
    path = QtGui.QPainterPath()
    path.moveTo(3.0, 15.0)
    path.lineTo(6.5, 15.0)
    path.lineTo(8.5, 7.0)
    path.lineTo(11.5, 18.0)
    path.lineTo(14.0, 11.0)
    path.lineTo(16.0, 15.0)
    path.lineTo(21.0, 15.0)
    p.drawPath(path)


def _wave(p):
    # trigger-driven capture: pulse + vertical trigger line
    path = QtGui.QPainterPath()
    path.moveTo(3.0, 16.5)
    path.lineTo(8.0, 16.5)
    path.lineTo(8.0, 7.5)
    path.lineTo(13.0, 7.5)
    path.lineTo(13.0, 16.5)
    path.lineTo(21.0, 16.5)
    p.drawPath(path)
    pen = p.pen()
    dashed = QtGui.QPen(pen)
    dashed.setStyle(Qt.DotLine)
    p.setPen(dashed)
    p.drawLine(QtCore.QPointF(8.0, 3.5), QtCore.QPointF(8.0, 20.5))
    p.setPen(pen)


def _history(p):
    p.drawEllipse(QtCore.QRectF(3.75, 3.75, 16.5, 16.5))
    p.drawLine(QtCore.QPointF(12.0, 7.5), QtCore.QPointF(12.0, 12.0))
    p.drawLine(QtCore.QPointF(12.0, 12.0), QtCore.QPointF(15.5, 14.0))


def _admin(p):
    # shield: authorization / oversight
    path = QtGui.QPainterPath()
    path.moveTo(12.0, 3.0)
    path.lineTo(20.0, 6.2)
    path.lineTo(20.0, 12.0)
    path.cubicTo(20.0, 17.0, 16.5, 20.0, 12.0, 21.2)
    path.cubicTo(7.5, 20.0, 4.0, 17.0, 4.0, 12.0)
    path.lineTo(4.0, 6.2)
    path.closeSubpath()
    p.drawPath(path)
    check = QtGui.QPainterPath()
    check.moveTo(8.6, 11.8)
    check.lineTo(11.2, 14.4)
    check.lineTo(15.6, 9.2)
    p.drawPath(check)


def _approve(p):
    # document + checkmark: approval queue
    path = QtGui.QPainterPath()
    path.moveTo(6.0, 3.2)
    path.lineTo(14.2, 3.2)
    path.lineTo(18.2, 7.2)
    path.lineTo(18.2, 20.8)
    path.lineTo(6.0, 20.8)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QtCore.QPointF(14.2, 3.2), QtCore.QPointF(14.2, 7.2))
    p.drawLine(QtCore.QPointF(14.2, 7.2), QtCore.QPointF(18.2, 7.2))
    check = QtGui.QPainterPath()
    check.moveTo(8.6, 14.2)
    check.lineTo(11.0, 16.6)
    check.lineTo(15.6, 10.8)
    p.drawPath(check)


def _theme(p):
    # half-filled circle: light / dark theme
    p.drawEllipse(QtCore.QRectF(4.0, 4.0, 16.0, 16.0))
    wedge = QtGui.QPainterPath()
    wedge.moveTo(12.0, 4.0)
    wedge.arcTo(QtCore.QRectF(4.0, 4.0, 16.0, 16.0), 90.0, -180.0)
    wedge.closeSubpath()
    p.fillPath(wedge, QtGui.QBrush(p.pen().color()))


def _logout(p):
    path = QtGui.QPainterPath()
    path.moveTo(14.0, 4.5)
    path.lineTo(6.0, 4.5)
    path.lineTo(6.0, 19.5)
    path.lineTo(14.0, 19.5)
    p.drawPath(path)
    p.drawLine(QtCore.QPointF(11.0, 12.0), QtCore.QPointF(20.0, 12.0))
    arrow = QtGui.QPainterPath()
    arrow.moveTo(17.0, 8.8)
    arrow.lineTo(20.5, 12.0)
    arrow.lineTo(17.0, 15.2)
    p.drawPath(arrow)


DRAWINGS = {
    "home": _home,
    "devices": _devices,
    "new": _new,
    "acquire": _acquire,
    "wave": _wave,
    "history": _history,
    "approve": _approve,
    "admin": _admin,
    "theme": _theme,
    "logout": _logout,
}


def pixmap(name, color, size=20, dpr=None):
    draw = DRAWINGS.get(name)
    if draw is None:
        return QtGui.QPixmap()
    # Drawn larger by the device pixel ratio and that ratio reported to
    # the pixmap, so icons don't blur on high-DPI screens.
    if dpr is None:
        app = QtGui.QGuiApplication.instance()
        dpr = app.devicePixelRatio() if app is not None else 1.0
    dpr = max(1.0, float(dpr))
    pm = QtGui.QPixmap(int(round(size * dpr)), int(round(size * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)

    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    scale = size / GRID
    p.scale(scale * dpr, scale * dpr)
    # Pen width is in grid units; scaling grows it proportionally with size.
    p.setPen(_pen(color, STROKE))
    p.setBrush(Qt.NoBrush)
    draw(p)
    p.end()
    return pm


def icon(name, color, size=20):
    """Single-color QIcon. Called separately for active/inactive states."""
    return QtGui.QIcon(pixmap(name, color, size))


def dual_icon(name, normal_color, active_color, size=20):
    """Icon that uses a different color in the normal vs. selected state."""
    ic = QtGui.QIcon()
    ic.addPixmap(pixmap(name, normal_color, size), QtGui.QIcon.Normal, QtGui.QIcon.Off)
    ic.addPixmap(pixmap(name, active_color, size), QtGui.QIcon.Normal, QtGui.QIcon.On)
    ic.addPixmap(pixmap(name, active_color, size), QtGui.QIcon.Selected, QtGui.QIcon.Off)
    ic.addPixmap(pixmap(name, active_color, size), QtGui.QIcon.Active, QtGui.QIcon.Off)
    return ic
