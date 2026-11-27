"""Cell values of a legacy Excel (.xls, BIFF8) workbook, with the standard library only.

The 国家统计局 census yearbooks publish their tables as .xls files. This reads them as data and nothing else: the
OLE2 compound file is unpacked to its "Workbook" stream, and only the cell records are decoded (shared strings
SST/LABELSST, LABEL, NUMBER, RK, MULRK, and cached FORMULA results). Formulas are never evaluated, macros and
embedded objects are ignored.

    sheets(data: bytes) -> list[(sheet name, {(row, col): value})]   # value: str or float; 0-based row/col
    grid(cells) -> list[list]                                         # the same as rows of a rectangular table
"""

from __future__ import annotations

import struct

_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_FREE, _END = 0xFFFFFFFF, 0xFFFFFFFE


class XlsError(ValueError):
    """Not a BIFF8 workbook, or a damaged one."""


# ------------------------------------------------------------------ OLE2 compound file


def _stream(data: bytes, wanted: tuple[str, ...] = ("Workbook", "Book")) -> bytes:
    if data[:8] != _MAGIC:
        raise XlsError("not an OLE2 compound file")
    sec_size = 1 << struct.unpack_from("<H", data, 0x1E)[0]
    mini_size = 1 << struct.unpack_from("<H", data, 0x20)[0]
    n_fat, first_dir = struct.unpack_from("<II", data, 0x2C)
    cutoff, first_minifat, n_minifat, first_difat, n_difat = struct.unpack_from("<IIIII", data, 0x38)

    def sector(i: int) -> bytes:
        off = (i + 1) * sec_size
        if off >= len(data):  # (the last sector may be short)
            raise XlsError(f"sector {i} out of range")
        return data[off: off + sec_size]

    difat = list(struct.unpack_from("<109I", data, 0x4C))
    nxt, seen = first_difat, 0
    while nxt not in (_FREE, _END) and seen < n_difat:
        s = sector(nxt)
        vals = struct.unpack(f"<{sec_size // 4}I", s)
        difat += vals[:-1]
        nxt, seen = vals[-1], seen + 1
    fat: list[int] = []
    for i in difat[:n_fat]:
        fat += struct.unpack(f"<{sec_size // 4}I", sector(i))

    def chain(start: int, table: list[int]) -> list[int]:
        out, i = [], start
        while i not in (_FREE, _END):
            if i >= len(table) or len(out) > len(table):
                raise XlsError("broken sector chain")
            out.append(i)
            i = table[i]
        return out

    def read(start: int) -> bytes:
        return b"".join(sector(i) for i in chain(start, fat))

    dirs = read(first_dir)
    entries = []
    for off in range(0, len(dirs) - 127, 128):
        name_len = struct.unpack_from("<H", dirs, off + 64)[0]
        name = dirs[off: off + max(0, name_len - 2)].decode("utf-16-le", errors="replace")
        kind = dirs[off + 66]
        start, size = struct.unpack_from("<II", dirs, off + 116)
        entries.append((name, kind, start, size))
    if not entries or entries[0][1] != 5:
        raise XlsError("no root entry")
    root = entries[0]
    for name, kind, start, size in entries:
        if kind != 2 or name not in wanted:
            continue
        if size >= cutoff:
            return read(start)[:size]
        minifat: list[int] = []
        for i in chain(first_minifat, fat) if n_minifat else []:
            minifat += struct.unpack(f"<{sec_size // 4}I", sector(i))
        ministream = read(root[2])
        return b"".join(ministream[i * mini_size: (i + 1) * mini_size] for i in chain(start, minifat))[:size]
    raise XlsError(f"no {' / '.join(wanted)} stream (not an Excel 97–2003 workbook?)")


# ------------------------------------------------------------------ BIFF8 records


def _records(wb: bytes):
    pos = 0
    while pos + 4 <= len(wb):
        rtype, length = struct.unpack_from("<HH", wb, pos)
        yield pos, rtype, wb[pos + 4: pos + 4 + length]
        pos += 4 + length


def _rk(v: int) -> float:
    if v & 2:
        n = v >> 2
        if n & 0x20000000:
            n -= 0x40000000
        x = float(n)
    else:
        x = struct.unpack("<d", struct.pack("<Q", (v & 0xFFFFFFFC) << 32))[0]
    return x / 100 if v & 1 else x


def _ustr(buf: bytes, pos: int, len_bytes: int = 2) -> tuple[str, int]:
    """A BIFF8 unicode string inside one record (no CONTINUE): length, flags, [runs], [ext], chars."""
    n = buf[pos] if len_bytes == 1 else struct.unpack_from("<H", buf, pos)[0]
    pos += len_bytes
    flags = buf[pos]
    pos += 1
    runs = ext = 0
    if flags & 8:
        runs = struct.unpack_from("<H", buf, pos)[0]
        pos += 2
    if flags & 4:
        ext = struct.unpack_from("<I", buf, pos)[0]
        pos += 4
    if flags & 1:
        s = buf[pos: pos + 2 * n].decode("utf-16-le", errors="replace")
        pos += 2 * n
    else:
        s = buf[pos: pos + n].decode("latin-1")
        pos += n
    return s, pos + 4 * runs + ext


class _Segments:
    """The SST record and its CONTINUE records: a string's characters may be split across them, and every split
    inside the characters starts with a fresh flags byte (compressed or not)."""

    def __init__(self, parts: list[bytes]):
        self.parts, self.i, self.pos = parts, 0, 0

    def _need(self):
        while self.i < len(self.parts) and self.pos >= len(self.parts[self.i]):
            self.i, self.pos = self.i + 1, 0
        if self.i >= len(self.parts):
            raise XlsError("SST ends early")

    def take(self, n: int) -> bytes:
        out = b""
        while n:
            self._need()
            part = self.parts[self.i]
            chunk = part[self.pos: self.pos + n]
            out += chunk
            self.pos += len(chunk)
            n -= len(chunk)
        return out

    def chars(self, n: int, wide: bool) -> str:
        out = []
        while n:
            if self.pos >= len(self.parts[self.i]):  # split inside the characters: new flags byte
                self.i, self.pos = self.i + 1, 0
                if self.i >= len(self.parts):
                    raise XlsError("SST ends early")
                wide = bool(self.parts[self.i][0] & 1)
                self.pos = 1
            part = self.parts[self.i]
            width = 2 if wide else 1
            k = min(n, (len(part) - self.pos) // width)
            raw = part[self.pos: self.pos + k * width]
            out.append(raw.decode("utf-16-le", errors="replace") if wide else raw.decode("latin-1"))
            self.pos += k * width
            n -= k
            if k == 0 and n:  # odd byte left over: treat as a split
                self.pos = len(part)
        return "".join(out)


def _sst(parts: list[bytes]) -> list[str]:
    seg = _Segments(parts)
    _total, unique = struct.unpack("<II", seg.take(8))
    out = []
    for _ in range(unique):
        n = struct.unpack("<H", seg.take(2))[0]
        flags = seg.take(1)[0]
        runs = struct.unpack("<H", seg.take(2))[0] if flags & 8 else 0
        ext = struct.unpack("<I", seg.take(4))[0] if flags & 4 else 0
        out.append(seg.chars(n, bool(flags & 1)))
        seg.take(4 * runs + ext)
    return out


def sheets(data: bytes) -> list[tuple[str, dict[tuple[int, int], object]]]:
    """[(sheet name, {(row, col): str | float})] of a BIFF8 workbook, in workbook order. Empty cells are absent."""
    wb = _stream(data)
    recs = list(_records(wb))
    if not recs or recs[0][1] != 0x0809:
        raise XlsError("workbook stream does not start with BOF")
    bof_version = struct.unpack_from("<H", recs[0][2], 0)[0]
    if bof_version != 0x0600:
        raise XlsError(f"BIFF version {bof_version:#x} is not BIFF8")
    sst: list[str] = []
    sheet_list: list[tuple[int, str]] = []
    for i, (pos, rtype, body) in enumerate(recs):
        if rtype == 0x000A:  # EOF of the workbook globals
            break
        if rtype == 0x0085:  # BOUNDSHEET
            offset = struct.unpack_from("<I", body, 0)[0]
            name, _ = _ustr(body, 6, len_bytes=1)
            sheet_list.append((offset, name))
        elif rtype == 0x00FC:  # SST (+ CONTINUE)
            parts = [body]
            for _p, t, b in recs[i + 1:]:
                if t != 0x003C:
                    break
                parts.append(b)
            sst = _sst(parts)
    by_pos = {pos: i for i, (pos, _t, _b) in enumerate(recs)}
    out = []
    for offset, name in sheet_list:
        if offset not in by_pos:
            raise XlsError(f"sheet {name!r}: no record at offset {offset}")
        cells: dict[tuple[int, int], object] = {}
        pending = None  # FORMULA whose string result follows in a STRING record
        for _p, rtype, body in recs[by_pos[offset] + 1:]:
            if rtype == 0x000A:
                break
            if rtype == 0x00FD:  # LABELSST
                r, c, _xf, idx = struct.unpack_from("<HHHI", body)
                cells[r, c] = sst[idx] if idx < len(sst) else ""
            elif rtype == 0x0204:  # LABEL
                r, c, _xf = struct.unpack_from("<HHH", body)
                cells[r, c] = _ustr(body, 6)[0]
            elif rtype == 0x0203:  # NUMBER
                r, c, _xf, v = struct.unpack_from("<HHHd", body)
                cells[r, c] = v
            elif rtype == 0x027E:  # RK
                r, c, _xf, v = struct.unpack_from("<HHHI", body)
                cells[r, c] = _rk(v)
            elif rtype == 0x00BD:  # MULRK
                r, c0 = struct.unpack_from("<HH", body)
                n = (len(body) - 6) // 6
                for k in range(n):
                    _xf, v = struct.unpack_from("<HI", body, 4 + 6 * k)
                    cells[r, c0 + k] = _rk(v)
            elif rtype == 0x0006:  # FORMULA: the cached result only
                r, c, _xf = struct.unpack_from("<HHH", body)
                res = body[6:14]
                if res[6:8] == b"\xff\xff":
                    if res[0] == 0:
                        pending = (r, c)
                    elif res[0] == 1:
                        cells[r, c] = float(res[2])
                else:
                    cells[r, c] = struct.unpack("<d", res)[0]
            elif rtype == 0x0207 and pending:  # STRING (result of the previous FORMULA)
                cells[pending] = _ustr(body, 0)[0]
                pending = None
        out.append((name, cells))
    return out


def grid(cells: dict[tuple[int, int], object]) -> list[list]:
    """Rows of a sheet as lists (None for empty cells), from row 0 and column 0 to the last non-empty ones."""
    if not cells:
        return []
    n_rows = max(r for r, _ in cells) + 1
    n_cols = max(c for _, c in cells) + 1
    return [[cells.get((r, c)) for c in range(n_cols)] for r in range(n_rows)]
