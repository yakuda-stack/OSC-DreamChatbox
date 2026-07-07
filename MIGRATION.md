# Projektstruktur (bereinigt)

```
OSC-DreamChatbox/
├── osc_dreamchatbox.py      Entry-Point (nur GUI-Start)
├── start.sh                 startet die GUI ueber ./venv
├── core/                    Logik
│   ├── constants.py         App-Name, Version, Pfade, Chatbox-Konstanten
│   ├── textutils.py         fmt_time_hm, Songbar-Styles, Templates
│   ├── mediafetch.py        MPRIS/D-Bus MediaFetcher
│   ├── hardware.py          CPU/GPU/RAM-Monitoring
│   └── speechtotext.py      Speech-to-Text + Uebersetzung
└── ui/                      PyQt6-Oberflaeche
    ├── ui_main.py           Style, ToggleSwitch, DebugConsole, ...
    └── mainwindow.py        Hauptfenster (Text Apps, Textbox, Options)
```

## Entfernt in dieser Version
- "Addons"-Bereich KOMPLETT entfernt (Katalog, Installer, Updates,
  .desktop/Taskbar-Integration, Start Programs) – alles laeuft heute
  ueber OSCQuery, daher unnoetiger Ballast.
- "OSC Routing" KOMPLETT entfernt (UDP-Relay, Quellenliste,
  Managed Programs) inkl. core/oscrouter.py.
- DreamManager-CLI KOMPLETT entfernt (scripts/, start-programs,
  start-all, ...). osc_dreamchatbox.py ist wieder ein reiner
  GUI-Starter.
- Alte config.json-Keys (route_*) werden beim Laden ignoriert.
  Rueckstaende frueherer Addon-Installationen unter
  ~/.config/OSC-DreamChatbox/tool + taskbar sowie Symlinks in
  ~/.local/share/applications koennen manuell geloescht werden.

## Neu / geaendert
- Personal Status: bei mehreren Texten wird jetzt RANDOM
  durchgeschaltet statt der Reihe nach – nie zweimal derselbe Text
  hintereinander.
- Musicbar: 5 waehlbare Styles (Dropdown "Songbar style" in der
  MediaPlay-Karte, gespeichert als "media_bar_style" 0-5):
    1  [───●────────]
    2  ──■──            (kompakter Slider, halbe Laenge)
    3  [████████░░░░]   (Standard)
    4  ▰▰▰▰▰▰▰▰▱▱▱▱
    5  🎵🎵🎵🎵────────
    6  ▓▓▓▓▓░░░░░░░░    (klassischer Look der frueheren Version)
  Gilt fuer die Standard-Anzeige UND den {bar}-Platzhalter im
  Custom-String / AIO.
- Music-Timer OHNE Sekunden: Anzeige nur Stunde:Minute (h:mm),
  z.B. "0:03/0:04" – betrifft Zeitzeile, {position}, {length}, {time}.
