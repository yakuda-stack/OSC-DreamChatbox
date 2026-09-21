"""
tests/test_v152_fixes.py - the two bugs reported against v1.5.1.

1. NVIDIA + AMD machine: the AMD entry in the GPU dropdown carried the
   GeForce's name ("AMD card2 · RTX 3060 (16GB)"), because the name
   lookup for the first AMD card asked nvidia-smi first.
2. LibreTranslate Online failed out of the box: the preset server
   (de.libretranslate.com) started requiring an API key.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

from core.backends import hardware_linux as hl
from core import translators as tr


def _monitor(nvidia, amd, glx_device, pci=None):
    m = hl.HardwareMonitor.__new__(hl.HardwareMonitor)
    m.has_nvidia = bool(nvidia)
    m.amd_cards = amd
    m._find_nvidia_cards = lambda: nvidia
    m._pci_device_names = lambda: pci or {}
    m._detect_gpu_name = lambda: nvidia[0][1] if nvidia else glx_device
    m._detect_mesa_amd_name = lambda: (
        glx_device if glx_device and "RX" in glx_device else "")
    return m


def test_amd_card_does_not_get_nvidia_name():
    dev = Path("/nonexistent/card2/device")
    m = _monitor([(0, "RTX 3060")], [("card2", dev, 16 * hl.GB)],
                 glx_device="")
    gpus = m._enumerate_gpus()
    amd = [g for g in gpus if g["vendor"] == "AMD"][0]
    assert "RTX" not in amd["name"]
    assert "RTX" not in amd["label"]


def test_single_amd_label_has_no_sysfs_node():
    dev = Path("/nonexistent/card1/device")
    m = _monitor([], [("card1", dev, 16 * hl.GB)],
                 glx_device="Radeon RX 7800 XT")
    g = m._enumerate_gpus()[0]
    assert g["label"] == "AMD · Radeon RX 7800 XT (16GB)"


def test_libre_online_preset():
    t = tr.get_translator(tr.METHOD_LIBRE_ONLINE)
    assert t.url == "https://de.libretranslate.com"
    urls = " ".join(v for _l, v in tr.LIBRE_ONLINE_SERVERS)
    assert "minopia" not in urls and "altermilkyway" not in urls


def test_libre_chinese_codes(monkeypatch):
    seen = []
    monkeypatch.setattr(tr.LibreTranslator, "_request",
                        lambda self, t, s, g: seen.append(g) or "ok")
    tr.LibreTranslator("http://x").translate("hi", "en-US", "zh-CN")
    assert seen == ["zh-Hans"]


def test_custom_url_is_used_verbatim():
    t = tr.get_translator(tr.METHOD_LIBRE_ONLINE,
                          libre_online_url="my.server.tld")
    assert t.url == "https://my.server.tld"
