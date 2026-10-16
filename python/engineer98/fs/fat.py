"""FAT12/FAT16 filesystem reader for PC-98 disk images.

Sits on top of the ``Image`` pyclass exposed by the Rust core. All sector
access goes through ``Image.read_sectors()``, which works in *physical*
sectors (the geometry's ``sector_size``). The BPB, however, describes the
volume in *logical* sectors, whose size is ``BPB_BytsPerSec``. On PC-98 DOS
volumes these two often differ (e.g. 1024-byte logical sectors on a
256-byte physical disk), so every read converts logical -> physical.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from engineer98 import Image, Partition

# --- On-disk constants -----------------------------------------------------

DIR_ENTRY_SIZE = 32
FAT12_EOC = 0xFF8          # first end-of-chain marker
FAT16_EOC = 0xFFF8

ATTR_READ_ONLY = 0x01
ATTR_HIDDEN = 0x02
ATTR_SYSTEM = 0x04
ATTR_VOLUME_ID = 0x08
ATTR_DIRECTORY = 0x10
ATTR_ARCHIVE = 0x20
ATTR_LONG_NAME = 0x0F      # RO | HIDDEN | SYSTEM | VOLUME_ID


# --- Value types -----------------------------------------------------------

@dataclass(frozen=True)
class Bpb:
    """Parsed BIOS Parameter Block plus the derived layout of the volume."""

    bytes_per_sector: int
    sectors_per_cluster: int
    reserved_sectors: int
    num_fats: int
    root_entry_count: int
    total_sectors: int
    media_descriptor: int
    fat_size_sectors: int
    sectors_per_track: int
    num_heads: int
    hidden_sectors: int
    volume_label: str
    fs_type: str

    # Derived — computed by `Bpb.parse`.
    root_dir_sectors: int = 0
    first_fat_sector: int = 0
    first_root_dir_sector: int = 0
    first_data_sector: int = 0
    count_of_clusters: int = 0

    @property
    def bytes_per_cluster(self) -> int:
        return self.bytes_per_sector * self.sectors_per_cluster


@dataclass
class FatEntry:
    """One 32-byte directory entry, excluding LFN and volume-label entries."""

    name: str               # human-readable, may differ from short_name
    short_name: str         # the raw 8.3 name, e.g. "IO      SYS"
    size: int
    attributes: int
    first_cluster: int
    is_directory: bool
    is_hidden: bool
    is_system: bool
    is_read_only: bool

    @property
    def is_volume_label(self) -> bool:
        return bool(self.attributes & ATTR_VOLUME_ID) and not self.is_directory


# --- Helpers ---------------------------------------------------------------

def _decode_short_name(raw: bytes) -> str:
    """Decode an 8.3 name from an 11-byte raw field into ``NAME.EXT`` form."""
    base = raw[0:8].decode("ascii", errors="replace").rstrip(" ")
    ext = raw[8:11].decode("ascii", errors="replace").rstrip(" ")
    if not base:
        return ""
    return f"{base}.{ext}" if ext else base


def _is_deleted_or_end(first_byte: int) -> tuple[bool, bool]:
    """Return (is_end, is_deleted) for a directory entry's first byte."""
    if first_byte == 0x00:
        return True, False
    if first_byte == 0xE5:
        return False, True
    return False, False


# --- The volume ------------------------------------------------------------

class FatVolume:
    """A parsed FAT12/FAT16 volume living inside one partition of an Image."""

    def __init__(self, image: Image, partition: Partition) -> None:
        self.image = image
        self.partition = partition
        self.bpb = self._parse_bpb()

        # Physical sectors per logical sector. On a PC-98 HDI this is
        # frequently 4 (1024-byte logical sectors on 256-byte physical).
        image_sector = image.geometry().sector_size
        if self.bpb.bytes_per_sector % image_sector != 0:
            raise ValueError(
                f"logical sector size {self.bpb.bytes_per_sector} is not a "
                f"multiple of physical sector size {image_sector}"
            )
        self._phys_per_logical = self.bpb.bytes_per_sector // image_sector

    # -- BPB parsing --------------------------------------------------------

    def _parse_bpb(self) -> Bpb:
        # We can't use _read_logical yet — _phys_per_logical isn't set.
        # The BPB fits in the first 64 bytes, so one physical sector is
        # always enough regardless of the logical sector size.
        header = bytes(self.image.read_sectors(self.partition.start_lba, 1))
        if len(header) < 0x40:
            raise ValueError("boot sector too short")

        jmp = header[0:3]
        if jmp[0] not in (0xEB, 0xE9):
            raise ValueError(f"not a FAT boot sector (jmp = {jmp.hex()})")

        (
            bytes_per_sector,
            sectors_per_cluster,
            reserved_sectors,
            num_fats,
            root_entry_count,
            total_sectors16,
            media_descriptor,
            fat_size16,
            sectors_per_track,
            num_heads,
            hidden_sectors,
            total_sectors32,
        ) = struct.unpack_from("<HBHBHHBHHHII", header, 0x0B)

        total_sectors = total_sectors16 or total_sectors32
        fat_size = fat_size16

        if bytes_per_sector == 0 or sectors_per_cluster == 0:
            raise ValueError("BPB has zero bytes-per-sector or sectors-per-cluster")

        root_dir_bytes = root_entry_count * DIR_ENTRY_SIZE
        root_dir_sectors = (root_dir_bytes + bytes_per_sector - 1) // bytes_per_sector

        first_fat = reserved_sectors
        first_root = first_fat + num_fats * fat_size
        first_data = first_root + root_dir_sectors

        data_sectors = total_sectors - (
            reserved_sectors + num_fats * fat_size + root_dir_sectors
        )
        count_of_clusters = data_sectors // sectors_per_cluster

        # Extended BPB at offset 0x24 (only present if BS_BootSig == 0x29).
        vol_label = ""
        fs_type = ""
        if len(header) > 0x26 and header[0x26] == 0x29:
            vol_label = (
                header[0x2B:0x36].decode("ascii", errors="replace").rstrip(" ")
            )
            fs_type = (
                header[0x36:0x3E].decode("ascii", errors="replace").rstrip(" ")
            )

        return Bpb(
            bytes_per_sector=bytes_per_sector,
            sectors_per_cluster=sectors_per_cluster,
            reserved_sectors=reserved_sectors,
            num_fats=num_fats,
            root_entry_count=root_entry_count,
            total_sectors=total_sectors,
            media_descriptor=media_descriptor,
            fat_size_sectors=fat_size,
            sectors_per_track=sectors_per_track,
            num_heads=num_heads,
            hidden_sectors=hidden_sectors,
            volume_label=vol_label,
            fs_type=fs_type,
            root_dir_sectors=root_dir_sectors,
            first_fat_sector=first_fat,
            first_root_dir_sector=first_root,
            first_data_sector=first_data,
            count_of_clusters=count_of_clusters,
        )
    # -- Sector IO ----------------------------------------------------------

    def _read_logical(self, logical_lba: int, count: int) -> bytes:
        """Read ``count`` logical sectors starting at ``logical_lba``."""
        phys_lba = self.partition.start_lba + logical_lba * self._phys_per_logical
        phys_count = count * self._phys_per_logical
        return bytes(self.image.read_sectors(phys_lba, phys_count))

    def _read_cluster(self, cluster: int) -> bytes:
        """Read one full cluster of data."""
        if cluster < 2:
            raise ValueError(f"invalid cluster number {cluster}")
        first_sector = self.bpb.first_data_sector + (cluster - 2) * self.bpb.sectors_per_cluster
        return self._read_logical(first_sector, self.bpb.sectors_per_cluster)

    # -- FAT access ---------------------------------------------------------

    def _fat_entry(self, cluster: int) -> int:
        """Look up the next-cluster value for ``cluster`` in the active FAT."""
        if self.bpb.fs_type.upper().startswith("FAT16") or self.bpb.count_of_clusters >= 0xFF5:
            return self._fat16_entry(cluster)
        return self._fat12_entry(cluster)

    def _fat12_entry(self, cluster: int) -> int:
        offset = cluster + (cluster // 2)          # 1.5 bytes per entry
        raw = self._read_fat_bytes(offset, 2)
        value = raw[0] | (raw[1] << 8)             # full 16-bit LE word
        if cluster & 1:
            value >>= 4                            # odd clusters: high 12 bits
        return value & 0x0FFF                      # mask AFTER shifting

    def _fat16_entry(self, cluster: int) -> int:
        raw = self._read_fat_bytes(cluster * 2, 2)
        return raw[0] | (raw[1] << 8)

    def _read_fat_bytes(self, offset: int, length: int) -> bytes:
        """Read ``length`` bytes from the active FAT starting at ``offset``."""
        fat_start = self.bpb.first_fat_sector * self.bpb.bytes_per_sector
        abs_byte = fat_start + offset
        sector = abs_byte // self.bpb.bytes_per_sector
        intra = abs_byte % self.bpb.bytes_per_sector
        chunk = self._read_logical(sector, 1)
        # Requests near a sector boundary may need two sectors, but for a
        # 2-byte read on a 512+ byte sector that never happens. Guard anyway.
        if intra + length > len(chunk):
            chunk += self._read_logical(sector + 1, 1)
        return chunk[intra : intra + length]

    def _cluster_chain(self, first_cluster: int) -> Iterator[int]:
        """Yield the cluster chain starting at ``first_cluster``."""
        if first_cluster < 2:
            return
        eoc = FAT16_EOC if self.bpb.fs_type.upper().startswith("FAT16") else FAT12_EOC
        cluster = first_cluster
        seen: set[int] = set()
        while 2 <= cluster < eoc:
            if cluster in seen:
                raise ValueError(f"cluster chain loop at cluster {cluster}")
            seen.add(cluster)
            yield cluster
            cluster = self._fat_entry(cluster)

    # -- Directory walking --------------------------------------------------

    def _read_root_dir_bytes(self) -> bytes:
        return self._read_logical(
            self.bpb.first_root_dir_sector, self.bpb.root_dir_sectors
        )

    def _read_directory_bytes(self, first_cluster: int) -> bytes:
        out = bytearray()
        for cluster in self._cluster_chain(first_cluster):
            out.extend(self._read_cluster(cluster))
        return bytes(out)

    def _parse_entries(self, raw: bytes) -> list[FatEntry]:
        entries: list[FatEntry] = []
        for off in range(0, len(raw), DIR_ENTRY_SIZE):
            entry = raw[off : off + DIR_ENTRY_SIZE]
            if len(entry) < DIR_ENTRY_SIZE:
                break
            is_end, is_deleted = _is_deleted_or_end(entry[0])
            if is_end:
                break
            if is_deleted:
                continue
            attr = entry[11]
            if attr == ATTR_LONG_NAME:
                continue
            short = _decode_short_name(entry[0:11])
            first_cluster = struct.unpack_from("<H", entry, 26)[0]
            size = struct.unpack_from("<I", entry, 28)[0]
            is_dir = bool(attr & ATTR_DIRECTORY)
            is_vol = bool(attr & ATTR_VOLUME_ID)
            if is_vol and not is_dir:
                # Volume label entry — surface but skip in normal listings.
                continue
            entries.append(
                FatEntry(
                    name=short,
                    short_name=short,
                    size=size,
                    attributes=attr,
                    first_cluster=first_cluster,
                    is_directory=is_dir,
                    is_hidden=bool(attr & ATTR_HIDDEN),
                    is_system=bool(attr & ATTR_SYSTEM),
                    is_read_only=bool(attr & ATTR_READ_ONLY),
                )
            )
        return entries

    # -- Public API ---------------------------------------------------------

    def list_root(self) -> list[FatEntry]:
        return self._parse_entries(self._read_root_dir_bytes())

    def list_dir(self, path: str = "/") -> list[FatEntry]:
        """List the contents of ``path``. ``"/"`` or ``""`` means root."""
        path = path.strip("/")
        if not path:
            return self.list_root()
        parts = path.split("/")
        current = self.list_root()
        for i, part in enumerate(parts):
            match = _find_entry(current, part)
            if match is None:
                raise FileNotFoundError(f"no such path: {path}")
            if not match.is_directory:
                raise NotADirectoryError(path)
            if i == len(parts) - 1:
                return self._parse_entries(
                    self._read_directory_bytes(match.first_cluster)
                )
            current = self._parse_entries(
                self._read_directory_bytes(match.first_cluster)
            )
        raise FileNotFoundError(path)

    def walk(self, path: str = "/") -> Iterator[tuple[str, FatEntry]]:
        """Yield ``(full_path, entry)`` for every file under ``path``."""
        for entry in self.list_dir(path):
            full = f"{path.rstrip('/')}/{entry.name}" if path != "/" else f"/{entry.name}"
            if entry.is_directory:
                yield full, entry
                yield from self.walk(full)
            else:
                yield full, entry

    def read_file(self, path: str) -> bytes:
        """Read the full contents of a file by path."""
        entry = self.find(path)
        if entry is None:
            raise FileNotFoundError(path)
        if entry.is_directory:
            raise IsADirectoryError(path)
        if entry.size == 0:
            return b""
        out = bytearray()
        for cluster in self._cluster_chain(entry.first_cluster):
            out.extend(self._read_cluster(cluster))
            if len(out) >= entry.size:
                break
        return bytes(out[: entry.size])

    def find(self, path: str) -> FatEntry | None:
        """Look up a single entry by full path, or None if not found."""
        path = path.strip("/")
        if not path:
            return None
        parts = path.split("/")
        current = self.list_root()
        for i, part in enumerate(parts):
            match = _find_entry(current, part)
            if match is None:
                return None
            if i == len(parts) - 1:
                return match
            if not match.is_directory:
                return None
            current = self._parse_entries(self._read_directory_bytes(match.first_cluster))
        return None

    def extract_all(self, dest: str | Path) -> int:
        """Recursively extract every file under root into ``dest``. Returns count."""
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        count = 0
        for full, entry in self.walk("/"):
            if entry.is_directory:
                (dest / full.lstrip("/")).mkdir(parents=True, exist_ok=True)
                continue
            target = dest / full.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.read_file(full))
            count += 1
        return count


def _find_entry(entries: list[FatEntry], name: str) -> FatEntry | None:
    """Case-insensitive lookup by either the display name or the 8.3 name."""
    upper = name.upper()
    for e in entries:
        if e.short_name.upper() == upper:
            return e
    return None