"""x86 / V30 disassembler backed by Capstone.

Capstone supports 16-bit real-mode x86 out of the box. PC-98 code is
16-bit real mode, sometimes with 80186/V30 extensions, which Capstone
handles as part of its x86 decoder. This module is the *only* place that
imports Capstone; everything downstream sees ``Instruction`` objects.
"""

from __future__ import annotations

from capstone import Cs, CS_ARCH_X86, CS_MODE_16
from capstone.x86 import (
    X86_OP_REG,
    X86_OP_IMM,
    X86_OP_MEM,
    X86_REG_INVALID,
)

from .instruction import Instruction, Operand, OperandKind


# Instructions Capstone knows are control flow, mapped to our hints.
# Capstone also exposes `insn.groups`, but the group constants changed
# between versions; matching on mnemonic prefixes is stable across them.
_CALL_MNEMONICS = {"call", "lcall"}
_RET_MNEMONICS = {"ret", "retf", "iret", "iretd", "iretq"}
_INT_MNEMONICS = {"int", "int1", "int3", "into"}


def _is_jump(mnemonic: str) -> bool:
    return mnemonic.startswith("j") and mnemonic not in {"jmp"} or mnemonic == "jmp"


def _operand_from_capstone(insn, op) -> Operand:
    """Convert a Capstone x86 operand into our flat ``Operand`` type."""
    text = insn.op_str  # rough; we refine per-operand below when possible

    if op.type == X86_OP_REG:
        name = insn.reg_name(op.reg)
        return Operand(kind=OperandKind.REG, text=name, reg=name)

    if op.type == X86_OP_IMM:
        return Operand(
            kind=OperandKind.IMM,
            text=f"0x{op.imm & 0xFFFFFFFF:x}",
            imm=op.imm,
        )

    if op.type == X86_OP_MEM:
        mem = op.mem
        base = insn.reg_name(mem.base) if mem.base != X86_REG_INVALID else None
        index = insn.reg_name(mem.index) if mem.index != X86_REG_INVALID else None
        segment = insn.reg_name(mem.segment) if mem.segment != X86_REG_INVALID else None
        return Operand(
            kind=OperandKind.MEM,
            text=text,
            base=base,
            index=index,
            scale=mem.scale or None,
            disp=mem.disp,
            segment=segment,
        )

    return Operand(kind=OperandKind.UNKNOWN, text=text)


class X86Disassembler:
    """Wraps a Capstone engine configured for 16-bit x86."""

    def __init__(self, syntax: str = "intel") -> None:
        self._md = Cs(CS_ARCH_X86, CS_MODE_16)
        self._md.detail = True
        # Intel syntax matches the IDA output we have for VG.EXE.
        if syntax == "intel":
            self._md.syntax = 0  # CS_OPT_SYNTAX_INTEL
        elif syntax == "att":
            self._md.syntax = 1  # CS_OPT_SYNTAX_ATT
        else:
            raise ValueError(f"unknown syntax: {syntax!r}")

    def disassemble(
        self,
        code: bytes,
        base_addr: int = 0,
        max_instructions: int | None = None,
    ) -> list[Instruction]:
        """Decode ``code`` starting at ``base_addr``.

        Stops early if the decoder encounters bytes it can't decode, or if
        ``max_instructions`` is reached. Never raises on bad bytes; the
        caller gets whatever decoded successfully.
        """
        out: list[Instruction] = []
        for insn in self._md.disasm(code, base_addr):
            operands = [_operand_from_capstone(insn, op) for op in insn.operands]
            mnemonic = insn.mnemonic.lower()

            out.append(
                Instruction(
                    address=insn.address,
                    size=insn.size,
                    bytes_=bytes(insn.bytes),
                    mnemonic=mnemonic,
                    op_str=insn.op_str,
                    operands=operands,
                    is_call=mnemonic in _CALL_MNEMONICS,
                    is_jump=mnemonic in {"jmp", "ljmp"} or (
                        mnemonic.startswith("j") and mnemonic not in _RET_MNEMONICS
                    ),
                    is_conditional_jump=(
                        mnemonic.startswith("j")
                        and mnemonic not in {"jmp", "ljmp"}
                    ),
                    is_return=mnemonic in _RET_MNEMONICS,
                    is_interrupt=mnemonic in _INT_MNEMONICS,
                )
            )
            if max_instructions is not None and len(out) >= max_instructions:
                break
        return out


# Module-level default instance. Constructing a Cs is cheap but not free;
# callers who disassemble frequently can import and reuse this, or make
# their own X86Disassembler.
_default = X86Disassembler()


def disassemble(
    code: bytes,
    base_addr: int = 0,
    max_instructions: int | None = None,
) -> list[Instruction]:
    """Disassemble 16-bit x86 code using the shared default engine."""
    return _default.disassemble(code, base_addr, max_instructions)