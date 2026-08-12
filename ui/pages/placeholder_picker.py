"""
ui/pages/placeholder_picker.py - the "+" menu next to a template field

The vocabulary has grown past the point where a hint line under the field
can carry it: five apps, ten status templates with twenty slots each, the
Custom Box, the formatting tags and whatever the installed plugins bring.
Nobody is going to type {text_t7_13} from memory, and scrolling a wall of
grey hint text to find {time_status} is not much better.

So the names live in a menu instead, grouped the way somebody looking for
one would think about it, and clicking inserts at the cursor.

Two details worth knowing:

* The menu is rebuilt on every click, never cached. Plugins are installed,
  removed and renamed at runtime, and status templates get filled in while
  the field is open - a menu built once at startup would be lying within
  minutes.

* The cursor position and the selection are read BEFORE the menu opens.
  A popup takes the focus, and a QLineEdit that lost focus does not
  reliably report what was selected. Everything is applied to the state
  captured up front.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu

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

    # ------------------------------------------------------------- submenus
    def _status_menu(self, parent, edit, state):
        m = parent.addMenu("Personal Status")
        self._add_items(m, (("{text}", "the rotating status text"),),
                        edit, state)

        slots = m.addMenu("Slots  (active template)")
        for i in range(1, 21):
            name = f"{{text_{i}}}"
            # the text itself as the hint - a menu of twenty identical
            # looking entries is useless, and the slot you want is the
            # one you recognise by what is in it
            preview = ""
            texts = self.cfg.get("status_texts") or []
            if i <= len(texts) and str(texts[i - 1]).strip():
                preview = f"   \u2013  {str(texts[i - 1]).strip()[:32]}"
            act = QAction(f"{name}{preview}", slots)
            act.triggered.connect(
                lambda _=False, n=name: self._insert_placeholder(
                    edit, n, state))
            slots.addAction(act)

        spec = m.addMenu("Specific templates")
        tpls = self.cfg.get("status_templates") or []
        active = int(self.cfg.get("status_template_active", 0))
        for t in range(1, 11):
            tpl = tpls[t - 1] if t - 1 < len(tpls) else {}
            texts = tpl.get("texts") or []
            filled = [str(x).strip() for x in texts if str(x).strip()]
            label = f"T{t}"
            if t - 1 == active:
                label += "  (active)"
            if filled:
                label += f"   \u2013  {filled[0][:24]}"
            sub = spec.addMenu(label)
            self._add_items(
                sub, ((f"{{text_t{t}}}", "the rotating text of this "
                                         "template"),), edit, state)
            sub.addSeparator()
            for i in range(1, 21):
                name = f"{{text_t{t}_{i}}}"
                preview = ""
                if i <= len(texts) and str(texts[i - 1]).strip():
                    preview = f"   \u2013  {str(texts[i - 1]).strip()[:32]}"
                act = QAction(f"{name}{preview}", sub)
                act.triggered.connect(
                    lambda _=False, n=name: self._insert_placeholder(
                        edit, n, state))
                sub.addAction(act)

    def _plugins_menu(self, parent, edit, state):
        """Every placeholder the installed plugins offer.

        Built from the manifests rather than from the last snapshot, so a
        plugin that happens to be switched off or has not produced a value
        yet still shows what it CAN provide - otherwise the menu would be
        empty exactly when you are setting things up.
        """
        plugins = [p for p in self.plugins.ordered() if p.supported]
        m = parent.addMenu(f"Plugins ({len(plugins)})" if plugins
                           else "Plugins")
        if not plugins:
            act = QAction("no plugins installed", m)
            act.setEnabled(False)
            m.addAction(act)
            return
        for plugin in plugins:
            sub = m.addMenu(plugin.name or plugin.pid)
            self._add_items(sub, self._plugin_items(plugin), edit, state)

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
        plugins = [p for p in self.plugins.ordered() if p.supported]
        own = [p for p in plugins if p.pid == pid]
        others = [p for p in plugins if p.pid != pid]
        for plugin in own:
            self._add_items(menu, self._plugin_items(plugin), edit, state)
        if not own:
            act = QAction("this plugin offers no placeholders", menu)
            act.setEnabled(False)
            menu.addAction(act)
        if others:
            menu.addSeparator()
            other = menu.addMenu(f"Other plugins ({len(others)})")
            for plugin in others:
                self._add_items(other.addMenu(plugin.name or plugin.pid),
                                self._plugin_items(plugin), edit, state)

    @staticmethod
    def _plugin_items(plugin):
        items = [(f"{{{plugin.pid}}}", "the plugin's own line")]
        for key, note in (plugin.placeholders or {}).items():
            items.append((f"{{{plugin.pid}_{key}}}", note or key))
        for key in sorted(plugin.global_keys or ()):
            items.append((f"{{{key}}}", "claimed by this plugin"))
        return items

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
            return self._show(menu, button)

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
        return self._show(menu, button)

    @staticmethod
    def _show(menu, button):
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
