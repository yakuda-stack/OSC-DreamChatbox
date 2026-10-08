"""
ui/osc_param_log.py – live log of the avatar parameters (v1.6.6)

Options -> OSC -> "Parameter log" opens this as a separate window. It
is not modal: the app keeps working while it is open, so you can flip
a toggle on your avatar and watch which parameter changes.

Two views of the same listener (core/oscin.py):
  * the table   - every parameter seen so far, its type and value now
  * the log     - what changed, newest on top, with the time

The listener only keeps the latest value per parameter, so the log is
built here by comparing two snapshots. Polled four times a second and
only when the listener's revision counter moved.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout)

from core.oscin import format_value, value_type

#: lines kept in the change log
MAX_LOG_LINES = 500
#: show raw OSC addresses outside /avatar/parameters too
_ALL_ADDR_TIP = ("Also list everything else that arrives on the port, "
                 "not only /avatar/parameters/* (e.g. /tracking/...).")


def diff_snapshots(old: dict, new: dict):
    """[(name, value)] for every entry that is new or changed in `new`,
    sorted by name. Pure function - unit-tested."""
    out = []
    for name in sorted(new):
        if name not in old or old[name] != new[name]:
            out.append((name, new[name]))
    return out


def _shown(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    text = format_value(value)
    return text if text != "" else "∅"


class OscParamLogDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("OSC avatar parameter log")
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(640, 560)
        self._rev = None
        self._last = {}
        self._paused = False
        self._all = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        self.status = QLabel("")
        self.status.setObjectName("dim")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        bar = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter … (e.g. Mute, Gesture)")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(lambda _t: self._refill(force=True))
        bar.addWidget(self.filter, 1)
        self.all_btn = QPushButton("All addresses")
        self.all_btn.setCheckable(True)
        self.all_btn.setToolTip(_ALL_ADDR_TIP)
        self.all_btn.toggled.connect(self._on_all)
        bar.addWidget(self.all_btn)
        self.pause_btn = QPushButton("⏸  Pause")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._on_pause)
        bar.addWidget(self.pause_btn)
        clear = QPushButton("\U0001F5D1  Clear log")
        clear.clicked.connect(self._on_clear)
        bar.addWidget(clear)
        lay.addLayout(bar)

        split = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Parameter", "Type", "Value"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        split.addWidget(self.table)

        self.log_list = QListWidget()
        self.log_list.setToolTip("Changes, newest on top")
        split.addWidget(self.log_list)
        split.setSizes([330, 170])
        lay.addWidget(split, 1)

        foot = QHBoxLayout()
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("dim")
        foot.addWidget(self.count_lbl, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        foot.addWidget(close)
        lay.addLayout(foot)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(250)
        self._poll()

    # ---------------------------------------------------------------
    def _listener(self):
        return getattr(self.win, "osc_in", None)

    def _snapshot(self):
        lst = self._listener()
        if lst is None:
            return {}
        return lst.address_snapshot() if self._all else lst.snapshot()

    def _on_all(self, on):
        self._all = bool(on)
        self._last = self._snapshot()
        self._refill(force=True)

    def _on_pause(self, on):
        self._paused = bool(on)
        self.pause_btn.setText("▶  Resume" if on else "⏸  Pause")
        if not on:
            self._poll()

    def _on_clear(self):
        self.log_list.clear()

    def _poll(self):
        lst = self._listener()
        if lst is None or not lst.running:
            self.status.setText(
                "⚠️ OSC input is off. Switch on “Receive "
                "avatar parameters (OSC input)” on the OSC tab, then "
                "change something on your avatar.")
            return
        self.status.setText(
            f"Listening on udp/{lst.port}. Change a toggle, a gesture or "
            "a menu value on your avatar and watch it show up here. The "
            "app keeps running while this window is open.")
        if self._paused:
            return
        rev = lst.revision()
        if rev == self._rev:
            return
        self._rev = rev
        snap = self._snapshot()
        changes = diff_snapshots(self._last, snap) if self._last else []
        self._last = snap
        if changes:
            stamp = time.strftime("%H:%M:%S")
            for name, value in changes:
                self.log_list.insertItem(
                    0, f"{stamp}   {name} = {_shown(value)}")
            while self.log_list.count() > MAX_LOG_LINES:
                self.log_list.takeItem(self.log_list.count() - 1)
        self._refill(snap)

    def _refill(self, snap=None, force=False):
        if snap is None:
            snap = self._last or self._snapshot()
        needle = self.filter.text().strip().casefold()
        rows = [(k, v) for k, v in sorted(snap.items(),
                                          key=lambda kv: kv[0].casefold())
                if not needle or needle in k.casefold()]
        self.table.setUpdatesEnabled(False)
        try:
            if self.table.rowCount() != len(rows):
                self.table.setRowCount(len(rows))
            for r, (name, value) in enumerate(rows):
                for c, text in enumerate((name, value_type(value),
                                          _shown(value))):
                    item = self.table.item(r, c)
                    if item is None:
                        self.table.setItem(r, c, QTableWidgetItem(text))
                    elif item.text() != text:
                        item.setText(text)
        finally:
            self.table.setUpdatesEnabled(True)
        self.count_lbl.setText(f"{len(snap)} parameters"
                               + (f" – {len(rows)} shown" if needle
                                  else ""))

    def closeEvent(self, ev):
        self.timer.stop()
        super().closeEvent(ev)


def open_param_log(win):
    """One window at a time; a second click brings it to the front."""
    dlg = getattr(win, "_osc_param_log", None)
    if dlg is None:
        dlg = OscParamLogDialog(win)
        win._osc_param_log = dlg
        dlg.finished.connect(lambda _r: setattr(win, "_osc_param_log", None))
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg
