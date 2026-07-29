# Third-Party Notices

OSC-DreamChatbox is licensed under **GPL-3.0-or-later** (see [LICENSE](LICENSE)).

This file lists the third-party software the project depends on, the external
services it talks to, and the licensing terms that apply to them. It is provided
for transparency and to satisfy the attribution requirements of those licenses.

No third-party source code is copied into this repository. All dependencies are
either installed by the user (pip / AUR) or bundled unmodified into the AppImage.

---

## 1. Required runtime dependencies

These are listed in `requirements.txt` and in the AUR `depends` array.

| Package | License | Project |
|---|---|---|
| **PyQt6** | GPL-3.0-only (or commercial, from Riverbank) | https://www.riverbankcomputing.com/software/pyqt/ |
| **python-osc** | The Unlicense (public domain) | https://github.com/attwad/python-osc |
| **zeroconf** | LGPL-2.1-or-later | https://github.com/python-zeroconf/python-zeroconf |
| **setproctitle** | BSD-3-Clause | https://github.com/dvarrazzo/py-setproctitle |

**Note on PyQt6:** PyQt6 is available under the GPL v3 or a commercial licence
from Riverbank Computing. This project uses the GPL-licensed build. Because
PyQt6 is GPL-3.0-**only**, the licence of the combined, distributed work is
effectively GPL-3.0, even though the original code in this repository is offered
as GPL-3.0-**or-later**.

**Note on zeroconf:** LGPL-2.1-or-later is compatible with GPL-3.0 via the
relicensing option in section 3 of the LGPL v2.1.

## 2. Optional runtime dependencies

Only needed for the features named below; the app runs without them.

| Package | License | Needed for |
|---|---|---|
| **SpeechRecognition** | BSD-3-Clause | Speech to Text |
| **PyAudio** | MIT | microphone access for Speech to Text |
| **deepl** (official DeepL Python library) | MIT | DeepL translation backend |
| **LibreTranslate** | AGPL-3.0 | offline translation backend |

**Note on LibreTranslate:** LibreTranslate is installed by the user and started
as a **separate process**; no LibreTranslate code is linked into or shipped with
this application. The AGPL's network clause applies to whoever operates the
server — normally the user, on their own machine.

## 3. Bundled dependencies (AppImage only)

The AppImage produced by `scripts/build_appimage.sh` bundles the Python
dependencies listed above, including **PyQt6 and the Qt 6 libraries** (GPL-3.0)
and **zeroconf** (LGPL-2.1-or-later).

In accordance with GPL-3.0 section 6 and LGPL-2.1 section 4, the complete
corresponding source code for this application is available at:

> https://github.com/yakuda-stack/OSC-DreamChatbox

The source code of the bundled dependencies is available from their upstream
projects linked in the tables above.

The AppImage is built with **appimagetool** (AppImageKit, MIT License,
https://github.com/AppImage/AppImageKit), which is downloaded at build time and
is not part of this repository.

## 4. External services

The app does not require an account anywhere, and it contacts a network service
only when the corresponding feature is enabled.

| Service | Used for | Terms |
|---|---|---|
| **LRCLIB** (https://lrclib.net) | synced lyrics | Free, key-less community API. The app identifies itself with a descriptive `User-Agent` as requested by LRCLIB. |
| **Lingva Translate** (default instance: lingva.adminforge.de) | default translation backend | Anonymous, key-less proxy in front of Google Translate. AGPL-3.0 software operated by a third party. |
| **Google Cloud Translation API** | translation, when the user supplies their own API key | Official, documented API. Quota, billing and Terms of Service acceptance are the user's. |
| **Google Translate web endpoint** (`translate.googleapis.com/translate_a/single`) | translation, when Google is selected without a key | **Unofficial and undocumented.** Not covered by an API agreement, shared by all users, and may be rate-limited or blocked by Google at any time. Provided as a convenience — **use at your own risk.** The app warns about this in the UI. |
| **DeepL API** | translation, with the user's own key | Official API, DeepL's Terms of Service apply to the key holder. |
| **Google Web Speech API** (via the SpeechRecognition library) | Speech to Text | Reached through `SpeechRecognition`'s built-in default key, which upstream provides **for testing purposes only**. It may be throttled or withdrawn at any time. |
| **GitHub API** (api.github.com) | update check | Read-only request for the latest release tag. |

## 5. System tools invoked at runtime

These are executed as external commands when present. They are **not** bundled
and **not** modified.

| Tool | License | Used for |
|---|---|---|
| `nvidia-smi` (nvidia-utils) | NVIDIA proprietary driver licence | NVIDIA GPU statistics |
| `glxinfo` (mesa-utils / mesa-demos) | MIT | exact GPU name detection |
| `lspci` (pciutils) | GPL-2.0-or-later | GPU name fallback |

## 6. Interfaces, protocols and formats

The following are open specifications or plain interoperability facts, not
third-party code, and no third-party implementation was used:

* **VRChat OSC** — the chatbox address `/chatbox/input`, the default ports and
  the 144-character limit are publicly documented interface details.
* **OSCQuery** — open specification; the implementation in `core/oscquery.py`
  is original.
* **MPRIS / D-Bus** — freedesktop.org specification.
* **`.lrc`** — de-facto standard lyrics format.
* **Linux sysfs / procfs** (`/proc/stat`, `/sys/class/drm`, …) — kernel
  interfaces.

## 7. Trademarks and independence

* **VRChat** is a registered trademark of VRChat Inc. This project is an
  independent third-party tool and is not affiliated with, endorsed by or
  sponsored by VRChat Inc.
* **MagicChatbox** is the work of BoiHanny and is distributed under its own
  source-available licence, which is **not** an OSI-approved open-source
  licence. OSC-DreamChatbox is an **independent reimplementation**: it contains
  no code, assets or configuration from MagicChatbox and is neither a fork nor a
  derivative work of it. MagicChatbox is referenced only descriptively, to
  explain what this project does.
* **Google**, **DeepL**, **Spotify** and other product names are trademarks of
  their respective owners and are used purely descriptively.

## 8. Content shown by the app

Song lyrics fetched from LRCLIB, and track titles and artist names read via
MPRIS, are the intellectual property of their respective rights holders. They
are displayed transiently; the app does not redistribute them, and no such
content is contained in this repository.

## 9. Assets in this repository

The application icon (`assets/icon.png`) and the screenshots (`assets/p*.png`)
were produced for this project and are covered by the project licence. The
screenshots show the application's own user interface only.

---

*If you believe something is missing or attributed incorrectly, please open an
issue at https://github.com/yakuda-stack/OSC-DreamChatbox/issues — corrections
are welcome.*
