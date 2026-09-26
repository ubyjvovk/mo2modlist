"""Optional provider credentials kept in Windows Credential Manager, never packs."""
import ctypes
from ctypes import wintypes
import os

from .core import PackError


TARGETS = {"nexus": "MO2Modlists/NexusApiKey", "github": "MO2Modlists/GitHubToken"}


class Credential(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


def api():
    if os.name != "nt":
        raise PackError("Provider credential storage requires Windows Credential Manager")
    library = ctypes.WinDLL("advapi32", use_last_error=True)
    library.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
    library.CredReadW.restype = wintypes.BOOL
    library.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    library.CredWriteW.restype = wintypes.BOOL
    library.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    library.CredDeleteW.restype = wintypes.BOOL
    library.CredFree.argtypes = [ctypes.c_void_p]
    return library


def read(provider):
    if os.name != "nt":
        return None
    library = api()
    pointer = ctypes.POINTER(Credential)()
    if not library.CredReadW(TARGETS[provider], 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:
            return None
        raise PackError("Could not read the stored provider credential")
    try:
        value = pointer.contents
        return ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize).decode("utf-8")
    finally:
        library.CredFree(pointer)


def save(provider, secret):
    if not secret.strip() or any(char.isspace() for char in secret):
        raise PackError("Provider credential must not be empty or contain whitespace")
    raw = secret.encode("utf-8")
    if len(raw) > 2500:
        raise PackError("Provider credential is too long")
    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    value = Credential(Type=1, TargetName=TARGETS[provider], CredentialBlobSize=len(raw),
        CredentialBlob=buffer, Persist=2, UserName="MO2 Modlists")
    if not api().CredWriteW(ctypes.byref(value), 0):
        raise PackError("Could not save the provider credential")


def remove(provider):
    if not api().CredDeleteW(TARGETS[provider], 1, 0) and ctypes.get_last_error() != 1168:
        raise PackError("Could not remove the provider credential")


def headers(provider):
    secret = read(provider)
    if not secret:
        return {}
    return {"apikey": secret} if provider == "nexus" else {"Authorization": "Bearer " + secret}
