"""Recursive traversal analysis.

Starts from a seed address and follows control flow to build a code map:
every instruction address that's reachable from the seed, plus the edges
between them (fall-through, direct jump, direct call).

Addresses are *module offsets*: 0 is the first byte of the load module
(immediately after the MZ header). Given a `CS:IP`, the module offset is
``(CS - e_cs) * 16 + IP``. See `exe` module for `e_cs`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from ..disasm import Instruction, X86Disassembler
from .._core import ExeFile


# Capstone stop condition: it yields instructions until it can't decode.
# We wrap it to decode one instruction at a time from a specific offset.
_CHUNK = 64  # bytes we hand to capstone per decode attempt


@dataclass
class CodeMap:
    """The result of a traversal pass."""

    # address (module offset) -> Instruction
    instructions: dict[int, Instruction] = field(default_factory=dict)
    # addresses that received a `call` or far jump target
    function_entries: set[int] = field(default_factory=set)
    # (source_addr, target_addr) for direct jumps and calls
    edges: set[tuple[int, int]] = field(default_factory=set)
    # addresses where a linear run terminated without an explicit jump
    terminal_addresses: set[int] = field(default_factory=set)

    def __len__(self) -> int:
        return len(self.instructions)

    def __contains__(self, addr: int) -> bool:
        return addr in self.instructions


class Traversal:
    """Recursive traversal disassembler over a module's load image."""

    def __init__(
        self,
        module_bytes: bytes,
        e_cs: int,
        max_instructions: int = 500_000,
    ) -> None:
        self.module = module_bytes
        self.e_cs = e_cs
        self.max_instructions = max_instructions
        self._dis = X86Disassembler()

    @classmethod
    def from_exe(cls, exe: ExeFile) -> "Traversal":
        return cls(exe.code_bytes(), exe.entry_cs)

    # -- Address helpers ---------------------------------------------------

    def _cs_ip_to_module_offset(self, cs: int, ip: int) -> int:
        """Convert a CS:IP pair to a module offset.

        All segment values in the file live in a single reference frame
        where 0 is the start of the load module. A ``CS:IP`` in the file
        maps to ``CS * 16 + IP`` module offset.
        """
        return cs * 16 + ip

    @classmethod
    def from_exe(cls, exe: ExeFile) -> "Traversal":
        return cls(exe.code_bytes(), exe.entry_cs)

    @staticmethod
    def entry_offset(exe: ExeFile) -> int:
        """Module offset of the EXE's entry point."""
        return exe.entry_cs * 16 + exe.entry_ip

    def _read_target_operand(self, insn: Instruction) -> int | None:
        """Extract the module offset of a direct call or jump target, if any.

        Two cases:
        - Far call/jmp (opcodes 0x9A / 0xEA): segment and offset come from
          the raw bytes. Target = segment * 16 + offset.
        - Near call/jmp: Capstone's single imm operand is already a flat
          target address, since we pass base_addr to disassemble().
        Indirect targets (register or memory operands) return None.
        """
        # Far call / far jump
        if len(insn.bytes_) >= 5 and insn.bytes_[0] in (0x9A, 0xEA):
            offset = insn.bytes_[1] | (insn.bytes_[2] << 8)
            segment = insn.bytes_[3] | (insn.bytes_[4] << 8)
            return segment * 16 + offset

        # Near call / jump
        if not insn.operands:
            return None
        op = insn.operands[0]
        if op.kind.value != "imm" or op.imm is None:
            return None
        return op.imm
    # -- The traversal -----------------------------------------------------

    def trace(self, entry_offset: int) -> CodeMap:
        """Recursively follow control flow from ``entry_offset``."""
        code_map = CodeMap()
        worklist: deque[int] = deque([entry_offset])
        visited_seeds: set[int] = set()

        while worklist:
            start = worklist.popleft()
            if start in visited_seeds:
                continue
            visited_seeds.add(start)
            self._run_linear(code_map, start, worklist)

            if len(code_map.instructions) >= self.max_instructions:
                break

        return code_map

    def _run_linear(
        self,
        code_map: CodeMap,
        start: int,
        worklist: deque[int],
    ) -> None:
        """Decode forward from ``start`` until control flow stops."""
        addr = start
        while True:
            if addr in code_map.instructions:
                return
            if addr >= len(self.module):
                code_map.terminal_addresses.add(addr)
                return
            if len(code_map.instructions) >= self.max_instructions:
                return

            insn = self._decode_one(addr)
            if insn is None:
                code_map.terminal_addresses.add(addr)
                return

            code_map.instructions[addr] = insn

            if insn.is_return:
                return
            if insn.is_jump:
                target = self._read_target_operand(insn)
                if target is not None:
                    code_map.edges.add((addr, target))
                    if insn.is_call:
                        code_map.function_entries.add(target)
                    worklist.append(target)
                if not insn.is_conditional_jump:
                    return
                addr = insn.end_address
                continue
            if insn.is_call:
                target = self._read_target_operand(insn)
                if target is not None:
                    code_map.edges.add((addr, target))
                    code_map.function_entries.add(target)
                    worklist.append(target)
                addr = insn.end_address
                continue

            addr = insn.end_address

    def _decode_one(self, addr: int) -> Instruction | None:
        """Decode exactly one instruction from module offset ``addr``."""
        chunk = self.module[addr : addr + _CHUNK]
        result = self._dis.disassemble(chunk, base_addr=addr, max_instructions=1)
        return result[0] if result else None