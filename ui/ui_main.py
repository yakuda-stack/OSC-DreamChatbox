"""
ui_main.py – Design & reusable UI widgets for OSC-DreamChatbox
(stylesheet, toggle switch, clickable labels, debug console)
"""

import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QColor, QBrush
from PyQt6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit,
                             QMainWindow, QPlainTextEdit,
                             QScrollArea, QStackedWidget, QVBoxLayout,
                             QWidget, QFrame, QGridLayout, QPushButton)

from core.emojis import (EMOJI_CATEGORIES, EMOJIS, cost as emoji_cost,
                         search as emoji_search)


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
            " font-family: Consolas, monospace; font-size: 12px; border: none; }"
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
/* the multi-line AIO template fields - same look as a QLineEdit, with
   room at the bottom for the drag-to-resize grip (ui/aio_edit.py) */
#aioedit {
    background: #14161c; border: 1px solid #333947; border-radius: 8px;
    padding: 6px 8px 10px 8px; color: #e5e9ef;
    selection-background-color: #5b8dc9;
}
#aioedit:focus { border-color: #5b8dc9; }
#aioedit:hover { border-color: #444c5c; }
/* Normal / Advanced switch at the top of the All in one card */
#modebtn {
    background: #232833; border: 1px solid #333947; border-radius: 8px;
    padding: 6px 16px; color: #aeb4bf; font-weight: 600;
}
#modebtn:hover { border-color: #5b8dc9; }
#modebtn:checked {
    background: #5b8dc9; border-color: #5b8dc9; color: #ffffff;
}
/* AIO slot tabs above the node canvas (ui/pages/advanced_page.py).
   Browser-tab shape: rounded on top, flat where they meet the canvas. */
#slottab {
    background: transparent; border: 1px solid transparent;
    border-bottom: 2px solid #333947; border-radius: 8px;
    border-bottom-left-radius: 0; border-bottom-right-radius: 0;
    padding: 6px 8px; color: #7a8290; font-weight: 600;
}
/* collapse button inside a side panel's header row */
#panelhide {
    background: #232833; border: 1px solid #333947; border-radius: 5px;
    color: #aeb4bf; font-size: 12px; font-weight: 700; padding: 0;
}
#panelhide:hover { background: #2f3542; color: #ffffff;
                   border-color: #5b8dc9; }
/* the folder / running-programs buttons on a picker field */
#pickbtn {
    background: #232833; border: 1px solid #333947; border-radius: 5px;
    color: #aeb4bf; font-size: 12px; padding: 0;
}
#pickbtn:hover { background: #2f3542; color: #ffffff;
                 border-color: #5b8dc9; }
/* the record button on a hotkey field */
#recordbtn {
    background: #232833; border: 1px solid #333947; border-radius: 5px;
    color: #aeb4bf; font-size: 12px; padding: 0;
}
#recordbtn:hover { border-color: #5b8dc9; color: #ffffff; }
#recordbtn:checked {
    background: #c95b5b; border-color: #c95b5b; color: #ffffff;
}
/* the tab that stays behind once a side panel is collapsed */
#panelshow {
    background: #232833; border: 1px solid #5b8dc9; border-radius: 6px;
    color: #e5e9ef; font-size: 13px; font-weight: 700; padding: 0;
}
#panelshow:hover { background: #5b8dc9; color: #ffffff; }
#slottab:hover { color: #e5e9ef; border-bottom-color: #444c5c; }
#slottab:checked {
    background: #232833; border-color: #333947;
    border-bottom: 2px solid #5b8dc9; color: #ffffff;
}
#slottab:disabled { color: #3a3f4a; border-bottom-color: #2c313c; }
/* node editor (ui/nodegraph.py). The canvas paints its own background
   and items - only the frame around it is styled here. */
#nodecanvas {
    background: #14161c; border: 1px solid #333947; border-radius: 10px;
}
#nodepalette {
    background: #14161c; border: 1px solid #333947; border-radius: 8px;
    padding: 2px; color: #d7dbe2;
}
#nodepalette::item {
    background: #232833; border: 1px solid #333947; border-radius: 6px;
    padding: 4px 8px;
}
#nodepalette::item:hover { border-color: #5b8dc9; }
#nodepalette::item:selected { background: #2f3542; color: #ffffff; }
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
class EmojiPopup(QFrame):
    """Category picker; choosing an icon inserts it into the target
    QLineEdit at the cursor position.

    The palette lives in core/emojis.py and is around a thousand entries,
    which is why this shows one category at a time instead of one long
    grid: a thousand QPushButtons built up front would be paid for on
    every start by everyone, including the people who never open the
    picker. Each category builds its buttons the first time it is
    selected and keeps them afterwards.
    """
    COLUMNS = 10
    CELL = 32
    MAX_RESULTS = 120

    def __init__(self):
        super().__init__(None, Qt.WindowType.Popup)
        self.setStyleSheet(
            "QFrame { background: #191c24; border: 1px solid #333947;"
            " border-radius: 10px; }"
            "QPushButton { background: transparent; border: none;"
            " font-size: 17px; border-radius: 6px; }"
            "QPushButton:hover { background: #2a2f3a; }"
            "QPushButton:checked { background: #2f3644; }"
            "QLabel { color: #6f7684; border: none; }"
            "QLineEdit { background: #14161c; border: 1px solid #333947;"
            " border-radius: 6px; color: #d7dae0; padding: 4px 8px; }"
            "QLineEdit:focus { border-color: #5b8dc9; }"
            "QScrollArea { border: none; background: transparent; }")
        self._target = None
        self._current = 0
        self._pages = {}        # index -> (widget, built?)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 6)
        outer.setSpacing(6)

        # ---- search --------------------------------------------------
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search  \u2013  fire, heart, cat \u2026")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        outer.addWidget(self._search)

        # ---- category tabs -------------------------------------------
        tabs = QHBoxLayout()
        tabs.setSpacing(1)
        self._tab_buttons = []
        for i, (name, icon, _block) in enumerate(EMOJI_CATEGORIES):
            b = QPushButton(icon)
            b.setCheckable(True)
            b.setFixedSize(30, 28)
            b.setToolTip(name)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, idx=i: self._on_tab(idx))
            tabs.addWidget(b)
            self._tab_buttons.append(b)
        outer.addLayout(tabs)

        # ---- the grid of the selected category -----------------------
        self._stack = QStackedWidget()
        self._stack.setFixedSize(self.COLUMNS * self.CELL + 24, 268)
        for i in range(len(EMOJI_CATEGORIES)):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            page = QWidget()
            grid = QGridLayout(page)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(1)
            grid.setAlignment(Qt.AlignmentFlag.AlignTop)
            scroll.setWidget(page)
            self._stack.addWidget(scroll)
            self._pages[i] = [page, grid, False]

        # the results page. Its buttons are created once and then only
        # relabelled - rebuilding a grid on every keystroke is the kind
        # of thing that makes a search box feel broken.
        self._result_scroll = QScrollArea()
        self._result_scroll.setWidgetResizable(True)
        self._result_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        result_page = QWidget()
        self._result_grid = QGridLayout(result_page)
        self._result_grid.setContentsMargins(0, 0, 0, 0)
        self._result_grid.setSpacing(1)
        self._result_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._result_scroll.setWidget(result_page)
        self._result_buttons = []
        self.RESULTS_INDEX = self._stack.addWidget(self._result_scroll)
        outer.addWidget(self._stack)

        self._hint = QLabel("")
        outer.addWidget(self._hint)
        self.show_category(0)

    # ------------------------------------------------------------------
    def show_category(self, index):
        self._current = index
        name, _icon, block = EMOJI_CATEGORIES[index]
        page, grid, built = self._pages[index]
        if not built:
            for i, em in enumerate(block):
                b = QPushButton(em)
                b.setFixedSize(self.CELL, self.CELL)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                # the 144 characters are the scarce thing here, and an
                # entry carrying a variation selector quietly costs two
                b.setToolTip("costs 2 characters" if emoji_cost(em) > 1
                             else "costs 1 character")
                b.clicked.connect(lambda _, e=em: self._pick(e))
                grid.addWidget(b, i // self.COLUMNS, i % self.COLUMNS)
            self._pages[index][2] = True
        self._stack.setCurrentIndex(index)
        for i, b in enumerate(self._tab_buttons):
            b.setChecked(i == index)
        self._hint.setText(f"{name}  \u2013  {len(block)} icons")

    def _on_tab(self, index):
        # picking a category is also how you leave a search
        if self._search.text():
            self._search.blockSignals(True)
            self._search.clear()
            self._search.blockSignals(False)
        self.show_category(index)

    def _on_search(self, text):
        """Empty box means "go back to where I was"; otherwise the
        results page takes over the stack."""
        text = (text or "").strip()
        if not text:
            self.show_category(self._current)
            return
        hits = emoji_search(text, limit=self.MAX_RESULTS)
        while len(self._result_buttons) < len(hits):
            b = QPushButton("")
            b.setFixedSize(self.CELL, self.CELL)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, btn=b: self._pick(btn.text()))
            i = len(self._result_buttons)
            self._result_grid.addWidget(b, i // self.COLUMNS, i % self.COLUMNS)
            self._result_buttons.append(b)
        for i, b in enumerate(self._result_buttons):
            if i < len(hits):
                b.setText(hits[i])
                b.setToolTip("costs 2 characters" if emoji_cost(hits[i]) > 1
                             else "costs 1 character")
                b.show()
            else:
                b.hide()
        for b in self._tab_buttons:
            b.setChecked(False)
        self._stack.setCurrentIndex(self.RESULTS_INDEX)
        self._hint.setText(
            f"{len(hits)} found" if hits
            else "nothing found \u2013 try an English word, e.g. fire, heart")

    def open_for(self, line_edit, anchor):
        self._target = line_edit
        if self._search.text():
            self._search.clear()      # also restores the category page
        self._search.setFocus()
        self.adjustSize()
        self.move(anchor.mapToGlobal(anchor.rect().bottomRight()) - self.rect().topRight())
        self.show()

    def _pick(self, emoji):
        if self._target is not None:
            self._target.insert(emoji)
        self.close()
