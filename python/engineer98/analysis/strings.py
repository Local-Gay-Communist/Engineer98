"""String extraction from a loaded binary module.

Scans the load module for null-terminated runs of printable bytes. Handles
both ASCII and Shift-JIS (which covers PC-98 Japanese text, half-width
katakana in 0xA1-0xDF, and full-width in 0x81-0x9F / 0xE0-0xEF leading
bytes).

The output is a ``StringMap`` — address → StringEntry — that other passes
use to classify immediate operands.
"""

from __future__ import annotations

from dataclasses import dataclass


MIN_STRING_LENGTH = 4


@dataclass(frozen=True)
class StringEntry:
    address: int
    raw: bytes
    encoding: str          # "ascii" or "shift_jis"
    text: str

    def __str__(self) -> str:
        return f"[{self.address:06x}] {self.text!r}"


@dataclass
class StringMap:
    entries: dict[int, StringEntry]

    def get(self, address: int) -> StringEntry | None:
        return self.entries.get(address)

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, address: int) -> bool:
        return address in self.entries


def _is_ascii_printable(b: int) -> bool:
    return 0x20 <= b < 0x7F


def _is_sjis_half_width(b: int) -> bool:
    return 0xA1 <= b <= 0xDF


def _is_sjis_lead(b: int) -> bool:
    return 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xEF


def _sjis_trail_ok(b: int) -> bool:
    return 0x40 <= b <= 0x7E or 0x80 <= b <= 0xFC


def _extract_at(data: bytes, start: int) -> tuple[bytes, int, str] | None:
    """Try to read a null-terminated string starting at ``start``.

    The decisive filter: a real string is preceded by a null byte (the
    terminator of the previous string, or padding). Code bytes almost
    never satisfy this, and without it, Shift-JIS byte ranges produce
    mountains of false positives inside the code segment.
    """
    # Preceded-by-null requirement, except at the very start of the module.
    if start > 0 and data[start - 1] != 0:
        return None

    i = start
    saw_sjis = False
    saw_ascii = False
    while i < len(data):
        b = data[i]
        if b == 0:
            break
        if _is_ascii_printable(b):
            saw_ascii = True
            i += 1
            continue
        if _is_sjis_half_width(b):
            saw_sjis = True
            i += 1
            continue
        if _is_sjis_lead(b) and i + 1 < len(data) and _sjis_trail_ok(data[i + 1]):
            saw_sjis = True
            i += 2
            continue
        # Anything else: not part of a string.
        return None

    if i >= len(data) or data[i] != 0:
        return None  # ran off the end without terminating

    length = i - start
    if length < MIN_STRING_LENGTH:
        return None

    # Reject strings that are purely half-width katakana: those are almost
    # always code-byte coincidences. Require either an ASCII component or
    # at least one full-width SJIS pair.
    raw = data[start:i]
    has_fullwidth_sjis = any(
        _is_sjis_lead(raw[k])
        for k in range(len(raw) - 1)
    )
    if not saw_ascii and not has_fullwidth_sjis:
        return None

    return raw, length, ("shift_jis" if saw_sjis else "ascii")


def extract_strings(module: bytes) -> StringMap:
    """Scan ``module`` for null-terminated strings.

    Walks byte-by-byte, accepting only strings that begin immediately
    after a null byte (see `_extract_at`). On a hit, skip past the
    string and its terminator; on a miss, advance one byte.
    """
    entries: dict[int, StringEntry] = {}
    i = 0
    n = len(module)
    while i < n:
        result = _extract_at(module, i)
        if result is None:
            i += 1
            continue
        raw, length, encoding = result
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            i += 1
            continue
        entries[i] = StringEntry(address=i, raw=raw, encoding=encoding, text=text)
        i += length + 1
    return StringMap(entries=entries)