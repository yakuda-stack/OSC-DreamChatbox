# Changelog

All notable changes to OSC-DreamChatbox are documented here.

## [v1.2.1] – 2026-07-30

Plugin store, one-click plugin updates, and the fixes for the v1.2.0 AppImage and installer.

### Added
- **Plugin store.** The Plugins page now has two tabs: **Installed** and
  **Store**. The store shows a 4-per-row grid of tiles with the plugin's
  preview image, name, version and author; clicking a tile opens a detail view
  with the full description, an *Open on GitHub* link and one Install button.
  Plugins that are already installed are marked as such, and a newer version
  upstream shows as *Update →*.
- **`config/plugins.json` as the catalogue.** Adding a plugin to the store
  means pasting one GitHub link into `config/plugins.json` next to the app. Name, version,
  author, description and the preview image are read from the plugin's own
  `plugin.json`, so nothing has to be kept in sync by hand. Links to the repo
  root, to `/tree/<branch>/<folder>` and even straight to a `plugin.json` are
  all understood. Entries in
  `~/.config/OSC-DreamChatbox/plugins_sources.json` are merged on top, so your
  own additions survive an app update.
- **Two new `plugin.json` keys for store listings:** `image` (file in the
  plugin folder or a full URL) and `summary`. A plugin without an image gets a
  generated tile with its initials rather than a hole in the grid.
- **Install and update straight from GitHub.** Downloading, unpacking and
  installing runs on a worker thread, so a slow GitHub never freezes the
  window. Updates keep `configs/`, so settings survive.
- **Plugin updates in "Check for updates".** The Options button now checks the
  app *and* every installed plugin. If something is newer, a dialog lists the
  version jumps and updates them all with one click. The Store tab has its own
  *Update all* button for the same thing.
- **Self-updating plugin list.** Hitting **Refresh** in the store downloads
  the current `plugins.json` from GitHub and caches it in
  `~/.config/OSC-DreamChatbox/plugins.json`, so new plugins appear without
  updating the app at all. No version number has to be bumped for that.
  Writing to the config folder instead of back into the project folder is what
  makes this work for **AppImage** users (read-only squashfs), AUR installs
  (root-owned under `/usr`) and git checkouts (a modified file would break the
  next `git pull --ff-only`) alike. A network error never destroys the working
  list – the previous one keeps being used. The optional `version` key only
  decides one thing: a later app release shipping a strictly newer catalogue
  wins over the cache, which is then discarded. An ⬆ button at the top of the
  Plugins page still offers the update when the check runs outside the store.
- **New `slider` setting type** for plugins, rendered as a real slider with a
  live value label next to it (optional `suffix` for the label).
- **Nested plugin settings** via an optional `depends` key: a row is indented
  under its parent switch and hidden while that switch is off, the same way
  *Max length* sits under *Song title* on the MediaPlay card.

### Changed
- **World Stats 1.1.0:** the maximum world-name length is a slider now instead
  of a number field, and it sits indented under *World name*, appearing only
  while that is switched on. Preview image (`logo.png`) shown in the store.
- **Sidebar order:** Plugins now sits above Options.
- Store previews fall back to conventional file names (`logo.png`,
  `preview.png`, `icon.png`, ...) when a manifest's `image` key is missing or
  points at a file that is not there.
- The plugin store deliberately avoids the GitHub API. That endpoint allows 60
  unauthenticated requests per hour per IP, which one store refresh would eat
  into; manifests come from `raw.githubusercontent.com` and downloads from
  `codeload.github.com`, both plain file fetches with no such limit.

### Fixed
- **AppImage now runs on Linux Mint / Ubuntu 22.04+ (FUSE 2 *and* FUSE 3).**
  The build used the AppImageKit runtime, which loads `libfuse.so.2` via
  `dlopen()`. Distributions that ship only fuse3 – Mint 21+ among them –
  failed with `dlopen(): error loading libfuse.so.2` before a single line of
  Python ran. The build script now embeds the statically linked
  [type2-runtime](https://github.com/AppImage/type2-runtime), which carries its
  own FUSE and picks whatever `fusermount*` the system provides, and verifies
  after the build that no `libfuse.so.2` reference is left.
- **Readable errors instead of Qt tracebacks.** `AppRun` checks for the Qt6
  system libraries that Mint/Ubuntu do not install by default (notably
  `libxcb-cursor0`) and names the package to install.
- **`install.sh` now actually installs the Qt libraries it lists.** The
  dependency step was guarded by `[ -t 0 ]`, which is never true for
  `curl -sL ... | bash` – the very install path the README recommends. So the
  step printed "Running non-interactively" and skipped itself, and the first
  launch died with "xcb-cursor0 or libxcb-cursor0 is needed to load the Qt xcb
  platform plugin". The prompt now goes through `/dev/tty`, which still works
  inside a pipe, and with no terminal at all the libraries are installed by
  default (`DREAMCHATBOX_SKIP_SYSDEPS=1` opts out, `DREAMCHATBOX_ASSUME_YES=1`
  skips the question). Same bug silently skipped `python3-venv`, which then
  broke the venv step on Debian-based systems.
- **`install.sh` verifies the GUI before claiming success.** After building the
  venv it runs `ldd` against Qt's `libqxcb.so`, maps any missing soname to the
  right package name for apt/pacman/dnf/zypper and prints the exact command.
  Works without a display, so it is also useful over SSH.
- **Complete xcb dependency list.** `libxcb-cursor0` alone is not enough;
  `libxcb-icccm4`, `libxcb-image0`, `libxcb-keysyms1`, `libxcb-render-util0`,
  `libxcb-shape0`, `libxcb-xkb1` and `libxkbcommon-x11-0` are now installed too,
  and the AUR package gained the matching `xcb-util-*` and `libxkbcommon-x11`
  dependencies.
- **Python version mismatch is caught up front.** The bundled C extensions
  (`PyQt6.sip`, `zeroconf`) are built for the Python minor version of the build
  machine. The AppImage now records that version, looks for a matching
  `pythonX.Y` on the target system, and otherwise says plainly what is wrong
  instead of dying with an `ImportError`.

## [v1.2.0] – 2026-07-29

First non-alpha release. The big change is a **plugin system**: features that
only some people need no longer have to live in the app itself.

### Added
- **Plugin system.** A new **Plugins** page in the sidebar. Plugins live in
  `~/.config/OSC-DreamChatbox/plugins/<id>/` as a folder with a `plugin.json`
  and a python file, are loaded dynamically via `importlib`, and can be
  installed from a `.zip`, switched on/off and deleted from the UI. Every call
  into plugin code is wrapped, so a broken plugin logs a traceback to the debug
  console and is skipped – it can never take the chatbox down.
- **Every plugin is a placeholder.** An active plugin is addressable as
  `{plugin_id}` in Personal Status texts, in the MediaPlay/Hardware custom
  strings and in All in one; anything it exports additionally shows up as
  `{plugin_id_key}`. A plugin may also claim unprefixed names via
  `global_placeholders` – a value the app itself produced always wins, so a
  plugin can never hijack a built-in placeholder.
- **Per-plugin Settings block.** Same expander as the Apps cards, with an
  *Own line in the chatbox* toggle (off = the plugin only feeds placeholders
  and stops printing itself), a *Custom string* with reset and emoji buttons,
  and the plugin's own options. Those options are declared in `plugin.json`
  (`text`, `bool`, `int`) and rendered automatically, so a plugin author gets a
  settings UI without writing a single line of Qt.
- **World Stats plugin.** Ships the live VRChat info that used to sit in the
  Personal Status card: `{player_in_world}`, `{group_world}`, `{instance_type}`
  and `{realtime}`, plus a combined `{world_stats}` line. Player icon, clock
  format, maximum world-name length and the log folder are configurable, and
  each of the three values can be switched off on its own.
- **Hello World example plugin** demonstrating settings, `get_text()`,
  `get_values()` and the `on_settings()` hook.
- **"Plugins & template" button** on the Plugins page, linking to
  [Dream-Chatbox-Plugins](https://github.com/yakuda-stack/Dream-Chatbox-Plugins)
  – ready-made plugins to download plus the template to start your own.
- **10 switchable All in one templates**, exactly like the Personal Status
  templates: each button keeps its own set of up to 5 strings and its own
  count, so you can flip between a gaming, a music and a minimal layout with
  one click. Existing configs are migrated – your current string lands in
  template 1.

### Changed
- **Plugin settings are stored with the plugin**, in
  `plugins/<id>/configs/config.json` – one file per plugin holding its on/off
  state, custom string and option values. Copy the folder and the settings come
  along; delete it and nothing is left behind. The `configs/` folder is
  preserved when a plugin is re-installed from a newer `.zip`, so an update
  never resets what you configured.
- The app no longer reads VRChat's `output_log` itself. `core/vrchatlog.py` is
  down to the Steam/Proton path discovery that the VRC Picture Folder Fix
  needs; the log watcher and its background thread now ship inside the World
  Stats plugin. Without that plugin installed, the chatbox tails no log file at
  all.
- The preview refresh timer is now driven by active plugins instead of the log
  watcher, so live values like clocks stay current between sends.

### Removed
- **Live info from the Personal Status card.** The *Player in world*, *Group
  world* and *Realtime* checkboxes and the VRChat log folder picker are gone –
  install the **World Stats** plugin instead. The placeholder names are
  unchanged, so existing status texts and All in one strings keep working once
  the plugin is enabled.
- The config keys `status_player_in_world`, `status_group_world`,
  `status_realtime` and `vrchat_log_dir` are no longer used.

### Notes
- Dropping `-alpha` reflects that the feature set is settled, not that every
  edge case is proven. Please keep reporting what breaks.

## [v1.1.5-alpha] – 2026-07-29

### Added
- **Own Google API key for translation.** Selecting *Google Translate* now
  shows an optional **Google API key** field. With a key the app uses the
  official **Google Cloud Translation API v2** – your own project, your own
  quota, covered by Google's Terms of Service. Get one at
  console.cloud.google.com and enable the *Cloud Translation API* for the
  project. The key is stored as `stt_google_key`, masked in the UI, and applies
  live to the translation test, Speech-to-Text and the manual Textbox
  translation.
- **Clear "use at your own risk" warning for the key-less mode.** Leaving the
  field empty keeps the previous behaviour, but the UI now says plainly what
  that means: the request goes to the **unofficial, undocumented** endpoint that
  the Google Translate website uses. It is not an API agreement, everybody
  shares the same anonymous endpoint, and Google can throttle or block it at any
  time – heavy use can get your IP temporarily blocked. The warning switches to
  a green confirmation as soon as a key is entered.
- **`THIRD_PARTY_NOTICES.md`** – full attribution for every dependency, external
  service and system tool, including their licences, the GPL/LGPL source offer
  for the AppImage, and the trademark and independence statements. Linked from
  the README.

### Changed
- **Better error messages for Google translation.** HTTP 429/403 from the
  key-less endpoint is now reported as "blocked/rate-limited – the unofficial
  endpoint is shared by everyone", and a rejected key as "key rejected – check
  the key and make sure the Cloud Translation API is enabled", instead of a raw
  exception. The failing backend still falls back to Lingva as before.
- The Google entry in the translation-service dropdown now reads
  *"Google Translate (direct / fastest, key optional)"*.
- An entered API key is also used when Google is reached as a **fallback**, not
  only when it is the selected service.
- **README:** new *Third-party licenses* pointer in the Legal & Credits section,
  and `THIRD_PARTY_NOTICES.md` added to the project structure listing.
- **Donations now go through Ko-fi.** The in-app *Support on Ko-fi* button on
  the Options page, plus the README support link and badge, all point to
  [ko-fi.com/yakuda_](https://ko-fi.com/yakuda_) instead of PayPal.

### Fixed
- Responses from the official Google API are now HTML-unescaped, so translations
  containing apostrophes or quotes no longer show up as `&#39;` / `&quot;`.

### Fixed
- **AppImage now runs on Linux Mint / Ubuntu 22.04+ (FUSE 2 *and* FUSE 3).**
  The build used the AppImageKit runtime, which loads `libfuse.so.2` via
  `dlopen()`. Distributions that ship only fuse3 – Mint 21+ among them –
  failed with `dlopen(): error loading libfuse.so.2` before a single line of
  Python ran. The build script now embeds the statically linked
  [type2-runtime](https://github.com/AppImage/type2-runtime), which carries its
  own FUSE and picks whatever `fusermount*` the system provides, and verifies
  after the build that no `libfuse.so.2` reference is left.
- **Readable errors instead of Qt tracebacks.** `AppRun` checks for the Qt6
  system libraries that Mint/Ubuntu do not install by default (notably
  `libxcb-cursor0`) and names the package to install.
- **`install.sh` now actually installs the Qt libraries it lists.** The
  dependency step was guarded by `[ -t 0 ]`, which is never true for
  `curl -sL ... | bash` – the very install path the README recommends. So the
  step printed "Running non-interactively" and skipped itself, and the first
  launch died with "xcb-cursor0 or libxcb-cursor0 is needed to load the Qt xcb
  platform plugin". The prompt now goes through `/dev/tty`, which still works
  inside a pipe, and with no terminal at all the libraries are installed by
  default (`DREAMCHATBOX_SKIP_SYSDEPS=1` opts out, `DREAMCHATBOX_ASSUME_YES=1`
  skips the question). Same bug silently skipped `python3-venv`, which then
  broke the venv step on Debian-based systems.
- **`install.sh` verifies the GUI before claiming success.** After building the
  venv it runs `ldd` against Qt's `libqxcb.so`, maps any missing soname to the
  right package name for apt/pacman/dnf/zypper and prints the exact command.
  Works without a display, so it is also useful over SSH.
- **Complete xcb dependency list.** `libxcb-cursor0` alone is not enough;
  `libxcb-icccm4`, `libxcb-image0`, `libxcb-keysyms1`, `libxcb-render-util0`,
  `libxcb-shape0`, `libxcb-xkb1` and `libxkbcommon-x11-0` are now installed too,
  and the AUR package gained the matching `xcb-util-*` and `libxkbcommon-x11`
  dependencies.
- **Python version mismatch is caught up front.** The bundled C extensions
  (`PyQt6.sip`, `zeroconf`) are built for the Python minor version of the build
  machine. The AppImage now records that version, looks for a matching
  `pythonX.Y` on the target system, and otherwise says plainly what is wrong
  instead of dying with an `ImportError`.

### Notes
- Lingva Translate remains the **default** translation backend – anonymous,
  key-less and without direct Google tracking. Nothing changes for existing
  configs.
- Housekeeping outside the code: the leftover third-party program logos in
  `assets/icons/` and the dead `scripts/dreammanager.py` (it imported a
  `core.addons` module that no longer exists) were removed, `LICENSE` was
  replaced with the verbatim GPL-3.0 text from gnu.org, and the duplicated
  `install.sh` / `build_appimage.sh` copies in the repository root were dropped
  in favour of the ones in `scripts/`. The `scripts/DreamManager` launcher (a
  wrapper around the already-deleted `dreammanager.py`) and the two empty
  `.SRCINFO` placeholders were removed as well – `.SRCINFO` is generated in the
  AUR clone with `makepkg --printsrcinfo`, not kept here.

## [v1.1.4-alpha] – 2026-07-28

### Changed
- **Smoother UI: media and hardware polling moved off the GUI thread.**
  Reading the media player (via D-Bus/MPRIS) and the hardware stats now runs
  in the background. On NVIDIA systems the periodic `nvidia-smi` call, and –
  with several media players open – the D-Bus round-trips, previously ran on
  the interface thread and could make the window stutter every 1–2 seconds.
  They no longer do. A guard skips a new poll while the previous one is still
  in flight, so slow queries can't pile up.
- **Leaner internals (foundation for a plugin system).** The main window
  (~3,600 lines) was split into focused modules – config handling and one
  module per page (Apps, Textbox, Options) – composed via mixins. This is a
  pure restructure with no change in behaviour; it makes the code far easier
  to navigate and prepares a clean place for future per-feature plugins.
- **Less duplicated code.** The repeated background-worker/queue/timer plumbing
  (translation test, text-to-text, update check) now lives in one shared
  helper, and its short-lived timers are disposed of after use instead of
  accumulating on the window.

### Fixed
- **A broken config no longer wipes your settings silently.** If
  `config.json` can't be read (corrupt/invalid JSON), the file is now copied
  to `config.json.bak` and a clear warning is logged *before* the app falls
  back to defaults, so your old settings can be recovered.
- Removed several unused imports and a leftover dead variable.
- The version number shown at startup and in *About* is now consistent with
  the actual release version.

## [v1.1.3-alpha] – 2026-07-27

### Added
- **VRChat Group button** in *Community & Updates*, next to Donate – opens
  the OSC-DreamChatbox VRChat group page.
- **Update check knows how you installed.** *Check for updates* still just
  reports the newest release (it never downloads or overwrites files); now the
  message is tailored: AppImage users get a link to grab the new AppImage from
  the release page, AUR users are told to update via whichever helper they
  actually have installed (auto-detects `yay` or `paru`), and script/source
  users get the `git pull` / `install.sh` hint.
- **Distro-aware system libraries in the installer.** Non-Arch users (e.g.
  Linux Mint) previously had to add libraries by hand. The install script now
  reads `/etc/os-release`, picks the right package manager (apt / dnf /
  zypper / pacman) and offers to install the libraries the app needs —
  PortAudio for the microphone and the Qt `xcb-cursor` library (without which
  Qt6 fails with "Could not load the Qt platform plugin xcb" on X11/non-KDE).
  Interactive runs ask first; piped `curl | bash` runs print the exact
  command instead (so `sudo` never blocks on a password).

### Fixed
- **Installer now pulls the full dependency set.** The one-line `install.sh`
  was missing `zeroconf`, `deepl` and `setproctitle`, which could leave
  OSCQuery, a translation backend and the process name broken. It now
  installs the same packages as the build script.
- **App Tray Fix – smarter replace.** If an old osc-dreamchatbox entry from a
  previous fix is found (a real .desktop file, a symlink pointing elsewhere,
  an absolute Icon= path, or a missing themed icon), the fix deletes it and
  writes a fresh one. An AUR entry (which ships its own icon) is left
  untouched. When running as an AppImage the entry now uses the stable
  `$APPIMAGE` path for `Exec=` instead of the ephemeral mount path.

## [v1.1.2-alpha] – 2026-07-27

### Added
- **Text to Text translation** (community request). The *Speech to Text* card
  is now **To Text** with a main **Speech or Text** mode switch at the top:
  - **Speech to Text** (OFF) – microphone + record button, as before.
  - **Text to Text** (ON) – a text field with Enter/Send instead of the mic.
    Typed messages run through the exact same translation pipeline and OSC
    output as speech, so no duplicated code and no microphone use.
  - thanks on @Algia- on my discord
  The UI adapts to the mode: mic/record widgets show in speech mode, the text
  field in text mode; languages and translation service are shared by both.
- **Show original + translation** toggle: when on and a translation happens,
  the chatbox shows both languages as `source → translation`. Works in both
  Speech-to-Text and Text-to-Text modes.

### Fixed
- **App Tray Fix now actually shows the icon.** The generated `.desktop`
  referenced the icon by absolute path, which KDE/Wayland taskbars usually
  ignore. It now installs the icon into the hicolor theme
  (`~/.local/share/icons/hicolor/256x256/apps/osc-dreamchatbox.png`) and
  references it by name (`Icon=osc-dreamchatbox`), exactly like the AUR
  package. Both install scripts do the same. If an old osc-dreamchatbox
  entry is found (a real .desktop file, a symlink pointing elsewhere, an
  absolute Icon= path, or a missing themed icon), the fix now deletes it and
  writes a fresh one. A full app restart (and one KDE/Wayland re-login) is
  still needed for the taskbar to refresh.
  Thanks on @royalrex25 on my discord

## [v1.1.1-alpha] – 2026-07-27

### Added
- **Desktop integration / App Tray Fix** – install-script users (curl | bash)
  previously got the generic Wayland icon and no application-menu entry
  because they don't receive the AUR `.desktop` file. Fixed two ways:
  - The **install script** now detects the desktop environment and writes a
    canonical `.desktop` into `~/.config/OSC-DreamChatbox/desktop/`, symlinked
    into `~/.local/share/applications/`. Skipped automatically when a system
    package (AUR) already provides the entry.
  - New **App Tray Fix** button on its own row under *Check for updates* in
    the *Community & Updates* card. It first checks whether an entry already
    exists (symlink **or** real file, in the user applications dir **or** a
    system dir) and does nothing if so; otherwise it creates the same
    canonical entry + symlink on demand.
  - Thanks on @royalrex25 in my discord server
- **VRC Picture Folder Fix** – button next to *App Tray Fix* in the
  *Community & Updates* card. Under Proton, VRChat saves camera photos deep
  inside the Steam prefix
  (`…/compatdata/438100/pfx/…/steamuser/Pictures/VRChat`); this replaces that
  folder with a symlink to the real Linux Pictures directory
  (`~/Pictures/VRChat`, honouring `XDG_PICTURES_DIR`), so new photos land
  there directly. Existing photos in the prefix are migrated first. Detects
  Steam via native, Flatpak and `libraryfolders.vdf` locations, repoints a
  wrong symlink, and is a no-op once set up.

### Changed
- **MediaPlay – tidier sub-options.** Sub-options now appear only when their
  parent is enabled, instead of always being visible: *Max length* shows only
  with *Song title*, *Time with seconds* only with *Time*, *Use my own .lrc
  files* only with *Lyrics* (folder row only when both are on), and the whole
  Songbar block (style, size, time position, custom editor) only when
  *Songbar* is enabled.


## [v1.1.0-alpha] – 2026-07-23

### Added
- **Song title length** – new slider under *Song title* in the MediaPlay
  card (`media_title_max`, default 24): set how many characters of the
  title are shown, anywhere from 3 to 64. Applies to the normal media
  line and the `{title}` placeholder

- **Local .lrc files** – new sub-toggle under *Lyrics* in the MediaPlay
  card (`media_lyrics_local`, default OFF): drop your own `.lrc` files
  into a folder and they are used offline, matched by artist/title on
  the filename (`Artist - Title.lrc`, `Title.lrc`, …). A local hit takes
  priority over LRCLIB; LRCLIB stays as the online fallback. Default
  folder is `~/.config/OSC-DreamChatbox/lyrics/`, changeable via a
  *Choose…* / *Open* row that only appears while the toggle is on
- **Personal Status live info** – three new checkboxes, each usable as a
  placeholder inside any status text (e.g. Text 1) AND in All in one:
  - **Player in world** → `{player_in_world}` – number of players in your
    current VRChat instance (incl. yourself)
  - **Group world** → `{group_world}` – the current world name (bonus:
    `{instance_type}` = Public / Friends / Group / Group+ / Invite …)
  - **Realtime** → `{realtime}` – your PC clock (HH:MM)

  World name, instance type and player count are read live from VRChat's
  Proton `output_log` – no VRChat login, no API calls, no rate limits.
  The log folder is auto-detected across the usual Steam locations
  (native, extra library folders, Flatpak) and can be overridden
  manually. The watcher only runs while *Player in world* or *Group
  world* is enabled. Placeholder aliases: `{playerin_word}` `{players}`
  `{player_count}` → `{player_in_world}`; `{world}` `{world_name}` →
  `{group_world}`; `{clock}` `{time_now}` → `{realtime}`. Status texts
  are only run through the template engine when they actually contain a
  `{…}`, so plain texts (e.g. `:3`) are never altered

### Changed
- **Long song titles are cut without a trailing `…`** – the ellipsis
  wasted one of the precious 144 chatbox characters on every long title,
  so the title is now hard-cut at the chosen length (a trailing space is
  trimmed too)
- **Options page order** – *Community & Updates* moved to the top, above
  OSCQuery and the OSC settings

## [v1.0.9-alpha] – 2026-07-17

### Added
- **Time with seconds** – new sub-toggle under Time in the MediaPlay
  card (`media_time_seconds`, default ON): the music timer now shows
  real seconds (`3:27/4:12`, long songs as `h:mm:ss`). Turn it off to
  get the previous hours:minutes style (`0:03/0:04`) back. The toggle
  applies everywhere the time appears: the time line, the time merged
  into the songbar line AND the placeholders `{time}` `{time_status}`
  `{time_end}` `{position}` `{length}`

### Fixed
- **Chatbox is cleared when SendToVRChat is switched OFF**: one empty
  OSC message is sent so the last text disappears from VRChat
  immediately instead of hanging there for minutes. The same clear
  also runs when the app is closed

## [v1.0.8-alpha] – 2026-07-16

### Fixed
- **Crash (SIGSEGV) with the debug console open**: background
  threads (lyrics fetcher, OSCQuery/mDNS listeners) wrote their log
  messages directly into the Qt debug console – GUI calls from a
  non-GUI thread crash Qt. `log()` is now thread-safe: messages are
  delivered to the console via a queued Qt signal, so they always
  arrive in the GUI thread no matter which thread logs. Thanks for
  the report!

## [v1.0.7-alpha] – 2026-07-16

### Added
- **Lyrics in MediaPlay** 🎶 – shows the current line of the song you
  are listening to, perfectly synced to the playback position:
  - New **"Lyrics" checkbox** in the MediaPlay card (between Time and
    Songbar). The line appears with a ♪ prefix between title/time and
    the songbar
  - Lyrics come from **[LRCLIB](https://lrclib.net)** – an open,
    key-less database of `.lrc` files with exact timestamps. Works
    with EVERY MPRIS player (Spotify, YT Music, browsers, VLC, …)
  - New placeholder **`{lyrics}`** for the MediaPlay custom string
    and All-in-one (aliases: `{lyric}`, `{songtext}`, `{liedtext}`).
    `{lyrics}` only fills in while the checkbox is checked
  - **Performance-first**: unchecked = ZERO network requests. Checked
    = one lookup per song in a background thread, cached (including
    negative results, so unknown songs are never re-queried)
  - **Fuzzy matching** so platform title variations still hit:
    noise like `(Official Video)`, `[4K Remastered]`, `feat. XY`,
    `- Topic` is stripped, then a 4-step chain from exact lookup to
    scored search runs. Search hits must match the title START
    (prefix) and stay within ±10 s of the song duration – so
    third-party uploads match, but wrong songs/remixes never do
    (`core/lyrics.py`, no new dependencies)

Huge thanks to **ewephoric (stupid lamb thing)** on Discord for the
idea! 🐑💙

## [v1.0.6-alpha] – 2026-07-15

### Added
- **Songbar size slider (30–100 %)** in the MediaPlay card – a shorter
  bar leaves room for the time on the same line (`media_bar_size`)
- **Time position** dropdown (`media_time_pos`) – the time can now be
  merged INTO the songbar line so the chatbox stays at two lines
  instead of three:
  - `Own line` (default, previous behaviour): time sits on the
    artist/title line, bar gets its own line
  - `Before bar`: `0:27/1:06 ▓▓▓▓░░░░`
  - `After bar`: `▓▓▓▓░░░░ 0:27/1:06`
  - `Around bar`: `0:27▓▓▓▓░░░░1:06`
  A live preview under the dropdown shows the resulting line + its
  character count
- **New placeholders `{time_status}` (current position) and
  `{time_end}` (when the song ends)** for the MediaPlay custom string
  and All-in-one – clearer aliases of `{position}` / `{length}`

## [v1.0.5-alpha] – 2026-07-12

### Changed
- **License changed from MIT to GPL-3.0-or-later** (LICENSE, README
  badge, PKGBUILD). Releases up to and including v1.0.4-alpha remain
  MIT; this release and everything after is GPL-3.0-or-later

## [v1.0.4-alpha] – 2026-07-12

### Added
- **AUR packaging**: `packaging/aur/PKGBUILD` + `.desktop` file for
  publishing as `osc-dreamchatbox` in the Arch User Repository
  (installs to /usr/share, launcher in /usr/bin, hicolor icon)
- **README screenshots** (assets/p1–p7)
- **Process name**: the app now shows up as `OSC-DreamChatbox`
  instead of `python` in htop/btop/KDE system monitor
  (setproctitle for the command line + prctl PR_SET_NAME for the
  kernel comm name)
- **Personal Status text templates (1–10)**: exclusive toggle row at
  the top of the card – enabling one template switches all others
  off. Every template stores its OWN set of up to 20 texts + count,
  so you can flip between predefined text sets you define yourself.
  Old configs are migrated into template 1 automatically
- **Personal Status: up to 20 texts** (was 10); AIO placeholders now
  go up to `{text_20}`. The text fields fold in/out ("Texts (1–20)"
  expander) so the card stays compact
- **Speech to Text: microphone selection** dropdown (system default +
  every input device, with refresh button). The device is stored by
  NAME and re-resolved on every recording start, so shifting device
  indexes between sessions can't pick the wrong mic

### Changed
- "Text Apps" page renamed back to **Apps**
- **Native OSCQuery smoother**: stays ON by default; the mDNS
  discovery is event-driven (no active re-scanning), the status
  poll only repaints on changes and relaxes from 2 s to 10 s once
  VRChat is found – near-zero idle cost

### Fixed
- **LibreTranslate integration hardened** (local server worked in the
  browser but the app fell back): default URL is now
  `http://127.0.0.1:5000` (avoids localhost/IPv6 mismatches), URLs
  typed without a scheme get `http://` prepended, the REAL server
  error message (`{"error": …}` body) is surfaced instead of a
  generic HTTP code, and a 400 for an explicit source language
  triggers one automatic retry with auto-detect (like the web UI)
- New **🧪 Test button** next to the translation-service dropdown:
  sends a test phrase through the selected service and shows the
  translation or the exact error in the hint line

### Changed
- **Translation reworked into a four-tier system** (dropdown
  "Translation service" replaces the old DeepL checkbox; modular
  backends in `core/translators.py` with one unified
  `translate(text, source, target)` interface):
  1. **Lingva Translate** (new default) – anonymous proxy
     (lingva.adminforge.de), no API key, no direct Google tracking
  2. **Google Translate (direct)** – the un-anonymised gtx web
     endpoint for minimal latency (fast live chat; user's choice)
  3. **LibreTranslate** (optional/local) – local instance for 100%
     offline translation (URL field, default http://localhost:5000)
     with a **Start/Stop server button**: once LibreTranslate is
     installed (manually: `pip install libretranslate`) the button
     "🚀 Start LibreTranslate" appears (spawns the server
     detached, status line shows "⏳ Starting …" and then
     "✅ Server running on port X"), while running it turns into a
     red "🛑 Stop LibreTranslate" (clean process-group terminate).
     A watchdog reports if the server dies; on app close a running
     server is always shut down – no orphaned processes.
     The automatic pip installation from within the app was removed
  4. **DeepL API** (optional/power user) – official `deepl` library
     with typed error handling (quota exceeded, invalid key, rate
     limit); raw-HTTP fallback when the library is missing
  If the chosen method fails for any reason, the chain automatically
  falls back to **Lingva first, then direct Google** – speech-to-text
  never crashes on a dead API.
  Old configs with the DeepL checkbox enabled are migrated to the
  DeepL method automatically. The direct free Google endpoint was
  removed.

## [v1.0.2-alpha] – 2026-07-08

### Added
- **Native OSCQuery** (`core/oscquery.py`): the app no longer binds
  hard-coded ports. On startup it picks a free dynamic UDP port,
  serves OSCQuery HOST_INFO over HTTP and registers both via
  mDNS/Zeroconf; the running VRChat instance is auto-discovered and
  its REAL OSC input port is used as send target (manual target stays
  as fallback). Toggle + live status on the Options page. Needs the
  `zeroconf` package (bundled by install/build scripts).
- **OSCQuery Fix UI reworked**: collapsible "Show supported programs"
  expander with a compact, scrollable list (fixed max height) –
  clicking a program folds its details (path + parameter) in and out
- **Custom songbar style**: new "Custom …" entry in the songbar style
  dropdown with its own editor (start/end brackets, filled/empty
  characters, optional travelling knob) and live preview – build your
  own bar, stored as `media_bar_custom`
- **OSCQuery Fix** on the Options page: one button writes the OSCQuery
  parameter directly into the config of every supported program
  (other settings in the file stay untouched). Supported programs
  live in a single, easily extensible `core/queryfix.py`:
  - OSCLeash    – `~/.config/OSCLeash/Config.json` → `"UseOSCQuery": true`
  - OscGoesBrrr – `~/.config/OscGoesBrrr/config.json` → `"useOscQuery": true`

## [v1.0.1-alpha] – 2026-07-07

### Removed
- **OSC Routing** removed completely (UDP relay, source list, managed
  programs, `core/oscrouter.py`, all `route_*` config keys – old keys
  in existing configs are ignored on load)
- **Addons / OSC Apps** removed completely (catalog, installer,
  update checks, Start Programs, `.desktop`/taskbar integration)
- **DreamManager CLI** removed completely (`scripts/dreammanager.py`,
  `start-programs`, `start-all`, …) – `osc_dreamchatbox.py` is a pure
  GUI starter again
- Reason: external OSC tools handle port discovery via **OSCQuery**
  nowadays, so the built-in relay/installer were unnecessary ballast.
  Leftovers of earlier addon installs under
  `~/.config/OSC-DreamChatbox/tool` + `taskbar` and symlinks in
  `~/.local/share/applications` can be deleted manually.

### Changed
- "Apps" page renamed to **Text Apps**
- Project restructured into `core/`, `ui/`, `assets/`, `scripts/`
- **Personal Status**: with multiple texts the rotation now switches
  **randomly** instead of sequentially (never the same text twice in
  a row)
- **MediaPlay time without seconds**: the music timer shows hours and
  minutes only (`h:mm`, e.g. `0:03/0:04`) – applies to the time line
  and the `{position}` / `{length}` / `{time}` placeholders
- Window/taskbar icon is now loaded from `assets/icon.png`
  (falls back to the project root for old checkouts)

### Added
- **6 selectable songbar styles** (dropdown "Songbar style" in the
  MediaPlay card, stored as `media_bar_style` 0–5), also used by the
  `{bar}` placeholder in custom strings / AIO:
  1. `[───●────────────────]`
  2. `──■──` (compact slider)
  3. `[████████░░░░░░░░░░░░]` (default)
  4. `▰▰▰▰▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱`
  5. `🎵🎵🎵🎵🎵🎵🎵─────────────`
  6. `▓▓▓▓▓▓▓▓░░░░░░░░░░░░` (classic look of earlier versions)

## [v1.0.0-alpha] – 2026-07-05

First public release. 🎉

### Apps
- **Personal Status**: 1–10 rotating texts, adjustable interval, icon picker
- **MediaPlay**: current song via MPRIS (Spotify, YT Music, browsers, VLC, …),
  artist/title/time/songbar toggles, 🎵 media icon, custom string
- **Hardware**: GPU/VRAM/CPU/RAM stats (AMD sysfs + NVIDIA nvidia-smi),
  auto/custom names, °C or 🔥 temps, custom string with `{temp_icon}`
- **All in one**: combine every app into one master string, up to 5 rotating
  layouts with all placeholders (`{text_1}…{text_10}`, media, hardware)
- Drag & drop card order = line order in VRChat

### Textbox
- Free chat field with instant send + app pausing
- Editable presets (5 default, up to 20)
- **Speech to Text**: realtime transcription (15 languages), live translation
  (13 output languages), optional DeepL API with Google fallback,
  "Block apps" master switch
- Drag & drop card order

### Core
- Slim Chatbox mode (BlankEgg trick) – default ON, suffix survives the
  144-char limit
- Preview with character counter, debug console (capped at 500 lines)
- Update checker, Discord & donate links
- Performance: debounced config writes, cached D-Bus player, cached hwmon
  sensors, timers only run when actually needed
- All settings persisted to `~/.config/OSC-DreamChatbox/config.json`
