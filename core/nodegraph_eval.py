"""
core/nodegraph_eval.py – turns a saved node graph into chatbox text.

The counterpart to ui/nodegraph.py: that module draws the graph and
writes it out as JSON, this one reads that JSON and evaluates it. No Qt
in here on purpose - the evaluation is the part that runs on every
frame and the part worth testing on its own, and neither wants a widget
toolkit in the way.

The contract with the rest of the app is deliberately small: hand in the
graph plus the same placeholder dict every custom string is rendered
against (MainWindow._template_values()) and get back {slot: text}, where
slot is the AIO string number 1-5. Everything downstream - the rotation,
the Custom Box, the character budget - keeps working on plain text and
never learns that a graph was involved.

Truthiness follows the rest of the template language: a value is true
when it is a non-empty string. There is no separate boolean type, which
means a Compare can feed an If and a Has value can feed a Join without
anything having to convert between them.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import datetime
import re
import time

from core.oscin import coerce_value, format_value, value_type
from core.textstyle import STYLE_SUB, STYLE_SUPER, apply_style
from core.textutils import substitute_placeholders

#: node type -> {output socket: placeholder name}. Everything in here is
#: a pure lookup into the values dict, which is why one table covers all
#: of them.
SOURCE_MAP = {
    "media": {"artist": "artist", "title": "title", "time": "time",
              "bar": "bar"},
    "hw_gpu": {"usage": "gpu_usage", "temp": "gpu_temp",
               "power": "gpu_power", "vram": "vram_usage",
               "name": "gpu_name"},
    "hw_cpu": {"usage": "cpu_usage", "temp": "cpu_temp",
               "power": "cpu_power", "name": "cpu_name"},
    "hw_sys": {"ram": "ram_usage", "ram_pct": "ram_pct",
               "ram_type": "ram_type", "fps": "fps"},
    "custom_box": {"start": "box_start", "stop": "box_stop",
                   "text": "box_text"},
    # the first combined Hardware block, kept loadable
    "hardware": {"cpu": "cpu_usage", "gpu": "gpu_usage",
                 "ram": "ram_usage", "fps": "fps"},
}

#: the Chat block's "Source" field -> placeholder
CHAT_SOURCES = {
    "chat": "chat_output",
    "stt": "stt_output",
    "ttt": "ttt_output",
    "any": "text_output",
}

#: blocks with no output socket - nothing pulls on them, so the commit
#: pass evaluates them explicitly
SIDE_EFFECT_TYPES = ("osc_out", "ext_osc_out", "aio_change", "hotkey",
                     "run_program")

#: how many nodes one output slot may pull in before we call it a runaway
#: graph. A canvas this size is not something you build by accident.
MAX_STEPS = 500


def _clean_id(value):
    return str(value or "")


class _Graph:
    """Index over the raw dict: nodes by id and, for every (node, input)
    pair, the (source node, output socket) feeding it."""

    def __init__(self, data):
        data = data if isinstance(data, dict) else {}
        self.nodes = {}
        for entry in data.get("nodes") or []:
            if not isinstance(entry, dict):
                continue
            node_id = _clean_id(entry.get("id"))
            if node_id:
                self.nodes[node_id] = entry
        self.wires = {}
        for entry in data.get("edges") or []:
            if not isinstance(entry, dict):
                continue
            src, dst = _clean_id(entry.get("from")), _clean_id(entry.get("to"))
            if src not in self.nodes or dst not in self.nodes:
                continue
            self.wires[(dst, _clean_id(entry.get("in")))] = (
                src, _clean_id(entry.get("out")))

    def output(self):
        """The Chatbox Output block of this canvas, or None.

        One canvas is one AIO string, so a second Output block is a
        mistake rather than a second slot; the first one (by id) wins and
        the other is ignored instead of the two being concatenated into
        something nobody asked for.
        """
        for node_id, entry in sorted(self.nodes.items()):
            if entry.get("type") == "output":
                return node_id
        return None

    def side_effect_nodes(self):
        """Blocks that DO something instead of producing text. They have
        no output socket, so nothing pulls on them - the commit pass has
        to go looking for them."""
        return [node_id for node_id, entry in sorted(self.nodes.items())
                if entry.get("type") in SIDE_EFFECT_TYPES]


def _values_of(entry):
    values = entry.get("values")
    return values if isinstance(values, dict) else {}


def _as_number(text):
    try:
        return float(str(text).strip().rstrip("%").replace(",", "."))
    except (TypeError, ValueError):
        return None


class _Evaluator:
    def __init__(self, graph, values, osc=None, state=None, actions=None,
                 keys=None, procs=None, shown=False):
        self.graph = graph
        # whether this canvas is the AIO string currently on screen
        self.shown = bool(shown)
        self.values = values
        self.osc = osc
        # the two system watchers, both optional: a graph that does not
        # ask about them must not require them to be switched on
        self.keys = keys
        self.procs = procs
        # timer / change tracking that has to survive between frames.
        # Owned by the caller (MainWindow), because a per-call dict would
        # make every timer fire on every frame.
        self.state = state if state is not None else {}
        # None = preview. A block with a side effect only ever runs when
        # this is a list, i.e. on a real send - a preview that silently
        # flipped avatar parameters would be a trap.
        self.actions = actions
        self.memo = {}
        self.visiting = set()
        self.steps = 0

    @property
    def committing(self):
        return self.actions is not None

    def output_of(self, node_id, socket):
        """The value on one output socket, with the two things every
        graph walker needs: a memo, so a block feeding three others is
        computed once, and a visiting set, so a cycle returns empty
        instead of recursing until Python gives up."""
        key = (node_id, socket)
        if key in self.memo:
            return self.memo[key]
        if key in self.visiting or self.steps > MAX_STEPS:
            return ""
        self.steps += 1
        self.visiting.add(key)
        try:
            result = self._compute(node_id, socket)
        finally:
            self.visiting.discard(key)
        self.memo[key] = result
        return result

    def input_of(self, node_id, socket):
        wire = self.graph.wires.get((node_id, socket))
        if wire is None:
            return ""
        return self.output_of(wire[0], wire[1])

    # ------------------------------------------------------------------
    def _compute(self, node_id, socket):
        entry = self.graph.nodes.get(node_id)
        if entry is None:
            return ""
        kind = entry.get("type")
        values = _values_of(entry)
        get_in = lambda name: self.input_of(node_id, name)   # noqa: E731

        if kind in ("status", "status_single"):
            return self._status_value(kind, values)

        if kind in SOURCE_MAP:
            name = SOURCE_MAP[kind].get(socket)
            raw = self.values.get(name) if name else None
            return "" if raw is None else str(raw)

        if kind == "text":
            # placeholders resolve here, but the tidy pass does not run
            # until the output block - a separator has to survive the
            # trip through Join
            return substitute_placeholders(str(values.get("value", "")),
                                           self.values)

        if kind == "placeholder":
            name = str(values.get("name", "")).strip().lstrip("{").rstrip("}")
            return substitute_placeholders("{%s}" % name, self.values) \
                if name else ""

        if kind == "chat":
            name = CHAT_SOURCES.get(str(values.get("source", "chat")),
                                    "chat_output")
            raw = self.values.get(name)
            return "" if raw is None else str(raw)

        if kind == "clock":
            fmt = str(values.get("format", "%H:%M")) or "%H:%M"
            try:
                return datetime.datetime.now().strftime(fmt)
            except (ValueError, TypeError):
                # a format string with a stray % should cost the block,
                # not the whole message
                return ""

        if kind == "info":
            return self._info(node_id, values)

        if kind == "step":
            return self._step(node_id, values, socket)

        if kind == "newline":
            return "\\n"

        if kind == "join":
            try:
                count = max(2, min(10, int(values.get("count", 4))))
            except (TypeError, ValueError):
                count = 4
            parts = [get_in(k) for k in "abcdefghij"[:count]]
            if str(values.get("skip_empty", "skip")) != "keep":
                parts = [p for p in parts if p.strip()]
            return str(values.get("sep", " ")).join(parts)

        if kind == "format":
            pattern = str(values.get("pattern", ""))
            slots = {"a": get_in("a"), "b": get_in("b"), "c": get_in("c")}
            return re.sub(r"\{([abc])\}",
                          lambda m: slots[m.group(1)], pattern)

        if kind == "style":
            text = get_in("in")
            style = str(values.get("style", "normal"))
            if style == "upper":
                return text.upper()
            if style == "lower":
                return text.lower()
            if style in (STYLE_SUPER, STYLE_SUB):
                return apply_style(text, style)
            return text

        if kind == "truncate":
            text = get_in("in")
            try:
                limit = max(1, int(values.get("max", 40)))
            except (TypeError, ValueError):
                limit = 40
            if len(text) <= limit:
                return text
            suffix = str(values.get("ellipsis", "\u2026"))
            # the suffix counts against the limit, otherwise "truncate to
            # 40" quietly produces 41 characters
            keep = max(0, limit - len(suffix))
            return text[:keep].rstrip() + suffix

        if kind == "if":
            return get_in("then") if get_in("cond").strip() \
                else get_in("else")

        if kind == "compare":
            return self._compare(str(values.get("op", "==")),
                                 get_in("a"), get_in("b"))

        if kind == "nonempty":
            return "1" if get_in("in").strip() else ""

        if kind == "osc_in":
            name = str(values.get("name", "")).strip()
            raw = self.osc.get(name) if (self.osc is not None and name) \
                else None
            text = format_value(raw)
            if socket == "bool":
                # a float parameter is true above zero, which is how a
                # radial ends up usable as a switch without a Compare
                number = _as_number(text)
                if number is not None:
                    return "1" if number != 0 else ""
                return "1" if text.strip() else ""
            return text

        if kind == "ext_osc_in":
            address = str(values.get("address", "")).strip()
            raw = self.osc.get_address(address) \
                if (self.osc is not None and address) else None
            if socket == "type":
                return value_type(raw)
            if socket == "text":
                # only for actual strings: a Text output that quietly
                # stringified a float would make the Type output pointless
                return raw if isinstance(raw, str) else ""
            text = format_value(raw)
            if socket == "bool":
                if isinstance(raw, bool):
                    return "1" if raw else ""
                number = _as_number(text)
                if number is not None:
                    return "1" if number != 0 else ""
                return "1" if text.strip() else ""
            return text

        if kind == "hotkey_in":
            combo = str(values.get("keys", "")).strip()
            if not combo or self.keys is None:
                return ""
            return "1" if self.keys.is_pressed(combo) else ""

        if kind == "proc_watch":
            name = str(values.get("name", "")).strip()
            if not name or self.procs is None:
                return ""
            return "1" if self.procs.is_running(name) else ""

        if kind == "button":
            return self._button(node_id, values)

        if kind == "timer":
            return self._timer(node_id, values)

        if kind in SIDE_EFFECT_TYPES:
            # nothing reads from these; run() drives them
            return ""

        if kind == "output":
            if socket == "shown":
                # true while this canvas is the string in the chatbox,
                # which is what makes "N seconds after it appears"
                # expressible at all
                return "1" if self.shown else ""
            return get_in("in")

        return ""

    # ------------------------------------------------------------------
    def _status_value(self, kind, values):
        """Personal Status, addressed the way the template language
        addresses it.

        "active" means the template selected on the Apps page, so the
        block follows what the user switches to; a number reaches into
        that template whether or not it is the selected one, which is
        what makes the ten templates usable as a text library.
        """
        template = str(values.get("template", "active")).strip().lower()
        prefix = "text" if template in ("", "active") \
            else f"text_t{template}"
        if kind == "status":
            name = prefix
        else:
            try:
                entry = max(1, min(20, int(values.get("entry", 1))))
            except (TypeError, ValueError):
                entry = 1
            name = f"{prefix}_{entry}"
        # through the values dict rather than a direct read: {text_tX} is
        # resolved lazily by the host (LazyStatusValues), and going
        # around it would mean a second implementation of the same rules
        raw = self.values.get(name)
        return "" if raw is None else str(raw)

    def _button(self, node_id, values):
        """The manual trigger. The click itself happens in the UI and
        only leaves a flag here.

        A pulse is cleared by the commit pass, never by the preview -
        otherwise a repaint between the click and the next send would
        eat the press and the button would look broken half the time.
        """
        key = ("button", node_id)
        armed = bool(self.state.get(key))
        if not armed:
            return ""
        if str(values.get("mode", "pulse")) != "toggle" and self.committing:
            self.state[key] = False
        return "1"

    def _info(self, node_id, values):
        """One page of a message.

        Two ways to decide whether it is the active page, because the
        two useful shapes are different: a single Timer flipping between
        two pages, and a Step counter dealing turns out to several. The
        field picks which, rather than the block guessing from what
        happens to be wired.
        """
        try:
            page = max(0, min(10, int(values.get("page", 0))))
        except (TypeError, ValueError):
            page = 0
        when = self.input_of(node_id, "when")
        if page == 0 and not any(n == node_id and k == "when"
                                 for (n, k) in self.graph.wires):
            # ungated: this is the page that shows when no other one
            # claims the turn, which is what the last block in a chain
            # is for. Without this rule an unwired Info hands over to an
            # Otherwise that is also unwired, and the chain ends in
            # nothing.
            active = True
        elif page == 0:
            active = bool(when.strip())
        else:
            number = _as_number(when)
            active = number is not None and int(number) == page
        # handing over rather than going empty is what lets these chain:
        # the last one in the chain is the one that decides what happens
        # when nobody is active
        return self.input_of(node_id, "text") if active \
            else self.input_of(node_id, "next")

    def _step(self, node_id, values, socket):
        """A counter that wraps, so a sequence starts over on its own."""
        try:
            steps = max(2, min(10, int(values.get("steps", 3))))
        except (TypeError, ValueError):
            steps = 3
        try:
            seconds = max(0, int(values.get("seconds", 0)))
        except (TypeError, ValueError):
            seconds = 0

        key = ("step", node_id)
        wrap_key = ("step_wrapped", node_id)
        current = self.state.get(key)
        if current is None:
            current = 1
            if self.committing:
                self.state[key] = 1

        if self.input_of(node_id, "reset").strip():
            if self.committing:
                self.state[key] = 1
                self.state[wrap_key] = False
            current = 1
        elif any(n == node_id and k == "advance"
                 for (n, k) in self.graph.wires):
            if self._rising_edge(node_id,
                                 bool(self.input_of(node_id,
                                                    "advance").strip())):
                current = current % steps + 1
                if self.committing:
                    self.state[key] = current
                    self.state[wrap_key] = current == 1
        elif seconds:
            # free-running: derived from the clock so it does not drift
            # with the send interval, and so two Steps with the same
            # settings stay together
            offset = int(time.time() / seconds) % steps
            previous = self.state.get(("step_offset", node_id))
            current = offset + 1
            if self.committing:
                self.state[key] = current
                self.state[wrap_key] = (previous is not None
                                        and previous != offset
                                        and current == 1)
                self.state[("step_offset", node_id)] = offset

        if socket == "wrapped":
            return "1" if self.state.get(wrap_key) else ""
        return str(current)

    def _timer(self, node_id, values):
        try:
            seconds = max(1, int(values.get("seconds", 10)))
        except (TypeError, ValueError):
            seconds = 10
        now = time.time()
        pulse = str(values.get("mode", "blink")) == "pulse"

        if any(n == node_id and k == "start" for (n, k) in self.graph.wires):
            # counting from an event rather than from the clock
            key = ("timer_since", node_id)
            if not self.input_of(node_id, "start").strip():
                # Start went away: forget when it began, so the next
                # time it comes back the count starts over instead of
                # firing immediately on a stale timestamp
                if self.committing:
                    self.state.pop(key, None)
                return ""
            since = self.state.get(key)
            if since is None:
                if self.committing:
                    self.state[key] = now
                return "" if pulse else "1"
            elapsed = now - since
            if not pulse:
                # blink keeps blinking when it is started by something -
                # measured from the start instead of from the clock, so
                # it lines up with whatever switched it on. Anything
                # else would make blink mean "delay", which is what
                # pulse is already for.
                return "1" if int(elapsed / seconds) % 2 == 0 else ""
            if elapsed < seconds:
                return ""
            if self.committing:
                self.state[key] = now      # and round again
            return "1"

        if not pulse:
            # stateless on purpose: two blink blocks with the same
            # interval stay in step, and a restart does not reset them
            return "1" if int(now / seconds) % 2 == 0 else ""
        key = ("pulse", node_id)
        last = self.state.get(key)
        if last is None:
            # a fresh pulse waits out its first interval instead of
            # firing the moment the app starts
            if self.committing:
                self.state[key] = now
            return ""
        if now - last < seconds:
            return ""
        if self.committing:
            self.state[key] = now
        return "1"

    def run_side_effects(self):
        """Evaluates the blocks that do something. Only called on the
        commit pass, so a preview never writes to the avatar."""
        if not self.committing:
            return
        for node_id in self.graph.side_effect_nodes():
            entry = self.graph.nodes.get(node_id) or {}
            values = _values_of(entry)
            kind = entry.get("type")
            if kind == "aio_change":
                if self.input_of(node_id, "trigger").strip():
                    self.actions.append(
                        ("aio_change", str(values.get("target", "next"))))
                continue
            if kind == "osc_out":
                self._osc_out(node_id, values)
                continue
            if kind == "ext_osc_out":
                self._ext_osc_out(node_id, values)
                continue
            if kind == "hotkey":
                self._hotkey(node_id, values)
                continue
            if kind == "run_program":
                self._run_program(node_id, values)

    def _trigger_wired(self, node_id):
        return any(n == node_id and k == "trigger"
                   for (n, k) in self.graph.wires)

    def _rising_edge(self, node_id, truthy):
        """True only on the frame the input turns true.

        A hotkey is an action, not a state: holding the avatar toggle on
        must press the combination once, not forty times a minute for as
        long as it stays on.
        """
        key = ("edge", node_id)
        was = bool(self.state.get(key))
        self.state[key] = truthy
        return truthy and not was

    def _ext_osc_out(self, node_id, values):
        address = str(values.get("address", "")).strip()
        if not address:
            return
        if not address.startswith("/"):
            address = "/" + address
        text = self.input_of(node_id, "value")
        if self._trigger_wired(node_id):
            if not self.input_of(node_id, "trigger").strip():
                return
        else:
            key = ("ext_osc", node_id)
            if self.state.get(key) == text:
                return
            self.state[key] = text
        payload = coerce_value(text, str(values.get("type", "auto")))
        if payload is None:
            return
        try:
            port = int(values.get("port", 0) or 0)
        except (TypeError, ValueError):
            port = 0
        self.actions.append(("osc_raw", str(values.get("ip", "")).strip(),
                             port, address, payload))

    def _hotkey(self, node_id, values):
        combo = str(values.get("keys", "")).strip()
        if not combo:
            return
        if not self._trigger_wired(node_id):
            # without a trigger there is no "turns true" to react to, and
            # firing every send would hammer the key forever
            return
        if self._rising_edge(node_id,
                             bool(self.input_of(node_id, "trigger").strip())):
            self.actions.append(("hotkey", combo))

    def _run_program(self, node_id, values):
        command = str(values.get("command", "")).strip()
        if not command or not self._trigger_wired(node_id):
            # without a trigger there is no "turns true" to react to, and
            # launching on every send would open a window a minute
            return
        if self._rising_edge(node_id,
                             bool(self.input_of(node_id, "trigger").strip())):
            self.actions.append(
                ("run_program", command,
                 str(values.get("debug", "off")) == "on"))

    def _osc_out(self, node_id, values):
        name = str(values.get("name", "")).strip()
        if not name:
            return
        text = self.input_of(node_id, "value")
        if self._trigger_wired(node_id):
            if not self.input_of(node_id, "trigger").strip():
                return
        else:
            # no trigger wired: send when the value changed, not on every
            # frame - VRChat does not need the same bool forty times a
            # minute and the rate limiter is for the chatbox, not for this
            key = ("osc_out", node_id)
            if self.state.get(key) == text:
                return
            self.state[key] = text
        payload = coerce_value(text, str(values.get("type", "bool")))
        if payload is None:
            return
        self.actions.append(("osc_set", name, payload))

    @staticmethod
    def _compare(op, a, b):
        if op == "contains":
            return "1" if b.strip() and b.strip() in a else ""
        if op == "==":
            return "1" if a.strip() == b.strip() else ""
        if op == "!=":
            return "1" if a.strip() != b.strip() else ""
        # < and > compare as numbers when both sides look like numbers,
        # and fall back to the string order otherwise - "10" vs "9" is
        # the whole reason this is not just a string compare
        na, nb = _as_number(a), _as_number(b)
        if na is not None and nb is not None:
            left, right = na, nb
        else:
            left, right = a.strip(), b.strip()
        try:
            return "1" if (left < right if op == "<" else left > right) else ""
        except TypeError:
            return ""


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def evaluate(graph, values, osc=None, state=None, actions=None,
             keys=None, procs=None, shown=False):
    """The text of one canvas, raw.

    "Raw" means \\n is still two characters and the tidy pass has not
    run - core.textutils.finish_template() does that, and the caller
    runs it once on the finished string.

    ``actions`` turns this into the commit pass: hand in a list and the
    blocks with side effects run and append what they want done
    (``("osc_set", name, value)`` / ``("aio_change", target)``). Leave it
    out and the graph is read-only, which is what the preview needs.
    """
    g = _Graph(graph)
    ev = _Evaluator(g, values, osc=osc, state=state, actions=actions,
                    keys=keys, procs=procs, shown=shown)
    node_id = g.output()
    text = ev.output_of(node_id, "in") if node_id else ""
    ev.run_side_effects()
    return text


def has_side_effects(graph):
    """True when this canvas contains a block that DOES something -
    Set parameter, External OSC out, Send Hotkey, Change AIO."""
    return any(entry.get("type") in SIDE_EFFECT_TYPES
               for entry in _Graph(graph).nodes.values())


def run_side_effects(graph, values, osc=None, state=None, keys=None,
                     procs=None, shown=False):
    """Runs only the blocks with side effects, ignoring any text.

    Separate from evaluate() because automation and display are two
    different questions: which string is on screen decides what is sent
    to the chatbox, but a canvas that only presses a hotkey has no
    string at all and still has to run.
    """
    g = _Graph(graph)
    actions = []
    ev = _Evaluator(g, values, osc=osc, state=state, actions=actions,
                    keys=keys, procs=procs, shown=shown)
    # Pull on the output first, even though the text is thrown away.
    # Blocks that keep state - a pulse Timer, a Step - only move on when
    # something reads them AND the pass is a commit. Nothing pulls on
    # them from the side-effect side, and the pass that builds the text
    # is not a commit, so without this a Step wired into nothing but
    # Info blocks would sit on 1 forever.
    node_id = g.output()
    if node_id:
        ev.output_of(node_id, "in")
    ev.run_side_effects()
    return actions


def output_ids(graph):
    """Every Chatbox Output block on this canvas, in the order the
    evaluator would pick them. Only the first one is used - this exists
    so the UI can say so."""
    return [node_id for node_id, entry in sorted(_Graph(graph).nodes.items())
            if entry.get("type") == "output"]


def has_output(graph):
    """True when this canvas ends in a Chatbox Output block.

    Structural on purpose: it answers "does this slot exist" for the
    rotation, and a slot must not drop out of the rotation just because
    the song it shows happens to be paused this second.
    """
    return _Graph(graph).output() is not None


def node_count(graph):
    return len(_Graph(graph).nodes)


def literals(graph):
    """Every literal the blocks of this canvas carry, joined together and
    NOT resolved.

    Two callers need the string before substitution rather than after:
    the Custom Box, which asks whether the message places {box_start}
    itself, and the MediaPlay idle symbol, which asks whether an empty
    result was a line about a song. Both search for placeholder names, so
    they have to look at what was written, not at what it turned into.
    """
    g = _Graph(graph)
    node_id = g.output()
    if node_id is None:
        return ""
    seen = set()
    parts = []

    def walk(current):
        if current in seen or len(seen) > MAX_STEPS:
            return
        seen.add(current)
        entry = g.nodes.get(current)
        if entry is None:
            return
        kind = entry.get("type")
        values = _values_of(entry)
        if kind == "text":
            parts.append(str(values.get("value", "")))
        elif kind == "placeholder":
            name = str(values.get("name", "")).strip().lstrip("{").rstrip("}")
            if name:
                parts.append("{%s}" % name)
        elif kind in ("status", "status_single"):
            # not in SOURCE_MAP: which placeholder these mean depends on
            # their fields, so they answer for themselves
            template = str(values.get("template", "active")).strip().lower()
            prefix = "text" if template in ("", "active") \
                else f"text_t{template}"
            if kind == "status":
                parts.append("{%s}" % prefix)
            else:
                parts.append("{%s_%s}" % (prefix, values.get("entry", 1)))
        elif kind in SOURCE_MAP:
            # a MediaPlay block IS a request for those values, even
            # though nobody typed {title} anywhere
            parts.extend("{%s}" % p for p in SOURCE_MAP[kind].values())
        for (dst, _in_key), (src, _out_key) in g.wires.items():
            if dst == current:
                walk(src)

    walk(node_id)
    return " ".join(p for p in parts if p)
