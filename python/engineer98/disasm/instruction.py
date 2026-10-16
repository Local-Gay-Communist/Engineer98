"""Instruction representation for the disassembler.

This module defines the *contract* between the disassembler and everything
that consumes it — analysis passes, the GUI, the decompiler, AI tooling.
No decoder-specific types leak past these dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class OperandKind(Enum):
    """Broad categories of x86 operands."""

    REG = "reg"
    IMM = "imm"
    MEM = "mem"
    FAR = "far"          # far pointer (seg:off)
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Operand:
    """One operand of an instruction.

    Kept deliberately flat so it serializes cleanly to JSON for AI tooling.
    """

    kind: OperandKind
    text: str            # Capstone's rendering, e.g. "ax", "1ADD", "[bx+si+4]"
    # Register operands
    reg: str | None = None
    # Immediate operands
    imm: int | None = None
    # Memory operands
    base: str | None = None
    index: str | None = None
    scale: int | None = None
    disp: int | None = None
    segment: str | None = None


@dataclass(frozen=True)
class Instruction:
    """A single decoded instruction at a specific address.

    ``address`` is the linear address in the analysis space (see the
    caller's ``base_addr`` argument). ``bytes_`` is the raw encoding.
    """

    address: int
    size: int
    bytes_: bytes
    mnemonic: str
    op_str: str                  # raw operand string from the decoder
    operands: list[Operand] = field(default_factory=list)

    # Control-flow hints. Populated by the decoder when it can tell.
    is_call: bool = False
    is_jump: bool = False
    is_conditional_jump: bool = False
    is_return: bool = False
    is_interrupt: bool = False

    @property
    def end_address(self) -> int:
        return self.address + self.size

    def __str__(self) -> str:
        return f"{self.address:08x}  {self.mnemonic:<8} {self.op_str}".rstrip()