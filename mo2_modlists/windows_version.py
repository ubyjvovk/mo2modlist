"""Read Windows executable version resources; no process or UI automation."""
import ctypes
from ctypes import wintypes
import os


def product_version(path):
    if os.name != "nt":
        return None
    api = ctypes.WinDLL("version", use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    size = api.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return None
    data = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(path), 0, size, data):
        return None
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not api.VerQueryValueW(data, "\\VarFileInfo\\Translation", ctypes.byref(pointer), ctypes.byref(length)):
        return None
    translations = ctypes.cast(pointer, ctypes.POINTER(wintypes.WORD))
    for index in range(0, length.value // 2, 2):
        key = f"\\StringFileInfo\\{translations[index]:04x}{translations[index + 1]:04x}\\ProductVersion"
        value, chars = ctypes.c_void_p(), wintypes.UINT()
        if api.VerQueryValueW(data, key, ctypes.byref(value), ctypes.byref(chars)):
            return ctypes.wstring_at(value, chars.value).rstrip("\0").strip()
    return None
