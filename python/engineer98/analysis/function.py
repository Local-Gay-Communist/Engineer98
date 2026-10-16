"""Function identification and body extraction.

Given a ``CodeMap`` from traversal, group instructions into functions.

We use the **contiguous range** model: a function is a single byte range
``[start, end)`` plus the ordered list of instructions inside it. Gaps —
data embedded in code, alignment padding, jump tables — stay within the
range but aren't represented as instructions. This matches how IDA and
every other disassembler displays code, and it gives the decompiler a
single address range to linearize per function.

The key rule: a function's body traversal stops at any other function
entry *and* at any address already claimed by a previously-built function.
Iterating entries in address order means the lowest-address function wins
shared tails, and the resulting function set is a strict partition of the
reachable code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..disasm import Instruction
from .traversal import CodeMap, resolve_target_address


@dataclass
class Function:
    """One identified function and its instruction range."""

    entry: int
    name: str
    start: int
    end: int
    instructions: list[Instruction] = field(default_factory=list)
    calls_out: set[int] = field(default_factory=set)
    callers: set[int] = field(default_factory=set)

    @property
    def size(self) -> int:
        return self.end - self.start

    @property
    def instruction_count(self) -> int:
        return len(self.instructions)

    def __repr__(self) -> str:
        return (
            f"<Function {self.name} @ {self.entry:#x} "
            f"size={self.size} insns={self.instruction_count} "
            f"callers={len(self.callers)} callees={len(self.calls_out)}>"
        )


@dataclass
class FunctionMap:
    """The result of a function-identification pass."""

    functions: dict[int, Function] = field(default_factory=dict)
    code_map: CodeMap | None = None
    entry_point: int | None = None

    def get(self, entry: int) -> Function | None:
        return self.functions.get(entry)

    def containing(self, addr: int) -> Function | None:
        """Find the function whose byte range contains ``addr``, if any."""
        for func in self.functions.values():
            if func.start <= addr < func.end:
                return func
        return None

    def __len__(self) -> int:
        return len(self.functions)

    def __iter__(self):
        return iter(self.functions.values())


class FunctionBuilder:
    """Groups the instructions of a ``CodeMap`` into ``Function`` objects."""

    def __init__(self, code_map: CodeMap, entry_point: int | None = None) -> None:
        self.code_map = code_map
        self.entry_point = entry_point
        # All function starts, including the EXE entry point (which is not
        # itself a `call` target in the code map).
        self._entries: set[int] = set(code_map.function_entries)
        if entry_point is not None:
            self._entries.add(entry_point)

    def build(self) -> FunctionMap:
        funcs: dict[int, Function] = {}
        # Addresses already claimed by a previously-built function. Iterating
        # entries in address order means the lowest-address function wins
        # shared tails (multiple entries falling into the same epilogue).
        claimed: set[int] = set()

        for entry in sorted(self._entries):
            if entry in claimed:
                continue
            func = self._analyze_one(entry, claimed)
            if func is not None:
                funcs[entry] = func
                for insn in func.instructions:
                    claimed.add(insn.address)

        # Populate callers based on callees that actually became functions.
        for func in funcs.values():
            for target in func.calls_out:
                callee = funcs.get(target)
                if callee is not None:
                    callee.callers.add(func.entry)

        return FunctionMap(
            functions=funcs,
            code_map=self.code_map,
            entry_point=self.entry_point,
        )

    # -- Internals ---------------------------------------------------------

    def _analyze_one(
        self, entry: int, claimed: set[int]
    ) -> Function | None:
        if entry not in self.code_map.instructions:
            return None

        visited: dict[int, Instruction] = {}
        calls_out: set[int] = set()
        worklist: list[int] = [entry]

        while worklist:
            addr = worklist.pop()
            if addr in visited or addr in claimed:
                continue
            # Stop at any *other* function entry.
            if addr in self._entries and addr != entry:
                continue
            insn = self.code_map.instructions.get(addr)
            if insn is None:
                continue

            visited[addr] = insn

            if insn.is_return:
                continue

            if insn.is_jump:
                target = resolve_target_address(insn)
                if target is not None and target not in self._entries:
                    # Follow internal jump targets (loops, branches within
                    # the same function). Don't follow jumps into other
                    # functions; those are tail calls in the best case and
                    # linker artifacts in the worst.
                    worklist.append(target)
                if not insn.is_conditional_jump:
                    continue
                worklist.append(insn.end_address)
                continue

            if insn.is_call:
                target = resolve_target_address(insn)
                if target is not None:
                    calls_out.add(target)
                # Calls return to the next instruction; keep going.
                worklist.append(insn.end_address)
                continue

            worklist.append(insn.end_address)

        if not visited:
            return None

        start = min(visited.keys())
        end = max(i.end_address for i in visited.values())
        ordered = sorted(visited.values(), key=lambda i: i.address)

        name = "entry" if entry == self.entry_point else f"sub_{entry:06X}"

        return Function(
            entry=entry,
            name=name,
            start=start,
            end=end,
            instructions=ordered,
            calls_out=calls_out,
        )