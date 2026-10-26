"""App-owned Windows read leases; no third-party bootstrap imports or ACL repair."""

from __future__ import annotations

import ctypes
import hashlib
import os
import threading
from ctypes import wintypes as w
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _libraries():
    return ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("advapi32", use_last_error=True)


class FILE_INFO(ctypes.Structure):
    _fields_ = [
        ("attributes", w.DWORD),
        ("created", w.FILETIME),
        ("accessed", w.FILETIME),
        ("written", w.FILETIME),
        ("volume", w.DWORD),
        ("size_high", w.DWORD),
        ("size_low", w.DWORD),
        ("links", w.DWORD),
        ("index_high", w.DWORD),
        ("index_low", w.DWORD),
    ]


class WindowsLease:
    """Keep the original file/directory generation and sharing denial until close.

    Files deny write/delete sharing. Directories permit write sharing but deny
    delete sharing, pinning ancestors without changing their permissions.
    """

    _current_user_sid = None

    def __init__(
        self, path, *, directory=False, expected_security=None, check_owner=True, _created_handle=None
    ):
        if os.name != "nt":
            raise OSError("Retained runtime leases require Windows")
        self.path = Path(path).absolute()
        self.directory = directory
        self.closed = False
        self.lock = threading.RLock()
        self.k, self.a = _libraries()
        self.k.CreateFileW.argtypes = [
            w.LPCWSTR,
            w.DWORD,
            w.DWORD,
            ctypes.c_void_p,
            w.DWORD,
            w.DWORD,
            w.HANDLE,
        ]
        self.k.CreateFileW.restype = w.HANDLE
        self.k.GetFileInformationByHandle.argtypes = [w.HANDLE, ctypes.POINTER(FILE_INFO)]
        self.k.CloseHandle.argtypes = [w.HANDLE]
        self.k.LocalFree.argtypes = [ctypes.c_void_p]
        self.a.GetSecurityInfo.argtypes = [
            w.HANDLE,
            w.DWORD,
            w.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.a.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
            ctypes.c_void_p,
            w.DWORD,
            w.DWORD,
            ctypes.POINTER(w.LPWSTR),
            ctypes.c_void_p,
        ]
        self.a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.LPWSTR)]
        self.a.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
        self.a.GetTokenInformation.argtypes = [
            w.HANDLE,
            w.DWORD,
            ctypes.c_void_p,
            w.DWORD,
            ctypes.POINTER(w.DWORD),
        ]
        self.k.GetCurrentProcess.restype = w.HANDLE
        self.a.GetSecurityDescriptorOwner.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(w.BOOL),
        ]
        self.a.GetSecurityDescriptorDacl.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(w.BOOL),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(w.BOOL),
        ]
        access = 0x20080 if directory else 0x80020000  # READ_CONTROL + attributes / GENERIC_READ
        flags = 0x00200000 | (0x02000000 if directory else 0)
        self.handle = (
            _created_handle
            if _created_handle is not None
            else self.k.CreateFileW(str(self.path), access, 3 if directory else 1, None, 3, flags, None)
        )
        if self.handle in (None, 0, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            self.identity = self._identity()
            self.security, owner = self._security()
            if check_owner and owner not in (self._user_sid(), "S-1-5-18"):
                raise ValueError("Foreign runtime owner")
            if check_owner:
                self._check_writers()
            if expected_security is not None and self.security != expected_security:
                raise ValueError("Runtime security descriptor changed")
        except BaseException:
            self.close()
            raise

    def _identity(self):
        if self.closed:
            raise ValueError("Closed original runtime lease")
        value = FILE_INFO()
        if not self.k.GetFileInformationByHandle(self.handle, ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        if value.attributes & 0x400 or bool(value.attributes & 0x10) != self.directory:
            raise ValueError("Reparse/type drift in runtime lease")
        if not self.directory and value.links != 1:
            raise ValueError("Hard-linked runtime payload refused")
        return (
            value.volume,
            value.index_high,
            value.index_low,
            value.created.dwHighDateTime,
            value.created.dwLowDateTime,
        )

    def _sid(self, pointer):
        text = w.LPWSTR()
        if not self.a.ConvertSidToStringSidW(pointer, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value
        finally:
            self.k.LocalFree(text)

    def _user_sid(self):
        if WindowsLease._current_user_sid is not None:
            return WindowsLease._current_user_sid
        token = w.HANDLE()
        if not self.a.OpenProcessToken(self.k.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            length = w.DWORD()
            self.a.GetTokenInformation(token, 1, None, 0, ctypes.byref(length))
            data = ctypes.create_string_buffer(length.value)
            if not self.a.GetTokenInformation(token, 1, data, length, ctypes.byref(length)):
                raise ctypes.WinError(ctypes.get_last_error())
            WindowsLease._current_user_sid = self._sid(ctypes.c_void_p.from_buffer(data).value)
            return WindowsLease._current_user_sid
        finally:
            self.k.CloseHandle(token)

    def _security(self):
        descriptor = ctypes.c_void_p()
        error = self.a.GetSecurityInfo(self.handle, 1, 5, None, None, None, None, ctypes.byref(descriptor))
        if error:
            raise OSError(error, "GetSecurityInfo failed")
        text = w.LPWSTR()
        try:
            owner, unused = ctypes.c_void_p(), w.BOOL()
            present, dacl = w.BOOL(), ctypes.c_void_p()
            if not self.a.GetSecurityDescriptorOwner(descriptor, ctypes.byref(owner), ctypes.byref(unused)):
                raise ctypes.WinError(ctypes.get_last_error())
            if (
                not self.a.GetSecurityDescriptorDacl(
                    descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(unused)
                )
                or not present
                or not dacl
            ):
                raise ValueError("Missing/null runtime DACL")
            if not self.a.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor, 1, 5, ctypes.byref(text), None
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            return text.value, self._sid(owner)
        finally:
            if text:
                self.k.LocalFree(text)
            self.k.LocalFree(descriptor)

    def check(self):
        if self._identity() != self.identity or self._security()[0] != self.security:
            raise ValueError("Original runtime identity/security drift")

    def _check_writers(self):
        descriptor = ctypes.c_void_p()
        if self.a.GetSecurityInfo(self.handle, 1, 4, None, None, None, None, ctypes.byref(descriptor)):
            raise ValueError("Cannot inspect runtime writer ACL")
        try:
            present, defaulted, dacl = w.BOOL(), w.BOOL(), ctypes.c_void_p()
            if (
                not self.a.GetSecurityDescriptorDacl(
                    descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)
                )
                or not present
                or not dacl
            ):
                raise ValueError("Missing runtime writer ACL")
            # ACL header's AceCount is a WORD at offset4; ACE SID follows mask.
            count = ctypes.c_ushort.from_address(dacl.value + 4).value
            self.a.GetAce.argtypes = [ctypes.c_void_p, w.DWORD, ctypes.POINTER(ctypes.c_void_p)]
            trusted = {self._user_sid(), "S-1-5-18", "S-1-5-32-544", "S-1-3-0"}
            for index in range(count):
                ace = ctypes.c_void_p()
                if not self.a.GetAce(dacl, index, ctypes.byref(ace)):
                    raise ctypes.WinError(ctypes.get_last_error())
                kind = ctypes.c_ubyte.from_address(ace.value).value
                if kind not in (0, 1):
                    raise ValueError("Unsupported runtime ACL entry")
                mask = ctypes.c_uint32.from_address(ace.value + 4).value
                if kind == 0 and mask & 0x500D0116 and self._sid(ace.value + 8) not in trusted:
                    raise ValueError("Foreign runtime writer")
        finally:
            self.k.LocalFree(descriptor)

    def read(self):
        """Read the SAME native handle; never reopen the payload by path."""
        with self.lock:
            return b"".join(self._chunks())

    def _chunks(self):
        self.check()
        self.k.SetFilePointerEx.argtypes = [w.HANDLE, ctypes.c_longlong, ctypes.c_void_p, w.DWORD]
        self.k.ReadFile.argtypes = [
            w.HANDLE,
            ctypes.c_void_p,
            w.DWORD,
            ctypes.POINTER(w.DWORD),
            ctypes.c_void_p,
        ]
        if not self.k.SetFilePointerEx(self.handle, 0, None, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        buffer, count = ctypes.create_string_buffer(1024 * 1024), w.DWORD()
        while True:
            if not self.k.ReadFile(self.handle, buffer, len(buffer), ctypes.byref(count), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not count.value:
                break
            yield buffer.raw[: count.value]

    def digest(self):
        with self.lock:
            value = hashlib.sha256()
            for chunk in self._chunks():
                value.update(chunk)
            return value.hexdigest()

    def map_readonly(self):
        """Map this exact file object; temporary FILE handle duplicate, never a job."""
        import mmap
        import msvcrt

        self.check()
        self.k.DuplicateHandle.argtypes = [
            w.HANDLE,
            w.HANDLE,
            w.HANDLE,
            ctypes.POINTER(w.HANDLE),
            w.DWORD,
            w.BOOL,
            w.DWORD,
        ]
        duplicate = w.HANDLE()
        process = self.k.GetCurrentProcess()
        if not self.k.DuplicateHandle(process, self.handle, process, ctypes.byref(duplicate), 0, False, 2):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            fd = msvcrt.open_osfhandle(duplicate.value, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            self.k.CloseHandle(duplicate)
            raise
        try:
            return mmap.mmap(fd, 0, access=mmap.ACCESS_READ)
        finally:
            os.close(fd)

    def close(self):
        if not self.closed:
            self.k.CloseHandle(self.handle)
            self.closed = True
