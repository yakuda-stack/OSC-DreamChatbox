"""
ui_main.py – Design & reusable UI widgets for OSC-DreamChatbox
(stylesheet, toggle switch, clickable labels, debug console)
"""

import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QColor, QBrush
from PyQt6.QtWidgets import (QCheckBox, QLabel, QMainWindow, QPlainTextEdit,
                             QWidget, QFrame, QGridLayout, QPushButton)


# ----------------------------------------------------------------------------
# Toggle switch (like in the mockup)
# ----------------------------------------------------------------------------
class ToggleSwitch(QCheckBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(52, 28)

    def hitButton(self, pos):
        # Make the whole widget clickable (default QCheckBox only reacts
        # to a small area)
        return self.rect().contains(pos)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        if self.isChecked():
            p.setBrush(QBrush(QColor("#5b8dc9")))
        else:
            p.setBrush(QBrush(QColor("#3a3f4a")))
        p.drawRoundedRect(0, 0, 52, 28, 14, 14)
        p.setBrush(QBrush(QColor("#e8ecf2")))
        x = 26 if self.isChecked() else 2
        p.drawEllipse(x, 2, 24, 24)
        p.end()


class ToggleLabel(QLabel):
    """Label next to a toggle – clicking the text toggles it too."""
    def __init__(self, text, toggle):
        super().__init__(text)
        self._toggle = toggle
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, ev):
        self._toggle.toggle()



class DragHandle(QWidget):
    """3x3 dot grip – drag it to reorder app cards."""
    def __init__(self, on_move, on_end):
        super().__init__()
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to reorder")
        self._on_move = on_move
        self._on_end = on_end

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#5a6270")))
        for ix in range(3):
            for iy in range(3):
                p.drawEllipse(3 + ix * 6, 3 + iy * 6, 3, 3)
        p.end()

    def mousePressEvent(self, e):
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        self._on_move(e.globalPosition().toPoint())

    def mouseReleaseEvent(self, e):
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._on_end()


# ----------------------------------------------------------------------------
# Debug console (separate window)
# ----------------------------------------------------------------------------
class DebugConsole(QMainWindow):
    def __init__(self, app_name):
        super().__init__()
        self.setWindowTitle(f"{app_name} – Debug Console")
        self.resize(680, 380)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(500)  # keep memory usage flat
        self.text.setStyleSheet(
            "QPlainTextEdit { background: #0d0f13; color: #9fd49f;"
            " font-family: monospace; font-size: 12px; border: none; }"
        )
        self.setCentralWidget(self.text)

    def log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.text.appendPlainText(f"[{ts}] {msg}")
        sb = self.text.verticalScrollBar()
        sb.setValue(sb.maximum())


# ----------------------------------------------------------------------------
# Stylesheet (dark design like the mockup)
# ----------------------------------------------------------------------------
STYLE = """
QMainWindow { background: #14161c; }
QWidget { color: #d7dbe2; font-size: 14px; background: transparent; }
QStackedWidget, QStackedWidget > QWidget { background: #14161c; }
#sidebar { background: #0f1116; }
#rightpanel { background: #101218; }
#navbtn {
    background: transparent; border: none; border-radius: 8px;
    padding: 10px 14px; text-align: left; color: #aeb4bf; font-size: 15px;
}
#navbtn:checked { background: #2a2f3a; color: #ffffff; }
#navbtn:hover { background: #232833; }
#pagetitle { font-size: 26px; font-weight: 700; color: #ffffff; }
#card { background: #191c24; border-radius: 12px; }
#cardtitle { font-size: 19px; font-weight: 600; color: #ffffff; }
#innerbox { background: #14161c; border: 1px solid #2c313c; border-radius: 10px; }
#expander {
    background: transparent; border: none; text-align: left;
    color: #d7dbe2; font-size: 15px; padding: 4px 0;
}
#previewbox { background: #14161c; border: 1px solid #2c313c; border-radius: 10px; }
#previewtitle { font-size: 15px; color: #e5e9ef; }
#hline { color: #2c313c; background: #2c313c; max-height: 1px; border: none; }
#dim { color: #7a8290; font-size: 12px; }
QLineEdit, QSpinBox {
    background: #14161c; border: 1px solid #333947; border-radius: 8px;
    padding: 8px 10px; color: #e5e9ef; selection-background-color: #5b8dc9;
}
QLineEdit:focus, QSpinBox:focus { border-color: #5b8dc9; }
QLineEdit:hover, QSpinBox:hover { border-color: #444c5c; }
QSpinBox::up-button, QSpinBox::down-button {
    width: 16px; background: #232833; border: none; border-radius: 3px; margin: 1px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #333947; }
#smallspin { padding: 2px 4px; font-size: 13px; }
#iconbtn {
    background: #232833; border: 1px solid #333947; border-radius: 8px;
    font-size: 15px; padding: 0;
}
#iconbtn:hover { background: #2f3542; border-color: #5b8dc9; }
#sendbtn {
    background: #5b8dc9; color: #ffffff; border: none; border-radius: 8px;
    padding: 4px 16px; font-weight: 600;
}
#sendbtn:hover { background: #6d9cd4; }
#sendbtn:pressed { background: #4c7cb5; }
#linkbtn {
    background: #232833; color: #e5e9ef; border: 1px solid #333947;
    border-radius: 8px; padding: 4px 16px; font-weight: 600;
}
#linkbtn:hover { background: #2f3542; border-color: #5b8dc9; }
#recbtn {
    background: #232833; color: #e5e9ef; border: 1px solid #333947;
    border-radius: 10px; padding: 6px 20px; font-weight: 600; font-size: 15px;
}
#recbtn:hover { border-color: #c95b5b; }
#recbtn:checked { background: #c95b5b; border-color: #c95b5b; color: #ffffff; }
QComboBox {
    background: #14161c; border: 1px solid #333947; border-radius: 8px;
    padding: 6px 10px; color: #e5e9ef;
}
QComboBox:hover { border-color: #444c5c; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #191c24; color: #e5e9ef; border: 1px solid #333947;
    selection-background-color: #2a2f3a;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border: 1px solid #444c5c;
    border-radius: 4px; background: #14161c;
}
QCheckBox::indicator:checked { background: #5b8dc9; border-color: #5b8dc9; }
QCheckBox::indicator:hover { border-color: #5b8dc9; }
QPlainTextEdit { background: #0d0f13; }
QScrollArea { border: none; background: #14161c; }
QScrollBar:vertical {
    background: #14161c; width: 10px; margin: 0; border: none;
}
QScrollBar::handle:vertical {
    background: #2c313c; border-radius: 5px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #3a4150; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
"""

# ----------------------------------------------------------------------------
# Emoji/icon picker popup (for VRChat-friendly icons in text fields)
# ----------------------------------------------------------------------------
EMOJIS = [
    "\U0001F525", "\U0001F3B5", "\U0001F3B6", "\U0001F3A7", "\U0001F3AE", "\U0001F47E",
    "\U0001F480", "\u2620\uFE0F", "\u2764\uFE0F", "\U0001F499", "\U0001F49C", "\U0001F5A4",
    "\u2B50", "\u2728", "\u26A1", "\U0001F319", "\u2600\uFE0F", "\U0001F308",
    "\U0001F355", "\U0001F37A", "\U0001F964", "\U0001F634", "\U0001F60E", "\U0001F919",
    "\U0001F44B", "\U0001F4A4", "\u2757", "\u2753", "\U0001F3A4", "\U0001F4AC",
]


class EmojiPopup(QFrame):
    """Small popup grid with icons; picking one inserts it into the
    target QLineEdit at the cursor position."""
    def __init__(self):
        super().__init__(None, Qt.WindowType.Popup)
        self.setStyleSheet(
            "QFrame { background: #191c24; border: 1px solid #333947;"
            " border-radius: 10px; }"
            "QPushButton { background: transparent; border: none;"
            " font-size: 17px; border-radius: 6px; }"
            "QPushButton:hover { background: #2a2f3a; }")
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(2)
        self._target = None
        for i, em in enumerate(EMOJIS):
            b = QPushButton(em)
            b.setFixedSize(34, 34)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, e=em: self._pick(e))
            grid.addWidget(b, i // 6, i % 6)

    def open_for(self, line_edit, anchor):
        self._target = line_edit
        self.adjustSize()
        self.move(anchor.mapToGlobal(anchor.rect().bottomRight()) - self.rect().topRight())
        self.show()

    def _pick(self, emoji):
        if self._target is not None:
            self._target.insert(emoji)
        self.close()
