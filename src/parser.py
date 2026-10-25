from typing import Dict, List, Optional, Set, Any, Tuple

from src.tokens import Token, TokenType
from src.ast_nodes import *
from src.paths import canonical_path, is_sentinel, same_file
from src.analysis_result import SourceLocation
from src.diagnostics import DiagnosticSink, make_diagnostic
from src.expression_repair import ExpressionRepairEngine, tokens_to_code
from src.delimiter_repair import (
    DelimiterRepairEngine,
    DelimiterEntry,
    STATEMENT_STARTERS,
    compute_line_indents,
)
from src.cross_language_repair import CrossLanguageRepairEngine


class ParseError(Exception):
    """Raised when the parser encounters a syntax error."""
    def __init__(
        self,
        token: Token,
        message: str,
        code: str = "P001",
        help_text: Optional[str] = None,
    ):
        self.token = token
        self.message = message
        self.code = code
        self.help_text = help_text
        super().__init__(message)


class Parser:
    def __init__(
        self,
        tokens: List[Token],
        source: str,
        filename: str,
        enable_repair: bool = True,
        patch_recorder: Optional[List[Any]] = None,
        preproc_result: Optional[Any] = None,
        diag_sink: Optional[DiagnosticSink] = None,
    ):
        self.tokens = tokens
        self.source = source
        self.filename = filename
        self.preproc_result = preproc_result
        self.entry_file = preproc_result.entry_file if preproc_result is not None else canonical_path(filename)
        self._pos = 0
        self.enable_repair = enable_repair
        self.patch_recorder = patch_recorder
        display_names = dict(preproc_result.display_names) if preproc_result is not None else {self.entry_file: filename}
        self.file_sources = dict(preproc_result.file_sources) if preproc_result is not None else {self.entry_file: source}
        self.sink: DiagnosticSink = diag_sink if diag_sink is not None else DiagnosticSink(emit=True, display_names=display_names)
        self.errors_count = 0
        self.diagnostics = self.sink.diagnostics

        self.scope_stack: List[Set[str]] = [set()]
        self._expr_depth = 0
        self._in_repair = False
        self._in_for_header = False
        self.block_stack: List[DelimiterEntry] = []
        self.delimiter_stack: List[DelimiterEntry] = []
        analysis_source = preproc_result.analysis_source if preproc_result is not None else source
        self._analysis_source = analysis_source
        self.delimiter_engine = DelimiterRepairEngine(
            source=analysis_source, filename=filename
        )
        self._line_indents = compute_line_indents(analysis_source)
        self.repair_engine = ExpressionRepairEngine(
            known_symbols=set(), source=analysis_source, filename=filename
        )
        self.cross_language_engine = CrossLanguageRepairEngine(
            source=analysis_source,
            filename=filename,
            enable_repair=enable_repair,
        )

    @property
    def pos(self) -> int:
        return self._pos

    @pos.setter
    def pos(self, value: int):
        self._pos = value
        if hasattr(self, "delimiter_stack") and self.delimiter_stack:
            while self.delimiter_stack and self.delimiter_stack[-1].pos >= self._pos:
                self.delimiter_stack.pop()

    def enter_scope(self, initial_symbols: Optional[Set[str]] = None):
        s = set(initial_symbols) if initial_symbols else set()
        self.scope_stack.append(s)

    def exit_scope(self):
        if len(self.scope_stack) > 1:
            self.scope_stack.pop()

    def declare_symbol(self, name: str):
        if self.scope_stack:
            self.scope_stack[-1].add(name)

    def get_active_symbols(self) -> Set[str]:
        symbols = set()
        for s in self.scope_stack:
            symbols.update(s)
        for i in range(min(self.pos, len(self.tokens))):
            t = self.tokens[i]
            if t.type == TokenType.IDENTIFIER:
                if i > 0 and self.tokens[i - 1].type in (
                    TokenType.INT,
                    TokenType.FLOAT,
                    TokenType.DOUBLE,
                    TokenType.CHAR,
                    TokenType.BOOL,
                    TokenType.AUTO,
                ):
                    symbols.add(t.lexeme)
        return symbols

    def token_analysis_location(self, token: Optional[Token]) -> Tuple[int, int]:
        if token is None:
            return (1, 1)
        return (token.line, token.col)

    def token_source_location(self, token: Optional[Token]) -> SourceLocation:
        if token is None:
            return SourceLocation(self.entry_file, 1, 1, 1, 2)
        tok_file = getattr(token, "file", None)
        file_path = canonical_path(tok_file) if tok_file else self.entry_file
        src_line = token.source_line if getattr(token, "source_line", None) is not None else token.line
        src_col = token.source_col if getattr(token, "source_col", None) is not None else token.col
        end_line = token.source_end_line if getattr(token, "source_end_line", None) is not None else src_line
        lex_len = max(1, len(token.lexeme or ""))
        end_col = token.source_end_col if getattr(token, "source_end_col", None) is not None else (src_col + lex_len)
        return SourceLocation(file_path, src_line, src_col, end_line, max(end_col, src_col))

    def source_for_token(self, token: Optional[Token]) -> str:
        loc = self.token_source_location(token)
        return self._source_for_file(loc.file_path)

    def _source_for_file(self, file_path: Optional[str]) -> str:
        target = canonical_path(file_path) if file_path else self.entry_file
        if self.preproc_result is not None:
            if target in self.preproc_result.file_sources:
                return self.preproc_result.file_sources[target]
            for k, v in self.preproc_result.file_sources.items():
                if same_file(k, target):
                    return v
        if same_file(target, self.entry_file):
            return self.source
        return ""

    def _get_file_and_source(self, token: Optional[Token] = None) -> Tuple[str, str]:
        loc = self.token_source_location(token)
        return loc.file_path, self._source_for_file(loc.file_path)

    def physical_file_for_span(self, tokens: List[Token]) -> Optional[str]:
        if not tokens:
            return None
        files = {self.token_source_location(t).file_path for t in tokens}
        if len(files) != 1:
            return None
        return next(iter(files))

    def span_contains_generated_text(self, tokens: List[Token]) -> bool:
        if not tokens:
            return False
        if any(getattr(t, "macro_generated", False) for t in tokens):
            return True
        if self.preproc_result is not None and getattr(self.preproc_result, "origin", None) is not None:
            omap = self.preproc_result.origin
            first = tokens[0]
            last = tokens[-1]
            start_off = omap.offset_of(first.line, first.col)
            end_off = omap.offset_of(last.line, last.col + max(1, len(last.lexeme or "")))
            if omap.locate(start_off, end_off).generated:
                return True
        return False

    def _after_token_is_generated(self, token: Optional[Token]) -> bool:
        if token is None:
            return False
        if getattr(token, "macro_generated", False):
            return True
        if self.preproc_result is not None and getattr(self.preproc_result, "origin", None) is not None:
            omap = self.preproc_result.origin
            end_col = token.col + len(token.lexeme or "")
            off = omap.offset_of(token.line, end_col)
            # Check if characters on the same analysis line right after token are generated
            starts = omap._starts()
            line_end = starts[token.line] - 1 if token.line < len(starts) else len(omap.text)
            if off < line_end and omap.locate(off, line_end).generated:
                return True
        return False

    def _can_patch_span(self, tokens: List[Token], check_after_last: bool = False) -> Tuple[bool, Optional[str]]:
        phys_file = self.physical_file_for_span(tokens)
        if phys_file is None:
            return False, None
        if self.span_contains_generated_text(tokens):
            return False, phys_file
        if check_after_last and tokens and self._after_token_is_generated(tokens[-1]):
            return False, phys_file
        return True, phys_file

    def _is_current_file(self, target: Any = None) -> bool:
        if target is None:
            return True
        if isinstance(target, str):
            return same_file(target, self.entry_file)
        tok_file = getattr(target, "file", None)
        if not tok_file:
            return True
        return same_file(tok_file, self.entry_file)

    def stamp_node(self, node: Any, anchor: Any = None) -> Any:
        if node is None or not isinstance(node, ASTNode):
            return node
        if isinstance(anchor, list):
            toks = [t for t in anchor if isinstance(t, Token)]
            if toks:
                loc = self.token_source_location(toks[0])
                phys_file = self.physical_file_for_span(toks) or loc.file_path
                macro_gen = self.span_contains_generated_text(toks)
                analysis_line, analysis_col = toks[0].line, toks[0].col
                src_line, src_col = loc.line, loc.col
            else:
                phys_file = self.entry_file
                macro_gen = False
                analysis_line, analysis_col = node.line, node.col
                src_line, src_col = node.line, node.col
        elif isinstance(anchor, Token):
            loc = self.token_source_location(anchor)
            phys_file = loc.file_path
            macro_gen = bool(getattr(anchor, "macro_generated", False))
            analysis_line, analysis_col = anchor.line, anchor.col
            src_line, src_col = loc.line, loc.col
        elif isinstance(anchor, DelimiterEntry):
            phys_file = canonical_path(anchor.file) if anchor.file else self.entry_file
            macro_gen = bool(anchor.macro_generated)
            analysis_line, analysis_col = anchor.line, anchor.col
            src_line = anchor.source_line if anchor.source_line is not None else anchor.line
            src_col = anchor.source_col if anchor.source_col is not None else anchor.col
        elif isinstance(anchor, ASTNode):
            phys_file = canonical_path(anchor.file) if getattr(anchor, "file", None) and not is_sentinel(anchor.file) else (getattr(anchor, "file", None) or self.entry_file)
            if phys_file == "<repair_sandbox>":
                phys_file = self.entry_file
            macro_gen = bool(getattr(anchor, "macro_generated", False))
            analysis_line = getattr(anchor, "analysis_line", None) or anchor.line
            analysis_col = getattr(anchor, "analysis_col", None) or anchor.col
            src_line, src_col = anchor.line, anchor.col
        else:
            phys_file = self.entry_file
            macro_gen = False
            analysis_line, analysis_col = node.line, node.col
            src_line, src_col = node.line, node.col

        node.line = src_line
        node.col = src_col
        node.file = phys_file
        node.analysis_line = analysis_line
        node.analysis_col = analysis_col
        node.macro_generated = macro_gen

        self._propagate_provenance_children(node, phys_file, src_line, src_col, analysis_line, analysis_col, macro_gen)
        return node

    def _propagate_provenance_children(
        self,
        node: ASTNode,
        phys_file: str,
        src_line: int,
        src_col: int,
        analysis_line: int,
        analysis_col: int,
        macro_gen: bool,
    ) -> None:
        for val in vars(node).values():
            if isinstance(val, ASTNode):
                if getattr(val, "file", None) in (None, "<repair_sandbox>"):
                    val.file = phys_file
                    val.line = src_line
                    val.col = src_col
                    val.analysis_line = analysis_line
                    val.analysis_col = analysis_col
                if macro_gen:
                    val.macro_generated = True
                self._propagate_provenance_children(
                    val,
                    val.file or phys_file,
                    val.line,
                    val.col,
                    getattr(val, "analysis_line", None) or analysis_line,
                    getattr(val, "analysis_col", None) or analysis_col,
                    bool(getattr(val, "macro_generated", False) or macro_gen),
                )
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, ASTNode):
                        if getattr(item, "file", None) in (None, "<repair_sandbox>"):
                            item.file = phys_file
                            item.line = src_line
                            item.col = src_col
                            item.analysis_line = analysis_line
                            item.analysis_col = analysis_col
                        if macro_gen:
                            item.macro_generated = True
                        self._propagate_provenance_children(
                            item,
                            item.file or phys_file,
                            item.line,
                            item.col,
                            getattr(item, "analysis_line", None) or analysis_line,
                            getattr(item, "analysis_col", None) or analysis_col,
                            bool(getattr(item, "macro_generated", False) or macro_gen),
                        )

    def _add_diag(self, diag: Any) -> bool:
        added = self.sink.add(diag)
        if added and diag.severity in ("error", "internal"):
            self.errors_count += 1
        return added

    def _restore_token_provenance_after_virtual_rewrite(
        self, old_tokens: List[Token], new_tokens: List[Token]
    ) -> List[Token]:
        """Carry physical origins across an in-memory, line-preserving rewrite.

        Cross-language normalization is used only to let parsing continue.  Re-lexing
        that normalized text must not turn tokens from an included file into tokens
        from the entry file.  The normalizer preserves lines and token order, so a
        per-line ordinal mapping is the stable fallback for replaced spellings.
        """
        old_by_line: Dict[int, List[Token]] = {}
        new_by_line: Dict[int, List[Token]] = {}
        for tok in old_tokens:
            old_by_line.setdefault(tok.line, []).append(tok)
        for tok in new_tokens:
            new_by_line.setdefault(tok.line, []).append(tok)

        for line, rewritten in new_by_line.items():
            originals = old_by_line.get(line, [])
            if not originals:
                continue
            for index, tok in enumerate(rewritten):
                if tok.type == TokenType.EOF:
                    anchor = originals[-1]
                else:
                    anchor = originals[min(index, len(originals) - 1)]
                tok.file = anchor.file
                tok.source_line = anchor.source_line
                tok.source_col = anchor.source_col
                tok.source_end_line = anchor.source_end_line
                tok.source_end_col = anchor.source_end_col
                tok.macro_generated = anchor.macro_generated
                tok.synthetic = tok.lexeme != anchor.lexeme or anchor.synthetic
        return new_tokens

    def record_parse_error(self, err: ParseError):
        loc = self.token_source_location(err.token)
        file_source = self._source_for_file(loc.file_path)
        diag = make_diagnostic(
            code=err.code,
            severity="error",
            message=err.message,
            file=loc.file_path,
            line=loc.line,
            col=loc.col,
            end_line=loc.end_line,
            end_col=loc.end_col,
            source_text=file_source,
            help_text=err.help_text or "",
            stage="parser",
        )
        self._add_diag(diag)

    def synchronize(self, context: Optional[str] = None, start_pos: Optional[int] = None):
        self._in_repair = False
        if self.is_at_end():
            return

        if context is None:
            if self._in_for_header:
                context = "for"
            elif self.delimiter_stack and self.delimiter_stack[-1].type == TokenType.LBRACKET:
                context = "subscript"
            elif self.delimiter_stack and self.delimiter_stack[-1].type == TokenType.LPAREN:
                context = "params"
            elif self.block_stack:
                context = "block"
            else:
                context = "top"

        TOP_STARTERS = {
            TokenType.TEMPLATE,
            TokenType.CLASS,
            TokenType.STRUCT,
            TokenType.ENUM,
            TokenType.NAMESPACE,
            TokenType.USING,
            TokenType.DEF,
            TokenType.CONSTEXPR,
            TokenType.VIRTUAL,
            TokenType.CONST,
            TokenType.INT,
            TokenType.FLOAT,
            TokenType.DOUBLE,
            TokenType.CHAR,
            TokenType.VOID,
            TokenType.BOOL,
            TokenType.AUTO,
            TokenType.BOOLEAN_TYPE,
            TokenType.STRING_JAVA_TYPE,
        }

        def is_safe_boundary() -> bool:
            curr = self.peek()
            prev = self.previous() if self.pos > 0 else None
            if curr.type == TokenType.EOF:
                return True
            if context == "for":
                return curr.type in (TokenType.SEMICOLON, TokenType.RPAREN, TokenType.LBRACE, TokenType.RBRACE)
            if context == "params":
                return curr.type in (TokenType.COMMA, TokenType.RPAREN, TokenType.SEMICOLON, TokenType.LBRACE, TokenType.RBRACE)
            if context == "subscript":
                return curr.type in (TokenType.RBRACKET, TokenType.SEMICOLON, TokenType.RBRACE)
            if context == "block":
                if curr.type == TokenType.RBRACE:
                    return True
                if prev is not None and prev.type == TokenType.SEMICOLON:
                    return True
                if curr.type in STATEMENT_STARTERS:
                    if curr.type == TokenType.IDENTIFIER:
                        return prev is not None and curr.line > prev.line
                    return True
                return False
            # context == "top"
            if prev is not None and prev.type in (TokenType.SEMICOLON, TokenType.RBRACE):
                return True
            if curr.type in TOP_STARTERS:
                return True
            return False

        advanced_since_start = start_pos is not None and self.pos > start_pos

        # Check current token before advancing!
        if self.peek().type == TokenType.SEMICOLON and context in ("block", "top", "for"):
            self.advance()
            return
        if self.peek().type == TokenType.RBRACE and context == "block":
            return
        if advanced_since_start and is_safe_boundary():
            return

        # Guarantee forward progress when not already at a boundary
        self.advance()
        while not self.is_at_end():
            if self.peek().type == TokenType.SEMICOLON and context in ("block", "top"):
                self.advance()
                return
            if is_safe_boundary():
                return
            self.advance()

    def parse(self) -> Program:
        if self.enable_repair:
            self.attempt_cross_language_repair()
        declarations = []
        while not self.is_at_end():
            decl_start = self.pos
            try:
                if self.check(TokenType.TEMPLATE):
                    declarations.append(self.parse_template_def())
                elif self.check(TokenType.CLASS):
                    declarations.append(self.parse_class_def())
                elif self.check(TokenType.NAMESPACE):
                    declarations.append(self.parse_namespace_def())
                elif self.check(TokenType.USING):
                    declarations.append(self.parse_using_namespace())
                elif self.check(TokenType.STRUCT):
                    saved_pos = self.pos
                    self.advance() # struct
                    self.advance() # name
                    if self.check(TokenType.LBRACE):
                        self.pos = saved_pos
                        declarations.append(self.parse_struct_def())
                    else:
                        self.pos = saved_pos
                        declarations.append(self.parse_struct_decl())
                elif self.check(TokenType.ENUM):
                    declarations.append(self.parse_enum_def())
                else:
                    if self._is_function_decl():
                        declarations.append(self.parse_function())
                    else:
                        declarations.append(self.parse_var_decl())
            except ParseError as err:
                if not self.enable_repair:
                    raise
                self.record_parse_error(err)
                self.synchronize(context="top", start_pos=decl_start)
        prog = Program(declarations, 1, 1, file=self.entry_file)
        for d in declarations:
            if isinstance(d, ASTNode) and getattr(d, "file", None) in (None, "<repair_sandbox>"):
                self.stamp_node(d, d)
        return prog

    def _is_function_decl(self):
        if self.check(TokenType.DEF):
            return True
        saved_pos = self.pos
        if self.match(TokenType.CONSTEXPR): pass
        if self.match(TokenType.VIRTUAL): pass
        if self.match(TokenType.CONST): pass
        if self.match(TokenType.SCOPE): pass
        if not (self.match_any([TokenType.INT, TokenType.FLOAT, TokenType.DOUBLE, TokenType.VOID, TokenType.CHAR, TokenType.BOOL, TokenType.STRUCT, TokenType.AUTO]) or self.match(TokenType.IDENTIFIER)):
            self.pos = saved_pos
            return False
        if self.previous().type == TokenType.STRUCT:
            self.match(TokenType.IDENTIFIER)
        while True:
            if self.match(TokenType.LT):
                depth = 1
                while depth > 0 and not self.is_at_end():
                    if self.match(TokenType.LT): depth += 1
                    elif self.match(TokenType.GT): depth -= 1
                    else: self.advance()
            if self.match(TokenType.SCOPE):
                if not self.match(TokenType.IDENTIFIER):
                    break
            else:
                break
        while self.match(TokenType.STAR) or self.match(TokenType.AMP): pass
        if self.match(TokenType.OPERATOR):
            self.advance() # operator token (+, -, ==, <<, etc.)
            if self.match(TokenType.LPAREN):
                self.pos = saved_pos
                return True
        elif self.match(TokenType.IDENTIFIER):
            while self.match(TokenType.SCOPE):
                self.match(TokenType.IDENTIFIER)
            if self.match(TokenType.LPAREN):
                self.pos = saved_pos
                return True
        self.pos = saved_pos
        return False

    def _is_var_decl(self):
        saved_pos = self.pos
        if self.match(TokenType.CONSTEXPR):
            self.pos = saved_pos
            return True
        if self.match(TokenType.AUTO):
            self.pos = saved_pos
            return True
        if self.match(TokenType.CONST):
            self.pos = saved_pos
            return True
        if self.match_any([
            TokenType.INT, TokenType.FLOAT, TokenType.DOUBLE, TokenType.CHAR,
            TokenType.BOOL, TokenType.VOID, TokenType.BOOLEAN_TYPE, TokenType.STRING_JAVA_TYPE
        ]):
            self.pos = saved_pos
            return True
        if self.match(TokenType.STRUCT):
            self.advance()
            if self.check(TokenType.LBRACE):
                self.pos = saved_pos
                return False
            self.pos = saved_pos
            return True
        if self.match(TokenType.SCOPE):
            pass
        if self.match(TokenType.IDENTIFIER):
            while True:
                if self.match(TokenType.LT):
                    depth = 1
                    while depth > 0 and not self.is_at_end():
                        if self.match(TokenType.LT): depth += 1
                        elif self.match(TokenType.GT): depth -= 1
                        else: self.advance()
                if self.match(TokenType.SCOPE):
                    if not self.match(TokenType.IDENTIFIER):
                        break
                else:
                    break
            while self.match(TokenType.STAR) or self.match(TokenType.AMP): pass
            if self.match(TokenType.IDENTIFIER):
                self.pos = saved_pos
                return True
        self.pos = saved_pos
        return False

    def parse_type(self):
        is_const = False
        if self.match(TokenType.CONST):
            is_const = True
        if self.match(TokenType.AUTO):
            t_name = "auto"
        elif self.match(TokenType.STRUCT):
            t_tok = self.consume(TokenType.IDENTIFIER, "Expected struct name")
            t_name = f"struct {t_tok.lexeme}"
        else:
            prefix = ""
            if self.match(TokenType.SCOPE):
                prefix = "::"
            t_tok = self.consume_any([
                TokenType.INT, TokenType.FLOAT, TokenType.DOUBLE, TokenType.VOID,
                TokenType.CHAR, TokenType.BOOL, TokenType.IDENTIFIER,
                TokenType.BOOLEAN_TYPE, TokenType.STRING_JAVA_TYPE
            ], "Expected type")
            if t_tok.type == TokenType.BOOLEAN_TYPE:
                t_name = prefix + "bool"
            elif t_tok.type == TokenType.STRING_JAVA_TYPE:
                t_name = prefix + "std::string"
            else:
                t_name = prefix + t_tok.lexeme
            while True:
                if self.match(TokenType.LT):
                    type_args = []
                    while True:
                        sub_t, _, _ = self.parse_type()
                        type_args.append(sub_t)
                        if not self.match(TokenType.COMMA):
                            break
                    self.consume(TokenType.GT, "Expected '>' after template arguments")
                    t_name = f"{t_name}<{','.join(type_args)}>"
                if self.match(TokenType.SCOPE):
                    mem_tok = self.consume(TokenType.IDENTIFIER, "Expected identifier after '::'")
                    t_name = f"{t_name}::{mem_tok.lexeme}"
                else:
                    break
        while self.match(TokenType.CONST):
            is_const = True
        while self.match(TokenType.STAR):
            t_name += "*"
            while self.match(TokenType.CONST):
                is_const = True
        is_reference = False
        if self.match(TokenType.AMP):
            is_reference = True
        return t_name, is_const, is_reference

    def parse_parameters(self) -> List[Parameter]:
        params = []
        if not self.check(TokenType.RPAREN):
            while True:
                p_tok = self.peek()
                p_type, p_const, p_ref = self.parse_type()
                p_name_tok = self.consume(TokenType.IDENTIFIER, "Expected parameter name")
                p_name = p_name_tok.lexeme
                params.append(self.stamp_node(Parameter(p_type, p_name, p_tok.line, p_tok.col, is_const=p_const, is_reference=p_ref), p_tok))
                if not self.match(TokenType.COMMA):
                    break
        return params

    def parse_struct_def(self):
        start_tok = self.consume(TokenType.STRUCT, "Expected 'struct'")
        name = self.consume(TokenType.IDENTIFIER, "Expected struct name").lexeme
        self.consume(TokenType.LBRACE, "Expected '{' after struct name")
        members = []
        while not self.check(TokenType.RBRACE) and not self.is_at_end():
            m_tok = self.consume_any([TokenType.INT, TokenType.FLOAT, TokenType.DOUBLE, TokenType.CHAR], "Expected member type")
            m_type = m_tok.lexeme
            while self.match(TokenType.STAR): m_type += "*"
            m_name_tok = self.consume(TokenType.IDENTIFIER, "Expected member name")
            m_name = m_name_tok.lexeme
            self.consume(TokenType.SEMICOLON, "Expected ';' after member")
            members.append(self.stamp_node(Parameter(m_type, m_name, m_name_tok.line, m_name_tok.col), m_name_tok))
        self.consume(TokenType.RBRACE, "Expected '}' after struct members")
        if not self.check(TokenType.SEMICOLON) and self.enable_repair and not self._in_repair:
            self.attempt_semicolon_repair("Expected ';' after struct definition", context="struct definition", in_class_or_struct=True)
        else:
            self.consume(TokenType.SEMICOLON, "Expected ';' after struct definition")
        return self.stamp_node(StructDef(name, members, start_tok.line, start_tok.col), start_tok)

    def parse_enum_def(self):
        start_tok = self.consume(TokenType.ENUM, "Expected 'enum'")
        name = self.consume(TokenType.IDENTIFIER, "Expected enum name").lexeme
        self.consume(TokenType.LBRACE, "Expected '{' after enum name")
        enumerators = []
        val = 0
        while not self.check(TokenType.RBRACE) and not self.is_at_end():
            e_name = self.consume(TokenType.IDENTIFIER, "Expected enum element name").lexeme
            if self.match(TokenType.ASSIGN):
                e_val_tok = self.consume(TokenType.INT_LIT, "Expected integer literal for enum value")
                val = int(e_val_tok.lexeme)
            enumerators.append((e_name, val))
            val += 1
            if not self.match(TokenType.COMMA):
                break
        self.consume(TokenType.RBRACE, "Expected '}' after enum elements")
        if not self.check(TokenType.SEMICOLON) and self.enable_repair and not self._in_repair:
            self.attempt_semicolon_repair("Expected ';' after enum definition", context="enum definition", in_class_or_struct=True)
        else:
            self.consume(TokenType.SEMICOLON, "Expected ';' after enum definition")
        return self.stamp_node(EnumDef(name, enumerators, start_tok.line, start_tok.col), start_tok)

    def parse_template_def(self) -> TemplateDef:
        start_tok = self.consume(TokenType.TEMPLATE, "Expected 'template'")
        self.consume(TokenType.LT, "Expected '<' after 'template'")
        template_params = []
        while True:
            if self.match(TokenType.TYPENAME) or self.match(TokenType.CLASS):
                param_name = self.consume(TokenType.IDENTIFIER, "Expected template parameter name").lexeme
                template_params.append(param_name)
            else:
                self.error(self.peek(), "Expected 'typename' or 'class' in template parameter list")
            if not self.match(TokenType.COMMA):
                break
        self.consume(TokenType.GT, "Expected '>' after template parameters")
        if self.check(TokenType.CLASS):
            decl = self.parse_class_def()
        else:
            decl = self.parse_function()
        return self.stamp_node(TemplateDef(template_params, decl, start_tok.line, start_tok.col), start_tok)

    def parse_class_def(self) -> ClassDef:
        start_tok = self.consume(TokenType.CLASS, "Expected 'class'")
        name = self.consume(TokenType.IDENTIFIER, "Expected class name").lexeme
        base_class = None
        base_access = "public"
        if self.match(TokenType.COLON):
            if self.match(TokenType.PUBLIC):
                base_access = "public"
            elif self.match(TokenType.PRIVATE):
                base_access = "private"
            elif self.match(TokenType.PROTECTED):
                base_access = "protected"
            base_class = self.consume(TokenType.IDENTIFIER, "Expected base class name").lexeme
            while self.match(TokenType.SCOPE):
                sub = self.consume(TokenType.IDENTIFIER, "Expected identifier after '::'").lexeme
                base_class += f"::{sub}"
        self.consume(TokenType.LBRACE, "Expected '{' after class name")
        members = []
        current_access = "private"
        while not self.check(TokenType.RBRACE) and not self.is_at_end():
            if self.match(TokenType.PUBLIC):
                self.consume(TokenType.COLON, "Expected ':' after 'public'")
                current_access = "public"
                continue
            elif self.match(TokenType.PRIVATE):
                self.consume(TokenType.COLON, "Expected ':' after 'private'")
                current_access = "private"
                continue
            elif self.match(TokenType.PROTECTED):
                self.consume(TokenType.COLON, "Expected ':' after 'protected'")
                current_access = "protected"
                continue

            # Destructor: ~ClassName()
            if self.match(TokenType.TILDE):
                d_tok = self.previous()
                d_name = self.consume(TokenType.IDENTIFIER, "Expected class name for destructor").lexeme
                self.consume(TokenType.LPAREN, "Expected '(' after destructor name")
                self.consume(TokenType.RPAREN, "Expected ')' for destructor")
                body = None
                if not self.match(TokenType.SEMICOLON):
                    body = self.parse_block()
                dtor = self.stamp_node(DestructorDef(d_name, body, d_tok.line, d_tok.col), d_tok)
                members.append(self.stamp_node(ClassMember(dtor, current_access, dtor.line, dtor.col), d_tok))
                continue

            # Constructor: ClassName(...)
            if self.check(TokenType.IDENTIFIER) and self.peek().lexeme == name:
                if self.pos + 1 < len(self.tokens) and self.tokens[self.pos + 1].type == TokenType.LPAREN:
                    c_tok = self.advance()
                    self.consume(TokenType.LPAREN, "Expected '(' after constructor name")
                    params = self.parse_parameters()
                    self.consume(TokenType.RPAREN, "Expected ')' after parameters")
                    body = None
                    if not self.match(TokenType.SEMICOLON):
                        body = self.parse_block()
                    ctor = self.stamp_node(ConstructorDef(name, params, body, c_tok.line, c_tok.col), c_tok)
                    members.append(self.stamp_node(ClassMember(ctor, current_access, ctor.line, ctor.col), c_tok))
                    continue

            # Method or member variable
            if self.check(TokenType.VIRTUAL) or self._is_function_decl():
                method_def = self.parse_function(is_method=True, class_name=name)
                members.append(self.stamp_node(ClassMember(method_def, current_access, method_def.line, method_def.col), method_def))
            else:
                var_decl = self.parse_var_decl()
                members.append(self.stamp_node(ClassMember(var_decl, current_access, var_decl.line, var_decl.col), var_decl))

        self.consume(TokenType.RBRACE, "Expected '}' after class definition")
        if not self.check(TokenType.SEMICOLON) and self.enable_repair and not self._in_repair:
            self.attempt_semicolon_repair("Expected ';' after class definition", context="class definition", in_class_or_struct=True)
        else:
            self.consume(TokenType.SEMICOLON, "Expected ';' after class definition")
        return self.stamp_node(ClassDef(name, members, start_tok.line, start_tok.col, base_class=base_class, base_access=base_access), start_tok)

    def parse_namespace_def(self) -> NamespaceDef:
        start_tok = self.consume(TokenType.NAMESPACE, "Expected 'namespace'")
        name = self.consume(TokenType.IDENTIFIER, "Expected namespace name").lexeme
        self.consume(TokenType.LBRACE, "Expected '{' after namespace name")
        decls = []
        while not self.check(TokenType.RBRACE) and not self.is_at_end():
            if self.check(TokenType.CLASS):
                decls.append(self.parse_class_def())
            elif self.check(TokenType.NAMESPACE):
                decls.append(self.parse_namespace_def())
            elif self.check(TokenType.STRUCT):
                decls.append(self.parse_struct_def())
            elif self._is_function_decl():
                decls.append(self.parse_function())
            else:
                decls.append(self.parse_var_decl())
        self.consume(TokenType.RBRACE, "Expected '}' after namespace")
        return self.stamp_node(NamespaceDef(name, decls, start_tok.line, start_tok.col), start_tok)

    def parse_using_namespace(self) -> Any:
        start_tok = self.consume(TokenType.USING, "Expected 'using'")
        if self.match(TokenType.NAMESPACE):
            name = self.consume(TokenType.IDENTIFIER, "Expected namespace name").lexeme
            self.consume(TokenType.SEMICOLON, "Expected ';' after using namespace")
            return self.stamp_node(UsingNamespace(name, start_tok.line, start_tok.col), start_tok)
        else:
            ns = self.consume(TokenType.IDENTIFIER, "Expected namespace identifier after 'using'").lexeme
            self.consume(TokenType.SCOPE, "Expected '::' after namespace in using declaration")
            member = self.consume(TokenType.IDENTIFIER, "Expected member identifier after '::'").lexeme
            self.consume(TokenType.SEMICOLON, "Expected ';' after using declaration")
            return self.stamp_node(UsingDeclaration(ns, member, start_tok.line, start_tok.col), start_tok)

    def parse_function(self, is_method: bool = False, class_name: Optional[str] = None) -> FunctionDef:
        ret_tok = self.peek()
        ret_line, ret_col = ret_tok.line, ret_tok.col
        if self.match(TokenType.DEF):
            name_tok = self.consume(TokenType.IDENTIFIER, "Expected function name after 'def'")
            func_name = name_tok.lexeme
            self.declare_symbol(func_name)
            self.consume(TokenType.LPAREN, "Expected '(' after function name")
            params = []
            if not self.check(TokenType.RPAREN):
                while True:
                    p_tok = self.peek()
                    if self._is_var_decl():
                        p_type, _, _ = self.parse_type()
                        p_name = self.consume(TokenType.IDENTIFIER, "Expected parameter name").lexeme
                    else:
                        p_name = self.consume(TokenType.IDENTIFIER, "Expected parameter name").lexeme
                        p_type = "auto"
                    params.append(self.stamp_node(Parameter(p_type, p_name, p_tok.line, p_tok.col), p_tok))
                    if not self.match(TokenType.COMMA):
                        break
            self.consume(TokenType.RPAREN, "Expected ')' after parameters")
            ret_type = "auto"
            if self.match(TokenType.ARROW):
                ret_type, _, _ = self.parse_type()
            elif func_name == "main":
                ret_type = "int"
            self.match(TokenType.COLON)
            header_indent = self._line_indents.get(ret_line, 0)
            self.enter_scope({p.name for p in params})
            try:
                body = self.parse_block(scope_type="function", header_indent=header_indent)
            finally:
                self.exit_scope()
            return self.stamp_node(FunctionDef(ret_type, func_name, params, body, is_method, class_name, ret_line, ret_col), ret_tok)

        is_constexpr = False
        if self.match(TokenType.CONSTEXPR):
            is_constexpr = True
        is_virtual = False
        if self.match(TokenType.VIRTUAL):
            is_virtual = True
        ret_type, is_const, is_ref = self.parse_type()
        if is_ref:
            ret_type += "&"
        if self.match(TokenType.OPERATOR):
            op_tok = self.advance()
            func_name = f"operator{op_tok.lexeme}"
        else:
            name_tok = self.consume(TokenType.IDENTIFIER, "Expected function name")
            func_name = name_tok.lexeme
        self.declare_symbol(func_name)
        self.consume(TokenType.LPAREN, "Expected '(' after function name")
        params = self.parse_parameters()
        self.consume(TokenType.RPAREN, "Expected ')' after parameters")
        is_override = False
        if self.match(TokenType.OVERRIDE):
            is_override = True
        is_pure_virtual = False
        body = None
        if self.match(TokenType.ASSIGN):
            zero_tok = self.consume(TokenType.INT_LIT, "Expected 0 for pure virtual function")
            if zero_tok.lexeme != "0":
                self.error(zero_tok, "Pure virtual function specifier must be 0")
            is_pure_virtual = True
            is_virtual = True
            self.consume(TokenType.SEMICOLON, "Expected ';' after pure virtual declaration")
        else:
            if not self.match(TokenType.SEMICOLON):
                self.enter_scope({p.name for p in params})
                header_indent = self._line_indents.get(ret_line, 0)
                body = self.parse_block(scope_type="function", header_indent=header_indent)
                self.exit_scope()
        return self.stamp_node(FunctionDef(ret_type, func_name, params, body, ret_line, ret_col, is_method=is_method, class_name=class_name, is_virtual=is_virtual, is_pure_virtual=is_pure_virtual, is_override=is_override, is_constexpr=is_constexpr), ret_tok)

    def parse_block(self, scope_type: str = "block", header_indent: Optional[int] = None) -> Block:
        open_brace = self.consume(TokenType.LBRACE, "Expected '{' before block")
        if header_indent is None:
            header_indent = self._line_indents.get(open_brace.line, getattr(open_brace, "indent", 0))

        open_loc = self.token_source_location(open_brace)
        block_entry = DelimiterEntry(
            type=TokenType.LBRACE,
            lexeme="{",
            line=open_brace.line,
            col=open_brace.col,
            indent=header_indent,
            scope_type=scope_type,
            statement_count=0,
            pos=max(0, self.pos - 1),
            file=open_loc.file_path,
            source_line=open_loc.line,
            source_col=open_loc.col,
            source_end_line=open_loc.end_line,
            source_end_col=open_loc.end_col,
            macro_generated=bool(getattr(open_brace, "macro_generated", False)),
        )
        self.block_stack.append(block_entry)
        self.enter_scope()
        statements = []
        start_line, start_col = open_brace.line, open_brace.col
        closed_via_indentation = False

        while not self.check(TokenType.RBRACE) and not self.is_at_end():
            if self.enable_repair and not self._in_repair:
                should_close, target_block = self.delimiter_engine.should_close_block_due_to_indentation(
                    self.block_stack,
                    self.previous(),
                    self.peek(),
                    self.tokens,
                )
                if should_close and target_block is not None:
                    if self.attempt_block_close_repair(target_block):
                        closed_via_indentation = True
                        break

            stmt_start = self.pos
            try:
                stmt = self.parse_statement()
                if stmt is not None:
                    statements.append(stmt)
                block_entry.statement_count += 1
            except ParseError as err:
                if not self.enable_repair:
                    raise
                self.record_parse_error(err)
                self.synchronize(context="block", start_pos=stmt_start)

        if not closed_via_indentation:
            if self.check(TokenType.RBRACE):
                self.advance()
            else:
                if self.enable_repair and not self._in_repair:
                    self.attempt_rbrace_repair(block_entry)
                else:
                    self.consume(TokenType.RBRACE, "Expected '}' after block")

        self.exit_scope()
        if self.block_stack:
            self.block_stack.pop()
        return self.stamp_node(Block(statements, start_line, start_col), open_brace)

    def parse_statement(self, header_indent: Optional[int] = None) -> Statement:
        if self.match(TokenType.IF):
            return self.parse_if()
        if self.match(TokenType.WHILE):
            return self.parse_while()
        if self.match(TokenType.DO):
            return self.parse_do_while()
        if self.match(TokenType.FOR):
            return self.parse_for()
        if self.match(TokenType.SWITCH):
            return self.parse_switch()
        if self.match(TokenType.TRY):
            return self.parse_try_catch()
        if self.match(TokenType.THROW):
            return self.parse_throw()
        if self.match(TokenType.RETURN):
            return self.parse_return()
        if self.match(TokenType.PASS):
            p_tok = self.previous()
            self.match(TokenType.SEMICOLON)
            return self.stamp_node(Block([], p_tok.line, p_tok.col), p_tok)
        if self.match(TokenType.BREAK):
            b_tok = self.previous()
            stmt = self.stamp_node(BreakStatement(b_tok.line, b_tok.col), b_tok)
            self.consume(TokenType.SEMICOLON, "Expected ';' after break")
            return stmt
        if self.match(TokenType.CONTINUE):
            c_tok = self.previous()
            stmt = self.stamp_node(ContinueStatement(c_tok.line, c_tok.col), c_tok)
            self.consume(TokenType.SEMICOLON, "Expected ';' after continue")
            return stmt
        if self.match(TokenType.DELETE):
            d_tok = self.previous()
            expr = self.parse_expression()
            self.consume(TokenType.SEMICOLON, "Expected ';' after delete expression")
            return self.stamp_node(DeleteStatement(expr, d_tok.line, d_tok.col), d_tok)
        if self.check(TokenType.USING):
            return self.parse_using_namespace()
        if self.check(TokenType.CLASS):
            return self.parse_class_def()
        if self.check(TokenType.NAMESPACE):
            return self.parse_namespace_def()
        if self._is_var_decl():
            return self.parse_var_decl()
        if self.check(TokenType.LBRACE):
            return self.parse_block(header_indent=header_indent)
        
        if self.match(TokenType.SEMICOLON):
            s_tok = self.previous()
            return self.stamp_node(Block([], s_tok.line, s_tok.col), s_tok)

        return self.parse_expr_statement()

    def parse_try_catch(self) -> TryCatchStatement:
        start_tok = self.previous()
        try_block = self.parse_block()
        catch_clauses = []
        while self.match(TokenType.CATCH):
            c_tok = self.previous()
            self.consume(TokenType.LPAREN, "Expected '(' after 'catch'")
            p_type, _, _ = self.parse_type()
            p_name = self.consume(TokenType.IDENTIFIER, "Expected parameter name in catch clause").lexeme
            self.consume(TokenType.RPAREN, "Expected ')' after catch parameter")
            c_body = self.parse_block()
            catch_clauses.append(self.stamp_node(CatchClause(p_type, p_name, c_body, c_tok.line, c_tok.col), c_tok))
        return self.stamp_node(TryCatchStatement(try_block, catch_clauses, start_tok.line, start_tok.col), start_tok)

    def parse_throw(self) -> ThrowStatement:
        start_tok = self.previous()
        expr = self.parse_expression()
        self.consume(TokenType.SEMICOLON, "Expected ';' after throw expression")
        return self.stamp_node(ThrowStatement(expr, start_tok.line, start_tok.col), start_tok)

    def parse_if(self) -> IfStatement:
        start_tok = self.previous()
        start_line, start_col = start_tok.line, start_tok.col
        self.consume(TokenType.LPAREN, "Expected '(' after 'if'")
        condition = self.parse_expression()
        self.consume(TokenType.RPAREN, "Expected ')' after if condition")
        self.match(TokenType.COLON)
        header_indent = self._line_indents.get(start_line, 0)
        then_branch = self.parse_statement(header_indent=header_indent)
        else_branch = None
        if self.match(TokenType.ELSE):
            self.match(TokenType.COLON)
            else_branch = self.parse_statement(header_indent=header_indent)
        elif self.match(TokenType.ELIF):
            elif_tok = self.previous()
            elif_line, elif_col = elif_tok.line, elif_tok.col
            self.consume(TokenType.LPAREN, "Expected '(' after 'elif'")
            elif_cond = self.parse_expression()
            self.consume(TokenType.RPAREN, "Expected ')' after elif condition")
            self.match(TokenType.COLON)
            elif_indent = self._line_indents.get(elif_line, 0)
            elif_then = self.parse_statement(header_indent=elif_indent)
            elif_else = None
            if self.match(TokenType.ELSE):
                self.match(TokenType.COLON)
                elif_else = self.parse_statement(header_indent=elif_indent)
            else_branch = self.stamp_node(IfStatement(elif_cond, elif_then, elif_else, elif_line, elif_col), elif_tok)
        return self.stamp_node(IfStatement(condition, then_branch, else_branch, start_line, start_col), start_tok)

    def parse_while(self) -> WhileStatement:
        start_tok = self.previous()
        start_line, start_col = start_tok.line, start_tok.col
        self.consume(TokenType.LPAREN, "Expected '(' after 'while'")
        condition = self.parse_expression()
        self.consume(TokenType.RPAREN, "Expected ')' after while condition")
        self.match(TokenType.COLON)
        header_indent = self._line_indents.get(start_line, 0)
        body = self.parse_statement(header_indent=header_indent)
        return self.stamp_node(WhileStatement(condition, body, start_line, start_col), start_tok)

    def parse_do_while(self) -> DoWhileStatement:
        start_tok = self.previous()
        start_line, start_col = start_tok.line, start_tok.col
        header_indent = self._line_indents.get(start_line, 0)
        body = self.parse_statement(header_indent=header_indent)
        self.consume(TokenType.WHILE, "Expected 'while' after do block")
        self.consume(TokenType.LPAREN, "Expected '(' after 'while'")
        condition = self.parse_expression()
        self.consume(TokenType.RPAREN, "Expected ')' after condition")
        self.consume(TokenType.SEMICOLON, "Expected ';' after do-while statement")
        return self.stamp_node(DoWhileStatement(body, condition, start_line, start_col), start_tok)

    def parse_for(self) -> Statement:
        start_tok = self.previous()
        start_line, start_col = start_tok.line, start_tok.col
        self.consume(TokenType.LPAREN, "Expected '(' after 'for'")
        
        saved_pos = self.pos
        if self.match(TokenType.AUTO) or self.match_any([TokenType.INT, TokenType.FLOAT, TokenType.DOUBLE, TokenType.CHAR, TokenType.BOOL, TokenType.IDENTIFIER]):
            while self.match(TokenType.STAR) or self.match(TokenType.AMP): pass
            if self.match(TokenType.IDENTIFIER):
                if self.match(TokenType.COLON):
                    self.pos = saved_pos
                    var_type, is_const, is_ref = self.parse_type()
                    var_name = self.consume(TokenType.IDENTIFIER, "Expected variable name in range-based for").lexeme
                    self.consume(TokenType.COLON, "Expected ':' in range-based for")
                    iterable = self.parse_expression()
                    self.consume(TokenType.RPAREN, "Expected ')' after range-based for")
                    self.match(TokenType.COLON)
                    header_indent = self._line_indents.get(start_line, 0)
                    body = self.parse_statement(header_indent=header_indent)
                    return self.stamp_node(RangeForStatement(var_type, var_name, iterable, body, start_line, start_col), start_tok)
                elif self.match(TokenType.IN):
                    self.pos = saved_pos
                    if self._is_var_decl():
                        var_type, _, _ = self.parse_type()
                    else:
                        var_type = "int"
                    var_name = self.consume(TokenType.IDENTIFIER, "Expected variable name").lexeme
                    self.consume(TokenType.IN, "Expected 'in'")
                    self.consume(TokenType.RANGE, "Expected 'range'")
                    self.consume(TokenType.LPAREN, "Expected '(' after 'range'")
                    range_args = []
                    while not self.check(TokenType.RPAREN):
                        range_args.append(self.parse_expression())
                        if not self.match(TokenType.COMMA):
                            break
                    self.consume(TokenType.RPAREN, "Expected ')' after range arguments")
                    self.consume(TokenType.RPAREN, "Expected ')' after for header")
                    self.match(TokenType.COLON)
                    start_val = self.stamp_node(IntLiteral(0, start_line, start_col), start_tok) if len(range_args) == 1 else range_args[0]
                    stop_val = range_args[0] if len(range_args) == 1 else range_args[1]
                    init_stmt = self.stamp_node(VarDeclaration(var_type, var_name, start_val, start_line, start_col), start_tok)
                    cond_id = self.stamp_node(Identifier(var_name, start_line, start_col), start_tok)
                    cond_expr = self.stamp_node(BinaryOp(cond_id, "<", stop_val, start_line, start_col), start_tok)
                    upd_id = self.stamp_node(Identifier(var_name, start_line, start_col), start_tok)
                    update_expr = self.stamp_node(PostIncrement(upd_id, start_line, start_col), start_tok)
                    header_indent = self._line_indents.get(start_line, 0)
                    body = self.parse_statement(header_indent=header_indent)
                    return self.stamp_node(ForStatement(init_stmt, cond_expr, update_expr, body, start_line, start_col), start_tok)
        self.pos = saved_pos

        self._in_for_header = True
        try:
            init = None
            if not self.match(TokenType.SEMICOLON):
                if self._is_var_decl():
                    init = self.parse_var_decl()
                else:
                    init = self.parse_expr_statement()
            
            condition = None
            if not self.check(TokenType.SEMICOLON):
                condition = self.parse_expression()
            self.consume(TokenType.SEMICOLON, "Expected ';' after loop condition")
            
            update = None
            if not self.check(TokenType.RPAREN):
                update = self.parse_expression()
            self.consume(TokenType.RPAREN, "Expected ')' after for clauses")
            self.match(TokenType.COLON)
        finally:
            self._in_for_header = False
        
        header_indent = self._line_indents.get(start_line, 0)
        body = self.parse_statement(header_indent=header_indent)
        return self.stamp_node(ForStatement(init, condition, update, body, start_line, start_col), start_tok)

    def parse_switch(self) -> SwitchStatement:
        start_tok = self.previous()
        start_line, start_col = start_tok.line, start_tok.col
        self.consume(TokenType.LPAREN, "Expected '(' after 'switch'")
        expr = self.parse_expression()
        self.consume(TokenType.RPAREN, "Expected ')' after switch expression")
        header_indent = self._line_indents.get(start_line, 0)
        self.consume(TokenType.LBRACE, "Expected '{' after switch expression")
        
        cases = []
        while not self.check(TokenType.RBRACE) and not self.is_at_end():
            c_tok = self.peek()
            c_line, c_col = c_tok.line, c_tok.col
            if self.match(TokenType.CASE):
                val = self.parse_expression()
                self.consume(TokenType.COLON, "Expected ':' after case value")
                stmts = []
                while not self.check_any([TokenType.CASE, TokenType.DEFAULT, TokenType.RBRACE]):
                    stmts.append(self.parse_statement(header_indent=header_indent))
                cases.append(self.stamp_node(CaseClause(val, stmts, c_line, c_col), c_tok))
            elif self.match(TokenType.DEFAULT):
                self.consume(TokenType.COLON, "Expected ':' after default")
                stmts = []
                while not self.check_any([TokenType.CASE, TokenType.DEFAULT, TokenType.RBRACE]):
                    stmts.append(self.parse_statement(header_indent=header_indent))
                cases.append(self.stamp_node(CaseClause(None, stmts, c_line, c_col), c_tok))
            else:
                self.error(self.peek(), "Expected 'case' or 'default'")
        self.consume(TokenType.RBRACE, "Expected '}' after switch block")
        return self.stamp_node(SwitchStatement(expr, cases, start_line, start_col), start_tok)

    def parse_return(self) -> ReturnStatement:
        start_tok = self.previous()
        start_line, start_col = start_tok.line, start_tok.col
        expr = None
        if (
            not self.check(TokenType.SEMICOLON)
            and not self.check(TokenType.RBRACE)
            and not (self.peek().line > start_line and self.peek().type in STATEMENT_STARTERS)
        ):
            expr = self.parse_expression()
        self.consume(TokenType.SEMICOLON, "Expected ';' after return value")
        return self.stamp_node(ReturnStatement(expr, start_line, start_col), start_tok)

    def parse_var_decl(self) -> Statement:
        start_tok = self.peek()
        start_line, start_col = start_tok.line, start_tok.col
        is_constexpr = False
        if self.match(TokenType.CONSTEXPR):
            is_constexpr = True
        var_type, is_const, is_reference = self.parse_type()
        if is_constexpr:
            is_const = True
        name_tok = self.consume(TokenType.IDENTIFIER, "Expected variable name")
        self.declare_symbol(name_tok.lexeme)
        
        # Object instantiation with constructor arguments: Point p(10, 20);
        if self.match(TokenType.LPAREN):
            args = []
            if not self.check(TokenType.RPAREN):
                while True:
                    args.append(self.parse_expression())
                    if not self.match(TokenType.COMMA):
                        break
            self.consume(TokenType.RPAREN, "Expected ')' after constructor arguments")
            self.consume(TokenType.SEMICOLON, "Expected ';' after declaration")
            return self.stamp_node(ClassInstanceDeclaration(var_type, name_tok.lexeme, args, start_line, start_col), start_tok)

        # Array declaration
        if self.match(TokenType.LBRACKET):
            dimensions = []
            dim_exprs = []
            while True:
                d_expr = None
                d_size = None
                if not self.check(TokenType.RBRACKET):
                    d_expr = self.parse_expression()
                    if isinstance(d_expr, IntLiteral):
                        d_size = d_expr.value
                    elif isinstance(d_expr, UnaryOp) and d_expr.op == "-" and isinstance(d_expr.expr, IntLiteral):
                        d_size = -d_expr.expr.value
                self.consume(TokenType.RBRACKET, "Expected ']' after array size")
                dimensions.append(d_size)
                dim_exprs.append(d_expr)
                if not self.match(TokenType.LBRACKET):
                    break

            size = dimensions[0] if dimensions else None
            size_expr = dim_exprs[0] if dim_exprs else None

            elements = None
            if self.match(TokenType.ASSIGN):
                self.consume(TokenType.LBRACE, "Expected '{' for array initializer")
                elements = []
                if not self.check(TokenType.RBRACE):
                    while True:
                        elements.append(self.parse_expression())
                        if not self.match(TokenType.COMMA):
                            break
                self.consume(TokenType.RBRACE, "Expected '}' after array initializer")
                if size is None and elements is not None:
                    size = len(elements)
                    if dimensions:
                        dimensions[0] = len(elements)
            self.consume(TokenType.SEMICOLON, "Expected ';' after array declaration")
            return self.stamp_node(ArrayDeclaration(var_type, name_tok.lexeme, size, elements, start_line, start_col, dimensions=dimensions, size_expr=size_expr, dim_exprs=dim_exprs), start_tok)
            
        initializer = None
        if self.match(TokenType.ASSIGN):
            initializer = self.parse_expression()
        first_decl = self.stamp_node(
            VarDeclaration(
                var_type, name_tok.lexeme, initializer, start_line, start_col,
                is_const=is_const, is_reference=is_reference, is_constexpr=is_constexpr,
            ),
            start_tok,
        )
        if self.match(TokenType.COMMA):
            declarations = [first_decl]
            while True:
                next_name = self.consume(TokenType.IDENTIFIER, "Expected variable name after ','")
                self.declare_symbol(next_name.lexeme)
                next_initializer = None
                if self.match(TokenType.ASSIGN):
                    next_initializer = self.parse_expression()
                declarations.append(
                    self.stamp_node(
                        VarDeclaration(
                            var_type,
                            next_name.lexeme,
                            next_initializer,
                            next_name.line,
                            next_name.col,
                            is_const=is_const,
                            is_reference=is_reference,
                            is_constexpr=is_constexpr,
                        ),
                        next_name,
                    )
                )
                if not self.match(TokenType.COMMA):
                    break
            self.consume(TokenType.SEMICOLON, "Expected ';' after variable declaration")
            return self.stamp_node(
                MultiVarDeclaration(declarations, start_line, start_col),
                start_tok,
            )
        self.consume(TokenType.SEMICOLON, "Expected ';' after variable declaration")
        return first_decl

    def parse_struct_decl(self) -> StructDeclaration:
        start_tok = self.consume(TokenType.STRUCT, "Expected 'struct'")
        struct_name = self.consume(TokenType.IDENTIFIER, "Expected struct name").lexeme
        name = self.consume(TokenType.IDENTIFIER, "Expected variable name").lexeme
        self.declare_symbol(name)
        elements = None
        if self.match(TokenType.ASSIGN):
            self.consume(TokenType.LBRACE, "Expected '{' for struct initializer")
            elements = []
            if not self.check(TokenType.RBRACE):
                while True:
                    elements.append(self.parse_expression())
                    if not self.match(TokenType.COMMA):
                        break
            self.consume(TokenType.RBRACE, "Expected '}' after struct initializer")
        self.consume(TokenType.SEMICOLON, "Expected ';' after struct declaration")
        return self.stamp_node(StructDeclaration(struct_name, name, elements, start_tok.line, start_tok.col), start_tok)

    def parse_expr_statement(self) -> ExpressionStatement:
        expr = self.parse_expression()
        self.consume(TokenType.SEMICOLON, "Expected ';' after expression")
        return self.stamp_node(ExpressionStatement(expr, expr.line, expr.col), expr)

    def parse_expression(self) -> Expression:
        if not self.enable_repair or self._in_repair:
            return self.parse_assignment()

        self._expr_depth += 1
        start_pos = self.pos
        try:
            expr = self.parse_assignment()

            if self._expr_depth == 1 and self._has_unparsed_expression_tokens():
                peek_tok = self.peek()
                raise ParseError(
                    peek_tok,
                    f"Unexpected token '{peek_tok.lexeme}' in expression",
                    code="P002",
                )

            return expr
        except ParseError as err:
            if self._expr_depth == 1:
                repaired = self.attempt_expression_repair(start_pos, err)
                if repaired is not None:
                    return repaired
            raise
        finally:
            self._expr_depth -= 1

    def _has_unparsed_expression_tokens(self) -> bool:
        if self.is_at_end():
            return False
        peek_tok = self.peek()
        # If peek_tok is on a subsequent line and is a statement starter or block delimiter,
        # it is not an unparsed token of this expression
        if peek_tok.line > self.previous().line and (
            peek_tok.type in STATEMENT_STARTERS
            or peek_tok.type in (TokenType.RBRACE, TokenType.SEMICOLON)
        ):
            return False
        # If on the same line, but is a keyword statement starter:
        if peek_tok.type in STATEMENT_STARTERS and peek_tok.type != TokenType.IDENTIFIER:
            return False
        # If inside a for-loop header init and an identifier begins the loop condition:
        if self._in_for_header and peek_tok.type == TokenType.IDENTIFIER:
            return False
        if peek_tok.type not in ExpressionRepairEngine.EXPR_DELIMITERS:
            return True
        return False

    def attempt_expression_repair(
        self, start_pos: int, err: ParseError
    ) -> Optional[Expression]:
        if not self.enable_repair or self._in_repair:
            return None

        expr_tokens, delimiter_pos = self.repair_engine.collect_expression_tokens(
            self.tokens, start_pos
        )

        if not expr_tokens:
            return None

        self.repair_engine.known_symbols = self.get_active_symbols()

        suggestions = self.repair_engine.repair(expr_tokens)
        if not suggestions:
            return None

        best = suggestions[0]
        first = expr_tokens[0]
        last = expr_tokens[-1]
        first_loc = self.token_source_location(first)
        last_loc = self.token_source_location(last)
        can_patch, phys_file = self._can_patch_span(expr_tokens)
        diag_file = phys_file or first_loc.file_path
        file_source = self._source_for_file(diag_file)
        raw_code = self._get_token_span_text(
            expr_tokens,
            file_source=file_source if can_patch else None,
            use_source_coords=can_patch,
        )

        explanations = [best.explanation] if isinstance(best.explanation, str) else list(best.explanation)
        patch_obj = None
        if can_patch and first_loc.line == last_loc.end_line:
            from src.patch_model import CodePatch
            patch_obj = CodePatch(
                file_path=diag_file,
                line_start=first_loc.line,
                line_end=first_loc.line,
                col_start=first_loc.col,
                col_end=first_loc.col + len(raw_code),
                original_text=raw_code,
                replacement_text=best.repaired_code,
                error_code="P002",
                summary=f"Malformed Expression: '{raw_code}' -> '{best.repaired_code}'",
                explanations=explanations,
                confidence="safe",
            )
            if self.patch_recorder is not None:
                self.patch_recorder.append(patch_obj)

        diag = make_diagnostic(
            code="P002",
            severity="error",
            message=f"malformed expression '{raw_code}'",
            file=diag_file,
            line=first_loc.line,
            col=first_loc.col,
            end_line=last_loc.end_line if phys_file else first_loc.line,
            end_col=max(first_loc.col + len(raw_code), last_loc.end_col if phys_file and last_loc.end_line == first_loc.line else first_loc.col + len(raw_code)),
            source_text=file_source,
            help_text=f"did you mean '{best.repaired_code}'?",
            notes=explanations,
            stage="parser",
            length=len(raw_code),
            style="malformed_expression",
            suggestion=best.repaired_code if can_patch else None,
            explanations=explanations,
            fixability="auto" if patch_obj is not None else "none",
            patch=patch_obj,
            macro_generated=not can_patch,
            extra={"suggestion": best.repaired_code},
        )
        overlaps_lexer_error = any(
            existing.code == "L001"
            and same_file(existing.file_path, diag_file)
            and first_loc.line <= existing.line <= last_loc.end_line
            for existing in self.sink.diagnostics
        )
        if not overlaps_lexer_error:
            self._add_diag(diag)

        # Recovery always updates only the in-memory token stream. Source edits
        # are represented by CodePatch and applied by RepairCoordinator.
        repaired_toks: List[Token] = []
        for rt in best.repaired_tokens:
            repaired_toks.append(
                Token(
                    rt.type,
                    rt.lexeme,
                    first.line,
                    first.col,
                    indent=getattr(first, "indent", 0),
                    file=diag_file,
                    source_line=first_loc.line,
                    source_col=first_loc.col,
                    source_end_line=last_loc.end_line,
                    source_end_col=last_loc.end_col,
                    synthetic=True,
                    macro_generated=not can_patch,
                )
            )
        self.tokens[start_pos:delimiter_pos] = repaired_toks
        self.pos = start_pos + len(repaired_toks)

        if best.ast_node:
            self.stamp_node(best.ast_node, expr_tokens)

        return best.ast_node

    def _get_token_span_text(
        self,
        expr_tokens: List[Token],
        file_source: Optional[str] = None,
        use_source_coords: bool = False,
    ) -> str:
        if not expr_tokens:
            return ""
        first = expr_tokens[0]
        last = expr_tokens[-1]
        if use_source_coords and file_source is not None:
            first_loc = self.token_source_location(first)
            last_loc = self.token_source_location(last)
            lines = file_source.splitlines(keepends=True)
            if 0 <= first_loc.line - 1 < len(lines) and first_loc.line == last_loc.end_line:
                line_str = lines[first_loc.line - 1]
                start_c = first_loc.col - 1
                end_c = last_loc.end_col - 1
                span = line_str[start_c:end_c].strip()
                if span:
                    return span
        lines = self._analysis_source.splitlines(keepends=True)
        if 0 <= first.line - 1 < len(lines):
            if first.line == last.line:
                line_str = lines[first.line - 1]
                start_c = first.col - 1
                end_c = last.col - 1 + len(last.lexeme)
                span = line_str[start_c:end_c].strip()
                if span:
                    return span
        return tokens_to_code(expr_tokens)

    def parse_assignment(self) -> Expression:
        expr = self.parse_ternary()
        if self.match_any([TokenType.ASSIGN, TokenType.PLUS_ASSIGN, TokenType.MINUS_ASSIGN, TokenType.STAR_ASSIGN, TokenType.SLASH_ASSIGN, TokenType.MOD_ASSIGN]):
            op_tok = self.previous()
            value = self.parse_assignment()
            
            if op_tok.type != TokenType.ASSIGN:
                op_map = {
                    TokenType.PLUS_ASSIGN: '+',
                    TokenType.MINUS_ASSIGN: '-',
                    TokenType.STAR_ASSIGN: '*',
                    TokenType.SLASH_ASSIGN: '/',
                    TokenType.MOD_ASSIGN: '%'
                }
                value = self.stamp_node(BinaryOp(expr, op_map[op_tok.type], value, op_tok.line, op_tok.col), op_tok)
            
            if isinstance(expr, Identifier):
                return self.stamp_node(Assignment(expr.name, value, expr.line, expr.col), expr)
            elif isinstance(expr, ArrayAccess):
                return self.stamp_node(ArrayAssignment(expr.name, expr.index, value, expr.line, expr.col, indices=getattr(expr, "indices", [expr.index])), expr)
            elif isinstance(expr, MemberAccess):
                return self.stamp_node(MemberAssignment(expr.object_expr, expr.member, value, expr.line, expr.col), expr)
            elif isinstance(expr, ArrowAccess):
                return self.stamp_node(ArrowAssignment(expr.object_expr, expr.member, value, expr.line, expr.col), expr)
            elif isinstance(expr, Deref):
                return self.stamp_node(DerefAssignment(expr.expr, value, expr.line, expr.col), expr)
            self.error(op_tok, "Invalid assignment target")
        return expr

    def parse_ternary(self) -> Expression:
        expr = self.parse_logical_or()
        if self.match(TokenType.QUESTION):
            q_tok = self.previous()
            true_expr = self.parse_expression()
            self.consume(TokenType.COLON, "Expected ':' in ternary operator")
            false_expr = self.parse_expression()
            return self.stamp_node(TernaryOp(expr, true_expr, false_expr, q_tok.line, q_tok.col), q_tok)
        return expr

    def parse_logical_or(self) -> Expression:
        expr = self.parse_logical_and()
        while self.match(TokenType.OR) or self.match(TokenType.OR_KEYWORD):
            op = self.previous()
            right = self.parse_logical_and()
            expr = self.stamp_node(BinaryOp(expr, "||", right, op.line, op.col), op)
        return expr

    def parse_logical_and(self) -> Expression:
        expr = self.parse_bitwise_or()
        while self.match(TokenType.AND) or self.match(TokenType.AND_KEYWORD):
            op = self.previous()
            right = self.parse_bitwise_or()
            expr = self.stamp_node(BinaryOp(expr, "&&", right, op.line, op.col), op)
        return expr

    def parse_bitwise_or(self) -> Expression:
        expr = self.parse_bitwise_xor()
        while self.match(TokenType.PIPE):
            op = self.previous()
            right = self.parse_bitwise_xor()
            expr = self.stamp_node(BinaryOp(expr, op.lexeme, right, op.line, op.col), op)
        return expr

    def parse_bitwise_xor(self) -> Expression:
        expr = self.parse_bitwise_and()
        while self.match(TokenType.CARET):
            op = self.previous()
            right = self.parse_bitwise_and()
            expr = self.stamp_node(BinaryOp(expr, op.lexeme, right, op.line, op.col), op)
        return expr

    def parse_bitwise_and(self) -> Expression:
        expr = self.parse_equality()
        while self.match(TokenType.AMP):
            op = self.previous()
            right = self.parse_equality()
            expr = self.stamp_node(BinaryOp(expr, op.lexeme, right, op.line, op.col), op)
        return expr

    def parse_equality(self) -> Expression:
        expr = self.parse_comparison()
        while self.match_any([TokenType.EQ, TokenType.NEQ, TokenType.IS]):
            op = self.previous()
            op_str = op.lexeme
            if op.type == TokenType.IS:
                if self.match(TokenType.NOT_KEYWORD):
                    op_str = "!="
                else:
                    op_str = "=="
            right = self.parse_comparison()
            expr = self.stamp_node(BinaryOp(expr, op_str, right, op.line, op.col), op)
        return expr

    def parse_comparison(self) -> Expression:
        expr = self.parse_shift()
        while self.match_any([TokenType.LT, TokenType.GT, TokenType.LE, TokenType.GE]):
            op = self.previous()
            right = self.parse_shift()
            expr = self.stamp_node(BinaryOp(expr, op.lexeme, right, op.line, op.col), op)
        return expr

    def parse_shift(self) -> Expression:
        expr = self.parse_term()
        while self.match_any([TokenType.SHL, TokenType.SHR]):
            op = self.previous()
            right = self.parse_term()
            expr = self.stamp_node(BinaryOp(expr, op.lexeme, right, op.line, op.col), op)
        return expr

    def parse_term(self) -> Expression:
        expr = self.parse_factor()
        while self.match_any([TokenType.PLUS, TokenType.MINUS]):
            op = self.previous()
            right = self.parse_factor()
            expr = self.stamp_node(BinaryOp(expr, op.lexeme, right, op.line, op.col), op)
        return expr

    def parse_factor(self) -> Expression:
        expr = self.parse_unary()
        while self.match_any([TokenType.STAR, TokenType.SLASH, TokenType.MOD]):
            op = self.previous()
            right = self.parse_unary()
            expr = self.stamp_node(BinaryOp(expr, op.lexeme, right, op.line, op.col), op)
        return expr

    def parse_unary(self) -> Expression:
        if self.match_any([TokenType.NOT, TokenType.NOT_KEYWORD, TokenType.MINUS]):
            op = self.previous()
            right = self.parse_unary()
            op_str = "!" if op.type == TokenType.NOT_KEYWORD else op.lexeme
            return self.stamp_node(UnaryOp(op_str, right, op.line, op.col), op)
        if self.match(TokenType.AMP):
            op = self.previous()
            right = self.parse_unary()
            return self.stamp_node(AddressOf(right, op.line, op.col), op)
        if self.match(TokenType.STAR):
            op = self.previous()
            right = self.parse_unary()
            return self.stamp_node(Deref(right, op.line, op.col), op)
        if self.match(TokenType.INCREMENT):
            op = self.previous()
            right = self.parse_unary()
            return self.stamp_node(PreIncrement(right, op.line, op.col), op)
        if self.match(TokenType.DECREMENT):
            op = self.previous()
            right = self.parse_unary()
            return self.stamp_node(PreDecrement(right, op.line, op.col), op)
        # Type cast: (int)expr or (Animal*)expr
        if self.check(TokenType.LPAREN):
            saved_pos = self.pos
            self.advance() # (
            if self.check_any([TokenType.INT, TokenType.FLOAT, TokenType.DOUBLE, TokenType.CHAR, TokenType.BOOL, TokenType.VOID, TokenType.IDENTIFIER]):
                t_tok = self.advance()
                t_type = t_tok.lexeme
                has_star = False
                while self.match(TokenType.STAR):
                    t_type += "*"
                    has_star = True
                if self.match(TokenType.RPAREN):
                    if t_tok.type != TokenType.IDENTIFIER or has_star:
                        expr = self.parse_unary()
                        if expr is not None:
                            return self.stamp_node(CastExpression(t_type, expr, t_tok.line, t_tok.col), t_tok)
            self.pos = saved_pos # backtrack if not cast
        return self.parse_postfix()

    def parse_postfix(self) -> Expression:
        expr = self.parse_primary()
        while True:
            if self.match(TokenType.LBRACKET):
                index = self.parse_expression()
                self.consume(TokenType.RBRACKET, "Expected ']' after array index")
                if isinstance(expr, Identifier):
                    expr = self.stamp_node(ArrayAccess(expr.name, index, expr.line, expr.col), expr)
                elif isinstance(expr, ArrayAccess):
                    indices = list(getattr(expr, "indices", [expr.index])) + [index]
                    expr = self.stamp_node(ArrayAccess(expr.name, expr.index, expr.line, expr.col, indices=indices), expr)
                else:
                    self.error(self.previous(), "Invalid array access")
            elif self.match(TokenType.DOT) or self.match(TokenType.ARROW):
                is_arrow = (self.previous().type == TokenType.ARROW)
                member = self.consume(TokenType.IDENTIFIER, "Expected member name").lexeme
                if self.match(TokenType.LPAREN):
                    args = []
                    if not self.check(TokenType.RPAREN):
                        while True:
                            args.append(self.parse_expression())
                            if not self.match(TokenType.COMMA):
                                break
                    self.consume(TokenType.RPAREN, "Expected ')' after arguments")
                    expr = self.stamp_node(MethodCall(expr, member, args, is_arrow=is_arrow, line=expr.line, col=expr.col), expr)
                else:
                    if is_arrow:
                        expr = self.stamp_node(ArrowAccess(expr, member, expr.line, expr.col), expr)
                    else:
                        expr = self.stamp_node(MemberAccess(expr, member, expr.line, expr.col), expr)
            elif self.match(TokenType.INCREMENT):
                expr = self.stamp_node(PostIncrement(expr, expr.line, expr.col), expr)
            elif self.match(TokenType.DECREMENT):
                expr = self.stamp_node(PostDecrement(expr, expr.line, expr.col), expr)
            else:
                break
        return expr

    def parse_primary(self) -> Expression:
        if self.match(TokenType.LBRACKET):
            lam_tok = self.previous()
            captures = []
            if not self.check(TokenType.RBRACKET):
                while True:
                    if self.match(TokenType.ASSIGN):
                        captures.append("=")
                    elif self.match(TokenType.AMP):
                        captures.append("&")
                    elif self.match(TokenType.IDENTIFIER):
                        captures.append(self.previous().lexeme)
                    if not self.match(TokenType.COMMA):
                        break
            self.consume(TokenType.RBRACKET, "Expected ']' after lambda captures")
            params = []
            if self.match(TokenType.LPAREN):
                params = self.parse_parameters()
                self.consume(TokenType.RPAREN, "Expected ')' after lambda parameters")
            ret_type = None
            if self.match(TokenType.ARROW):
                ret_type, _, _ = self.parse_type()
            body = self.parse_block()
            return self.stamp_node(LambdaExpr(captures, params, ret_type, body, lam_tok.line, lam_tok.col), lam_tok)
        if self.match(TokenType.TRUE) or self.match(TokenType.TRUE_LIT):
            tok = self.previous()
            return self.stamp_node(BoolLiteral(True, tok.line, tok.col), tok)
        if self.match(TokenType.FALSE) or self.match(TokenType.FALSE_LIT):
            tok = self.previous()
            return self.stamp_node(BoolLiteral(False, tok.line, tok.col), tok)
        if self.match(TokenType.NONE) or self.match(TokenType.NULL_LIT):
            tok = self.previous()
            return self.stamp_node(Identifier("nullptr", tok.line, tok.col), tok)
        if self.match(TokenType.THIS):
            tok = self.previous()
            return self.stamp_node(ThisExpr(tok.line, tok.col), tok)
        if self.match(TokenType.NEW):
            n_tok = self.previous()
            t_tok = self.consume_any([TokenType.INT, TokenType.FLOAT, TokenType.DOUBLE, TokenType.CHAR, TokenType.BOOL, TokenType.IDENTIFIER], "Expected type after 'new'")
            t_name = t_tok.lexeme
            args = []
            if self.match(TokenType.LPAREN):
                if not self.check(TokenType.RPAREN):
                    while True:
                        args.append(self.parse_expression())
                        if not self.match(TokenType.COMMA):
                            break
                self.consume(TokenType.RPAREN, "Expected ')' after constructor arguments")
            return self.stamp_node(NewExpr(t_name, args, n_tok.line, n_tok.col), n_tok)
        if self.match(TokenType.INT_LIT):
            tok = self.previous()
            return self.stamp_node(IntLiteral(int(tok.lexeme), tok.line, tok.col), tok)
        if self.match(TokenType.FLOAT_LIT):
            tok = self.previous()
            return self.stamp_node(FloatLiteral(float(tok.lexeme), tok.line, tok.col), tok)
        if self.match(TokenType.STRING_LIT):
            tok = self.previous()
            return self.stamp_node(StringLiteral(tok.lexeme, tok.line, tok.col), tok)
        if self.match(TokenType.CHAR_LIT):
            tok = self.previous()
            c_str = tok.lexeme
            # Evaluate escape sequences
            if c_str == '\\n': val = ord('\n')
            elif c_str == '\\t': val = ord('\t')
            elif c_str == '\\0': val = 0
            elif c_str == '\\\\': val = ord('\\')
            elif c_str == '\\\'': val = ord('\'')
            else: val = ord(c_str[0])
            return self.stamp_node(IntLiteral(val, tok.line, tok.col), tok)
        if self.match(TokenType.SIZEOF):
            s_tok = self.previous()
            start_line, start_col = s_tok.line, s_tok.col
            self.consume(TokenType.LPAREN, "Expected '(' after sizeof")
            t_tok = self.consume_any([TokenType.INT, TokenType.FLOAT, TokenType.DOUBLE, TokenType.CHAR, TokenType.BOOL, TokenType.IDENTIFIER], "Expected type in sizeof")
            t_type = t_tok.lexeme
            while self.match(TokenType.STAR): t_type += "*"
            self.consume(TokenType.RPAREN, "Expected ')' after sizeof type")
            sizes = {"char": 1, "bool": 1, "int": 4, "float": 4, "double": 8}
            size = 8 if "*" in t_type else sizes.get(t_type, 4)
            return self.stamp_node(IntLiteral(size, start_line, start_col), s_tok)
        if self.match(TokenType.IDENTIFIER):
            name = self.previous()
            if self.match(TokenType.SCOPE):
                mem = self.consume(TokenType.IDENTIFIER, "Expected identifier after '::'").lexeme
                type_args = []
                if self.check(TokenType.LT):
                    saved_pos = self.pos
                    self.advance() # consume <
                    is_template_call = False
                    while not self.is_at_end():
                        if self.check_any([TokenType.INT, TokenType.FLOAT, TokenType.DOUBLE, TokenType.CHAR, TokenType.BOOL, TokenType.IDENTIFIER]):
                            arg_tok = self.advance()
                            arg_name = arg_tok.lexeme
                            while self.match(TokenType.STAR) or self.match(TokenType.AMP): pass
                            type_args.append(arg_name)
                            if self.match(TokenType.COMMA):
                                continue
                            elif self.match(TokenType.GT):
                                if self.check(TokenType.LPAREN):
                                    is_template_call = True
                                break
                            else:
                                break
                        else:
                            break
                    if not is_template_call:
                        self.pos = saved_pos
                        type_args = []
                if self.match(TokenType.LPAREN):
                    args = []
                    if not self.check(TokenType.RPAREN):
                        while True:
                            args.append(self.parse_expression())
                            if not self.match(TokenType.COMMA):
                                break
                    self.consume(TokenType.RPAREN, "Expected ')' after arguments")
                    call_name = f"{name.lexeme}::{mem}<{','.join(type_args)}>" if type_args else f"{name.lexeme}::{mem}"
                    return self.stamp_node(FunctionCall(call_name, args, name.line, name.col), name)
                return self.stamp_node(ScopeResolution(name.lexeme, mem, name.line, name.col), name)
            # Check for template arguments on function call: func<int>(...)
            if self.check(TokenType.LT):
                saved_pos = self.pos
                self.advance() # consume <
                type_args = []
                is_template_call = False
                while not self.is_at_end():
                    if self.check_any([TokenType.INT, TokenType.FLOAT, TokenType.DOUBLE, TokenType.CHAR, TokenType.BOOL, TokenType.IDENTIFIER]):
                        arg_tok = self.advance()
                        arg_name = arg_tok.lexeme
                        while self.match(TokenType.STAR) or self.match(TokenType.AMP): pass
                        type_args.append(arg_name)
                        if self.match(TokenType.COMMA):
                            continue
                        elif self.match(TokenType.GT):
                            if self.check(TokenType.LPAREN):
                                is_template_call = True
                            break
                        else:
                            break
                    else:
                        break
                if is_template_call:
                    self.consume(TokenType.LPAREN, "Expected '(' after template arguments")
                    args = []
                    if not self.check(TokenType.RPAREN):
                        while True:
                            args.append(self.parse_expression())
                            if not self.match(TokenType.COMMA):
                                break
                    self.consume(TokenType.RPAREN, "Expected ')' after arguments")
                    return self.stamp_node(FunctionCall(f"{name.lexeme}<{','.join(type_args)}>", args, name.line, name.col), name)
                else:
                    self.pos = saved_pos
            if self.match(TokenType.LPAREN):
                args = []
                if not self.check(TokenType.RPAREN):
                    while True:
                        args.append(self.parse_expression())
                        if not self.match(TokenType.COMMA):
                            break
                self.consume(TokenType.RPAREN, "Expected ')' after arguments")
                return self.stamp_node(FunctionCall(name.lexeme, args, name.line, name.col), name)
            return self.stamp_node(Identifier(name.lexeme, name.line, name.col), name)
        if self.match(TokenType.LPAREN):
            expr = self.parse_expression()
            self.consume(TokenType.RPAREN, "Expected ')' after expression")
            expr.is_parenthesized = True
            return expr
            
        self.error(self.peek(), "Expected expression")

    # Helpers
    def match(self, token_type: TokenType) -> bool:
        if self.check(token_type):
            self.advance()
            return True
        return False

    def match_any(self, types: List[TokenType]) -> bool:
        for t in types:
            if self.check(t):
                self.advance()
                return True
        return False

    def check(self, token_type: TokenType) -> bool:
        if self.is_at_end(): return False
        if token_type == TokenType.IDENTIFIER:
            return self.peek().type in (TokenType.IDENTIFIER, TokenType.RANGE, TokenType.IN, TokenType.IS)
        return self.peek().type == token_type
        
    def check_any(self, types: List[TokenType]) -> bool:
        if self.is_at_end(): return False
        return self.peek().type in types

    def advance(self) -> Token:
        current_idx = self._pos
        if not self.is_at_end():
            self._pos += 1
        tok = self.tokens[current_idx]
        if tok.type in (TokenType.LPAREN, TokenType.LBRACKET, TokenType.LBRACE):
            loc = self.token_source_location(tok)
            self.delimiter_stack.append(
                DelimiterEntry(
                    tok.type,
                    tok.lexeme,
                    tok.line,
                    tok.col,
                    self._line_indents.get(tok.line, getattr(tok, "indent", 0)),
                    pos=current_idx,
                    file=loc.file_path,
                    source_line=loc.line,
                    source_col=loc.col,
                    source_end_line=loc.end_line,
                    source_end_col=loc.end_col,
                    macro_generated=bool(getattr(tok, "macro_generated", False)),
                )
            )
        elif tok.type in (TokenType.RPAREN, TokenType.RBRACKET, TokenType.RBRACE):
            matching = {
                TokenType.RPAREN: TokenType.LPAREN,
                TokenType.RBRACKET: TokenType.LBRACKET,
                TokenType.RBRACE: TokenType.LBRACE,
            }
            if self.delimiter_stack and self.delimiter_stack[-1].type == matching.get(tok.type):
                self.delimiter_stack.pop()
        return tok

    def is_at_end(self) -> bool:
        return self.peek().type == TokenType.EOF

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def previous(self) -> Token:
        return self.tokens[self.pos - 1]

    def consume(self, token_type: TokenType, message: str) -> Token:
        if self.check(token_type):
            return self.advance()
        if token_type == TokenType.IDENTIFIER and self.peek().type in (TokenType.RANGE, TokenType.IN, TokenType.IS):
            return self.advance()
        if self.enable_repair and not self._in_repair:
            if token_type == TokenType.SEMICOLON:
                repaired = self.attempt_semicolon_repair(message)
                if repaired is not None:
                    return repaired
            elif token_type == TokenType.RPAREN:
                repaired = self.attempt_rparen_repair(message)
                if repaired is not None:
                    return repaired
            elif token_type == TokenType.RBRACKET:
                repaired = self.attempt_rbracket_repair(message)
                if repaired is not None:
                    return repaired
            elif token_type == TokenType.RBRACE:
                repaired = self.attempt_rbrace_repair()
                if repaired is not None:
                    return repaired
        self.error(self.peek(), message)

    def attempt_cross_language_repair(self):
        """Scans for cross-language anti-patterns, emitting diagnostics and repairing code if enabled."""
        if not self.enable_repair or self._in_repair:
            return

        self._in_repair = True
        try:
            self.cross_language_engine.known_symbols = self.get_active_symbols()
            diagnostics = self.cross_language_engine.analyze(self.tokens)
            if not diagnostics:
                return

            patchable_diags = []
            for diag in diagnostics:
                diag_file = getattr(diag, "file", None) or self.filename
                src_text = self.file_sources.get(diag_file, self.source) if self.file_sources else self.source
                phys_line = getattr(diag, "source_line", None) or diag.line
                phys_col = getattr(diag, "source_col", None) or diag.col
                phys_end_line = getattr(diag, "source_end_line", None) or phys_line
                phys_end_col = getattr(diag, "source_end_col", None) or (phys_col + diag.length)
                is_gen = bool(getattr(diag, "macro_generated", False))
                crosses = bool(getattr(diag, "crosses_files", False))
                can_patch = not is_gen and not crosses

                patch_obj = None
                if can_patch:
                    from src.patch_model import CodePatch
                    patch_obj = CodePatch(
                        file_path=diag_file,
                        line_start=phys_line,
                        line_end=phys_end_line,
                        col_start=phys_col,
                        col_end=phys_end_col,
                        original_text=diag.alien_syntax,
                        replacement_text=diag.suggested_code,
                        error_code="P005",
                        summary=f"Cross-Language Syntax: '{diag.alien_syntax}' -> '{diag.suggested_code}'",
                        explanations=diag.explanations,
                        confidence="review",
                    )
                    patchable_diags.append((diag, patch_obj))

                d = make_diagnostic(
                    code="P005",
                    severity="error",
                    message=f"cross-language syntax '{diag.alien_syntax}' is not valid in C++",
                    file_path=diag_file,
                    line=phys_line,
                    col=phys_col,
                    end_line=phys_end_line,
                    end_col=phys_end_col,
                    source=src_text,
                    stage="parser",
                    style="cross_language",
                    suggestion=diag.suggested_code,
                    explanations=diag.explanations,
                    fixability="auto" if can_patch else "none",
                    patch=patch_obj,
                    macro_generated=is_gen,
                    extra={"suggestion": diag.suggested_code},
                )
                self._add_diag(d)

            all_in_current_and_patchable = (
                len(patchable_diags) == len(diagnostics)
                and all(self._is_current_file(getattr(d, "file", None)) for d in diagnostics)
            )
            translated_source = None
            if all_in_current_and_patchable:
                translated_source, _ = self.cross_language_engine.translate_entire_source(self.tokens)
                from src.auto_include import restore_preprocessor_includes

                translated_source = restore_preprocessor_includes(translated_source)
                if self.patch_recorder is not None and translated_source != self.source:
                    from src.patch_model import CodePatch

                    line_count = max(1, len(self.source.splitlines()))
                    self.patch_recorder.append(
                        CodePatch(
                            file_path=self.filename,
                            line_start=1,
                            line_end=line_count,
                            col_start=1,
                            col_end=1,
                            original_text=self.source,
                            replacement_text=translated_source,
                            error_code="P005",
                            summary="Translate cross-language constructs and balance converted blocks",
                            explanations=[
                                "Applies the complete translation as one atomic patch so dependent brace repairs are not lost."
                            ],
                            start_offset=0,
                            end_offset=len(self.source),
                            confidence="review",
                        )
                    )
            repaired_source = translated_source
            if repaired_source is None:
                repaired_source, _ = self.cross_language_engine.translate_entire_source(self.tokens)
            from src.lexer import Lexer
            silent_sink = DiagnosticSink(emit=False)
            old_tokens = self.tokens
            rewritten_tokens = Lexer(
                repaired_source,
                self.filename,
                diag_sink=silent_sink,
            ).tokenize()
            self.tokens = self._restore_token_provenance_after_virtual_rewrite(
                old_tokens, rewritten_tokens
            )
            self._pos = 0
            self._line_indents = compute_line_indents(self.source)
        finally:
            self._in_repair = False

    def attempt_semicolon_repair(
        self,
        message: str = "",
        context: Optional[str] = None,
        in_class_or_struct: bool = False,
    ) -> Optional[Token]:
        if not self.enable_repair or self._in_repair:
            return None

        self._in_repair = True
        try:
            prev = self.previous()
            curr = self.peek()

            is_missing, inferred_context = self.delimiter_engine.is_missing_semicolon(
                prev,
                curr,
                in_class_or_struct=in_class_or_struct,
                in_for_header=self._in_for_header,
            )
            if not is_missing:
                return None

            ctx = context or inferred_context or "statement"
            prev_loc = self.token_source_location(prev)
            diag_file = prev_loc.file_path
            file_source = self.source_for_token(prev)
            phys_insert_line = prev_loc.end_line
            phys_insert_col = prev_loc.end_col
            analysis_insert_line = prev.line
            analysis_insert_col = prev.col + len(prev.lexeme)

            is_gen = bool(getattr(prev, "macro_generated", False)) or self._after_token_is_generated(prev)
            can_patch = not is_gen

            patch_obj = None
            if can_patch:
                from src.patch_model import CodePatch
                patch_obj = CodePatch(
                    file_path=diag_file,
                    line_start=phys_insert_line,
                    line_end=phys_insert_line,
                    col_start=phys_insert_col,
                    col_end=phys_insert_col,
                    original_text="",
                    replacement_text=";",
                    error_code="P003",
                    summary=f"Missing Semicolon at line {phys_insert_line}, col {phys_insert_col}",
                    explanations=["C++ statements, declarations, and struct/class definitions require a terminating ';'."],
                    confidence="safe",
                )
                if self.patch_recorder is not None:
                    self.patch_recorder.append(patch_obj)

            diag = make_diagnostic(
                code="P003",
                severity="error",
                message=f"missing semicolon ';' after {ctx}",
                file_path=diag_file,
                line=phys_insert_line,
                col=phys_insert_col,
                end_line=phys_insert_line,
                end_col=phys_insert_col + 1,
                source=file_source,
                stage="parser",
                style="missing_semicolon",
                help_text="insert ';' here",
                suggestion=";" if can_patch else None,
                explanations=["C++ statements, declarations, and struct/class definitions require a terminating ';'."],
                fixability="auto" if can_patch else "none",
                patch=patch_obj,
                macro_generated=is_gen,
            )
            self._add_diag(diag)

            synth = Token(
                TokenType.SEMICOLON,
                ";",
                analysis_insert_line,
                analysis_insert_col,
                file=diag_file,
                source_line=phys_insert_line,
                source_col=phys_insert_col,
                source_end_line=phys_insert_line,
                source_end_col=phys_insert_col,
                macro_generated=is_gen,
                synthetic=True,
            )
            self.tokens.insert(self.pos, synth)
            return self.advance()
        finally:
            self._in_repair = False

    def attempt_rparen_repair(
        self, message: str = "", header_name: str = "condition or arguments"
    ) -> Optional[Token]:
        if not self.enable_repair or self._in_repair:
            return None

        self._in_repair = True
        try:
            prev = self.previous()
            curr = self.peek()

            is_missing, reason = self.delimiter_engine.is_missing_rparen(
                prev, curr, context_name=header_name
            )
            if not is_missing:
                return None

            prev_loc = self.token_source_location(prev)
            curr_loc = self.token_source_location(curr)

            if curr.type == TokenType.LBRACE and curr_loc.file_path == prev_loc.file_path:
                analysis_insert_line = curr.line
                analysis_insert_col = curr.col
                phys_insert_line = curr_loc.line
                phys_insert_col = curr_loc.col
                diag_file = curr_loc.file_path
                file_source = self.source_for_token(curr)
                anchor_tok = curr
                insert_str = ") "
                suggestion = "insert ')' before '{'"
            elif curr.type == TokenType.SEMICOLON:
                analysis_insert_line = prev.line
                analysis_insert_col = prev.col + len(prev.lexeme)
                phys_insert_line = prev_loc.end_line
                phys_insert_col = prev_loc.end_col
                diag_file = prev_loc.file_path
                file_source = self.source_for_token(prev)
                anchor_tok = prev
                insert_str = ")"
                suggestion = "insert ')' before ';'"
            elif curr.type == TokenType.COMMA:
                analysis_insert_line = prev.line
                analysis_insert_col = prev.col + len(prev.lexeme)
                phys_insert_line = prev_loc.end_line
                phys_insert_col = prev_loc.end_col
                diag_file = prev_loc.file_path
                file_source = self.source_for_token(prev)
                anchor_tok = prev
                insert_str = ")"
                suggestion = "insert ')' before ','"
            else:
                analysis_insert_line = prev.line
                analysis_insert_col = prev.col + len(prev.lexeme)
                phys_insert_line = prev_loc.end_line
                phys_insert_col = prev_loc.end_col
                diag_file = prev_loc.file_path
                file_source = self.source_for_token(prev)
                anchor_tok = prev
                insert_str = ")"
                suggestion = f"insert ')' in {header_name}"

            msg = f"unclosed '(' in {header_name}"
            open_paren_gen = any(
                e.type == TokenType.LPAREN and e.macro_generated
                for e in reversed(self.delimiter_stack)
            )
            is_gen = (
                bool(getattr(anchor_tok, "macro_generated", False))
                or self._after_token_is_generated(prev)
                or open_paren_gen
            )
            can_patch = not is_gen

            patch_obj = None
            if can_patch:
                from src.patch_model import CodePatch
                patch_obj = CodePatch(
                    file_path=diag_file,
                    line_start=phys_insert_line,
                    line_end=phys_insert_line,
                    col_start=phys_insert_col,
                    col_end=phys_insert_col,
                    original_text="",
                    replacement_text=insert_str,
                    error_code="P004",
                    summary=f"Unbalanced Delimiter (insert missing ')') in {header_name}",
                    explanations=[f"Unclosed '(' in {header_name}; inserting matching ')'."],
                    confidence="safe",
                )
                if self.patch_recorder is not None:
                    self.patch_recorder.append(patch_obj)

            diag = make_diagnostic(
                code="P004",
                severity="error",
                message=msg,
                file_path=diag_file,
                line=phys_insert_line,
                col=phys_insert_col,
                end_line=phys_insert_line,
                end_col=phys_insert_col + 1,
                source=file_source,
                stage="parser",
                style="delimiter",
                help_text=suggestion,
                suggestion=suggestion if can_patch else None,
                explanations=[f"Unclosed '(' in {header_name}; inserting matching ')'."],
                fixability="auto" if can_patch else "none",
                patch=patch_obj,
                macro_generated=is_gen,
            )
            self._add_diag(diag)

            synth = Token(
                TokenType.RPAREN,
                ")",
                analysis_insert_line,
                analysis_insert_col,
                file=diag_file,
                source_line=phys_insert_line,
                source_col=phys_insert_col,
                source_end_line=phys_insert_line,
                source_end_col=phys_insert_col,
                macro_generated=is_gen,
                synthetic=True,
            )
            self.tokens.insert(self.pos, synth)
            return self.advance()
        finally:
            self._in_repair = False

    def attempt_rbracket_repair(
        self, message: str = "", context_name: str = "array index or bounds"
    ) -> Optional[Token]:
        if not self.enable_repair or self._in_repair:
            return None

        self._in_repair = True
        try:
            prev = self.previous()
            curr = self.peek()

            is_missing, reason = self.delimiter_engine.is_missing_rbracket(
                prev, curr, context_name=context_name
            )
            if not is_missing:
                return None

            prev_loc = self.token_source_location(prev)
            diag_file = prev_loc.file_path
            file_source = self.source_for_token(prev)
            phys_insert_line = prev_loc.end_line
            phys_insert_col = prev_loc.end_col
            analysis_insert_line = prev.line
            analysis_insert_col = prev.col + len(prev.lexeme)
            insert_str = "]"

            msg = f"unclosed '[' in {context_name}"
            suggestion = "insert ']' to close bracket"
            open_bracket_gen = any(
                e.type == TokenType.LBRACKET and e.macro_generated
                for e in reversed(self.delimiter_stack)
            )
            is_gen = (
                bool(getattr(prev, "macro_generated", False))
                or self._after_token_is_generated(prev)
                or open_bracket_gen
            )
            can_patch = not is_gen

            patch_obj = None
            if can_patch:
                from src.patch_model import CodePatch
                patch_obj = CodePatch(
                    file_path=diag_file,
                    line_start=phys_insert_line,
                    line_end=phys_insert_line,
                    col_start=phys_insert_col,
                    col_end=phys_insert_col,
                    original_text="",
                    replacement_text=insert_str,
                    error_code="P004",
                    summary=f"Unbalanced Delimiter (insert missing ']') in {context_name}",
                    explanations=[f"Unclosed '[' in {context_name}; inserting matching ']'."],
                    confidence="safe",
                )
                if self.patch_recorder is not None:
                    self.patch_recorder.append(patch_obj)

            diag = make_diagnostic(
                code="P004",
                severity="error",
                message=msg,
                file_path=diag_file,
                line=phys_insert_line,
                col=phys_insert_col,
                end_line=phys_insert_line,
                end_col=phys_insert_col + 1,
                source=file_source,
                stage="parser",
                style="delimiter",
                help_text=suggestion,
                suggestion=suggestion if can_patch else None,
                explanations=[f"Unclosed '[' in {context_name}; inserting matching ']'."],
                fixability="auto" if can_patch else "none",
                patch=patch_obj,
                macro_generated=is_gen,
            )
            self._add_diag(diag)

            synth = Token(
                TokenType.RBRACKET,
                "]",
                analysis_insert_line,
                analysis_insert_col,
                file=diag_file,
                source_line=phys_insert_line,
                source_col=phys_insert_col,
                source_end_line=phys_insert_line,
                source_end_col=phys_insert_col,
                macro_generated=is_gen,
                synthetic=True,
            )
            self.tokens.insert(self.pos, synth)
            return self.advance()
        finally:
            self._in_repair = False

    def attempt_rbrace_repair(
        self, block_entry: Optional[DelimiterEntry] = None
    ) -> Optional[Token]:
        if not self.enable_repair or self._in_repair:
            return None

        self._in_repair = True
        try:
            curr = self.peek()
            prev = self.previous()

            if block_entry is not None and block_entry.file:
                diag_file = block_entry.file
            else:
                diag_file = self.token_source_location(prev).file_path

            # Find the last token belonging to diag_file at or before prev
            anchor_tok = prev
            for idx in range(self.pos - 1, -1, -1):
                candidate = self.tokens[idx]
                if self.token_source_location(candidate).file_path == diag_file:
                    anchor_tok = candidate
                    break

            anchor_loc = self.token_source_location(anchor_tok)
            curr_loc = self.token_source_location(curr)
            file_source = self.file_sources.get(diag_file, self.source) if self.file_sources else self.source

            if not self.is_at_end() and curr_loc.file_path == diag_file:
                phys_insert_line = curr_loc.line
                phys_insert_col = curr_loc.col
                analysis_insert_line = curr.line
                analysis_insert_col = curr.col
            else:
                phys_insert_line = anchor_loc.end_line
                phys_insert_col = anchor_loc.end_col
                analysis_insert_line = anchor_tok.line
                analysis_insert_col = anchor_tok.col + len(anchor_tok.lexeme)

            opened_line = (
                (block_entry.source_line or block_entry.line)
                if block_entry is not None
                else anchor_loc.line
            )
            indent = block_entry.indent if block_entry else 0

            msg = f"missing closing brace '}}' for block opened at line {opened_line}"
            suggestion = f"insert '}}' to close block opened at line {opened_line}"
            is_gen = (
                bool(block_entry.macro_generated if block_entry else False)
                or bool(getattr(anchor_tok, "macro_generated", False))
            )
            can_patch = not is_gen

            patch_obj = None
            if can_patch:
                from src.patch_model import CodePatch
                indent_spaces = " " * indent
                patch_obj = CodePatch(
                    file_path=diag_file,
                    line_start=phys_insert_line,
                    line_end=phys_insert_line,
                    col_start=phys_insert_col,
                    col_end=phys_insert_col,
                    original_text="",
                    replacement_text=f"\n{indent_spaces}}}",
                    error_code="P004",
                    summary=f"Unbalanced Delimiter (insert missing '}}' for block opened at line {opened_line})",
                    explanations=[f"Missing closing '}}' for block opened at line {opened_line}."],
                    confidence="review",
                )
                if self.patch_recorder is not None:
                    self.patch_recorder.append(patch_obj)

            diag = make_diagnostic(
                code="P004",
                severity="error",
                message=msg,
                file_path=diag_file,
                line=phys_insert_line,
                col=phys_insert_col,
                end_line=phys_insert_line,
                end_col=phys_insert_col + 1,
                source=file_source,
                stage="parser",
                style="delimiter",
                help_text=suggestion,
                suggestion=suggestion if can_patch else None,
                explanations=[f"Missing closing '}}' for block opened at line {opened_line}."],
                fixability="auto" if can_patch else "none",
                patch=patch_obj,
                macro_generated=is_gen,
            )
            self._add_diag(diag)

            synth = Token(
                TokenType.RBRACE,
                "}",
                analysis_insert_line,
                analysis_insert_col,
                file=diag_file,
                source_line=phys_insert_line,
                source_col=phys_insert_col,
                source_end_line=phys_insert_line,
                source_end_col=phys_insert_col,
                macro_generated=is_gen,
                synthetic=True,
            )
            self.tokens.insert(self.pos, synth)
            return self.advance()
        finally:
            self._in_repair = False

    def attempt_block_close_repair(self, target_block: DelimiterEntry) -> bool:
        if not self.enable_repair or self._in_repair:
            return False

        self._in_repair = True
        try:
            curr = self.peek()
            curr_loc = self.token_source_location(curr)
            block_file = target_block.file or curr_loc.file_path
            block_open_line = target_block.source_line or target_block.line

            indent_spaces = " " * target_block.indent
            brace_line_str = f"{indent_spaces}}}"

            if block_file != curr_loc.file_path:
                # Block was opened in an included file (e.g., header.h), not in curr's file!
                diag_file = block_file
                file_source = self.file_sources.get(diag_file, self.source) if self.file_sources else self.source
                anchor_tok = self.previous()
                for idx in range(self.pos - 1, -1, -1):
                    candidate = self.tokens[idx]
                    if self.token_source_location(candidate).file_path == diag_file:
                        anchor_tok = candidate
                        break
                anchor_loc = self.token_source_location(anchor_tok)
                phys_insert_line = anchor_loc.end_line
                phys_insert_col = anchor_loc.end_col
                replacement_text = f"\n{brace_line_str}"
                cross_file_block = True
            else:
                diag_file = block_file
                file_source = self.file_sources.get(diag_file, self.source) if self.file_sources else self.source
                phys_insert_line = curr_loc.line
                phys_insert_col = 1
                replacement_text = brace_line_str + "\n"
                cross_file_block = False

            msg = f"missing closing brace '}}' for block opened at line {block_open_line}"
            suggestion = f"insert '}}' matching indentation of enclosing statement (line {block_open_line})"
            is_gen = bool(target_block.macro_generated) or (not cross_file_block and bool(getattr(curr, "macro_generated", False)))
            can_patch = not is_gen

            patch_obj = None
            if can_patch:
                from src.patch_model import CodePatch
                patch_obj = CodePatch(
                    file_path=diag_file,
                    line_start=phys_insert_line,
                    line_end=phys_insert_line,
                    col_start=phys_insert_col,
                    col_end=phys_insert_col,
                    original_text="",
                    replacement_text=replacement_text,
                    error_code="P004",
                    summary=f"Unbalanced Block (insert missing '}}' matching block at line {block_open_line})",
                    explanations=[f"Block scope opened at line {block_open_line} was not closed; inserting matching '}}'."],
                    confidence="review",
                )
                if self.patch_recorder is not None:
                    self.patch_recorder.append(patch_obj)

            diag = make_diagnostic(
                code="P004",
                severity="error",
                message=msg,
                file_path=diag_file,
                line=phys_insert_line,
                col=phys_insert_col,
                end_line=phys_insert_line,
                end_col=phys_insert_col + 1,
                source=file_source,
                stage="parser",
                style="delimiter",
                help_text=suggestion,
                suggestion=suggestion if can_patch else None,
                explanations=[f"Block scope opened at line {block_open_line} was not closed; inserting matching '}}'."],
                fixability="auto" if can_patch else "none",
                patch=patch_obj,
                macro_generated=is_gen,
            )
            self._add_diag(diag)

            return True
        finally:
            self._in_repair = False

    def consume_any(self, types: List[TokenType], message: str) -> Token:
        for t in types:
            if self.check(t):
                return self.advance()
        self.error(self.peek(), message)

    def error(self, token: Token, message: str, code: str = "P001", help_text: Optional[str] = None):
        raise ParseError(token, message, code=code, help_text=help_text)
