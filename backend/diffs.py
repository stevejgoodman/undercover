"""The lines that change between two texts, as the lab finds them with difflib, for
the configuration's versions and the recipe's."""

import difflib

from backend.models import DiffLine, LineChange


def diff(old: str, new: str) -> list[DiffLine]:
    """Return every line of the new text and every line taken out of the old, in
    order, each marked added, removed or unchanged."""
    before, after = old.splitlines(), new.splitlines()
    lines: list[DiffLine] = []
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    for kind, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if kind == "equal":
            lines += lines_of(LineChange.UNCHANGED, after[new_start:new_end])
            continue
        lines += lines_of(LineChange.REMOVED, before[old_start:old_end])
        lines += lines_of(LineChange.ADDED, after[new_start:new_end])
    return lines


def lines_of(change: LineChange, texts: list[str]) -> list[DiffLine]:
    return [DiffLine(change=change, text=text) for text in texts]
