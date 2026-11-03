"""
core/backends/adl_windows.py – AMD GPU sensors from the driver's own DLL

Every AMD driver installs atiadlxx.dll (AMD Display Library) into
System32. It reports the card's power draw, temperature and load to a
normal user process, so an AMD card needs no LibreHardwareMonitor, no
administrator rights and no kernel driver for any of the three. This is
the AMD counterpart to nvidia-smi: already on the machine, nothing to set
up. Machines without the DLL simply never get this source.

Sensor numbers come from ADLSensorType in AMD's adl_structures.h. That
enum has grown across driver generations, so every value is checked for
plausibility and the raw table of each card is logged once at startup.
That log line is what confirms the mapping on a real card.

Reading a card goes through its display outputs: one physical card shows
up as several ADL adapters, so they are grouped by PCI address and name.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import ctypes
import os
import re
import threading
import time

_DLL_NAME = "atiadlxx.dll"
_LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800
_HEAP_ZERO_MEMORY = 0x00000008

_ADL_OK = 0
_ADL_MAX_PATH = 256
_ADL_MAX_SENSORS = 256
#: a garbage adapter count must not turn into a long scan
_MAX_ADAPTERS = 64
#: snapshot() asks more than once per poll
_CACHE_SEC = 1.0

_S_ACTIVITY_GFX = 19
_S_CLOCK_GFX = 1
_S_CLOCK_MEM = 2
_S_TEMP_MEM = 9
_S_FAN_RPM = 14
_S_FAN_PERCENT = 15
_S_TEMP_HOTSPOT = 27

# First supported sensor with a plausible value wins. Board power is the
# figure AMD's own overlay shows on RDNA3 and newer; ASIC power still
# answers there but covers less of the card. Edge is the same "normal"
# reading as the sensor scoring in the LHM reader, the hot spot runs
# 15-30 degrees higher and is only the last resort.
_POWER_SENSORS = (73, 23, 30)          # BOARD, ASIC, GFX
_TEMP_SENSORS = (8, 28, 27)            # EDGE, GFX, HOTSPOT


class AdapterInfo(ctypes.Structure):
    """ADL's AdapterInfo, Windows layout. 1572 bytes."""
    _fields_ = [("iSize", ctypes.c_int),
                ("iAdapterIndex", ctypes.c_int),
                ("strUDID", ctypes.c_char * _ADL_MAX_PATH),
                ("iBusNumber", ctypes.c_int),
                ("iDeviceNumber", ctypes.c_int),
                ("iFunctionNumber", ctypes.c_int),
                ("iVendorID", ctypes.c_int),
                ("strAdapterName", ctypes.c_char * _ADL_MAX_PATH),
                ("strDisplayName", ctypes.c_char * _ADL_MAX_PATH),
                ("iPresent", ctypes.c_int),
                ("iExist", ctypes.c_int),
                ("strDriverPath", ctypes.c_char * _ADL_MAX_PATH),
                ("strDriverPathExt", ctypes.c_char * _ADL_MAX_PATH),
                ("strPNPString", ctypes.c_char * _ADL_MAX_PATH),
                ("iOSDisplayIndex", ctypes.c_int)]


class SensorData(ctypes.Structure):
    _fields_ = [("supported", ctypes.c_int),
                ("value", ctypes.c_int)]


class PmLogOutput(ctypes.Structure):
    """ADLPMLogDataOutput. 2052 bytes."""
    _fields_ = [("size", ctypes.c_int),
                ("sensors", SensorData * _ADL_MAX_SENSORS)]


class PmLogBuffer(ctypes.Structure):
    """PMLog takes a bare pointer without a length and writes as much as
    the installed driver thinks the struct is, so leave room behind it."""
    _fields_ = [("output", PmLogOutput),
                ("headroom", ctypes.c_ubyte * 4096)]


def _norm(name):
    """'AMD Radeon(TM) RX 9060' -> 'amdradeonrx9060'"""
    name = re.sub(r"\((r|tm)\)", "", (name or "").lower())
    return re.sub(r"[^a-z0-9]", "", name)


def _decode(raw):
    return raw.decode("utf-8", "replace").strip()


def _first_plausible(raw, sensors, low, high):
    for sensor in sensors:
        value = raw.get(sensor)
        if value is not None and low < value < high:
            return float(value)
    return None


def _in_range(raw, sensor, low, high):
    """A sensor value if it is inside [low, high], else None. A fan that
    stands still is a real 0, which _first_plausible() would refuse."""
    value = raw.get(sensor)
    return float(value) if value is not None and low <= value <= high \
        else None


def _load():
    """-> (dll, handle to keep alive). Absolute path on purpose: a bare
    name would search the app folder before System32."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    path = os.path.join(root, "System32", _DLL_NAME)
    if not os.path.isfile(path):
        raise OSError(f"{_DLL_NAME} not found, no AMD driver installed")
    lib = ctypes.WinDLL(path, winmode=_LOAD_LIBRARY_SEARCH_SYSTEM32)

    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetProcessHeap.restype = ctypes.c_void_p
    kernel32.HeapAlloc.restype = ctypes.c_void_p
    kernel32.HeapAlloc.argtypes = (ctypes.c_void_p, ctypes.c_ulong,
                                   ctypes.c_size_t)
    malloc_type = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_int)

    @malloc_type
    def adl_malloc(size):
        if size <= 0:
            return None
        return kernel32.HeapAlloc(kernel32.GetProcessHeap(),
                                  _HEAP_ZERO_MEMORY, size)

    lib.ADL2_Main_Control_Create.argtypes = (
        malloc_type, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))
    lib.ADL2_Adapter_NumberOfAdapters_Get.argtypes = (
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))
    lib.ADL2_New_QueryPMLogData_Get.argtypes = (
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
    try:
        lib.ADL2_Adapter_AdapterInfo_Get.argtypes = (
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int)
    except AttributeError:
        pass

    context = ctypes.c_void_p()
    if lib.ADL2_Main_Control_Create(adl_malloc, 1,
                                    ctypes.byref(context)) != _ADL_OK:
        raise OSError("ADL2_Main_Control_Create failed")
    # the context lives as long as the app, and ADL keeps the callback
    return lib, context, adl_malloc


class AdlReader:
    """Power, temperature and load per AMD card.

    Raises OSError from the constructor when nothing can be read, so the
    backend treats it like every other optional source.

    ``lib`` and ``context`` exist for the tests, which have no driver.
    """

    def __init__(self, log=None, lib=None, context=None):
        self.log = log
        self._lock = threading.Lock()
        self._cache = {}
        self._callback = None
        if lib is None:
            lib, context, self._callback = _load()
        self._lib = lib
        self._context = context
        self.cards = self._discover()
        if not self.cards:
            raise OSError("no AMD card reports PMLog sensors")
        if callable(log):
            for card in self.cards:
                table = dict(sorted(self._read_raw(card["index"]).items()))
                log(f"Hardware: AMD driver sensors for "
                    f"'{card['name']}': {table}")

    # ------------------------------------------------------- discovery
    def _rows(self, count):
        """[(adapter_index, name, physical_card_key), ...]"""
        try:
            table = (AdapterInfo * count)()
            size = ctypes.sizeof(table)
            for row in table:
                row.iSize = ctypes.sizeof(AdapterInfo)
            if self._lib.ADL2_Adapter_AdapterInfo_Get(
                    self._context, ctypes.byref(table), size) == _ADL_OK:
                return [(row.iAdapterIndex, _decode(row.strAdapterName),
                         (row.iBusNumber, row.iDeviceNumber,
                          row.iFunctionNumber,
                          _norm(_decode(row.strAdapterName))))
                        for row in table]
        except (AttributeError, OSError):
            pass
        # no table: treat everything as one card, the single-GPU case
        return [(i, "", "") for i in range(count)]

    def _discover(self):
        count = ctypes.c_int(0)
        rc = self._lib.ADL2_Adapter_NumberOfAdapters_Get(
            self._context, ctypes.byref(count))
        if rc != _ADL_OK:
            return []
        count = max(0, min(count.value, _MAX_ADAPTERS))
        if not count:
            return []
        seen, cards = set(), []
        for index, name, key in self._rows(count):
            if key in seen or not self._read_raw(index):
                continue
            seen.add(key)
            cards.append({"index": index, "name": name,
                          "norm": _norm(name)})
        return cards

    # --------------------------------------------------------- reading
    def _read_raw(self, index):
        """{sensor_number: raw_value} of the supported sensors, or {}."""
        buffer = PmLogBuffer()
        try:
            rc = self._lib.ADL2_New_QueryPMLogData_Get(
                self._context, index, ctypes.byref(buffer))
        except OSError:
            return {}
        if rc != _ADL_OK:
            return {}
        return {number: sensor.value
                for number, sensor in enumerate(buffer.output.sensors)
                if sensor.supported}

    def _card_for(self, name, sole):
        wanted = _norm(name)
        for card in self.cards:
            if wanted and card["norm"] == wanted:
                return card
        if sole and len(self.cards) == 1:
            return self.cards[0]
        return None

    def has(self, name):
        """True when this adapter name belongs to a card ADL can read."""
        return self._card_for(name, sole=False) is not None

    def values(self, name, sole=False):
        """{"power", "temp", "usage", "hotspot", "vram_temp", "fan",
        "fan_rpm", "clock", "vram_clock"}, each may be None. {} for a card
        this reader does not know.

        ``sole`` means the machine has one adapter, so the only card is
        the right one even when the two name spellings differ. Without
        that, an Intel iGPU next to a Radeon would get the Radeon's
        numbers.
        """
        card = self._card_for(name, sole)
        if card is None:
            return {}
        index = card["index"]
        now = time.monotonic()
        with self._lock:
            when, cached = self._cache.get(index, (0.0, None))
            if cached is not None and now - when < _CACHE_SEC:
                return dict(cached)
            raw = self._read_raw(index)
            result = {
                "power": _first_plausible(raw, _POWER_SENSORS, 0, 2000),
                "temp": _first_plausible(raw, _TEMP_SENSORS, 0, 150),
                "usage": _in_range(raw, _S_ACTIVITY_GFX, 0, 100),
                "hotspot": _first_plausible(
                    raw, (_S_TEMP_HOTSPOT,), 0, 150),
                "vram_temp": _first_plausible(raw, (_S_TEMP_MEM,), 0, 150),
                "fan": _in_range(raw, _S_FAN_PERCENT, 0, 100),
                "fan_rpm": _in_range(raw, _S_FAN_RPM, 0, 20000),
                "clock": _first_plausible(raw, (_S_CLOCK_GFX,), 0, 20000),
                "vram_clock": _first_plausible(
                    raw, (_S_CLOCK_MEM,), 0, 20000),
            }
            self._cache[index] = (now, result)
            return dict(result)
