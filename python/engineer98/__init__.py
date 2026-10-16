"""Engineer98 — decompilation and reverse engineering suite for PC98 software."""

from .analysis import (
    CodeMap,
    Function,
    FunctionBuilder,
    FunctionMap,
    FunctionRefs,
    ReferenceMap,
    StringEntry,
    StringMap,
    Traversal,
    build_references,
    extract_strings,
)
from ._core import ExeFile, Geometry, Image, Partition, version
from .disasm import Instruction, Operand, OperandKind, X86Disassembler, disassemble
from .fs import FatVolume


__version__ = version()
__all__ = [
    "__version__",
    "CodeMap",
    "ExeFile",
    "FatVolume",
    "Function",
    "FunctionBuilder",
    "FunctionMap",
    "Geometry",
    "Image",
    "Instruction",
    "Operand",
    "OperandKind",
    "Partition",
    "Traversal",
    "X86Disassembler",
    "describe_image",
    "disassemble",
]

def describe_image(path: str) -> str:
    """Open a disk image and return a human-readable summary string."""
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