"""Manual smoke test for core/perfprobe.py.

    DCB_PERF=1 DCB_PERF_SEC=3 QT_QPA_PLATFORM=offscreen \
        python tests/test_perfprobe_manual.py

Builds a fake window with the same method names the real one has, makes
one of them deliberately slow and one thread deliberately busy, and
checks the report notices both.
"""

import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DCB_PERF", "1")
os.environ.setdefault("DCB_PERF_SEC", "3")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMainWindow

from core import perfprobe


class FakeHw:
    def snapshot(self):
        time.sleep(0.05)          # a poller that shells out
        return {"cpu_usage": 1.0}


class FakeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.hw = FakeHw()
        self.lines = []

    def log(self, msg):
        self.lines.append(str(msg))
        print(msg)

    def poll_hw(self):
        self.hw.snapshot()

    def update_preview(self):
        # ~2 ms of real work, the kind a template engine does
        x = 0
        for i in range(20000):
            x += i * i
        return x

    def build_payload(self):
        return "x"


def burn(stop):
    """A thread that really does spin - the report has to name it."""
    x = 0
    while not stop.is_set():
        x += 1


def main():
    app = QApplication(sys.argv)
    win = FakeWindow()

    stop = threading.Event()
    t = threading.Thread(target=burn, args=(stop,), name="busy-loop",
                         daemon=True)
    t.start()

    probe = perfprobe.install(win)
    assert probe is not None, "probe did not install"

    hw = QTimer(win)
    hw.timeout.connect(win.poll_hw)
    hw.start(200)
    pv = QTimer(win)
    pv.timeout.connect(win.update_preview)
    pv.start(50)

    QTimer.singleShot(7000, app.quit)
    app.exec()
    stop.set()


    text = "\n".join(win.lines)
    problems = []
    if "busy-loop" not in text:
        problems.append("the spinning thread was not named")
    if "poll_hw" not in text:
        problems.append("poll_hw was not timed")
    if "hw.snapshot" not in text:
        problems.append("hw.snapshot was not wrapped")
    if "update_preview" not in text:
        problems.append("update_preview was not sampled or timed")
    if "RSS" not in text:
        problems.append("no RSS line")

    print("\n" + "=" * 60)
    if problems:
        print("FAIL:")
        for p in problems:
            print("  -", p)
        return 1
    print("OK - the probe reported CPU per thread, hot code and poller "
          "timings.")
    print(f"report file: {probe.report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
