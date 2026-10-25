from typing import Optional, List

from src.tokens import Token, TokenType, KEYWORDS
from src.analysis_result import Diagnostic
from src.diagnostics import DiagnosticSink, make_diagnostic
from src.paths import canonical_path
from src.provenance import OriginMap


class Lexer:
    """Lexer to tokenize a string of source code.

    Every token carries dual coordinates: ``line``/``col``/``indent`` describe
    the text being lexed (analysis coordinates) while ``file`` and the
    ``source_*`` fields describe the physical origin.  When the text came from
    the preprocessor, pass ``preproc_result`` so tokens map back to the right
    file/line/column (including text produced by macro replacement).  Direct
    lexing initialises source coordinates from the analysis coordinates.
    """

    def __init__(
        self,
        source: str,
        filename: str = "<stdin>",
        preproc_result=None,
        diag_sink: Optional[DiagnosticSink] = None,
        origin: Optional[OriginMap] = None,
    ):
        self.source = source
        self.filename = filename
        self.entry_file = canonical_path(filename)
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: List[Token] = []
        self.errors_count = 0
        self.sink = diag_sink if diag_sink is not None else DiagnosticSink(emit=True)
        self.diagnostics: List[Diagnostic] = []

        if preproc_result is not None and origin is None:
            origin = preproc_result.origin
        if origin is not None and origin.text != source:
            origin = None  # stale/mismatched map: fall back to direct coordinates
        self.origin = origin
        if preproc_result is not None:
            self.file_sources = preproc_result.file_sources
        else:
            self.file_sources = {self.entry_file: source}
        self._line_indents = self._compute_line_indents()

    # ------------------------------------------------------------------ tokens
    def _make_token(self, token_type: TokenType, lexeme: str, start_line: int, start_col: int, start_pos: int) -> Token:
        indent = self._line_indents.get(start_line, 0)
        if self.origin is not None and len(self.origin) > 0:
            if token_type == TokenType.EOF:
                last = self.origin.locate(len(self.origin) - 1, len(self.origin))
                file, sl, sc, el, ec, gen = last.file, last.end_line, last.end_col, last.end_line, last.end_col, False
            else:
                span = self.origin.locate(start_pos, max(self.pos, start_pos + 1))
                file, sl, sc, el, ec, gen = span.file, span.line, span.col, span.end_line, span.end_col, span.generated
        else:
            file, sl, sc, el, ec, gen = self.entry_file, start_line, start_col, self.line, self.col, False
        return Token(
            token_type, lexeme, start_line, start_col, indent=indent, file=file,
            source_line=sl, source_col=sc, source_end_line=el, source_end_col=ec,
            synthetic=False, macro_generated=gen,
        )

    def _compute_line_indents(self):
        # Indentation is calculated on the analysis source *before* any origin mapping.
        indents = {}
        for idx, line in enumerate(self.source.splitlines(), start=1):
            expanded = line.expandtabs(4)
            indents[idx] = len(expanded) - len(expanded.lstrip(' '))
        return indents

    # ------------------------------------------------------------- diagnostics
    def _lex_error(self, code: str, message: str, help_text: str, start_pos: int, length: int = 1):
        if self.origin is not None and len(self.origin) > 0:
            span = self.origin.locate(start_pos, start_pos + max(1, length))
            file, line, col, end_line, end_col = span.file, span.line, span.col, span.end_line, span.end_col
        else:
            # Direct lexing: analysis coordinates are the source coordinates.
            before = self.source[:start_pos]
            line = before.count("\n") + 1
            col = start_pos - (before.rfind("\n") + 1) + 1
            file, end_line, end_col = self.entry_file, line, col + max(1, length)
        source_text = self.file_sources.get(file, self.source if file == self.entry_file else "")
        diag = make_diagnostic(
            code, "error", message, file, line, col, end_line, end_col,
            source_text=source_text, help_text=help_text, stage="lexer",
        )
        if self.sink.add(diag):
            self.errors_count += 1
            self.diagnostics.append(diag)

    # ------------------------------------------------------------------- lexing
    def tokenize(self):
        while self.pos < len(self.source):
            char = self.source[self.pos]

            if char.isspace():
                self.advance()
                continue

            if char == '/' and self.peek() == '/':
                self.skip_line_comment()
                continue

            if char == '/' and self.peek() == '*':
                self.skip_block_comment()
                continue

            if char.isalpha() or char == '_':
                self.tokens.append(self.lex_identifier())
                continue

            if char.isdigit():
                self.tokens.append(self.lex_number())
                continue

            if char == '"':
                self.tokens.append(self.lex_string())
                continue

            if char == "'":
                self.tokens.append(self.lex_char())
                continue

            # Operators and separators
            tok = self.lex_operator_or_sep()
            if tok:
                self.tokens.append(tok)
            else:
                self._lex_error(
                    "L001", f"Invalid character: '{char}'",
                    f"remove or replace unexpected character '{char}'", self.pos,
                )
                self.advance()

        self.tokens.append(self._make_token(TokenType.EOF, "", self.line, self.col, len(self.source)))
        return self.tokens

    def advance(self):
        if self.pos < len(self.source):
            if self.source[self.pos] == '\n':
                self.line += 1
                self.col = 1
            else:
                self.col += 1
            self.pos += 1

    def peek(self):
        if self.pos + 1 < len(self.source):
            return self.source[self.pos + 1]
        return '\0'

    def skip_line_comment(self):
        while self.pos < len(self.source) and self.source[self.pos] != '\n':
            self.advance()

    def skip_block_comment(self):
        self.advance()  # /
        self.advance()  # *
        while self.pos < len(self.source):
            if self.source[self.pos] == '*' and self.peek() == '/':
                self.advance()
                self.advance()
                return
            self.advance()

    def lex_identifier(self):
        start_line, start_col, start_pos = self.line, self.col, self.pos
        while self.pos < len(self.source) and (self.source[self.pos].isalnum() or self.source[self.pos] == '_'):
            self.advance()
        lexeme = self.source[start_pos:self.pos]
        tok_type = KEYWORDS.get(lexeme, TokenType.IDENTIFIER)
        return self._make_token(tok_type, lexeme, start_line, start_col, start_pos)

    def lex_number(self):
        start_line, start_col, start_pos = self.line, self.col, self.pos
        is_float = False
        while self.pos < len(self.source) and self.source[self.pos].isdigit():
            self.advance()
        if self.pos < len(self.source) and self.source[self.pos] == '.':
            is_float = True
            self.advance()
            while self.pos < len(self.source) and self.source[self.pos].isdigit():
                self.advance()
        lexeme = self.source[start_pos:self.pos]
        return self._make_token(TokenType.FLOAT_LIT if is_float else TokenType.INT_LIT, lexeme, start_line, start_col, start_pos)

    def lex_string(self):
        start_line, start_col, start_pos = self.line, self.col, self.pos
        self.advance()  # skip "
        # A string literal cannot span lines: stop at the end of the line.
        while self.pos < len(self.source) and self.source[self.pos] not in ('"', '\n'):
            self.advance()
        if self.pos >= len(self.source) or self.source[self.pos] != '"':
            self._lex_error(
                "E004", "Unterminated string literal",
                'add closing quote " to terminate string literal',
                start_pos, max(1, self.pos - start_pos),
            )
            lexeme = self.source[start_pos + 1:self.pos]
        else:
            self.advance()  # skip closing "
            lexeme = self.source[start_pos + 1:self.pos - 1]
        return self._make_token(TokenType.STRING_LIT, lexeme, start_line, start_col, start_pos)

    def lex_char(self):
        start_line, start_col, start_pos = self.line, self.col, self.pos
        self.advance()  # skip '
        if self.pos < len(self.source) and self.source[self.pos] == '\\':
            self.advance()
            if self.pos < len(self.source) and self.source[self.pos] != '\n':
                self.advance()  # the escaped char
        elif self.pos < len(self.source) and self.source[self.pos] not in ("'", '\n'):
            self.advance()  # the char

        if self.pos >= len(self.source) or self.source[self.pos] != "'":
            self._lex_error(
                "E004", "Unterminated character literal",
                "add closing quote ' to terminate character literal",
                start_pos, max(1, self.pos - start_pos),
            )
            lexeme = self.source[start_pos + 1:self.pos]
        else:
            self.advance()  # skip closing '
            # Like string literals, character literals drop their quotes.
            lexeme = self.source[start_pos + 1:self.pos - 1]
        return self._make_token(TokenType.CHAR_LIT, lexeme, start_line, start_col, start_pos)

    def lex_operator_or_sep(self):
        char = self.source[self.pos]
        start_line, start_col, start_pos = self.line, self.col, self.pos
        nxt = self.peek()

        # Two-char operators
        two_char_ops = {
            '+=': TokenType.PLUS_ASSIGN, '-=': TokenType.MINUS_ASSIGN,
            '*=': TokenType.STAR_ASSIGN, '/=': TokenType.SLASH_ASSIGN,
            '%=': TokenType.MOD_ASSIGN, '++': TokenType.INCREMENT, '--': TokenType.DECREMENT,
            '==': TokenType.EQ, '!=': TokenType.NEQ,
            '<=': TokenType.LE, '>=': TokenType.GE,
            '&&': TokenType.AND, '||': TokenType.OR,
            '->': TokenType.ARROW, '::': TokenType.SCOPE,
            '<<': TokenType.SHL, '>>': TokenType.SHR
        }

        if char + nxt in two_char_ops:
            op = char + nxt
            self.advance()
            self.advance()
            return self._make_token(two_char_ops[op], op, start_line, start_col, start_pos)

        single_char_ops = {
            '+': TokenType.PLUS, '-': TokenType.MINUS,
            '*': TokenType.STAR, '/': TokenType.SLASH,
            '%': TokenType.MOD, '=': TokenType.ASSIGN,
            '<': TokenType.LT, '>': TokenType.GT,
            '!': TokenType.NOT, '(': TokenType.LPAREN,
            ')': TokenType.RPAREN, '{': TokenType.LBRACE,
            '}': TokenType.RBRACE, ';': TokenType.SEMICOLON,
            ',': TokenType.COMMA, '[': TokenType.LBRACKET,
            ']': TokenType.RBRACKET, ':': TokenType.COLON,
            '.': TokenType.DOT, '?': TokenType.QUESTION,
            '&': TokenType.AMP, '~': TokenType.TILDE,
            '|': TokenType.PIPE, '^': TokenType.CARET
        }

        if char in single_char_ops:
            self.advance()
            return self._make_token(single_char_ops[char], char, start_line, start_col, start_pos)

        return None
