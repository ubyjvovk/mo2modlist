"""New Vegas active plugin ordering, separate from MO2 asset priorities.

Automatic ordering only satisfies declared masters; it is not a LOOT substitute.
Explicit exported orders are preserved and checked, never silently sorted.
"""
import io
import os
import struct

from .core import PackError, safe_relative
from .games import FNV_DLCS
from .sources import stream_member


def validate_plugins(plugins):
    if not isinstance(plugins, list) or not plugins:
        raise PackError("New Vegas plugins must be a nonempty ordered list of active ESM/ESP filenames")
    seen = set()
    for name in plugins:
        safe_relative(name)
        if "/" in name or not name.casefold().endswith((".esm", ".esp")) or name.casefold() in seen:
            raise PackError("Invalid or duplicate New Vegas plugin: " + name)
        try:
            name.encode("mbcs" if os.name == "nt" else "cp1252")
        except UnicodeEncodeError:
            raise PackError("Plugin filename is not representable in the Windows game encoding: " + name) from None
        seen.add(name.casefold())
    if plugins[0].casefold() != "falloutnv.esm":
        raise PackError("FalloutNV.esm must be the first active plugin")
    if len(plugins) > 255:
        raise PackError("New Vegas supports at most 255 active plugins")


def _lines(path, encoding):
    return [s.strip().lstrip("\ufeff") for s in path.read_text(encoding=encoding).splitlines()
            if s.strip() and not s.lstrip().startswith("#")]


def profile_plugins(profile):
    enabled = _lines(profile / "plugins.txt", "mbcs" if os.name == "nt" else "cp1252")
    if not any(p.casefold() == "falloutnv.esm" for p in enabled):
        enabled.insert(0, "FalloutNV.esm")
    order_path = profile / "loadorder.txt"
    order = _lines(order_path, "utf-8-sig") if order_path.exists() else enabled
    if not any(p.casefold() == "falloutnv.esm" for p in order):
        order.insert(0, "FalloutNV.esm")
    names = {p.casefold() for p in enabled}
    if len(names) != len(enabled) or not names.issubset({p.casefold() for p in order}):
        raise PackError("Active plugins are duplicated or missing from loadorder.txt")
    result = [p for p in order if p.casefold() in names]
    validate_plugins(result)
    return result


def write_plugins(profile, plugins):
    validate_plugins(plugins)
    content = "# MO2 Modlists: active plugins in load order\n" + "\n".join(plugins) + "\n"
    (profile / "plugins.txt").write_text(content, encoding="mbcs" if os.name == "nt" else "cp1252")
    (profile / "loadorder.txt").write_text(content, encoding="utf-8")


def read_header(stream, name):
    header = stream.read(24)
    if len(header) != 24 or header[:4] != b"TES4":
        raise PackError("Invalid TES4 plugin header: " + name)
    size, flags = struct.unpack_from("<II", header, 4)
    if size > 16 * 1024 * 1024 or flags & 0x40000:
        raise PackError("Unsupported plugin header: " + name)
    data = stream.read(size)
    if len(data) != size:
        raise PackError("Truncated plugin header: " + name)
    pos, masters = 0, []
    while pos < size:
        if pos + 6 > size:
            raise PackError("Truncated plugin subrecord: " + name)
        tag, length = struct.unpack_from("<4sH", data, pos)
        pos += 6
        if tag == b"XXXX":
            if length != 4 or pos + 10 > size:
                raise PackError("Invalid extended plugin subrecord: " + name)
            length = struct.unpack_from("<I", data, pos)[0]
            tag = data[pos + 4:pos + 8]
            pos += 10  # Extended size followed by the real six-byte subrecord header.
        if pos + length > size:
            raise PackError("Truncated plugin subrecord: " + name)
        if tag == b"MAST":
            master = data[pos:pos + length].rstrip(b"\0").decode("cp1252")
            safe_relative(master)
            if "/" in master or not master.casefold().endswith((".esm", ".esp")):
                raise PackError("Unsafe plugin master: " + master)
            masters.append(master.casefold())
        pos += length
    return bool(flags & 1), masters


class HeaderSink:
    """Retain only the TES4 record while archive extraction streams the file."""
    def __init__(self):
        self.data = bytearray()
        self.limit = 24

    def write(self, chunk):
        if len(self.data) < 24:
            take = min(24 - len(self.data), len(chunk))
            self.data.extend(chunk[:take])
            chunk = chunk[take:]
            if len(self.data) == 24:
                self.limit = 24 + min(struct.unpack_from("<I", self.data, 4)[0], 16 * 1024 * 1024)
        if len(self.data) < self.limit:
            self.data.extend(chunk[:self.limit - len(self.data)])


def resolve_plugins(document, lock, store, game):
    base_names = {name.casefold() for name in ["FalloutNV.esm", *FNV_DLCS.values()]}
    vanilla = {p.name.casefold(): p for p in (game / "Data").iterdir()
               if p.is_file() and p.name.casefold() in base_names}
    winners = {}
    for key in reversed(lock["priority"]):
        package = lock["packages"][key]
        for entry in package["outputs"]:
            parts = entry["path"].split("/")
            if len(parts) == 2 and parts[0].casefold() == "data" and parts[1].casefold().endswith((".esm", ".esp")):
                if entry["class"] != "mo2-overlay":
                    raise PackError("New Vegas plugins must be installed as MO2 Data overlays")
                winners[parts[1].casefold()] = (parts[1], package, entry)
    addition = document.get("extensions", {}).get("profileAddPlugins")
    if addition:
        requested = [name for name in addition["enabled"] if name.casefold() not in addition["previousFiles"]
                     or name.casefold() in winners or name.casefold() in vanilla]
        excluded = set(addition["previousFiles"]) | {p.casefold() for p in requested}
        requested.extend(value[0] for key, value in winners.items() if key not in excluded)
    elif "plugins" in document:
        requested = document["plugins"]
    else:
        requested = ["FalloutNV.esm"] + [name for name in FNV_DLCS.values() if name.casefold() in vanilla]
        requested.extend(value[0] for key, value in winners.items() if key not in {p.casefold() for p in requested})
    validate_plugins(requested)
    definitions, names = {}, {p.casefold(): p for p in requested}
    for key, name in names.items():
        if key in winners:
            _, package, entry = winners[key]
            sink = HeaderSink()
            stream_member(store.path(package["artifact"]["sha256"]), entry["member"], sink)
            definitions[key] = read_header(io.BytesIO(sink.data), name)
        elif key in vanilla:
            with vanilla[key].open("rb") as stream:
                definitions[key] = read_header(stream, name)
        else:
            raise PackError("Active plugin is missing from the pack and game: " + name)
    for key, (_, masters) in definitions.items():
        missing = set(masters) - names.keys()
        if missing:
            raise PackError(f"{names[key]} requires missing or disabled masters: {', '.join(sorted(missing))}")
    if "plugins" in document:
        positions = {name.casefold(): i for i, name in enumerate(requested)}
        seen_regular = False
        for name in requested:
            key = name.casefold()
            master, dependencies = definitions[key]
            if master and seen_regular:
                raise PackError("Master-flagged plugins must precede regular plugins: " + name)
            seen_regular |= not master
            if any(positions[d] >= positions[key] for d in dependencies):
                raise PackError("Plugin loads before a required master: " + name)
        return requested
    ordered, visiting = [], set()
    def visit(key):
        if key in ordered:
            return
        if key in visiting:
            raise PackError("Cyclic plugin master dependency: " + names[key])
        visiting.add(key)
        for master in definitions[key][1]:
            if definitions[key][0] and not definitions[master][0]:
                raise PackError("Master-flagged plugin depends on a regular plugin: " + names[key])
            visit(master)
        visiting.remove(key)
        ordered.append(key)
    for key in sorted(names, key=lambda key: not definitions[key][0]):
        visit(key)
    result = [names[key] for key in ordered]
    validate_plugins(result)
    return result
