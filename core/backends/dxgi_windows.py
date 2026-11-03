"""
core/backends/dxgi_windows.py – the graphics cards Windows really has

DXGI lists the adapters that exist right now. The registry, which this
app read before, also keeps the entries of cards that were swapped out.
DXGI additionally gives each adapter's LUID, the id the performance
counters carry in their instance names, and that is what makes per-card
readings possible at all.

DXGI is a COM API. ctypes has no COM support, so the two calls needed are
made through the object's method table: a COM pointer points at a table
of function pointers, in the order the interface declares them.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import ctypes

VENDOR_AMD = 0x1002
VENDOR_NVIDIA = 0x10DE
VENDOR_INTEL = 0x8086
VENDOR_MICROSOFT = 0x1414

_ADAPTER_FLAG_SOFTWARE = 2
#: most adapters a machine will reasonably have, against a runaway loop
_MAX_ADAPTERS = 16

#: IUnknown 0-2, IDXGIObject 3-6, IDXGIFactory 7-11, IDXGIFactory1 12-13
_FACTORY1_ENUM_ADAPTERS1 = 12
#: IUnknown 0-2, IDXGIObject 3-6, IDXGIAdapter 7-9, IDXGIAdapter1 10
_ADAPTER1_GET_DESC1 = 10
_RELEASE = 2

#: IDXGIFactory1
_FACTORY1_GUID = (0x770aae78, 0xf26f, 0x4dba,
                  (0xa8, 0x29, 0x25, 0x3c, 0x83, 0xd1, 0xb3, 0x87))

_FUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


class DXGI_ADAPTER_DESC1(ctypes.Structure):
    """c_uint16 rather than c_wchar: WCHAR is 16 bits on Windows, and this
    way the layout is the same on the machine running the tests."""
    _fields_ = [("Description", ctypes.c_uint16 * 128),
                ("VendorId", ctypes.c_uint32),
                ("DeviceId", ctypes.c_uint32),
                ("SubSysId", ctypes.c_uint32),
                ("Revision", ctypes.c_uint32),
                ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t),
                ("LuidLowPart", ctypes.c_uint32),
                ("LuidHighPart", ctypes.c_int32),
                ("Flags", ctypes.c_uint32)]


def _method(com_pointer, index, *argtypes):
    """Method `index` of a COM object, as a callable taking the object
    first. Returns HRESULT, 0 means success."""
    table = ctypes.cast(
        com_pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    prototype = _FUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
    return prototype(table[index])


def _release(com_pointer):
    table = ctypes.cast(
        com_pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    _FUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[_RELEASE])(com_pointer)


def _text(chars):
    out = []
    for c in chars:
        if c == 0:
            break
        out.append(chr(c))
    return "".join(out).strip()


def _describe(desc):
    return {"name": _text(desc.Description),
            "vendor": desc.VendorId,
            "vram": desc.DedicatedVideoMemory,
            "luid": (desc.LuidHighPart & 0xFFFFFFFF, desc.LuidLowPart),
            "software": bool(desc.Flags & _ADAPTER_FLAG_SOFTWARE)}


def walk_factory(factory):
    """Every adapter of a factory COM pointer, as dicts."""
    enum_adapters = _method(factory, _FACTORY1_ENUM_ADAPTERS1,
                            ctypes.c_uint,
                            ctypes.POINTER(ctypes.c_void_p))
    found = []
    for index in range(_MAX_ADAPTERS):
        adapter = ctypes.c_void_p()
        if enum_adapters(factory, index, ctypes.byref(adapter)) != 0 \
                or not adapter:
            break
        try:
            desc = DXGI_ADAPTER_DESC1()
            get_desc = _method(adapter, _ADAPTER1_GET_DESC1,
                               ctypes.POINTER(DXGI_ADAPTER_DESC1))
            if get_desc(adapter, ctypes.byref(desc)) == 0:
                found.append(_describe(desc))
        finally:
            _release(adapter)
    return found


def usable(adapters):
    """Drops the software renderer, sorts by VRAM. sorted() keeps Windows'
    own order for equal sizes, and Windows lists the main adapter first."""
    real = [a for a in adapters
            if not a["software"] and a["vendor"] != VENDOR_MICROSOFT
            and a["name"]]
    return sorted(real, key=lambda a: -a["vram"])


def list_adapters():
    """The real graphics cards, most VRAM first. Raises when DXGI is not
    available, the caller falls back to the registry."""
    dxgi = ctypes.WinDLL("dxgi")
    guid = GUID(_FACTORY1_GUID[0], _FACTORY1_GUID[1], _FACTORY1_GUID[2],
                (ctypes.c_ubyte * 8)(*_FACTORY1_GUID[3]))
    factory = ctypes.c_void_p()
    dxgi.CreateDXGIFactory1.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    dxgi.CreateDXGIFactory1.restype = ctypes.c_long
    if dxgi.CreateDXGIFactory1(ctypes.byref(guid),
                               ctypes.byref(factory)) != 0:
        raise OSError("CreateDXGIFactory1 failed")
    try:
        return usable(walk_factory(factory))
    finally:
        _release(factory)
