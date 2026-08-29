"""
core/vrchatlog.py – where VRChat lives on a Linux/Proton install.

Only the Steam/Proton path discovery lives here now; core/vrc_pictures.py
imports VRCHAT_APPID and _STEAM_ROOTS from it to find the camera folder
inside the prefix.

Reading VRChat's output_log for live world/player info used to be part of
the app. It moved into the "World Stats" plugin in v1.2.0, which ships its
own copy of the watcher – so the chatbox itself no longer tails any log
file or runs a background thread for it.

Under Proton VRChat's data lives inside the Steam prefix, e.g.

    ~/.local/share/Steam/steamapps/compatdata/438100/pfx/drive_c/users/
        steamuser/AppData/LocalLow/VRChat/VRChat/

We probe a couple of well-known Steam locations (native + Flatpak + extra
library folders from libraryfolders.vdf). No extra dependencies.
"""


from pathlib import Path

VRCHAT_APPID = "438100"

# folder inside a Steam prefix where VRChat drops its logs
_PREFIX_TAIL = Path(
    "pfx/drive_c/users/steamuser/AppData/LocalLow/VRChat/VRChat")

# Steam roots to probe (native + common variants + Flatpak)
_STEAM_ROOTS = [
    Path.home() / ".local/share/Steam",
    Path.home() / ".steam/steam",
    Path.home() / ".steam/root",
    Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam",
]
