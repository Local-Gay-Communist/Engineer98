"""Engineer98 — decompilation and reverse engineering suite for PC98 software."""

from ._core import ExeFile, Geometry, Image, Partition, version
from .fs import FatVolume

__version__ = version()
__all__ = [
    "__version__",
    "ExeFile",
    "FatVolume",
    "Geometry",
    "Image",
    "Partition",
    "describe_image",
]


def describe_image(path: str) -> str:
    """Open a disk image and return a human-readable summary string.

    Thin formatting helper around ``Image`` — kept in Python so contributors
    can tweak the output without rebuilding the Rust core.
    """
    img = Image.open(path)
    g = img.geometry()
    parts = img.partitions()
    lines = [
        f"{img.format_name()}: {g.cylinders} cyl × {g.heads} heads "
        f"× {g.sectors_per_track} spt, {g.sector_size} bytes/sector",
        f"Partitions: {len(parts)}",
    ]
    for p in parts:
        tag = "boot" if p.bootable else "    "
        lines.append(
            f"  [{tag}] {p.name} start_lba={p.start_lba} sectors={p.sector_count}"
        )
    return "\n".join(lines)