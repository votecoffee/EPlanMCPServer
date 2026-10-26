"""Atomic private directory creation returning the ORIGINAL created-object lease."""

import ctypes
from ctypes import wintypes as w
from pathlib import Path

from .runtime_leases import WindowsLease


def create_private_directory(path):
    path = Path(path).absolute()
    parents = []
    descriptor = ctypes.c_void_p()
    handle = w.HANDLE()
    try:
        for parent in reversed(path.parents):
            parents.append(WindowsLease(parent, directory=True, check_owner=False))
        api = parents[-1]
        api.a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            w.LPCWSTR,
            w.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
        ]
        sddl = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;" + api._user_sid() + ")"
        if not api.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        class Unicode(ctypes.Structure):
            _fields_ = [("length", w.USHORT), ("maximum", w.USHORT), ("buffer", w.LPWSTR)]

        class Attributes(ctypes.Structure):
            _fields_ = [
                ("length", w.ULONG),
                ("root", w.HANDLE),
                ("name", ctypes.POINTER(Unicode)),
                ("flags", w.ULONG),
                ("descriptor", ctypes.c_void_p),
                ("qos", ctypes.c_void_p),
            ]

        class Status(ctypes.Structure):
            _fields_ = [("status", ctypes.c_void_p), ("information", ctypes.c_size_t)]

        # Relative to the retained parent handle: no path-based adoption/repair.
        text = ctypes.create_unicode_buffer(path.name)
        length = len(path.name.encode("utf-16-le"))
        name = Unicode(length, length + 2, ctypes.cast(text, w.LPWSTR))
        attributes = Attributes(
            ctypes.sizeof(Attributes), api.handle, ctypes.pointer(name), 0x1040, descriptor, None
        )
        status = Status()
        nt = ctypes.WinDLL("ntdll").NtCreateFile
        nt.restype = w.LONG
        nt.argtypes = [
            ctypes.POINTER(w.HANDLE),
            w.DWORD,
            ctypes.POINTER(Attributes),
            ctypes.POINTER(Status),
            ctypes.c_void_p,
            w.ULONG,
            w.ULONG,
            w.ULONG,
            w.ULONG,
            ctypes.c_void_p,
            w.ULONG,
        ]
        result = nt(
            ctypes.byref(handle),
            0x120080,
            ctypes.byref(attributes),
            ctypes.byref(status),
            None,
            0x10,
            3,
            2,
            0x200021,
            None,
            0,
        )
        if result < 0:
            raise OSError("NtCreateFile FILE_CREATE refused: " + hex(result & 0xFFFFFFFF))
        original = handle.value
        handle = w.HANDLE()
        return WindowsLease(path, directory=True, _created_handle=original)
    finally:
        if parents:
            if handle:
                parents[-1].k.CloseHandle(handle)
            if descriptor:
                parents[-1].k.LocalFree(descriptor)
        for parent in reversed(parents):
            parent.close()
