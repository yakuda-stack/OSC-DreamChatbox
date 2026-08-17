"""
ui/nodegraph.py – the node canvas behind the AIO "Advanced mode".

A small, dependency-free node editor on top of QGraphicsView: drag a
block out of the palette onto the canvas, drag from an output dot to an
input dot to wire them up, and the whole thing serialises to plain JSON
so it can live in the normal config file.

This module is deliberately dumb about OSC-DreamChatbox: it knows the
*shape* of the graph (which node types exist, what sockets they have,
which fields they carry) but never evaluates it. Turning a graph into a
chatbox line is a separate step and lives outside of the drawing code,
so the editor can be built, themed and tested on its own.

Coordinate note: nodes are positioned in scene coordinates and stored
that way, so a saved graph reopens exactly where the user left it
regardless of window size or zoom.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import math

from PyQt6.QtCore import QMimeData, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QDrag, QFont, QPainter, QPainterPath, QPen, QTransform)
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView,
    QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem)

#: MIME type used when a palette entry is dragged onto the canvas.
NODE_MIME = "application/x-dreamchatbox-node"

#: payload prefix that means "not a node type, a placeholder name" - the
#: variable list drags these so a {gpu_usage} becomes a ready-made block
PLACEHOLDER_PREFIX = "placeholder:"

#: payload prefix for a live avatar parameter picked out of the received
#: list - drops in as a ready-made "Avatar parameter" block
OSCPARAM_PREFIX = "oscparam:"

#: How the canvas paints itself. Overwritten from the active theme via
#: NodeCanvas.apply_tokens() - the stylesheet cannot reach items that
#: are drawn by hand, so the colours have to be handed over explicitly.
DEFAULT_TOKENS = {
    "bg": "#14161c",
    "panel": "#0f1116",
    "card": "#191c24",
    "inner": "#232833",
    "border": "#333947",
    "accent": "#5b8dc9",
    "accent_hi": "#6d9cd4",
    "text": "#e5e9ef",
    "dim": "#7a8290",
    "danger": "#c95b5b",
}

# ---------------------------------------------------------------------------
# Node catalogue
# ---------------------------------------------------------------------------
# Every entry describes one kind of block:
#   title    what the header says
#   cat      palette group
#   accent   header colour
#   inputs   list of (key, label) sockets on the left
#   outputs  list of (key, label) sockets on the right
#   fields   list of (key, kind, label, default, extra) editable values
#            kind is one of: text | multiline | int | choice
#            extra carries the choices for "choice" and (min, max) for "int"
#   note     one line of help shown in the inspector
NODE_DEFS = {
    # ---------------- sources -------------------------------------------
    "text": {
        "title": "Text", "cat": "Sources", "accent": "#5b8dc9",
        "inputs": [], "outputs": [("out", "Text")],
        "fields": [("value", "multiline", "Text", "", None)],
        "note": "A fixed piece of text. Placeholders like {text} still "
                "work inside it.",
    },
    "placeholder": {
        "title": "Placeholder", "cat": "Sources", "accent": "#5b8dc9",
        "inputs": [], "outputs": [("out", "Value")],
        "fields": [("name", "text", "Name", "text", None)],
        "note": "Any placeholder by name, without the braces - e.g. "
                "\"artist\" for {artist}.",
    },
    "status": {
        "title": "Personal Status", "cat": "Sources", "accent": "#5b8dc9",
        "inputs": [], "outputs": [("text", "Text")],
        "fields": [("template", "choice", "Template", "active",
                    ["active"] + [str(i) for i in range(1, 11)])],
        "note": "The rotating status text. \u201cactive\u201d follows "
                "whichever template is selected on the Apps page; picking "
                "a number reads that one instead, whether or not it is "
                "the selected one.",
    },
    "status_single": {
        "title": "Status text", "cat": "Sources", "accent": "#5b8dc9",
        "inputs": [], "outputs": [("text", "Text")],
        "fields": [("template", "choice", "Template", "active",
                    ["active"] + [str(i) for i in range(1, 11)]),
                   ("entry", "choice", "Text entry", "1",
                    [str(i) for i in range(1, 21)])],
        "note": "One specific status text, no rotation - the way "
                "{text_3} or {text_t2_5} would address it. Useful as a "
                "text library: a slot you never put on rotation is still "
                "readable from here.",
    },
    "media": {
        "title": "MediaPlay", "cat": "Sources", "accent": "#5b8dc9",
        "inputs": [],
        "outputs": [("artist", "Artist"), ("title", "Title"),
                    ("time", "Time"), ("bar", "Songbar")],
        "fields": [], "note": "What the media player is currently doing.",
    },
    "hw_gpu": {
        "title": "GPU", "cat": "Sources", "accent": "#5b8dc9",
        "inputs": [],
        "outputs": [("usage", "Load"), ("temp", "Temp"), ("power", "Watts"),
                    ("vram", "VRAM"), ("name", "Name")],
        "fields": [], "note": "Live GPU values. The Hardware app has to be "
                              "Active for these to fill in; Watts needs the "
                              "power draw tick on that card.",
    },
    "hw_cpu": {
        "title": "CPU", "cat": "Sources", "accent": "#5b8dc9",
        "inputs": [],
        "outputs": [("usage", "Load"), ("temp", "Temp"), ("power", "Watts"),
                    ("name", "Name")],
        "fields": [], "note": "Live CPU values. The Hardware app has to be "
                              "Active for these to fill in; Watts needs the "
                              "power draw tick on that card.",
    },
    "hw_sys": {
        "title": "RAM & System", "cat": "Sources", "accent": "#5b8dc9",
        "inputs": [],
        "outputs": [("ram", "RAM"), ("ram_pct", "RAM %"),
                    ("ram_type", "RAM type"), ("fps", "FPS")],
        "fields": [], "note": "Memory and frames per second. FPS is read "
                              "from MangoHud's log (Linux) or RTSS "
                              "(Windows).",
    },
    "custom_box": {
        "title": "Custom Box", "cat": "Sources", "accent": "#5b8dc9",
        "inputs": [],
        "outputs": [("start", "Top line"), ("stop", "Bottom line"),
                    ("text", "Middle text")],
        "fields": [],
        "note": "The frame lines from the Custom Box card. With All in "
                "one active the frame appears ONLY where you place it - "
                "so wire these in wherever you want them.",
    },
    # not in the palette (see NODE_CATEGORIES): the first Hardware
    # block, kept loadable so a canvas built with it still works
    "hardware": {
        "title": "Hardware", "cat": "Legacy", "accent": "#5b8dc9",
        "inputs": [],
        "outputs": [("cpu", "CPU"), ("gpu", "GPU"), ("ram", "RAM"),
                    ("fps", "FPS")],
        "fields": [], "note": "Replaced by the separate GPU / CPU / "
                              "RAM & System blocks.",
    },
    "chat": {
        "title": "Chat / STT", "cat": "Sources", "accent": "#5b8dc9",
        "inputs": [], "outputs": [("out", "Message")],
        "fields": [("source", "choice", "Source", "chat",
                    ["chat", "stt", "ttt", "any"])],
        "note": "The last message that came from the chat box, speech to "
                "text or text to text.",
    },
    "clock": {
        "title": "Clock", "cat": "Sources", "accent": "#5b8dc9",
        "inputs": [], "outputs": [("out", "Time")],
        "fields": [("format", "text", "Format", "%H:%M", None)],
        "note": "The current time in a strftime format.",
    },

    # ---------------- text ----------------------------------------------
    "join": {
        "title": "Join", "cat": "Text", "accent": "#6fae72",
        "inputs": [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")],
        # the sockets come from the "count" field instead of the list
        # above, which is only the starting point - see inputs_for()
        "dynamic_inputs": ("count", "abcdefghij"),
        "outputs": [("out", "Text")],
        "fields": [("count", "int", "Inputs", 4, (2, 10)),
                   ("sep", "text", "Separator", " ", None),
                   ("skip_empty", "choice", "Empty inputs", "skip",
                    ["skip", "keep"])],
        "note": "Glues the connected inputs together in order. Grow it "
                "to as many as ten - the wires you already made stay "
                "where they are.",
    },
    "format": {
        "title": "Format", "cat": "Text", "accent": "#6fae72",
        "inputs": [("a", "A"), ("b", "B"), ("c", "C")],
        "outputs": [("out", "Text")],
        "fields": [("pattern", "text", "Pattern", "{a} - {b}", None)],
        "note": "Free-form pattern; {a}, {b} and {c} stand for the "
                "connected inputs.",
    },
    "style": {
        "title": "Style", "cat": "Text", "accent": "#6fae72",
        "inputs": [("in", "Text")], "outputs": [("out", "Text")],
        "fields": [("style", "choice", "Style", "normal",
                    ["normal", "super", "sub", "upper", "lower"])],
        "note": "Superscript / subscript use the same character map as "
                "the rest of the app.",
    },
    "truncate": {
        "title": "Truncate", "cat": "Text", "accent": "#6fae72",
        "inputs": [("in", "Text")], "outputs": [("out", "Text")],
        "fields": [("max", "int", "Max characters", 40, (1, 144)),
                   ("ellipsis", "text", "Suffix", "\u2026", None)],
        "note": "Keeps a long title from eating the whole 144 character "
                "budget.",
    },
    "info": {
        "title": "Info", "cat": "Text", "accent": "#6fae72",
        "inputs": [("text", "Text"), ("when", "When"),
                   ("next", "Otherwise")],
        "outputs": [("out", "Text")],
        "fields": [("page", "int", "Show on step", 0, (0, 10))],
        "note": "One page of a message. Passes its Text through while it "
                "is the active one and hands over to Otherwise when it "
                "is not - so several of them chain into a single Chatbox "
                "Output and take turns.\n"
                "Show on step 0: active while When is true (wire a "
                "Timer), or always when nothing is wired to When \u2013 "
                "which is what the last block in a chain wants. 1-10: "
                "active while When equals that number (wire a Step).",
    },
    "step": {
        "title": "Step", "cat": "Flow", "accent": "#c9a35b",
        "inputs": [("advance", "Advance"), ("reset", "Reset")],
        "outputs": [("step", "Step"), ("wrapped", "Wrapped?")],
        "fields": [("steps", "int", "Steps", 3, (2, 10)),
                   ("seconds", "int", "Or every (sec, 0 = off)", 0,
                    (0, 3600))],
        "note": "Counts 1, 2, 3 \u2026 and starts over. Advance moves it "
                "on when that input turns true; with nothing wired "
                "there it moves on by itself every N seconds. Feed the "
                "Step output into the When of several Info blocks to "
                "give each one its turn.",
    },
    "newline": {
        "title": "Line break", "cat": "Text", "accent": "#6fae72",
        "inputs": [], "outputs": [("out", "\\n")],
        "fields": [], "note": "Starts a new line in the VRChat chatbox.",
    },

    # ---------------- logic ---------------------------------------------
    "if": {
        "title": "If / Else", "cat": "Logic", "accent": "#c9a35b",
        "inputs": [("cond", "Condition"), ("then", "Then"),
                   ("else", "Else")],
        "outputs": [("out", "Text")],
        "fields": [],
        "note": "Passes Then through when the condition is true, "
                "otherwise Else.",
    },
    "compare": {
        "title": "Compare", "cat": "Logic", "accent": "#c9a35b",
        "inputs": [("a", "A"), ("b", "B")], "outputs": [("out", "True?")],
        "fields": [("op", "choice", "Operator", "==",
                    ["==", "!=", "<", ">", "contains"])],
        "note": "Compares two values; feed the result into an If / Else.",
    },
    "nonempty": {
        "title": "Has value", "cat": "Logic", "accent": "#c9a35b",
        "inputs": [("in", "Value")], "outputs": [("out", "True?")],
        "fields": [],
        "note": "True whenever the input is not empty - the usual way to "
                "hide a line while nothing is playing.",
    },

    # ---------------- OSC ------------------------------------------------
    "osc_in": {
        "title": "Avatar parameter", "cat": "OSC", "accent": "#9a6ee0",
        "inputs": [],
        "outputs": [("value", "Value"), ("bool", "True?")],
        "fields": [("name", "text", "Parameter", "", None)],
        "note": "Reads an avatar parameter VRChat sends out - the same "
                "name as in the Expressions menu. Needs OSC input "
                "switched on under Options.",
    },
    "osc_out": {
        "title": "Set parameter", "cat": "OSC", "accent": "#9a6ee0",
        "inputs": [("value", "Value"), ("trigger", "When")],
        "outputs": [],
        "fields": [("name", "text", "Parameter", "", None),
                   ("type", "choice", "Type", "bool",
                    ["bool", "int", "float"])],
        "note": "Writes an avatar parameter. Fires when \u201cWhen\u201d is "
                "true, or on every change when nothing is wired to it. "
                "Only on a real send, never on the preview.",
    },

    "ext_osc_in": {
        "title": "External OSC in", "cat": "OSC", "accent": "#9a6ee0",
        "inputs": [],
        "outputs": [("value", "Value"), ("type", "Type"),
                    ("bool", "True?"), ("text", "Text")],
        "fields": [("address", "text", "OSC address",
                    "/external/example", None)],
        "note": "Any OSC address, not just avatar parameters - whatever "
                "another tool on this machine sends to the input port. "
                "Type says what arrived (string / bool / int / float); "
                "Text is filled only for strings.",
    },
    "ext_osc_out": {
        "title": "External OSC out", "cat": "OSC", "accent": "#9a6ee0",
        "inputs": [("value", "Value"), ("trigger", "When")],
        "outputs": [],
        "fields": [("address", "text", "OSC address",
                    "/external/example", None),
                   ("type", "choice", "Send as", "auto",
                    ["auto", "string", "bool", "int", "float"]),
                   ("ip", "text", "Target IP (blank = default)", "", None),
                   ("port", "int", "Target port (0 = default)", 0,
                    (0, 65535))],
        "fields_note": "",
        "note": "Sends to any app that listens for OSC, not to VRChat. "
                "Leave IP and port empty to use the external target set "
                "under Options. Only on a real send, never on the "
                "preview.",
    },

    # ---------------- flow -----------------------------------------------
    "timer": {
        "title": "Timer", "cat": "Flow", "accent": "#c9a35b",
        "inputs": [("start", "Start")], "outputs": [("out", "True?")],
        "fields": [("seconds", "int", "Every (sec)", 10, (1, 3600)),
                   ("mode", "choice", "Mode", "blink", ["blink", "pulse"])],
        "note": "blink = true for N seconds, then false for N, over and "
                "over. pulse = true for one send every N seconds.\n"
                "With nothing wired to Start both run off the clock. "
                "Wire Start and they count from the moment it turns "
                "true and start over when it turns false - hang it off "
                "a Chatbox Output's Shown? to time something from the "
                "moment that string appears.",
    },
    "button": {
        "title": "Button", "cat": "Flow", "accent": "#c9a35b",
        "inputs": [], "outputs": [("out", "True?")],
        "fields": [("mode", "choice", "Mode", "pulse",
                    ["pulse", "toggle"]),
                   ("press", "action", "Press", "Trigger now", None)],
        "note": "A trigger you fire by hand, for testing a chain without "
                "waiting for the thing that would normally set it off. "
                "pulse is true for one send, toggle stays until you "
                "click again.",
    },
    "hotkey_in": {
        "title": "Get Hotkey", "cat": "Hotkeys", "accent": "#c9a35b",
        "inputs": [], "outputs": [("out", "Held?")],
        "fields": [("keys", "hotkey", "Combination", "f13", None)],
        "note": "True while the combination is held down anywhere on the "
                "system, VRChat or not. Put it in front of anything that "
                "reacts to a rising edge to get \u201cwhen pressed\u201d. "
                "Needs hotkey input switched on under Options.",
    },
    "hotkey": {
        "title": "Send Hotkey", "cat": "Hotkeys", "accent": "#c9a35b",
        "inputs": [("trigger", "When")], "outputs": [],
        "fields": [("keys", "hotkey", "Combination", "ctrl+shift+m", None)],
        "note": "Presses a key combination at the operating system when "
                "the input turns true - once per change, not once per "
                "send. Written the way you would say it: ctrl+shift+m, "
                "alt+F4, F13. Only on a real send, never on the preview.",
    },
    "aio_change": {
        "title": "Change AIO", "cat": "Flow", "accent": "#c9a35b",
        "inputs": [("trigger", "When")], "outputs": [],
        "fields": [("target", "choice", "Go to", "next",
                    ["next", "previous", "1", "2", "3", "4", "5"])],
        "note": "Switches which AIO string is on screen. Only on a real "
                "send, never on the preview.",
    },

    # ---------------- system ---------------------------------------------
    "proc_watch": {
        "title": "Program running", "cat": "System", "accent": "#59a3a3",
        "inputs": [], "outputs": [("running", "Running?")],
        "fields": [("name", "process", "Program", "VRChat", None)],
        "fields_note": "",
        "note": "True while a process whose name contains this is "
                "running. Part of a name is enough - \u201cvrchat\u201d "
                "finds VRChat.exe under Proton.",
    },
    "run_program": {
        "title": "Start program", "cat": "System", "accent": "#59a3a3",
        "inputs": [("trigger", "When")], "outputs": [],
        "fields": [("command", "file", "Command", "", None),
                   ("debug", "choice", "Debug", "off", ["off", "on"])],
        "note": "Starts a program when the input turns true - once per "
                "change, not once per send. Debug runs it in a terminal "
                "window that stays open, so you can see what it said. "
                "Only on a real send, never on the preview.",
    },

    # ---------------- output --------------------------------------------
    "output": {
        "title": "Chatbox Output", "cat": "Output", "accent": "#c95b5b",
        "inputs": [("in", "Text")], "outputs": [("shown", "Shown?")],
        "fields": [],
        "note": "Where this canvas ends up. One per AIO string - the "
                "canvas you are on decides which. Shown? is true while "
                "this string is the one in the chatbox, so a Timer hung "
                "off it counts from the moment it appears.",
    },
}

#: palette order
NODE_CATEGORIES = ["Sources", "Text", "Logic", "Flow", "OSC", "Output",
                   "System", "Hotkeys"]

#: How the palette is grouped. A category is a list of (subgroup, ids);
#: an empty subgroup name means "straight under the category". Kept as
#: data rather than derived from `cat`, because the useful grouping is
#: not the same as the evaluation grouping: Hardware is three blocks
#: that belong together on screen and nowhere else.
PALETTE_TREE = [
    ("Sources", [
        ("", ["text", "placeholder", "clock", "custom_box"]),
        ("Personal Status", ["status", "status_single"]),
        ("Hardware", ["hw_gpu", "hw_cpu", "hw_sys"]),
        ("Media", ["media"]),
        ("Chat", ["chat"]),
    ]),
    ("Text", [("", ["join", "format", "info", "style", "truncate",
                    "newline"])]),
    ("Logic", [("", ["if", "compare", "nonempty"])]),
    ("Flow", [("", ["timer", "step", "button", "aio_change"])]),
    ("OSC", [("VRChat avatar", ["osc_in", "osc_out"]),
             ("External", ["ext_osc_in", "ext_osc_out"])]),
    ("Output", [("", ["output"])]),
    # last two on purpose: the groups that reach outside the app
    ("System", [("", ["proc_watch", "run_program"])]),
    ("Hotkeys", [("", ["hotkey_in", "hotkey"])]),
]


def inputs_for(type_id, values):
    """The input sockets a block actually has right now.

    Most blocks answer from their definition. A Join answers from its
    "count" field, because "how many things am I gluing together" is a
    property of the one block, not of the block type - and four was
    always going to be the wrong number for somebody.
    """
    definition = NODE_DEFS.get(type_id) or {}
    dynamic = definition.get("dynamic_inputs")
    if not dynamic:
        return definition.get("inputs", [])
    field, keys = dynamic
    try:
        count = int((values or {}).get(field, len(keys)))
    except (TypeError, ValueError):
        count = len(keys)
    count = max(2, min(len(keys), count))
    return [(keys[i], keys[i].upper()) for i in range(count)]


def node_ids_for(category):
    return [k for k, d in NODE_DEFS.items() if d["cat"] == category]


# ---------------------------------------------------------------------------
# Sockets and edges
# ---------------------------------------------------------------------------
class SocketItem(QGraphicsItem):
    """One connection dot. Inputs take a single edge, outputs any number -
    the same rule every node editor uses, and the one that keeps
    evaluation unambiguous later on."""

    RADIUS = 5.5

    def __init__(self, node, key, label, is_input, index):
        super().__init__(node)
        self.node = node
        self.key = key
        self.label = label
        self.is_input = is_input
        self.index = index
        self.edges = []
        self.setZValue(2)
        self.setAcceptHoverEvents(True)
        self._hover = False
        self.setToolTip(f"{label} \u2013 drag to connect")

    def boundingRect(self):
        r = self.RADIUS + 4
        return QRectF(-r, -r, r * 2, r * 2)

    def paint(self, painter, option, widget=None):
        t = self.node.tokens
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        filled = bool(self.edges) or self._hover
        painter.setPen(QPen(QColor(t["accent"] if filled else t["border"]),
                            1.6))
        painter.setBrush(QBrush(QColor(t["accent"] if filled else t["card"])))
        painter.drawEllipse(QPointF(0, 0), self.RADIUS, self.RADIUS)

    def hoverEnterEvent(self, ev):
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, ev):
        self._hover = False
        self.update()

    def can_accept(self, other):
        """Two sockets may be wired when they face opposite ways and do
        not belong to the same node."""
        if other is None or other is self:
            return False
        return self.is_input != other.is_input and other.node is not self.node

    def detach_all(self):
        for edge in list(self.edges):
            edge.remove()


class EdgeItem(QGraphicsPathItem):
    """A bezier between two sockets. Owns nothing but its own line - both
    endpoints keep a reference so a deleted node can clean up."""

    def __init__(self, source, target):
        super().__init__()
        self.source = source          # output socket
        self.target = target          # input socket
        self.setZValue(-1)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        source.edges.append(self)
        target.edges.append(self)
        self.update_path()

    @property
    def tokens(self):
        return self.source.node.tokens

    def update_path(self):
        p1 = self.source.scenePos()
        p2 = self.target.scenePos()
        self.setPath(bezier(p1, p2))
        self.source.update()
        self.target.update()

    def paint(self, painter, option, widget=None):
        t = self.tokens
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = QColor(t["accent_hi"] if self.isSelected() else t["accent"])
        if not self.isSelected():
            colour.setAlpha(200)
        painter.setPen(QPen(colour, 2.6 if self.isSelected() else 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())

    def shape(self):
        """Fat stroke so the thin line is still clickable."""
        stroker = QPen(Qt.GlobalColor.black, 10)
        path = QPainterPath(self.path())
        from PyQt6.QtGui import QPainterPathStroker
        s = QPainterPathStroker()
        s.setWidth(10)
        _ = stroker
        return s.createStroke(path)

    def remove(self):
        for socket in (self.source, self.target):
            if self in socket.edges:
                socket.edges.remove(self)
            socket.update()
        if self.scene() is not None:
            self.scene().removeItem(self)


def bezier(p1, p2):
    """Horizontal-ish curve; the handle grows with the distance so short
    hops stay tight and long ones do not fold back on themselves."""
    path = QPainterPath(p1)
    dx = max(40.0, min(160.0, abs(p2.x() - p1.x()) * 0.6))
    path.cubicTo(QPointF(p1.x() + dx, p1.y()),
                 QPointF(p2.x() - dx, p2.y()), p2)
    return path


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
class NodeItem(QGraphicsItem):
    HEADER = 28
    ROW = 22
    PAD_BOTTOM = 10
    WIDTH = 186

    def __init__(self, type_id, tokens, node_id=None):
        super().__init__()
        self.type_id = type_id
        self.definition = NODE_DEFS[type_id]
        self.tokens = dict(tokens)
        self.node_id = node_id
        self.values = {key: default
                       for key, _kind, _lbl, default, _extra
                       in self.definition["fields"]}
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        self.inputs = []
        self.outputs = []
        self._build_sockets()

    def _build_sockets(self):
        for i, (key, label) in enumerate(
                inputs_for(self.type_id, self.values)):
            s = SocketItem(self, key, label, True, i)
            s.setPos(0, self.HEADER + self.ROW * i + self.ROW / 2)
            self.inputs.append(s)
        for i, (key, label) in enumerate(self.definition["outputs"]):
            s = SocketItem(self, key, label, False, i)
            s.setPos(self.WIDTH,
                     self.HEADER + self.ROW * i + self.ROW / 2)
            self.outputs.append(s)

    def rebuild_sockets(self):
        """Re-makes the sockets after a field changed how many there are.

        Wires are kept by socket key, not by position: growing a Join
        from four inputs to six must not disturb the four that are
        already connected, and shrinking it should cost exactly the
        wires whose sockets went away.
        """
        keep_in, keep_out = [], []
        for socket in self.inputs:
            for edge in list(socket.edges):
                keep_in.append((socket.key, edge.source))
                edge.remove()
        for socket in self.outputs:
            # the wire leaving this block is not affected by how many
            # inputs it has, and losing it on every resize would be a
            # nasty surprise
            for edge in list(socket.edges):
                keep_out.append((socket.key, edge.target))
                edge.remove()
        for socket in self.inputs + self.outputs:
            socket.detach_all()
            if self.scene() is not None:
                self.scene().removeItem(socket)
            socket.setParentItem(None)
        self.inputs, self.outputs = [], []
        self.prepareGeometryChange()
        self._build_sockets()
        scene = self.scene()
        if scene is not None:
            for key, source in keep_in:
                target = next((s for s in self.inputs if s.key == key), None)
                if target is not None and source.scene() is scene:
                    scene.connect_sockets(source, target)
            for key, target in keep_out:
                source = next((s for s in self.outputs if s.key == key),
                              None)
                if source is not None and target.scene() is scene:
                    scene.connect_sockets(source, target)
        self.update()

    # -- geometry ------------------------------------------------------
    @property
    def rows(self):
        return max(len(self.inputs), len(self.outputs), 1)

    @property
    def height(self):
        return self.HEADER + self.ROW * self.rows + self.PAD_BOTTOM

    def boundingRect(self):
        return QRectF(-3, -3, self.WIDTH + 6, self.height + 6)

    # -- painting ------------------------------------------------------
    def paint(self, painter, option, widget=None):
        t = self.tokens
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(0, 0, self.WIDTH, self.height)

        painter.setPen(QPen(QColor(t["accent"] if self.isSelected()
                                   else t["border"]),
                            2.0 if self.isSelected() else 1.0))
        painter.setBrush(QBrush(QColor(t["card"])))
        painter.drawRoundedRect(body, 9, 9)

        # header: rounded on top, square at the seam
        header = QPainterPath()
        header.addRoundedRect(QRectF(0, 0, self.WIDTH, self.HEADER), 9, 9)
        header.addRect(QRectF(0, self.HEADER - 9, self.WIDTH, 9))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(self.definition["accent"])))
        painter.drawPath(header.simplified())

        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QPen(QColor("#ffffff")))
        painter.drawText(QRectF(10, 0, self.WIDTH - 20, self.HEADER),
                         Qt.AlignmentFlag.AlignVCenter
                         | Qt.AlignmentFlag.AlignLeft,
                         self.definition["title"])

        f.setBold(False)
        f.setPointSize(8)
        painter.setFont(f)
        for socket in self.inputs:
            painter.setPen(QPen(QColor(t["text"])))
            painter.drawText(
                QRectF(12, socket.pos().y() - self.ROW / 2,
                       self.WIDTH - 24, self.ROW),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                socket.label)
        for socket in self.outputs:
            painter.setPen(QPen(QColor(t["text"])))
            painter.drawText(
                QRectF(12, socket.pos().y() - self.ROW / 2,
                       self.WIDTH - 24, self.ROW),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                socket.label)

        summary = self.summary()
        if summary:
            painter.setPen(QPen(QColor(t["dim"])))
            painter.drawText(
                QRectF(10, self.height - self.PAD_BOTTOM - 9,
                       self.WIDTH - 20, 12),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                summary)

    def summary(self):
        """The one field worth showing on the block itself, shortened.
        Opening the inspector for every node just to see which
        placeholder it carries would defeat the point of a canvas."""
        fields = [f for f in self.definition["fields"]
                  if f[1] not in ("action",)]
        dynamic = self.definition.get("dynamic_inputs")
        if dynamic:
            # the first field of a Join is its socket count, which the
            # block already shows by having that many sockets
            fields = [f for f in fields if f[0] != dynamic[0]]
        if not fields:
            return ""
        key = fields[0][0]
        value = str(self.values.get(key, "")).replace("\n", " ")
        if not value:
            return ""
        return value if len(value) <= 26 else value[:25] + "\u2026"

    # -- behaviour -----------------------------------------------------
    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for socket in self.inputs + self.outputs:
                for edge in socket.edges:
                    edge.update_path()
        return super().itemChange(change, value)

    def set_tokens(self, tokens):
        self.tokens = dict(tokens)
        self.update()
        for socket in self.inputs + self.outputs:
            socket.update()

    def remove(self):
        for socket in self.inputs + self.outputs:
            socket.detach_all()
        if self.scene() is not None:
            self.scene().removeItem(self)

    # -- serialisation -------------------------------------------------
    def to_dict(self):
        return {
            "id": self.node_id,
            "type": self.type_id,
            "x": round(self.pos().x(), 1),
            "y": round(self.pos().y(), 1),
            "values": dict(self.values),
        }


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------
class NodeScene(QGraphicsScene):
    """Holds the items and owns the "drag a wire" interaction."""

    graphChanged = pyqtSignal()

    GRID = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tokens = dict(DEFAULT_TOKENS)
        self.setSceneRect(-2000, -2000, 4000, 4000)
        self._link_from = None
        self._link_item = None

    # -- background ----------------------------------------------------
    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor(self.tokens["bg"]))
        left = int(math.floor(rect.left() / self.GRID) * self.GRID)
        top = int(math.floor(rect.top() / self.GRID) * self.GRID)
        fine = QPen(QColor(self.tokens["border"]), 0)
        colour = QColor(self.tokens["border"])
        colour.setAlpha(70)
        fine.setColor(colour)
        painter.setPen(fine)
        x = left
        while x < rect.right():
            painter.drawLine(int(x), int(rect.top()), int(x),
                             int(rect.bottom()))
            x += self.GRID
        y = top
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), int(y), int(rect.right()),
                             int(y))
            y += self.GRID

    def set_tokens(self, tokens):
        self.tokens = dict(tokens)
        for item in self.items():
            if isinstance(item, NodeItem):
                item.set_tokens(tokens)
        self.update()

    # -- wiring --------------------------------------------------------
    def socket_at(self, scene_pos):
        for item in self.items(scene_pos):
            if isinstance(item, SocketItem):
                return item
        return None

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            socket = self.socket_at(ev.scenePos())
            if socket is not None:
                self._start_link(socket, ev.scenePos())
                ev.accept()
                return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._link_item is not None:
            self._link_item.setPath(
                bezier(self._link_from.scenePos(), ev.scenePos()))
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._link_item is not None:
            target = self.socket_at(ev.scenePos())
            self.removeItem(self._link_item)
            self._link_item = None
            start, self._link_from = self._link_from, None
            if start.can_accept(target):
                self.connect_sockets(start, target)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def _start_link(self, socket, scene_pos):
        # dragging off a wired input picks the existing wire back up
        # instead of silently doing nothing
        if socket.is_input and socket.edges:
            edge = socket.edges[0]
            socket = edge.source
            edge.remove()
            self.graphChanged.emit()
        self._link_from = socket
        self._link_item = QGraphicsPathItem()
        pen = QPen(QColor(self.tokens["accent"]), 2.0, Qt.PenStyle.DashLine)
        self._link_item.setPen(pen)
        self._link_item.setZValue(-1)
        self._link_item.setPath(bezier(socket.scenePos(), scene_pos))
        self.addItem(self._link_item)

    def connect_sockets(self, a, b):
        source, target = (a, b) if not a.is_input else (b, a)
        # one wire per input: the new one replaces the old
        for edge in list(target.edges):
            edge.remove()
        for edge in source.edges:
            if edge.target is target:
                return None
        edge = EdgeItem(source, target)
        self.addItem(edge)
        self.graphChanged.emit()
        return edge

    # -- items ---------------------------------------------------------
    def add_node(self, type_id, pos, values=None, node_id=None):
        if type_id not in NODE_DEFS:
            return None
        node = NodeItem(type_id, self.tokens, node_id)
        if values:
            for key, value in values.items():
                if key in node.values:
                    node.values[key] = value
        node.setPos(pos)
        self.addItem(node)
        self.graphChanged.emit()
        return node

    def nodes(self):
        return [i for i in self.items() if isinstance(i, NodeItem)]

    def edges(self):
        return [i for i in self.items() if isinstance(i, EdgeItem)]

    def delete_selected(self):
        removed = False
        for item in list(self.selectedItems()):
            if isinstance(item, EdgeItem):
                item.remove()
                removed = True
        for item in list(self.selectedItems()):
            if isinstance(item, NodeItem):
                item.remove()
                removed = True
        if removed:
            self.graphChanged.emit()
        return removed

    def clear_graph(self):
        for item in self.nodes():
            item.remove()
        for item in self.edges():
            item.remove()
        self.graphChanged.emit()

    # -- serialisation -------------------------------------------------
    def to_dict(self):
        """The graph as plain JSON-able data.

        Ordering is fixed (nodes by position, edges by the ids they
        connect) because this ends up in the config file: an order that
        follows QGraphicsScene's internal item list would rewrite the
        same graph differently on every save.
        """
        ordered = sorted(self.nodes(),
                         key=lambda n: (n.pos().x(), n.pos().y()))
        seen = set()
        for i, node in enumerate(ordered):
            # a loaded graph brings its own ids along; only fill in the
            # gaps, and never hand out one twice
            candidate = node.node_id or f"n{i + 1}"
            while candidate in seen:
                candidate += "_"
            node.node_id = candidate
            seen.add(candidate)

        edges = [{"from": e.source.node.node_id, "out": e.source.key,
                  "to": e.target.node.node_id, "in": e.target.key}
                 for e in self.edges()]
        edges.sort(key=lambda e: (e["from"], e["out"], e["to"], e["in"]))
        return {"nodes": [n.to_dict() for n in ordered], "edges": edges}

    def from_dict(self, data):
        """Rebuilds a graph. Unknown node types and dangling edges are
        skipped rather than refused - a config written by a newer version
        should cost you the block it mentions, not the whole canvas."""
        self.clear_graph()
        data = data if isinstance(data, dict) else {}
        by_id = {}
        for entry in data.get("nodes") or []:
            if not isinstance(entry, dict):
                continue
            node = self.add_node(
                str(entry.get("type", "")),
                QPointF(float(entry.get("x", 0) or 0),
                        float(entry.get("y", 0) or 0)),
                entry.get("values") if isinstance(entry.get("values"), dict)
                else None,
                str(entry.get("id") or "") or None)
            if node is not None and node.node_id:
                by_id[node.node_id] = node
        for entry in data.get("edges") or []:
            if not isinstance(entry, dict):
                continue
            src = by_id.get(str(entry.get("from") or ""))
            dst = by_id.get(str(entry.get("to") or ""))
            if src is None or dst is None:
                continue
            out = next((s for s in src.outputs
                        if s.key == entry.get("out")), None)
            inp = next((s for s in dst.inputs
                        if s.key == entry.get("in")), None)
            if out is not None and inp is not None:
                self.connect_sockets(out, inp)


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------
class NodeCanvas(QGraphicsView):
    """Pan with the middle mouse button, zoom with the wheel, drop
    palette entries anywhere."""

    selectionChanged = pyqtSignal(object)   # NodeItem or None

    MIN_ZOOM = 0.35
    MAX_ZOOM = 2.4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.node_scene = NodeScene(self)
        self.setScene(self.node_scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setAcceptDrops(True)
        self.setMinimumHeight(420)
        self._zoom = 1.0
        self._panning = False
        self._pan_start = None
        self.node_scene.selectionChanged.connect(self._on_selection)

    # -- selection -----------------------------------------------------
    def _on_selection(self):
        nodes = [i for i in self.node_scene.selectedItems()
                 if isinstance(i, NodeItem)]
        self.selectionChanged.emit(nodes[0] if len(nodes) == 1 else None)

    # -- zoom / pan ----------------------------------------------------
    def wheelEvent(self, ev):
        step = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        target = self._zoom * step
        if target < self.MIN_ZOOM or target > self.MAX_ZOOM:
            return
        self._zoom = target
        self.scale(step, step)

    def reset_zoom(self):
        self.setTransform(QTransform())
        self._zoom = 1.0

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = ev.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._panning:
            delta = ev.position() - self._pan_start
            self._pan_start = ev.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y()))
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._panning and ev.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.node_scene.delete_selected():
                ev.accept()
                return
        super().keyPressEvent(ev)

    # -- drag & drop from the palette ----------------------------------
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasFormat(NODE_MIME):
            ev.acceptProposedAction()
            return
        super().dragEnterEvent(ev)

    def dragMoveEvent(self, ev):
        if ev.mimeData().hasFormat(NODE_MIME):
            ev.acceptProposedAction()
            return
        super().dragMoveEvent(ev)

    def dropEvent(self, ev):
        if not ev.mimeData().hasFormat(NODE_MIME):
            super().dropEvent(ev)
            return
        payload = bytes(ev.mimeData().data(NODE_MIME)).decode(
            "utf-8", "ignore")
        pos = self.mapToScene(ev.position().toPoint())
        # drop point = where the cursor is, not the top left corner
        at = QPointF(pos.x() - NodeItem.WIDTH / 2, pos.y() - 14)
        if payload.startswith(PLACEHOLDER_PREFIX):
            # a variable dragged out of the list becomes a ready-made
            # Placeholder block - the whole point is not having to type
            # the name again
            name = payload[len(PLACEHOLDER_PREFIX):]
            node = self.node_scene.add_node("placeholder", at, {"name": name})
        elif payload.startswith(OSCPARAM_PREFIX):
            name = payload[len(OSCPARAM_PREFIX):]
            node = self.node_scene.add_node("osc_in", at, {"name": name})
        else:
            node = self.node_scene.add_node(payload, at)
        if node is not None:
            self.node_scene.clearSelection()
            node.setSelected(True)
        ev.acceptProposedAction()

    # -- theming -------------------------------------------------------
    def apply_tokens(self, tokens):
        merged = dict(DEFAULT_TOKENS)
        merged.update({k: v for k, v in (tokens or {}).items()
                       if k in merged})
        self.node_scene.set_tokens(merged)


class DragList(QListWidget):
    """A list whose entries can be dragged onto the canvas. The item
    carries its drop payload and nothing else, which is what keeps the
    node palette and the variable list the same widget."""

    ROW = 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("nodepalette")
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setSpacing(2)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def fill(self, entries, max_rows=None):
        """entries: [(label, payload, tooltip)]"""
        self.clear()
        for label, payload, tip in entries:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, payload)
            if tip:
                item.setToolTip(tip)
            self.addItem(item)
        rows = self.count() if max_rows is None else min(self.count(),
                                                         max_rows)
        # sized to content where it can be: a scrollbar inside a page
        # that also scrolls is a trap, so only the long lists get one
        self.setFixedHeight(max(1, rows) * self.ROW + 8)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if max_rows
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def startDrag(self, actions):
        item = self.currentItem()
        if item is None:
            return
        mime = QMimeData()
        mime.setData(NODE_MIME,
                     str(item.data(Qt.ItemDataRole.UserRole)).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class NodePalette(DragList):
    """The blocks of one category."""

    def __init__(self, category, parent=None):
        super().__init__(parent)
        self.fill([(NODE_DEFS[t]["title"], t, NODE_DEFS[t]["note"])
                   for t in node_ids_for(category)])


class OscParamPalette(DragList):
    """The avatar parameters actually seen on the wire.

    Typing a parameter name from memory is exactly the kind of thing
    that fails silently - one capital letter wrong and the block reads
    nothing forever. The listener already knows every name VRChat sent,
    so the list is the picker.
    """

    MAX_ROWS = 8

    def set_parameters(self, params):
        """params: {name: value}"""
        entries = []
        for name in sorted(params, key=str.lower):
            value = params[name]
            entries.append((f"{name}", OSCPARAM_PREFIX + name,
                            f"currently {value!r} \u2013 drag onto the "
                            "canvas as an Avatar parameter block"))
        self.fill(entries, self.MAX_ROWS)


class VariableTree(QTreeWidget):
    """Every placeholder the app knows, grouped the way the \u201c+\u201d
    menu on a normal AIO field groups them, and draggable.

    A flat alphabetical list was the wrong shape: nobody looks for
    \u201cthe one starting with v\u201d, they look for \u201cthe VRAM one
    under GPU\u201d. Same groups, same order, same wording as the picker,
    so the two do not teach different mental models of the same
    vocabulary.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("nodepalette")
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragOnly)
        self.setIndentation(12)
        self.setMinimumHeight(240)
        self._groups = []

    def set_groups(self, groups):
        """groups: [(group name, [(placeholder name, note)])]"""
        self._groups = list(groups)
        self.apply_filter("")

    def apply_filter(self, text):
        text = (text or "").strip().lower()
        self.clear()
        for group, items in self._groups:
            hits = [(n, note) for n, note in items
                    if not text or text in n.lower()
                    or text in (note or "").lower()]
            if not hits:
                continue
            parent = QTreeWidgetItem([group])
            parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.addTopLevelItem(parent)
            for name, note in hits:
                child = QTreeWidgetItem([f"{{{name}}}"])
                child.setData(0, Qt.ItemDataRole.UserRole,
                              PLACEHOLDER_PREFIX + name)
                child.setToolTip(0, note or f"Drag in as {{{name}}}")
                parent.addChild(child)
            # collapsed while browsing, expanded while searching - a
            # search that hides its hits behind a triangle is not a search
            parent.setExpanded(bool(text))

    def startDrag(self, actions):
        item = self.currentItem()
        if item is None:
            return
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload:
            return          # a group header is not draggable
        mime = QMimeData()
        mime.setData(NODE_MIME, str(payload).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class BlockTree(QTreeWidget):
    """The palette, as an accordion.

    Six flat lists under six headings was fine at twelve blocks and is
    not at twenty: the list you want is somewhere below the fold, and
    the three Hardware blocks read as three unrelated things. Categories
    collapse, and the ones that group naturally (Hardware, Personal
    Status, Media) get a level of their own.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("nodepalette")
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragOnly)
        self.setIndentation(12)
        self.setMinimumHeight(220)
        self.apply_filter("")

    def apply_filter(self, text):
        """Rebuilds the tree, keeping only the blocks that match.

        Same shape as VariableTree.apply_filter() on purpose: two lists
        in one panel that answer a search differently is one list too
        many. A block is a hit on its title, on its description or on
        its internal id - the description is where the words people
        actually search for live ("battery", "vrchat", "key"), and the
        title alone would miss all of them.
        """
        query = (text or "").strip().lower()
        self.clear()
        for category, groups in PALETTE_TREE:
            top = QTreeWidgetItem([category])
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            kept = 0
            for subgroup, ids in groups:
                parent = top
                sub_item = None
                if subgroup:
                    sub_item = QTreeWidgetItem([subgroup])
                    sub_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    parent = sub_item
                found = 0
                for type_id in ids:
                    definition = NODE_DEFS.get(type_id)
                    if definition is None:
                        continue
                    if query:
                        hay = (f"{definition['title']} {definition['note']} "
                               f"{type_id} {category} {subgroup or ''}").lower()
                        if query not in hay:
                            continue
                    item = QTreeWidgetItem([definition["title"]])
                    item.setData(0, Qt.ItemDataRole.UserRole, type_id)
                    item.setToolTip(0, definition["note"])
                    parent.addChild(item)
                    found += 1
                kept += found
                if sub_item is not None:
                    if not found:
                        continue        # an empty subgroup is noise
                    top.addChild(sub_item)
                    # closed while browsing, open while searching - a
                    # search that hides its hits behind a triangle is
                    # not a search
                    sub_item.setExpanded(bool(query))
            if query and not kept:
                continue
            self.addTopLevelItem(top)
            # Sources open, the rest closed: the first block of any graph
            # comes from there, so it is the one worth costing a click
            top.setExpanded(bool(query) or category == "Sources")

    def startDrag(self, actions):
        item = self.currentItem()
        if item is None:
            return
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload:
            return          # a heading is not draggable
        mime = QMimeData()
        mime.setData(NODE_MIME, str(payload).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)
