"""
ui/pages/placeholder_picker.py - the "+" menu next to a template field

The vocabulary has grown past the point where a hint line under the field
can carry it: five apps, ten status templates with twenty slots each, the
Custom Box, the formatting tags and whatever the installed plugins bring.
Nobody is going to type {text_t7_13} from memory, and scrolling a wall of
grey hint text to find {time_status} is not much better.

So the names live in a menu instead, grouped the way somebody looking for
one would think about it, and clicking inserts at the cursor.

The grouping only helps as long as you know which group a name is in.
Past a few hundred entries - which is where the plugins put us - that
stopped being true, so the menu opens with a SEARCH LINE and a scope
selector next to it:

    Everywhere        every name this field can resolve
    This app          only the built-in ones, no plugins
    <plugin name>     only what that plugin brings

Typing filters to a flat list of hits, each one carrying the group it
came from, so the answer to "where did {hmd_battery} come from" is in the
result rather than three folders away. Picking a plugin with the box
empty simply lists everything that plugin offers.

Three details worth knowing:

* The menu is rebuilt on every click, never cached. Plugins are installed,
  removed and renamed at runtime, and status templates get filled in while
  the field is open - a menu built once at startup would be lying within
  minutes.

* The cursor position and the selection are read BEFORE the menu opens.
  A popup takes the focus, and a QLineEdit that lost focus does not
  reliably report what was selected. Everything is applied to the state
  captured up front.

* The browse entries and the search index come from the SAME item lists
  (the _*_items helpers below). Two hand-written copies of four hundred
  names would drift apart on the first plugin that changes something,
  and a name that is findable but not browsable is a bug report.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLineEdit,
                             QMenu, QWidget, QWidgetAction)

from ui.pages.placeholder_complete import PlaceholderCompleter

#: (label, what to insert). A tuple of two strings means a WRAPPER:
#: selected text goes between them, and with no selection the cursor is
#: parked in the middle so the next thing typed lands inside.
FORMATTING = (
    ("\\n   \u2013  line break", "\\n"),
    None,                                   # separator
    ("{sup}\u2026{/sup}   \u2013  superscript  \u1D34\u1D2C\u1D38\u1D38"
     "\u1D3C", ("{sup}", "{/sup}")),
    ("{sub}\u2026{/sub}   \u2013  subscript  \u2095\u2090\u2097\u2097"
     "\u2092", ("{sub}", "{/sub}")),
    None,
    ('_"word"_   \u2013  keep this word unstyled', '_"word"_'),
)
# The older {super/"word"} / {sub/"word"} form is deliberately NOT in this
# menu. The tag pair does everything it does and more - it spans several
# placeholders, and selecting text first wraps it - so offering both would
# mean two entries for one job and a decision nobody wants to make. The
# engine still understands the slash form (core/textstyle.py), so strings
# written before this menu existed keep working.

HARDWARE_GROUPS = (
    ("GPU", (
        ("{gpu_name}", "name"),
        ("{gpu_usage}", "load in %"),
        ("{gpu_temp}", "temperature"),
        ("{gpu_power}", "power draw in watts - needs the GPU watt tick"),
        ("{vram_usage}", "VRAM used / total"),
        ("{vram_pct}", "VRAM in %"),
    )),
    ("CPU", (
        ("{cpu_name}", "name"),
        ("{cpu_usage}", "load in %"),
        ("{cpu_temp}", "temperature"),
        ("{cpu_power}", "power draw in watts - needs the CPU watt tick"),
    )),
    ("RAM & System", (
        ("{ram_usage}", "RAM used / total"),
        ("{ram_pct}", "RAM in %"),
        ("{ram_type}", "the label you typed, e.g. DDR5"),
        ("{fps}", "frames per second"),
        ("{temp_icon}", "the temperature unit (\u00b0C or \U0001F525)"),
    )),
)

MEDIA_ITEMS = (
    ("{artist}", "artist"),
    ("{title}", "song title"),
    ("{album}", "album"),
    ("{time}", "elapsed / total"),
    ("{time_status}", "elapsed with the play/pause symbol"),
    ("{time_end}", "total length"),
    ("{bar}", "progress bar"),
    ("{lyrics}", "current line, synced via LRCLIB"),
    ("{lyrics_prefix}", "the symbol in front of the lyrics"),
)

BOX_ITEMS = (
    ("{box_start}", "the frame line above everything"),
    ("{box_stop}", "the frame line below everything"),
    ("{box_text}", "the Custom Box middle text"),
)

#: Grouped by source. {text_*} answers for whichever of the three sent
#: last; the others answer only for their own, so exactly one of them is
#: ever filled - which is what lets a string route speech and typing to
#: different places.
CHAT_GROUPS = (
    ("Any source", (
        ("{text_input}", "what was typed or said, whichever sent last"),
        ("{text_output}", "what actually went out (the translation)"),
    )),
    ("Speech to Text only", (
        ("{stt_input}", "what you said"),
        ("{stt_output}", "what went out (the translation)"),
    )),
    ("Text to Text only", (
        ("{ttt_input}", "what you typed into the To Text field"),
        ("{ttt_output}", "what went out (the translation)"),
    )),
    ("Chat card only", (
        ("{chat_input}", "what you typed into the Chat field"),
        ("{chat_output}", "what went out"),
    )),
)

#: how many hits the flat result list shows before it stops and says how
#: many more there are. A menu longer than the screen scrolls one line at
#: a time, which is worse than being told to type another letter.
MAX_RESULTS = 50

#: scope keys for the selector. Anything else is a plugin id.
SCOPE_ALL = None
SCOPE_APP = "\x00app"
#: a single built-in section ("Personal Status", "Hardware", ...). The
#: section is the first step of an entry's path, so nothing has to be
#: tagged twice - see _PickerSearch._sections().
SCOPE_SECTION = "\x00sec:"
#: how a path spells its steps
PATH_SEP = " \u203a "


class _PickerSearchLine(QLineEdit):
    """The search box that lives inside the menu.

    A QMenu grabs the keyboard, so the keys that steer the menu have to
    be handed back to it: Down walks into the results, Escape closes the
    whole thing, Enter takes the first hit. Everything else is ordinary
    typing and stays here.
    """

    def __init__(self, parent=None, on_accept=None):
        super().__init__(parent)
        self._on_accept = on_accept

    def _menu(self):
        w = self.parent()
        while w is not None and not isinstance(w, QMenu):
            w = w.parent()
        return w

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._on_accept is not None:
                self._on_accept()
            return
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Escape,
                   Qt.Key.Key_Tab):
            menu = self._menu()
            if menu is not None:
                self.clearFocus()      # the menu highlights entries again
                QApplication.sendEvent(menu, event)
                return
        super().keyPressEvent(event)


class _PickerSearch:
    """Search line + scope selector + the flat result list under it.

    The result actions are created once, hidden, and only relabelled
    afterwards - adding and removing actions from a menu that is already
    on screen makes it jump around under the cursor.
    """

    STYLE = ("QLineEdit { background: #14161c; border: 1px solid #333947;"
             " border-radius: 6px; color: #d7dae0; padding: 4px 8px; }"
             "QLineEdit:focus { border-color: #5b8dc9; }"
             "QComboBox { background: #14161c; border: 1px solid #333947;"
             " border-radius: 6px; color: #d7dae0; padding: 3px 8px; }"
             "QComboBox::drop-down { border: none; width: 16px; }")

    def __init__(self, menu, entries, sources, on_pick):
        self.menu = menu
        self.entries = entries
        self.on_pick = on_pick
        self.browse = []

        row = QWidget(menu)
        row.setStyleSheet(self.STYLE)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(6)
        self.line = _PickerSearchLine(row, on_accept=self._accept)
        self.line.setPlaceholderText(
            "Search  \u2013  gpu, battery, lyrics \u2026")
        self.line.setClearButtonEnabled(True)
        self.line.setMinimumWidth(240)
        lay.addWidget(self.line, 1)
        self.combo = QComboBox(row)
        self.combo.addItem("Everywhere", SCOPE_ALL)
        sections = self._sections()
        if sources or len(sections) > 1:
            if sources:
                self.combo.addItem("This app", SCOPE_APP)
            # the built-in groups, so "only the status slots" or "only
            # the hardware values" is one pick rather than a word you
            # have to guess is in every description
            if len(sections) > 1:
                if sources:
                    self.combo.insertSeparator(self.combo.count())
                for name in sections:
                    self.combo.addItem(f"\u2003{name}",
                                       SCOPE_SECTION + name)
            if sources:
                self.combo.insertSeparator(self.combo.count())
                for key, label in sources:
                    self.combo.addItem(f"\u2003{label}", key)
        else:
            # nothing to narrow down to - one entry that can only mean
            # "everything" is a control that does nothing
            self.combo.setVisible(False)
        self.combo.setMinimumWidth(120)
        lay.addWidget(self.combo, 0)

        holder = QWidgetAction(menu)
        holder.setDefaultWidget(row)
        menu.addAction(holder)
        self.separator = menu.addSeparator()

        self.results = []
        for _ in range(MAX_RESULTS):
            act = QAction("", menu)
            act.setVisible(False)
            act.triggered.connect(
                lambda _=False, a=act: self._pick(a))
            menu.addAction(act)
            self.results.append(act)
        self.note = QAction("", menu)
        self.note.setEnabled(False)
        self.note.setVisible(False)
        menu.addAction(self.note)

        self._browse_from = len(menu.actions())
        self.line.textChanged.connect(lambda _: self.refresh())
        self.combo.currentIndexChanged.connect(lambda _: self.refresh())

    # ------------------------------------------------------------------
    def attach_browse(self):
        """Everything added after the search block is the browse tree.

        Called once the menu is fully built, because the grouped entries
        have to disappear while a search is running - a result list with
        seven closed folders hanging underneath reads as "nothing found".
        """
        self.browse = self.menu.actions()[self._browse_from:]

    def _pick(self, action):
        payload = action.data()
        if payload is not None:
            self.on_pick(payload)

    def _accept(self):
        """Enter takes the first hit, which is what the box is for."""
        for act in self.results:
            if act.isVisible():
                act.trigger()
                self.menu.close()
                return

    def _sections(self):
        """The built-in groups, in the order the browse tree shows them.

        Taken from the first step of each entry's path rather than from a
        second hand-written list - a group that gets renamed or added
        upstairs is in the selector without anybody remembering to put it
        there.
        """
        names = []
        for _payload, _name, _note, path, key in self.entries:
            if key != "app" or not path:
                continue
            head = path.split(PATH_SEP)[0].strip()
            if head and head not in names:
                names.append(head)
        return names

    @staticmethod
    def _in_scope(scope, path, key):
        if scope == SCOPE_ALL:
            return True
        if scope == SCOPE_APP:
            return key == "app"
        if isinstance(scope, str) and scope.startswith(SCOPE_SECTION):
            wanted = scope[len(SCOPE_SECTION):]
            return (path or "").split(PATH_SEP)[0].strip() == wanted
        return key == scope

    def _matches(self, query, scope):
        hits = []
        for payload, name, note, path, key in self.entries:
            if not self._in_scope(scope, path, key):
                continue
            if query:
                hay = f"{name} {note} {path}".lower()
                if query not in hay:
                    continue
                # a name that literally contains what was typed beats one
                # that only matches on its description
                rank = 0 if query in name.lower() else 1
            else:
                rank = 0
            hits.append((rank, len(hits), payload, name, note, path))
        hits.sort(key=lambda h: (h[0], h[1]))
        return hits

    def refresh(self):
        query = self.line.text().strip().lower()
        scope = self.combo.currentData()
        # empty box AND no narrowing: the ordinary grouped menu
        if not query and scope == SCOPE_ALL:
            for act in self.results:
                act.setVisible(False)
            self.note.setVisible(False)
            self.separator.setVisible(bool(self.browse))
            for act in self.browse:
                act.setVisible(True)
            self._resize()
            return
        for act in self.browse:
            act.setVisible(False)
        self.separator.setVisible(True)
        hits = self._matches(query, scope)
        for i, act in enumerate(self.results):
            if i < len(hits):
                _rank, _idx, payload, name, note, path = hits[i]
                label = f"{name}   \u2013  {note}" if note else name
                act.setText(f"{label}      \u00b7  {path}")
                act.setData(payload)
                act.setVisible(True)
            else:
                act.setData(None)
                act.setVisible(False)
        if not hits:
            self.note.setText("nothing found here \u2013 try Everywhere")
            self.note.setVisible(True)
        elif len(hits) > MAX_RESULTS:
            self.note.setText(
                f"\u2026 and {len(hits) - MAX_RESULTS} more \u2013 "
                f"type another letter")
            self.note.setVisible(True)
        else:
            self.note.setVisible(False)
        self._resize()

    def _resize(self):
        """A menu sizes itself when it pops up, not when its entries come
        and go afterwards - without this the result list is drawn into
        the geometry the grouped menu happened to need."""
        self.menu.resize(self.menu.sizeHint())


class PlaceholderPickerMixin:
    """Adds open_placeholder_menu() to MainWindow."""

    # ---------------------------------------------------------- inserting
    @staticmethod
    def _capture(edit):
        """(cursor, selection_start, selected_text) before the popup takes
        the focus and the selection stops being readable."""
        start = edit.selectionStart()
        return (edit.cursorPosition(), start,
                edit.selectedText() if start >= 0 else "")

    def _insert_placeholder(self, edit, payload, state):
        """Puts `payload` into `edit` at the captured position.

        A plain string is inserted, replacing whatever was selected. A
        (open, close) pair wraps the selection instead - which is the
        whole point of the formatting entries, since "make THIS bit
        small" is the thing you actually want to say.
        """
        cursor, sel_start, sel_text = state
        text = edit.text()
        if isinstance(payload, tuple):
            open_tag, close_tag = payload
            if sel_text:
                new = (text[:sel_start] + open_tag + sel_text + close_tag
                       + text[sel_start + len(sel_text):])
                caret = sel_start + len(open_tag) + len(sel_text) \
                    + len(close_tag)
            else:
                new = text[:cursor] + open_tag + close_tag + text[cursor:]
                # between the tags, so whatever is typed next is styled
                caret = cursor + len(open_tag)
        else:
            if sel_text:
                new = (text[:sel_start] + payload
                       + text[sel_start + len(sel_text):])
                caret = sel_start + len(payload)
            else:
                new = text[:cursor] + payload + text[cursor:]
                caret = cursor + len(payload)
        limit = edit.maxLength()
        if limit and len(new) > limit:
            # Silently truncating would corrupt a placeholder halfway
            # through and leave a stray "{gpu_pow" in the string, which
            # renders as nothing and looks like the picker is broken.
            self.log(f"Picker: no room left for {payload!r} \u2013 the "
                     f"field is limited to {limit} characters.")
            return
        edit.setText(new)
        edit.setCursorPosition(caret)
        edit.setFocus()

    def _add_items(self, menu, items, edit, state):
        """items = ((placeholder, description), ...)"""
        for name, note in items:
            act = QAction(f"{name}   \u2013  {note}" if note else name, menu)
            act.triggered.connect(
                lambda _=False, n=name: self._insert_placeholder(
                    edit, n, state))
            menu.addAction(act)

    # --------------------------------------------------------- item lists
    # One source of truth per group: the browse menus below and the search
    # index both read these, so a name can never be in one and not in the
    # other.
    @staticmethod
    def _slot_items(texts, prefix):
        """The twenty numbered slots of one status template.

        The text itself is the description - a menu of twenty identical
        looking entries is useless, and the slot you want is the one you
        recognise by what is in it.
        """
        items = []
        for i in range(1, 21):
            preview = ""
            if i <= len(texts) and str(texts[i - 1]).strip():
                preview = str(texts[i - 1]).strip()[:32]
            items.append((f"{{{prefix}{i}}}", preview))
        return items

    def _status_template_label(self, t):
        """"T3  (active)  -  Feeling good" for the templates submenu."""
        tpls = self.cfg.get("status_templates") or []
        active = int(self.cfg.get("status_template_active", 0))
        tpl = tpls[t - 1] if t - 1 < len(tpls) else {}
        texts = tpl.get("texts") or []
        filled = [str(x).strip() for x in texts if str(x).strip()]
        label = f"T{t}"
        if t - 1 == active:
            label += "  (active)"
        if filled:
            label += f"   \u2013  {filled[0][:24]}"
        return label, texts

    @staticmethod
    def _plugin_items(plugin):
        items = [(f"{{{plugin.pid}}}", "the plugin's own line")]
        for key, note in (plugin.placeholders or {}).items():
            items.append((f"{{{plugin.pid}_{key}}}", note or key))
        for key in sorted(plugin.global_keys or ()):
            items.append((f"{{{key}}}", "claimed by this plugin"))
        return items

    @staticmethod
    def _plugin_own_items(plugin):
        """The plugin's own line plus its {pid_key} names."""
        items = [(f"{{{plugin.pid}}}", "the plugin's own line")]
        for key, note in (plugin.placeholders or {}).items():
            items.append((f"{{{plugin.pid}_{key}}}", note or key))
        return items

    @staticmethod
    def _plugin_alias_items(plugin):
        """The short names a plugin claimed without its own prefix.

        Kept apart from the list above because they are the same values
        under a second name: fifteen lines of "claimed by this plugin"
        below the real ones is noise you have to scroll past every time.
        """
        return [(f"{{{key}}}", "same value, short name")
                for key in sorted(plugin.global_keys or ())]

    def _supported_plugins(self):
        return [p for p in self.plugins.ordered() if p.supported]

    # ------------------------------------------------------------- submenus
    def _status_menu(self, parent, edit, state):
        m = parent.addMenu("Personal Status")
        self._add_items(m, (("{text}", "the rotating status text"),),
                        edit, state)
        slots = m.addMenu("Slots  (active template)")
        self._add_items(slots, self._slot_items(
            self.cfg.get("status_texts") or [], "text_"), edit, state)

        spec = m.addMenu("Specific templates")
        for t in range(1, 11):
            label, texts = self._status_template_label(t)
            sub = spec.addMenu(label)
            self._add_items(
                sub, ((f"{{text_t{t}}}", "the rotating text of this "
                                         "template"),), edit, state)
            sub.addSeparator()
            self._add_items(sub, self._slot_items(texts, f"text_t{t}_"),
                            edit, state)

    def _plugin_menu(self, parent, plugin, edit, state):
        """One plugin's submenu: its own names first, aliases folded away."""
        sub = parent.addMenu(plugin.name or plugin.pid)
        self._add_items(sub, self._plugin_own_items(plugin), edit, state)
        aliases = self._plugin_alias_items(plugin)
        if aliases:
            sub.addSeparator()
            self._add_items(sub.addMenu(f"Short names ({len(aliases)})"),
                            aliases, edit, state)
        return sub

    def _plugins_menu(self, parent, edit, state):
        """Every placeholder the installed plugins offer.

        Built from the manifests rather than from the last snapshot, so a
        plugin that happens to be switched off or has not produced a value
        yet still shows what it CAN provide - otherwise the menu would be
        empty exactly when you are setting things up.
        """
        plugins = self._supported_plugins()
        m = parent.addMenu(f"Plugins ({len(plugins)})" if plugins
                           else "Plugins")
        if not plugins:
            act = QAction("no plugins installed", m)
            act.setEnabled(False)
            m.addAction(act)
            return
        for plugin in plugins:
            self._plugin_menu(m, plugin, edit, state)

    def _add_formatting(self, menu, edit, state):
        fmt = menu.addMenu("Formatting")
        for entry in FORMATTING:
            if entry is None:
                fmt.addSeparator()
                continue
            label, payload = entry
            act = QAction(label, fmt)
            act.triggered.connect(
                lambda _=False, p=payload: self._insert_placeholder(
                    edit, p, state))
            fmt.addAction(act)

    def _plugin_scope_menu(self, menu, edit, state, pid):
        """The vocabulary a PLUGIN's own custom string can use.

        Deliberately not the full list: a plugin template is rendered
        against raw_values() (see PluginManager.values()), so hardware
        and media placeholders would come out empty. Offering them would
        be offering something that cannot work.

        It is not limited to the one plugin either, because raw_values()
        holds every plugin's keys - referencing another plugin is legal,
        so it is in the menu, just not first.
        """
        plugins = self._supported_plugins()
        own = [p for p in plugins if p.pid == pid]
        others = [p for p in plugins if p.pid != pid]
        for plugin in own:
            self._add_items(menu, self._plugin_own_items(plugin), edit, state)
            aliases = self._plugin_alias_items(plugin)
            if aliases:
                self._add_items(
                    menu.addMenu(f"Short names ({len(aliases)})"),
                    aliases, edit, state)
        if not own:
            act = QAction("this plugin offers no placeholders", menu)
            act.setEnabled(False)
            menu.addAction(act)
        if others:
            menu.addSeparator()
            other = menu.addMenu(f"Other plugins ({len(others)})")
            for plugin in others:
                self._plugin_menu(other, plugin, edit, state)

    # -------------------------------------------------------- search index
    def _picker_entries(self, scope=None, pid=None):
        """[(payload, name, note, path, source_key)] for the search line.

        `path` is the trail the same entry sits under in the grouped menu,
        so a hit answers "where is this normally" on the spot. `source_key`
        is "app" for everything built in and the plugin id otherwise -
        that is what the scope selector filters on.
        """
        entries = []

        def add(items, path, key="app"):
            for name, note in items:
                entries.append((name, name, note, path, key))

        for entry in FORMATTING:
            if entry is None:
                continue
            label, payload = entry
            name = label.split("   ")[0]
            entries.append((payload, name, "", "Formatting", "app"))

        if scope == "hardware":
            for group, items in HARDWARE_GROUPS:
                add(items, group)
            add((("{icon_flame}", "the flame symbol"),), "Hardware")
            return entries
        if scope == "media":
            add(MEDIA_ITEMS, "Media")
            return entries
        if scope == "plugin":
            plugins = self._supported_plugins()
            for plugin in plugins:
                label = plugin.name or plugin.pid
                if plugin.pid != pid:
                    label = f"Other \u203a {label}"
                add(self._plugin_own_items(plugin), label, plugin.pid)
                add(self._plugin_alias_items(plugin),
                    f"{label} \u203a short", plugin.pid)
            return entries

        add((("{text}", "the rotating status text"),), "Personal Status")
        add(self._slot_items(self.cfg.get("status_texts") or [], "text_"),
            "Personal Status \u203a Slots")
        for t in range(1, 11):
            label, texts = self._status_template_label(t)
            path = f"Personal Status \u203a {label.split('   ')[0]}"
            add(((f"{{text_t{t}}}", "the rotating text of this template"),),
                path)
            add(self._slot_items(texts, f"text_t{t}_"), path)
        for group, items in HARDWARE_GROUPS:
            add(items, f"Hardware \u203a {group}")
        add(MEDIA_ITEMS, "Media")
        add(BOX_ITEMS, "Custom Box")
        for group, items in CHAT_GROUPS:
            add(items, f"Chat / Speech to Text \u203a {group}")
        for plugin in self._supported_plugins():
            label = plugin.name or plugin.pid
            add(self._plugin_own_items(plugin), f"Plugins \u203a {label}",
                plugin.pid)
            add(self._plugin_alias_items(plugin),
                f"Plugins \u203a {label} \u203a short", plugin.pid)
        return entries

    def _picker_sources(self, scope=None, pid=None):
        """The scope selector's plugin entries, in the Plugins page order."""
        plugins = self._supported_plugins()
        if scope in ("hardware", "media"):
            return []
        if scope == "plugin":
            # the field's own plugin first - it is the one you mean
            plugins = ([p for p in plugins if p.pid == pid]
                       + [p for p in plugins if p.pid != pid])
        return [(p.pid, p.name or p.pid) for p in plugins]

    # ----------------------------------------------------------- completion
    def attach_placeholder_completer(self, edit, scope=None, pid=None):
        """Types-ahead for one template field.

        Same `scope` / `pid` as open_placeholder_menu(), and for the same
        reason: a field only completes what it can actually resolve.

        The index is rebuilt per keystroke rather than handed over once,
        because status texts get typed and plugins get installed while a
        field is open, and a suggestion list that is a snapshot of
        startup would offer names that are gone and miss the ones that
        matter.
        """
        return PlaceholderCompleter(
            edit, lambda: self._picker_entries(scope, pid), log=self.log)

    # ---------------------------------------------------------------- entry
    def open_placeholder_menu(self, edit, button, scope=None, pid=None):
        """Opens the picker under `button` and inserts into `edit`.

        `scope` narrows the menu to what the field can actually resolve:

            None         everything - All in one, which sees all of it
            "hardware"   the Hardware card's custom string
            "media"      the MediaPlay custom string
            "plugin"     a plugin's custom string (`pid` says which)

        A card whose custom string only understands its own values has no
        business offering the other four hundred names: every extra entry
        is one more thing to scroll past, and picking one would silently
        produce an empty string.
        """
        state = self._capture(edit)
        menu = QMenu(button)

        # The search block goes in first so it stays at the top, but it
        # can only know what the browse tree holds because both are fed
        # from the same item lists (see _picker_entries).
        search = None
        if scope not in ("hardware", "media"):
            # Hardware and Media are a dozen entries in three folders -
            # a search box there is a control looking for a job.
            search = _PickerSearch(
                menu, self._picker_entries(scope, pid),
                self._picker_sources(scope, pid),
                lambda payload: self._insert_placeholder(edit, payload, state))

        self._add_formatting(menu, edit, state)
        menu.addSeparator()

        if scope == "hardware":
            # flattened: the whole menu is hardware already, so wrapping
            # it in a "Hardware" submenu would be one pointless click
            for group, items in HARDWARE_GROUPS:
                self._add_items(menu.addMenu(group), items, edit, state)
            self._add_items(menu, (("{icon_flame}", "the flame symbol"),),
                            edit, state)
            return self._show(menu, button)
        if scope == "media":
            self._add_items(menu, MEDIA_ITEMS, edit, state)
            return self._show(menu, button)
        if scope == "plugin":
            self._plugin_scope_menu(menu, edit, state, pid)
            search.attach_browse()
            return self._show(menu, button, search)

        self._status_menu(menu, edit, state)
        hw = menu.addMenu("Hardware")
        for group, items in HARDWARE_GROUPS:
            sub = hw.addMenu(group)
            self._add_items(sub, items, edit, state)
        self._add_items(menu.addMenu("Media"), MEDIA_ITEMS, edit, state)
        self._add_items(menu.addMenu("Custom Box"), BOX_ITEMS, edit, state)
        chat = menu.addMenu("Chat / Speech to Text")
        for group, items in CHAT_GROUPS:
            self._add_items(chat.addMenu(group), items, edit, state)
        self._plugins_menu(menu, edit, state)
        search.attach_browse()
        return self._show(menu, button, search)

    @staticmethod
    def _show(menu, button, search=None):
        if search is not None:
            # exec() starts its own event loop, so a zero timer scheduled
            # here fires inside it - which is the first moment the line
            # edit exists on screen and can take the focus. Focusing it
            # before that would be handed straight back to the menu.
            QTimer.singleShot(0, search.line.setFocus)
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
