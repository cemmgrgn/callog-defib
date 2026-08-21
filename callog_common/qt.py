"""Qt binding layer.

PySide6 (Qt 6, LGPL). The Qt 5 fallback was removed because Windows 7
support was dropped — Qt 6 only runs on Windows 10 and above.
"""

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Signal, Slot

Qt = QtCore.Qt
QT_BINDING = "PySide6"

__all__ = ["QtCore", "QtGui", "QtWidgets", "Signal", "Slot", "Qt", "QT_BINDING"]
