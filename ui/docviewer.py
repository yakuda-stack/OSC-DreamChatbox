"""
ui/docviewer.py – Changelog and Highlights as a readable window.

Both files are plain Markdown in the project root. Qt renders Markdown
itself (QTextBrowser.setMarkdown), so there is no extra dependency and
the files stay exactly what GitHub shows.

Where the files are looked for, first hit wins:
  * next to the app (core.osinfo.resource_root): from source, AppImage,
    AUR package and the Windows build all put them there
  * /usr/share/doc/osc-dreamchatbox: where the AUR package has always
    installed CHANGELOG.md, so an older package still finds it
If neither exists, the file opens on GitHub instead of showing an error.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QTextCursor
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout)

from core.constants import GITHUB_REPO
from core.osinfo import resource_root

CHANGELOG_FILE = "CHANGELOG.md"
HIGHLIGHTS_FILE = "HIGHLIGHTS.md"

DOC_DIRS = (resource_root(), Path("/usr/share/doc/osc-dreamchatbox"))


def find_doc(name):
    """Path of a shipped document, or None."""
    for folder in DOC_DIRS:
        path = folder / name
        if path.is_file():
            return path
    return None


def doc_url(name):
    return f"https://github.com/{GITHUB_REPO}/blob/main/{name}"


class DocDialog(QDialog):
    """One Markdown file in a scrollable, read-only window."""

    def __init__(self, parent, title, text, name):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 640)
        self.name = name

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 12)
        lay.setSpacing(10)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setStyleSheet(
            "QTextBrowser { background: #191c24; color: #e6e9ef;"
            " border: 1px solid #333947; border-radius: 8px;"
            " padding: 10px 14px; }")
        self.view.setMarkdown(text)
        self._space_headings()
        lay.addWidget(self.view)

        row = QHBoxLayout()
        row.setSpacing(8)
        if name == HIGHLIGHTS_FILE:
            # the short version should always lead to the long one
            full = self._button("\U0001F4DC  Full changelog", "linkbtn")
            full.clicked.connect(self._open_changelog)
            row.addWidget(full)
        gh = self._button("\U0001F310  On GitHub", "linkbtn")
        gh.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(doc_url(self.name))))
        row.addWidget(gh)
        row.addStretch()
        close = self._button("Close", "sendbtn")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

    def _space_headings(self):
        """Qt's Markdown puts headings right on top of the list before
        them. A bit of air above every heading makes each release its
        own block."""
        block = self.view.document().begin()
        while block.isValid():
            fmt = block.blockFormat()
            level = fmt.headingLevel()
            if level:
                fmt.setTopMargin(20 if level <= 2 else 12)
                fmt.setBottomMargin(6)
                QTextCursor(block).setBlockFormat(fmt)
            block = block.next()

    @staticmethod
    def _button(label, object_name):
        b = QPushButton(label)
        b.setObjectName(object_name)
        b.setFixedHeight(32)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        return b

    def _open_changelog(self):
        parent = self.parentWidget()
        self.accept()
        show_doc(parent, "Changelog", CHANGELOG_FILE)


def show_doc(parent, title, name):
    """Open `name` in a DocDialog, or on GitHub if it was not shipped."""
    path = find_doc(name)
    if path is None:
        QDesktopServices.openUrl(QUrl(doc_url(name)))
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        QDesktopServices.openUrl(QUrl(doc_url(name)))
        return
    DocDialog(parent, title, text, name).exec()
