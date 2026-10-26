import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from src.paths import canonical_path, is_sentinel
from src.provenance import OriginMap, OriginSpan

if TYPE_CHECKING:
    from src.analysis_result import Diagnostic


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
    diagnostics: List[Any] = field(default_factory=list)

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


@dataclass
class _CondFrame:
    directive: str
    ident: str
    file: str
    line: int
    parent_active: bool
    branch_active: bool
    has_else: bool = False
    any_branch_taken: bool = False


class _Context:
    """Mutable state of exactly one preprocessing call."""

    def __init__(self, entry_file: str):
        self.entry_file = entry_file
        self.macros: Dict[str, str] = {}
        self.function_macros: Dict[str, Any] = {}
        self.included_files: Set[str] = set()
        self.included_headers: Set[str] = set()
        self.file_sources: Dict[str, str] = {}
        self.display_names: Dict[str, str] = {}
        self.origin = OriginMap()
        self.in_block_comment = False
        self.cond_stack: List[_CondFrame] = []
        self.diagnostics: List[Any] = []

    def is_active(self) -> bool:
        if not self.cond_stack:
            return True
        return self.cond_stack[-1].branch_active

    def add_diagnostic(
        self,
        message: str,
        file: str,
        lineno: int,
        col: int = 1,
        end_col: Optional[int] = None,
        line_text: str = "",
        help_text: str = "",
    ) -> None:
        from src.analysis_result import Diagnostic, SourceLocation
        end_c = end_col if end_col is not None else max(col + 1, len(line_text) + 1)
        self.diagnostics.append(
            Diagnostic(
                code="P001",
                severity="error",
                message=message,
                location=SourceLocation(file, lineno, col, lineno, end_c),
                help_text=help_text,
                source_stage="preprocessor",
                source_line=line_text,
            )
        )


@dataclass
class _FunctionMacro:
    name: str
    params: List[str]
    body: str


_TOKEN_RE = re.compile(
    r'"(?:\\.|[^"\\])*"?'      # string literal (possibly unterminated at EOL)
    r"|'(?:\\.|[^'\\])*'?"     # character literal
    r"|//.*"                   # line comment
    r"|/\*.*?\*/"              # same-line block comment
    r"|/\*.*"                  # block comment opening (continues on later lines)
    r"|[A-Za-z_][A-Za-z0-9_]*"  # identifier
    r"|\d[A-Za-z0-9_.]*"       # number
)

_BODY_TOKEN_RE = re.compile(
    r'##'
    r'|#\s*([A-Za-z_][A-Za-z0-9_]*)'
    r'|"(?:\\.|[^"\\])*"?'
    r"|'(?:\\.|[^'\\])*'?"
    r'|[A-Za-z_][A-Za-z0-9_]*'
    r'|\d[A-Za-z0-9_.]*'
    r'|[^\sA-Za-z0-9_"\'#]+'
    r'|\s+'
)

_EXPR_TOKEN_RE = re.compile(
    r'\s*(?:'
    r'(\|\||&&|==|!=|<=|>=|<<|>>|[|^&<>+\-*/%!~?:()])' # operators & punctuation
    r'|(0[xX][0-9a-fA-F]+|0[bB][01]+|0[0-7]+|\d+)'     # numbers
    r"|'(\\.|[^'\\])'"                                  # char literals
    r')'
)

_PRECEDENCE = {
    '?': 1,
    '||': 2,
    '&&': 3,
    '|': 4,
    '^': 5,
    '&': 6,
    '==': 7, '!=': 7,
    '<': 8, '<=': 8, '>': 8, '>=': 8,
    '<<': 9, '>>': 9,
    '+': 10, '-': 10,
    '*': 11, '/': 11, '%': 11,
}


class _ExprParser:
    def __init__(self, tokens: List[Tuple[str, str]]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Optional[Tuple[str, str]]:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def consume(self, expected: Optional[str] = None) -> Tuple[str, str]:
        tok = self.peek()
        if not tok:
            raise ValueError("Unexpected end of expression")
        if expected and tok[1] != expected:
            raise ValueError(f"Expected '{expected}', got '{tok[1]}'")
        self.pos += 1
        return tok

    def parse(self) -> int:
        val = self.parse_expr(0)
        if self.pos < len(self.tokens):
            raise ValueError(f"Unexpected token '{self.tokens[self.pos][1]}' after expression")
        return val

    def parse_expr(self, min_prec: int) -> int:
        left = self.parse_unary()
        while True:
            tok = self.peek()
            if not tok:
                break
            ttype, op = tok
            if op == '?' and min_prec <= 1:
                self.consume('?')
                true_val = self.parse_expr(0)
                self.consume(':')
                false_val = self.parse_expr(1)
                left = true_val if left != 0 else false_val
                continue

            prec = _PRECEDENCE.get(op)
            if prec is None or prec < min_prec:
                break

            self.consume()
            right = self.parse_expr(prec + 1)

            if op == '||': left = 1 if (left != 0 or right != 0) else 0
            elif op == '&&': left = 1 if (left != 0 and right != 0) else 0
            elif op == '|': left = left | right
            elif op == '^': left = left ^ right
            elif op == '&': left = left & right
            elif op == '==': left = 1 if left == right else 0
            elif op == '!=': left = 1 if left != right else 0
            elif op == '<': left = 1 if left < right else 0
            elif op == '<=': left = 1 if left <= right else 0
            elif op == '>': left = 1 if left > right else 0
            elif op == '>=': left = 1 if left >= right else 0
            elif op == '<<': left = left << right
            elif op == '>>': left = left >> right
            elif op == '+': left = left + right
            elif op == '-': left = left - right
            elif op == '*': left = left * right
            elif op == '/': left = int(left / right) if right != 0 else 0
            elif op == '%': left = (left % right) if right != 0 else 0

        return left

    def parse_unary(self) -> int:
        tok = self.peek()
        if not tok:
            raise ValueError("Unexpected end of expression in unary")
        ttype, val = tok
        if val == '+':
            self.consume()
            return +self.parse_unary()
        elif val == '-':
            self.consume()
            return -self.parse_unary()
        elif val == '!':
            self.consume()
            return 1 if self.parse_unary() == 0 else 0
        elif val == '~':
            self.consume()
            return ~self.parse_unary()
        elif val == '(':
            self.consume('(')
            res = self.parse_expr(0)
            self.consume(')')
            return res
        elif ttype == 'NUM':
            self.consume()
            if val.startswith(('0x', '0X')): return int(val, 16)
            elif val.startswith(('0b', '0B')): return int(val, 2)
            elif val.startswith('0') and len(val) > 1 and val.isdigit(): return int(val, 8)
            return int(val)
        elif ttype == 'CHAR':
            self.consume()
            content = val[1:-1]
            if content.startswith('\\'):
                escape_map = {'\\n': 10, '\\t': 9, '\\r': 13, '\\0': 0, "\\'": 39, '\\\\': 92}
                return escape_map.get(content, ord(content[-1]))
            return ord(content)
        else:
            raise ValueError(f"Unexpected token in expression: '{val}'")


def _tokenize_c_expr(s: str) -> List[Tuple[str, str]]:
    tokens: List[Tuple[str, str]] = []
    pos = 0
    n = len(s)
    while pos < n:
        m = _EXPR_TOKEN_RE.match(s, pos)
        if not m:
            if s[pos].isspace():
                pos += 1
                continue
            raise ValueError(f"Invalid character in expression: '{s[pos]}'")
        if m.group(1):
            tokens.append(('OP', m.group(1)))
        elif m.group(2):
            tokens.append(('NUM', m.group(2)))
        elif m.group(3):
            tokens.append(('CHAR', m.group(0).strip()))
        pos = m.end()
    return tokens


def _scan_comment_transition(line: str, in_block_comment: bool) -> bool:
    """Scans line for block comment transitions, respecting string literals."""
    pos = 0
    if in_block_comment:
        end = line.find("*/")
        if end == -1:
            return True
        pos = end + 2
        in_block_comment = False

    for m in _TOKEN_RE.finditer(line, pos):
        tok = m.group(0)
        if tok[0] == "/" and tok.startswith("/*") and not tok.endswith("*/"):
            in_block_comment = True
            break
    return in_block_comment


def _split_macro_args(arg_str: str) -> List[str]:
    if not arg_str.strip():
        return []
    args = []
    current = []
    depth = 0
    in_quote = None
    escaped = False
    for ch in arg_str:
        if in_quote:
            if escaped: escaped = False
            elif ch == "\\": escaped = True
            elif ch == in_quote: in_quote = None
            current.append(ch)
        else:
            if ch in ('"', "'"):
                in_quote = ch
                current.append(ch)
            elif ch == "(":
                depth += 1
                current.append(ch)
            elif ch == ")":
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                args.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
    args.append("".join(current).strip())
    return args


def _find_matching_paren(s: str, open_idx: int) -> int:
    depth = 0
    in_q = None
    esc = False
    for i in range(open_idx, len(s)):
        c = s[i]
        if in_q:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == in_q: in_q = None
        else:
            if c in ('"', "'"): in_q = c
            elif c == '(': depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    return i
    return -1


def _expand_fn_macro_call(
    fn: _FunctionMacro,
    raw_args: List[str],
    macros: Dict[str, str],
    fn_macros: Dict[str, _FunctionMacro],
    disabled: frozenset = frozenset(),
    depth: int = 0
) -> str:
    if depth > 16:
        return ""
    # In C, arguments are expanded before substitution
    expanded_args = [_expand_all_macros(a, macros, fn_macros, frozenset(), depth + 1) for a in raw_args]
    param_map = dict(zip(fn.params, expanded_args))
    raw_param_map = dict(zip(fn.params, raw_args))
    tokens = []
    b_pos = 0
    body = fn.body
    while b_pos < len(body):
        bm = _BODY_TOKEN_RE.match(body, b_pos)
        if not bm:
            tokens.append(body[b_pos])
            b_pos += 1
            continue
        btok = bm.group(0)
        if btok == '##':
            tokens.append('##')
        elif btok.startswith('#') and bm.group(1) in raw_param_map:
            arg_val = raw_param_map[bm.group(1)]
            esc_val = arg_val.replace('\\', '\\\\').replace('"', '\\"')
            tokens.append(f'"{esc_val}"')
        elif btok in param_map:
            tokens.append(param_map[btok])
        else:
            tokens.append(btok)
        b_pos = bm.end()
    # Token pasting (##)
    res = []
    i = 0
    while i < len(tokens):
        if tokens[i] == '##':
            if res and i + 1 < len(tokens):
                prev = res.pop().rstrip()
                nxt = tokens[i+1].lstrip()
                res.append(prev + nxt)
                i += 2
                continue
        res.append(tokens[i])
        i += 1
    sub_text = ''.join(res)
    return _expand_all_macros(sub_text, macros, fn_macros, disabled | {fn.name}, depth + 1)


def _expand_all_macros(
    text: str,
    macros: Dict[str, str],
    fn_macros: Optional[Dict[str, _FunctionMacro]] = None,
    disabled: frozenset = frozenset(),
    depth: int = 0
) -> str:
    if depth > 16 or (not macros and not fn_macros):
        return text
    fn_map = fn_macros or {}
    out: List[str] = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOKEN_RE.search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        out.append(text[pos:m.start()])
        tok = m.group(0)
        first = tok[0]
        if first == "/" and (tok.startswith("/*") or tok.startswith("//")):
            out.append(tok)
            pos = m.end()
            continue
        if first in ('"', "'"):
            out.append(tok)
            pos = m.end()
            continue
        if (first.isalpha() or first == "_") and tok not in disabled:
            if tok in fn_map:
                rest = text[m.end():]
                stripped_rest = rest.lstrip()
                if stripped_rest.startswith("("):
                    open_idx = m.end() + (len(rest) - len(stripped_rest))
                    close_idx = _find_matching_paren(text, open_idx)
                    if close_idx != -1:
                        raw_args = _split_macro_args(text[open_idx + 1:close_idx])
                        fn = fn_map[tok]
                        expanded_body = _expand_fn_macro_call(fn, raw_args, macros, fn_map, disabled | {tok}, depth + 1)
                        out.append(expanded_body)
                        pos = close_idx + 1
                        continue
            elif tok in macros and tok not in fn_map:
                expanded_val = _expand_all_macros(macros[tok], macros, fn_map, disabled | {tok}, depth + 1)
                out.append(expanded_val)
                pos = m.end()
                continue
        out.append(tok)
        pos = m.end()
    return "".join(out)


def _strip_comment_from_macro_val(val: str) -> str:
    """Strip comments from macro value while preserving string and char literals."""
    in_quote = None
    escaped = False
    for i, ch in enumerate(val):
        if in_quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_quote:
                in_quote = None
        else:
            if ch in ('"', "'"):
                in_quote = ch
            elif ch == '/' and i + 1 < len(val):
                if val[i + 1] == '/':
                    return val[:i].rstrip()
                elif val[i + 1] == '*':
                    end = val.find('*/', i + 2)
                    if end != -1:
                        return (val[:i] + val[end + 2:]).strip()
                    else:
                        return val[:i].rstrip()
    return val.strip()


def _expand_value(text: str, macros: Dict[str, str], disabled: frozenset, depth: int = 0) -> str:
    """Expand macros inside a macro value (strings/comments protected). Compatibility wrapper."""
    return _expand_all_macros(text, macros, {}, disabled, depth)


class Preprocessor:
    """Basic C preprocessor supporting #include, #define, #undef, and conditional compilation.

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
            diagnostics=list(ctx.diagnostics),
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
        initial_cond_depth = len(ctx.cond_stack)

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

            # Check if continuing an unfinished multi-line block comment
            if ctx.in_block_comment:
                end = line.find("*/")
                if end == -1:
                    if ctx.is_active():
                        omap.add_literal(line, file, lineno, 1)
                        omap.add_newline(file, lineno, eol_col)
                    else:
                        emit_generated("")
                    continue
                else:
                    if not ctx.is_active():
                        ctx.in_block_comment = False
                        emit_generated("")
                        continue
                    self._emit_expanded_line(ctx, line, file, lineno)
                    continue

            # Check for preprocessor directives (#...)
            directive_match = re.match(r'^#\s*([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*(.*))?$', stripped)
            if directive_match:
                cmd = directive_match.group(1)
                args = directive_match.group(2) or ""

                # --- Conditionals: #if, #elif, #ifdef, #ifndef, #else, #endif ---
                if cmd == "if":
                    cond_expr = args.strip()
                    if not cond_expr:
                        ctx.add_diagnostic(
                            "#if directive requires an expression",
                            file=file,
                            lineno=lineno,
                            line_text=line,
                            help_text="syntax: #if <constant-expression>",
                        )
                    parent_active = ctx.is_active()
                    branch_active = False
                    if parent_active and cond_expr:
                        branch_active = self._eval_condition(ctx, cond_expr, file, lineno, line)
                    ctx.cond_stack.append(
                        _CondFrame(
                            directive="if",
                            ident=cond_expr,
                            file=file,
                            line=lineno,
                            parent_active=parent_active,
                            branch_active=branch_active,
                            has_else=False,
                            any_branch_taken=branch_active,
                        )
                    )
                    emit_generated("")
                    continue

                if cmd == "elif":
                    cond_expr = args.strip()
                    if len(ctx.cond_stack) <= initial_cond_depth:
                        ctx.add_diagnostic(
                            "unmatched #elif without #if, #ifdef or #ifndef",
                            file=file,
                            lineno=lineno,
                            line_text=line,
                            help_text="ensure #elif corresponds to an open conditional block",
                        )
                    else:
                        top = ctx.cond_stack[-1]
                        if top.has_else:
                            ctx.add_diagnostic(
                                "#elif after #else in the same conditional block",
                                file=file,
                                lineno=lineno,
                                line_text=line,
                                help_text="#else must be the last branch in a conditional block",
                            )
                        elif not cond_expr:
                            ctx.add_diagnostic(
                                "#elif directive requires an expression",
                                file=file,
                                lineno=lineno,
                                line_text=line,
                                help_text="syntax: #elif <constant-expression>",
                            )
                            top.branch_active = False
                        else:
                            if top.parent_active and not top.any_branch_taken:
                                cond_val = self._eval_condition(ctx, cond_expr, file, lineno, line)
                                if cond_val:
                                    top.branch_active = True
                                    top.any_branch_taken = True
                                else:
                                    top.branch_active = False
                            else:
                                top.branch_active = False
                    emit_generated("")
                    continue

                if cmd == "ifdef":
                    ident = args.split()[0] if args.split() else ""
                    if not ident or not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', ident):
                        ctx.add_diagnostic(
                            "macro name in #ifdef must be an identifier",
                            file=file,
                            lineno=lineno,
                            line_text=line,
                            help_text="syntax: #ifdef MACRO_NAME",
                        )
                    parent_active = ctx.is_active()
                    branch_active = parent_active and (ident in ctx.macros or ident in ctx.function_macros)
                    ctx.cond_stack.append(
                        _CondFrame(
                            directive="ifdef",
                            ident=ident,
                            file=file,
                            line=lineno,
                            parent_active=parent_active,
                            branch_active=branch_active,
                            has_else=False,
                            any_branch_taken=branch_active,
                        )
                    )
                    emit_generated("")
                    continue

                if cmd == "ifndef":
                    ident = args.split()[0] if args.split() else ""
                    if not ident or not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', ident):
                        ctx.add_diagnostic(
                            "macro name in #ifndef must be an identifier",
                            file=file,
                            lineno=lineno,
                            line_text=line,
                            help_text="syntax: #ifndef MACRO_NAME",
                        )
                    parent_active = ctx.is_active()
                    branch_active = parent_active and (ident not in ctx.macros and ident not in ctx.function_macros)
                    ctx.cond_stack.append(
                        _CondFrame(
                            directive="ifndef",
                            ident=ident,
                            file=file,
                            line=lineno,
                            parent_active=parent_active,
                            branch_active=branch_active,
                            has_else=False,
                            any_branch_taken=branch_active,
                        )
                    )
                    emit_generated("")
                    continue

                if cmd == "else":
                    if len(ctx.cond_stack) <= initial_cond_depth:
                        ctx.add_diagnostic(
                            "unmatched #else without #if, #ifdef or #ifndef",
                            file=file,
                            lineno=lineno,
                            line_text=line,
                            help_text="ensure #else corresponds to an open conditional block",
                        )
                    else:
                        top = ctx.cond_stack[-1]
                        if top.has_else:
                            ctx.add_diagnostic(
                                "duplicate #else directive in the same conditional block",
                                file=file,
                                lineno=lineno,
                                line_text=line,
                                help_text="only one #else branch is permitted per conditional block",
                            )
                        else:
                            top.has_else = True
                            top.branch_active = top.parent_active and (not top.any_branch_taken)
                            if top.branch_active:
                                top.any_branch_taken = True
                    emit_generated("")
                    continue

                if cmd == "endif":
                    if len(ctx.cond_stack) <= initial_cond_depth:
                        ctx.add_diagnostic(
                            "unmatched #endif without #if, #ifdef or #ifndef",
                            file=file,
                            lineno=lineno,
                            line_text=line,
                            help_text="ensure every #endif has a matching conditional directive",
                        )
                    else:
                        ctx.cond_stack.pop()
                    emit_generated("")
                    continue

                # --- Inactive branch for any other directive ---
                if not ctx.is_active():
                    emit_generated("")
                    continue

                # --- Active branch directives: #include, #define, #undef ---
                if cmd == "include":
                    match_quote = re.match(r'["\']([^"\']+)["\']', args.strip())
                    match_angle = re.match(r'<([^>]+)>', args.strip())
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

                if cmd == "define":
                    raw_args = args.strip()
                    fn_match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\(([^)]*)\)(?:\s+(.*))?$', raw_args)
                    if fn_match:
                        name = fn_match.group(1)
                        raw_params = fn_match.group(2)
                        body = fn_match.group(3) if fn_match.group(3) is not None else ""
                        body = _strip_comment_from_macro_val(body)
                        params = [p.strip() for p in raw_params.split(",") if p.strip()]
                        ctx.function_macros[name] = _FunctionMacro(name, params, body)
                        ctx.macros[name] = body
                    else:
                        def_match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)(?:\s+(.*))?$', raw_args)
                        if def_match:
                            name = def_match.group(1)
                            val = def_match.group(2) if def_match.group(2) is not None else ""
                            val = _strip_comment_from_macro_val(val)
                            ctx.macros[name] = val
                            ctx.function_macros.pop(name, None)
                    emit_generated("")
                    continue

                if cmd == "undef":
                    undef_match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)', args.strip())
                    if undef_match:
                        mname = undef_match.group(1)
                        ctx.macros.pop(mname, None)
                        ctx.function_macros.pop(mname, None)
                    emit_generated("")
                    continue

                # Any other unrecognized directive (e.g. #pragma, etc.)
                emit_generated("")
                continue

            # Non-directive line: check if branch is active
            if not ctx.is_active():
                ctx.in_block_comment = _scan_comment_transition(line, ctx.in_block_comment)
                emit_generated("")
                continue

            self._emit_expanded_line(ctx, line, file, lineno)

        # Check for unclosed conditionals when file ends
        while len(ctx.cond_stack) > initial_cond_depth:
            unclosed = ctx.cond_stack.pop()
            ctx.add_diagnostic(
                f"unterminated #{unclosed.directive} directive (opened at line {unclosed.line})",
                file=file,
                lineno=unclosed.line,
                line_text="",
                help_text="add matching #endif before end of file",
            )

    def _eval_condition(self, ctx: _Context, expr: str, file: str, lineno: int, line_text: str) -> bool:
        """Evaluates a constant preprocessor condition (#if / #elif)."""
        expr = _strip_comment_from_macro_val(expr).strip()
        if not expr:
            return False

        # 1. Replace defined(NAME) and defined NAME
        def _replace_defined(m: re.Match) -> str:
            ident = m.group(1) or m.group(2)
            is_def = (ident in ctx.macros) or (ident in ctx.function_macros)
            return "1" if is_def else "0"

        expr = re.sub(r'\bdefined\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)|\bdefined\s+([A-Za-z_][A-Za-z0-9_]*)', _replace_defined, expr)

        # 2. Expand macros (both object-like and function-like)
        expr = _expand_all_macros(expr, ctx.macros, ctx.function_macros)

        # 3. Replace boolean keywords
        expr = re.sub(r'\btrue\b', '1', expr)
        expr = re.sub(r'\bfalse\b', '0', expr)

        # 4. Replace remaining undefined identifiers with 0 (C99 6.10.1p4)
        expr = re.sub(r'\b[A-Za-z_][A-Za-z0-9_]*\b', '0', expr)

        # 5. Tokenize and parse
        try:
            tokens = _tokenize_c_expr(expr)
            if not tokens:
                return False
            val = _ExprParser(tokens).parse()
            return val != 0
        except Exception as e:
            ctx.add_diagnostic(
                f"error evaluating preprocessor condition: {e}",
                file=file,
                lineno=lineno,
                line_text=line_text,
                help_text="verify the expression syntax in preprocessor condition",
            )
            return False

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
        while pos < n:
            m = _TOKEN_RE.search(line, pos)
            if not m:
                break
            tok = m.group(0)
            first = tok[0]
            if first == "/" and tok.startswith("/*") and not tok.endswith("*/"):
                ctx.in_block_comment = True
                break
            if first == "/" and (tok.startswith("//") or tok.startswith("/*")):
                pos = m.end()
                continue
            if first in ('"', "'"):
                pos = m.end()
                continue
            if first.isalpha() or first == "_":
                # Check for function-like macro invocation first
                if tok in ctx.function_macros:
                    rest = line[m.end():]
                    stripped_rest = rest.lstrip()
                    if stripped_rest.startswith("("):
                        open_idx = m.end() + (len(rest) - len(stripped_rest))
                        close_idx = _find_matching_paren(line, open_idx)
                        if close_idx != -1:
                            if m.start() > literal_start:
                                omap.add_literal(line[literal_start:m.start()], file, lineno, literal_start + 1)
                            raw_args = _split_macro_args(line[open_idx + 1:close_idx])
                            fn = ctx.function_macros[tok]
                            expanded_text = _expand_fn_macro_call(fn, raw_args, ctx.macros, ctx.function_macros)
                            if expanded_text:
                                omap.add_generated(expanded_text, file, lineno, m.start() + 1, lineno, close_idx + 2)
                            else:
                                omap.add_generated(" ", file, lineno, m.start() + 1, lineno, close_idx + 2)
                            literal_start = close_idx + 1
                            pos = close_idx + 1
                            continue
                # Object-like macro invocation
                if tok in ctx.macros and tok not in ctx.function_macros:
                    if m.start() > literal_start:
                        omap.add_literal(line[literal_start:m.start()], file, lineno, literal_start + 1)
                    value = _expand_all_macros(ctx.macros[tok], ctx.macros, ctx.function_macros, frozenset({tok}))
                    if value:
                        omap.add_generated(value, file, lineno, m.start() + 1, lineno, m.end() + 1)
                    else:
                        omap.add_generated(" ", file, lineno, m.start() + 1, lineno, m.end() + 1)
                    literal_start = m.end()
                    pos = m.end()
                    continue
            pos = m.end()

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
