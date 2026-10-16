"""Cross-reference pass: what does each function reference?

Given a ``FunctionMap``, a ``CodeMap``, and a ``StringMap``, produce a
``ReferenceMap`` that, for each function entry, lists the strings it
loads and the code addresses it references as data or callbacks.

The key insight: classify each immediate operand by *looking it up* in
the string set and code map, rather than guessing from its numeric range.
A value like 0x1468 is only meaningful once we know it's a code address
and not a string.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .function import FunctionMap
from .strings import StringMap


@dataclass
class FunctionRefs:
    entry: int
    strings: set[int] = field(default_factory=set)       # string addresses
    code_refs: set[int] = field(default_factory=set)     # code addresses as data
    other_immediates: set[int] = field(default_factory=set)  # everything else


@dataclass
class ReferenceMap:
    refs: dict[int, FunctionRefs] = field(default_factory=dict)
    strings: StringMap | None = None

    def get(self, entry: int) -> FunctionRefs | None:
        return self.refs.get(entry)

    def __len__(self) -> int:
        return len(self.refs)

    def __iter__(self):
        return iter(self.refs.values())


def build_references(
    function_map: FunctionMap,
    string_map: StringMap,
) -> ReferenceMap:
    """Classify immediates in every function's instructions."""
    code_map = function_map.code_map
    if code_map is None:
        return ReferenceMap(strings=string_map)

    code_addrs = set(code_map.instructions.keys())
    result = ReferenceMap(strings=string_map)

    for func in function_map:
        fr = FunctionRefs(entry=func.entry)
        for insn in func.instructions:
            for op in insn.operands:
                if op.kind.value != "imm" or op.imm is None:
                    continue
                value = op.imm & 0xFFFF
                if value in string_map:
                    fr.strings.add(value)
                elif value in code_addrs:
                    fr.code_refs.add(value)
                else:
                    fr.other_immediates.add(value)
        result.refs[func.entry] = fr

    return result