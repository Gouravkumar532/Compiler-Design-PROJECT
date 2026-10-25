"""Character-level source provenance for generated (analysis) text.

The preprocessor expands quoted includes and macros into an *analysis source*.
The parser reasons about analysis coordinates, but every diagnostic and patch
must be expressed in the coordinates of the *physical* file that the text came
from.  ``OriginMap`` records, for every character of the analysis text, which
physical file/line/column produced it, and whether the character belongs to
generated text (macro replacement or a repair translation).
"""

import bisect
import difflib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class OriginSpan:
    """A physical source span. Lines/columns are 1-based; the end is exclusive."""
    file: str
    line: int
    col: int
    end_line: int
    end_col: int
    generated: bool = False


class OriginMap:
    """Per-character origin table for one analysis text."""

    def __init__(self) -> None:
        self.text: str = ""
        self.files: List[str] = []
        self._file_ids: Dict[str, int] = {}
        self.file_id: List[int] = []
        self.line: List[int] = []
        self.col: List[int] = []
        self.gen: List[int] = []  # 0 = literal text, n>0 = spans[n-1]
        self.spans: List[Tuple[int, int, int, int, int]] = []
        self._parts: List[str] = []
        self._line_starts: Optional[List[int]] = None

    # ------------------------------------------------------------------ build
    def _fid(self, file: str) -> int:
        fid = self._file_ids.get(file)
        if fid is None:
            fid = len(self.files)
            self.files.append(file)
            self._file_ids[file] = fid
        return fid

    def add_literal(self, text: str, file: str, line: int, col: int) -> None:
        """Append ``text`` that maps 1:1 onto ``file`` starting at (line, col)."""
        if not text:
            return
        fid = self._fid(file)
        n = len(text)
        self._parts.append(text)
        self.file_id.extend([fid] * n)
        self.line.extend([line] * n)
        self.col.extend(range(col, col + n))
        self.gen.extend([0] * n)
        self._line_starts = None

    def add_generated(
        self, text: str, file: str, line: int, col: int, end_line: int, end_col: int
    ) -> None:
        """Append generated text that maps onto the whole span (line,col)-(end)."""
        if not text:
            return
        fid = self._fid(file)
        self.spans.append((fid, line, col, end_line, end_col))
        idx = len(self.spans)
        n = len(text)
        self._parts.append(text)
        self.file_id.extend([fid] * n)
        self.line.extend([line] * n)
        self.col.extend([col] * n)
        self.gen.extend([idx] * n)
        self._line_starts = None

    def add_newline(self, file: str, line: int, col: int) -> None:
        self.add_literal("\n", file, line, col)

    def drop_trailing_newline(self) -> None:
        text = "".join(self._parts)
        if text.endswith("\n"):
            text = text[:-1]
            self._parts = [text]
            for lst in (self.file_id, self.line, self.col, self.gen):
                lst.pop()
        self._line_starts = None

    def finish(self) -> "OriginMap":
        self.text = "".join(self._parts)
        self._parts = [self.text]
        self._line_starts = None
        return self

    @classmethod
    def identity(cls, text: str, file: str) -> "OriginMap":
        """Map ``text`` onto itself (direct lexing, no preprocessing)."""
        omap = cls()
        lines = text.split("\n")
        for idx, ln in enumerate(lines, start=1):
            omap.add_literal(ln, file, idx, 1)
            if idx < len(lines):
                omap.add_newline(file, idx, len(ln) + 1)
        return omap.finish()

    # ------------------------------------------------------------------ query
    def __len__(self) -> int:
        return len(self.line)

    def _starts(self) -> List[int]:
        if self._line_starts is None:
            starts = [0]
            text = self.text
            idx = text.find("\n")
            while idx != -1:
                starts.append(idx + 1)
                idx = text.find("\n", idx + 1)
            self._line_starts = starts
        return self._line_starts

    def offset_of(self, line: int, col: int) -> int:
        """Analysis (line, col) -> character offset in the analysis text."""
        starts = self._starts()
        if line < 1:
            return 0
        if line > len(starts):
            return len(self.text)
        return min(starts[line - 1] + max(0, col - 1), len(self.text))

    def locate(self, start: int, end: Optional[int] = None) -> OriginSpan:
        """Physical origin of analysis text range [start, end)."""
        n = len(self.line)
        if n == 0:
            return OriginSpan("", 1, 1, 1, 2, False)
        start = max(0, min(start, n - 1))
        if end is None or end <= start:
            end = start + 1
        end = min(end, n)
        first_gen = next((k for k in range(start, end) if self.gen[k]), -1)
        if self.gen[start]:
            fid, l, c, el, ec = self.spans[self.gen[start] - 1]
            return OriginSpan(self.files[fid], l, c, el, ec, True)
        file = self.files[self.file_id[start]]
        line = self.line[start]
        col = self.col[start]
        last = end - 1
        if first_gen != -1:
            # The range runs into generated text: extend to the invocation end.
            fid, _l, _c, el, ec = self.spans[self.gen[first_gen] - 1]
            if self.files[fid] == file:
                return OriginSpan(file, line, col, el, ec, True)
        while last > start and (self.gen[last] or self.file_id[last] != self.file_id[start]):
            last -= 1
        end_line = self.line[last]
        end_col = self.col[last] + 1
        if self.text and self.text[last] == "\n":
            end_line, end_col = self.line[last], self.col[last]
        return OriginSpan(file, line, col, end_line, max(end_col, col), first_gen != -1)

    def locate_lc(self, line: int, col: int, length: int = 1) -> OriginSpan:
        off = self.offset_of(line, col)
        return self.locate(off, off + max(1, length))

    def is_generated(self, line: int, col: int) -> bool:
        off = self.offset_of(line, col)
        return bool(self.gen) and off < len(self.gen) and bool(self.gen[off])

    # ----------------------------------------------------------------- derive
    def derive(self, new_text: str) -> "OriginMap":
        """Origin map for ``new_text`` derived from this map's text.

        Unchanged characters keep their origin; inserted/replaced characters are
        attributed (as generated text) to the span they replaced.
        """
        omap = OriginMap()
        omap.files = list(self.files)
        omap._file_ids = dict(self._file_ids)
        omap.spans = list(self.spans)
        old = self.text
        if not old:
            omap.add_generated(new_text, self.files[0] if self.files else "", 1, 1, 1, 2)
            return omap.finish()
        matcher = difflib.SequenceMatcher(None, old, new_text, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                omap.file_id.extend(self.file_id[i1:i2])
                omap.line.extend(self.line[i1:i2])
                omap.col.extend(self.col[i1:i2])
                omap.gen.extend(self.gen[i1:i2])
            elif tag in ("replace", "insert"):
                if i2 > i1:
                    span = self.locate(i1, i2)
                else:
                    anchor = max(0, i1 - 1)
                    span = self.locate(anchor, anchor + 1)
                fid = omap._fid(span.file)
                omap.spans.append((fid, span.line, span.col, span.end_line, span.end_col))
                idx = len(omap.spans)
                n = j2 - j1
                omap.file_id.extend([fid] * n)
                omap.line.extend([span.line] * n)
                omap.col.extend([span.col] * n)
                omap.gen.extend([idx] * n)
            # "delete": nothing to add
        omap.text = new_text
        omap._parts = [new_text]
        return omap
