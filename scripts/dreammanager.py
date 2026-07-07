"""
scripts/dreammanager.py – DreamManager CLI for OSC-DreamChatbox

Unified syntax (case-insensitive, legacy "Start All" style still works):
    DreamManager start <name>        start one specific catalog addon
    DreamManager stop <name>         stop one specific catalog addon
    DreamManager start-programs      start the personal Start-Programs
                                     selection (VRCFaceTracking, if
                                     selected, is ALWAYS started first)
    DreamManager stop-programs       stop the Start-Programs selection
    DreamManager start-all           start every installed addon
                                     (VRCFaceTracking first)
    DreamManager stop-all            stop every running addon
    DreamManager status              show install/run state
    DreamManager list                list all catalog addons

Used by the `scripts/DreamManager` wrapper, the generated .desktop
files and `python osc_dreamchatbox.py <command>`.
"""

import sys
from pathlib import Path

# allow running this file directly (python scripts/dreammanager.py ...)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.addons import (CATALOG, AddonManager,  # noqa: E402
                         catalog_by_name)

USAGE = """DreamManager – addon control for OSC-DreamChatbox

Usage:
  DreamManager start <name>        Start a specific addon (e.g. OSCLeash)
  DreamManager stop <name>         Stop a specific addon
  DreamManager start-programs      Start your Start-Programs selection
                                   (VRCFaceTracking always first)
  DreamManager stop-programs       Stop your Start-Programs selection
  DreamManager start-all           Start all installed addons
  DreamManager stop-all            Stop all running addons
  DreamManager status              Show catalog status
  DreamManager list                List catalog addons
"""


def _print_result(verb, names, empty_hint):
    print(f"{verb}: " + (", ".join(names) if names else empty_hint))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    mgr = AddonManager(log_fn=print)

    if not argv:
        print(USAGE)
        return 1

    cmd = argv[0].lower()
    rest = argv[1:]
    # legacy syntax: "Start All" / "Stop All" -> start-all / stop-all
    if cmd in ("start", "stop") and rest and rest[0].lower() == "all":
        cmd, rest = f"{cmd}-all", rest[1:]

    if cmd == "list":
        for addon in CATALOG:
            extra = " (always started first)" \
                if addon.get("start_priority", 50) == 0 else ""
            print(f"{addon['name']:<20} {addon['repo']}{extra}")
        return 0

    if cmd == "status":
        for addon in CATALOG:
            meta = mgr.load_meta(addon)
            state = ("running" if mgr.is_running(addon) else
                     "installed" if meta.get("installed") else
                     "not installed")
            flags = []
            if meta.get("autostart"):
                flags.append("start-program")
            if meta.get("debug"):
                flags.append("debug")
            ver = f" {meta.get('version')}" if meta.get("version") else ""
            flag_s = f"  [{', '.join(flags)}]" if flags else ""
            print(f"{addon['name']:<20} {state}{ver}{flag_s}")
        return 0

    if cmd == "start-all":
        _print_result("Started", mgr.start_all(),
                      "nothing (nothing to start)")
        return 0
    if cmd == "stop-all":
        _print_result("Stopped", mgr.stop_all(),
                      "nothing (nothing was running)")
        return 0
    if cmd == "start-programs":
        _print_result("Started", mgr.start_programs(),
                      "nothing (selection empty or already running)")
        return 0
    if cmd == "stop-programs":
        _print_result("Stopped", mgr.stop_programs(),
                      "nothing (selection empty or not running)")
        return 0

    if cmd in ("start", "stop"):
        if not rest:
            print(USAGE)
            return 1
        target = " ".join(rest).strip()
        addon = catalog_by_name(target)
        if addon is None:
            print(f"Unknown addon '{target}'. Known addons: "
                  + ", ".join(a["name"] for a in CATALOG))
            return 1
        try:
            if cmd == "start":
                mgr.start(addon)
            else:
                if not mgr.stop(addon):
                    print(f"{addon['name']} was not running.")
        except Exception as e:
            print(f"Error: {e}")
            return 1
        return 0

    print(USAGE)
    return 1


if __name__ == "__main__":
    sys.exit(main())
