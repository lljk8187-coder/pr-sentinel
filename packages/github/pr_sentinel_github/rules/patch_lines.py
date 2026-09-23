"""Map unified-diff character offsets to new-file line numbers."""

from __future__ import annotations

import re

_HUNK_RE = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@")


def patch_offset_to_new_line(patch: str, char_offset: int) -> int | None:
    """Return the new-file line for a character offset inside a unified diff.

    Matches on hunk headers or deleted (``-``) lines yield ``None``.
    """
    if not patch or char_offset < 0 or char_offset >= len(patch):
        return None

    next_new: int | None = None
    pos = 0
    for line in patch.splitlines(keepends=True):
        end = pos + len(line)
        stripped = line.rstrip("\r\n")
        hit = pos <= char_offset < end

        if stripped.startswith("@@"):
            m = _HUNK_RE.match(stripped)
            if m:
                next_new = int(m.group(1))
            if hit:
                return None
        elif stripped.startswith("\\"):
            if hit:
                return None
        elif stripped.startswith("+") or stripped.startswith(" "):
            line_no = next_new
            if hit:
                return line_no
            if next_new is not None:
                next_new += 1
        elif stripped.startswith("-"):
            if hit:
                return None
        else:
            if hit:
                return next_new

        pos = end
    return None
