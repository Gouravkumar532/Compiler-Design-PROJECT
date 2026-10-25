import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from src.paths import canonical_path, is_sentinel
from src.provenance import OriginMap, OriginSpan


@dataclass
class PreprocessResult:
    """Outcome of one preprocessing call.

    ``original_source`` is the untouched text of the entry file and is the only
    buffer a repair may ever be written to.  ``analysis_source`` is the expanded
    text used purely for parsing; ``origin`` maps every analysis character back
    to its physical file/line/column.
    """
    original_source: str
    analysis_source: str
    included_headers: Set[str]
    included_files: Set[str]
    macros: Dict[str, str]
    origin: OriginMap
    file_sources: Dict[str, str]
    entry_file: str = "<stdin>"
    display_names: Dict[str, str] = field(default_factory=dict)

    # ---------------------------------------------------------------- helpers
    def locate(self, line: int, col: int, length: int = 1) -> OriginSpan:
        """Analysis (line, col) -> physical origin span."""
        return self.origin.locate_lc(line, col, length)

    def source_for(self, file: Optional[str]) -> str:
        """Original text of a physical file known to this preprocessing call."""
        key = file or self.entry_file
        if key in self.file_sources:
            return self.file_sources[key]
        return self.original_source if key == self.entry_file else ""

    @property
    def identity(self) -> bool:
        """True when analysis text equals the original text (no expansion)."""
        return self.analysis_source == self.original_source

    @property
    def line_map(self) -> Dict[int, Tuple[str, int]]:
        """Compatibility view: analysis line -> (file, original line)."""
        result: Dict[int, Tuple[str, int]] = {}
        omap = self.origin
        starts = omap._starts()
        for idx, off in enumerate(starts, start=1):
            if off < len(omap.line):
                span = omap.locate(off, off + 1)
                result[idx] = (span.file, span.line)
        return result


class _Context:
    """Mutable state of exactly one preprocessing call."""

    def __init__(self, entry_file: str):
        self.entry_file = entry_file
        self.macros: Dict[str, str] = {}
        self.included_files: Set[str] = set()
        self.included_headers: Set[str] = set()
        self.file_sources: Dict[str, str] = {}
        self.display_names: Dict[str, str] = {}
        self.origin = OriginMap()
        self.in_block_comment = False


_TOKEN_RE = re.compile(
    r'"(?:\\.|[^"\\])*"?'      # string literal (possibly unterminated at EOL)
    r"|'(?:\\.|[^'\\])*'?"     # character literal
    r"|//.*"                   # line comment
    r"|/\*.*?\*/"              # same-line block comment
    r"|/\*.*"                  # block comment opening (continues on later lines)
    r"|[A-Za-z_][A-Za-z0-9_]*"  # identifier
    r"|\d[A-Za-z0-9_.]*"       # number
)


def _expand_value(text: str, macros: Dict[str, str], disabled: frozenset, depth: int = 0) -> str:
    """Expand macros inside a macro value (strings/comments protected)."""
    if depth > 16 or not macros:
        return text
    out: List[str] = []
    last = 0
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0)
        if tok[0].isalpha() or tok[0] == "_":
            if tok in macros and tok not in disabled:
                out.append(text[last:m.start()])
                out.append(_expand_value(macros[tok], macros, disabled | {tok}, depth + 1))
                last = m.end()
    out.append(text[last:])
    return "".join(out)


class Preprocessor:
    """Basic C preprocessor supporting #include and #define.

    Every public call (``preprocess``/``process``) runs in a fresh private
    context: macros, included headers and the include-deduplication set can
    never leak from one call to the next, even when one ``Preprocessor``
    instance is reused.  Only the configured include paths are shared and they
    are immutable.
    """

    def __init__(self, include_paths: Optional[List[str]] = None):
        self._include_paths: Tuple[str, ...] = tuple(include_paths or (".",))
        # Snapshots of the most recent call (compatibility attributes). They are
        # replaced -- never accumulated -- on every call.
        self.macros: Dict[str, str] = {}
        self.included_files: Set[str] = set()
        self.included_headers: Set[str] = set()

    @property
    def include_paths(self) -> Tuple[str, ...]:
        return self._include_paths

    # ------------------------------------------------------------- public API
    def preprocess(self, source: str, filename: str = "<stdin>") -> PreprocessResult:
        entry = canonical_path(filename)
        ctx = _Context(entry)
        ctx.file_sources[entry] = source
        ctx.display_names[entry] = filename if is_sentinel(filename) else filename

        self._run(ctx, source, entry, depth=0)
        if not source.endswith(("\n", "\r")):
            ctx.origin.drop_trailing_newline()
        ctx.origin.finish()

        result = PreprocessResult(
            original_source=source,
            analysis_source=ctx.origin.text,
            included_headers=set(ctx.included_headers),
            included_files=set(ctx.included_files),
            macros=dict(ctx.macros),
            origin=ctx.origin,
            file_sources=dict(ctx.file_sources),
            entry_file=entry,
            display_names=dict(ctx.display_names),
        )
        self.macros = dict(result.macros)
        self.included_files = set(result.included_files)
        self.included_headers = set(result.included_headers)
        return result

    def process(self, source: str, filename: str = "<stdin>") -> str:
        """Compatibility wrapper returning preprocessed analysis source text."""
        return self.preprocess(source, filename).analysis_source

    # --------------------------------------------------------------- internals
    def _run(self, ctx: _Context, source: str, file: str, depth: int) -> None:
        base_dir = os.path.dirname(file) if not is_sentinel(file) else os.getcwd()
        lines = source.splitlines()
        omap = ctx.origin
        if not lines and depth > 0:
            omap.add_newline(file, 1, 1)
            return

        for idx, line in enumerate(lines):
            lineno = idx + 1
            stripped = line.strip()
            eol_col = len(line) + 1

            def emit_generated(text: str) -> None:
                omap.add_generated(text, file, lineno, 1, lineno, eol_col)
                omap.add_newline(file, lineno, eol_col)

            if stripped.startswith("#include") and not ctx.in_block_comment:
                match_quote = re.match(r'#include\s*["\']([^"\']+)["\']', stripped)
                match_angle = re.match(r'#include\s*<([^>]+)>', stripped)
                if match_quote:
                    inc_path = match_quote.group(1).strip()
                    ctx.included_headers.add(inc_path)
                    full_path = self._resolve_path(inc_path, base_dir)
                    if full_path and full_path != ctx.entry_file and full_path not in ctx.included_files:
                        if depth >= 64:
                            emit_generated(f"// Error: maximum include depth (64) exceeded: {inc_path}")
                        else:
                            ctx.included_files.add(full_path)
                            try:
                                with open(full_path, "r", encoding="utf-8") as f:
                                    inc_source = f.read()
                            except (IOError, UnicodeDecodeError) as e:
                                emit_generated(f"// Error including {inc_path}: {e}")
                            else:
                                ctx.file_sources[full_path] = inc_source
                                ctx.display_names.setdefault(full_path, os.path.abspath(full_path))
                                self._run(ctx, inc_source, full_path, depth + 1)
                    else:
                        emit_generated(f"// Already included or missing: {inc_path}")
                elif match_angle:
                    inc_path = match_angle.group(1).strip()
                    ctx.included_headers.add(inc_path)
                    full_path = self._resolve_path(inc_path, base_dir)
                    if full_path and os.path.exists(full_path) and full_path != ctx.entry_file and full_path not in ctx.included_files:
                        if depth >= 64:
                            emit_generated(f"// Error: maximum include depth (64) exceeded: <{inc_path}>")
                        else:
                            ctx.included_files.add(full_path)
                            try:
                                with open(full_path, "r", encoding="utf-8") as f:
                                    inc_source = f.read()
                            except (IOError, UnicodeDecodeError) as e:
                                emit_generated(f"// Error including <{inc_path}>: {e}")
                            else:
                                ctx.file_sources[full_path] = inc_source
                                ctx.display_names.setdefault(full_path, os.path.abspath(full_path))
                                self._run(ctx, inc_source, full_path, depth + 1)
                    else:
                        emit_generated(f"// Standard header <{inc_path}> provided by compiler runtime")
                else:
                    emit_generated("")
                continue

            if stripped.startswith("#define") and not ctx.in_block_comment:
                def_match = re.match(r'#define\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+(.*))?$', stripped)
                if def_match:
                    name = def_match.group(1)
                    val = def_match.group(2) if def_match.group(2) is not None else ""
                    if "//" in val:
                        val = val.split("//")[0]
                    val = re.sub(r"/\*.*?\*/", "", val).strip()
                    ctx.macros[name] = val
                emit_generated("")
                continue

            if stripped.startswith("#undef") and not ctx.in_block_comment:
                undef_match = re.match(r'#undef\s+([A-Za-z_][A-Za-z0-9_]*)', stripped)
                if undef_match:
                    ctx.macros.pop(undef_match.group(1), None)
                emit_generated("")
                continue

            self._emit_expanded_line(ctx, line, file, lineno)

    def _emit_expanded_line(self, ctx: _Context, line: str, file: str, lineno: int) -> None:
        """Emit one source line, expanding macros and recording origin spans."""
        omap = ctx.origin
        pos = 0
        n = len(line)

        # Continue an unfinished block comment from a previous line.
        if ctx.in_block_comment:
            end = line.find("*/")
            if end == -1:
                omap.add_literal(line, file, lineno, 1)
                omap.add_newline(file, lineno, n + 1)
                return
            omap.add_literal(line[: end + 2], file, lineno, 1)
            pos = end + 2
            ctx.in_block_comment = False

        literal_start = pos
        for m in _TOKEN_RE.finditer(line, pos):
            tok = m.group(0)
            first = tok[0]
            if first == "/" and tok.startswith("/*") and not tok.endswith("*/"):
                ctx.in_block_comment = True
                break
            if (first.isalpha() or first == "_") and tok in ctx.macros:
                if m.start() > literal_start:
                    omap.add_literal(line[literal_start:m.start()], file, lineno, literal_start + 1)
                value = _expand_value(ctx.macros[tok], ctx.macros, frozenset({tok}))
                if value:
                    omap.add_generated(value, file, lineno, m.start() + 1, lineno, m.end() + 1)
                else:
                    # An empty expansion still marks the invocation span as generated.
                    omap.add_generated(" ", file, lineno, m.start() + 1, lineno, m.end() + 1)
                literal_start = m.end()
        if literal_start < n:
            omap.add_literal(line[literal_start:], file, lineno, literal_start + 1)
        omap.add_newline(file, lineno, n + 1)

    def _resolve_path(self, rel_path: str, base_dir: str) -> Optional[str]:
        local_path = os.path.join(base_dir, rel_path)
        if os.path.exists(local_path):
            return canonical_path(local_path)
        for search_dir in self._include_paths:
            candidate = os.path.join(search_dir, rel_path)
            if os.path.exists(candidate):
                return canonical_path(candidate)
        return None
