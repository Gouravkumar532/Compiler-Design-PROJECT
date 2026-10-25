from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional, Set

from src.tokens import Token, TokenType


@dataclass
class DelimiterEntry:
    """Represents an active opening delimiter in the delimiter tracking stack."""
    type: TokenType
    lexeme: str
    line: int
    col: int
    indent: int
    scope_type: str = "block"  # "block", "paren", "class", "struct", "for", "if", etc.
    statement_count: int = 0
    pos: int = 0
    file: Optional[str] = None
    source_line: Optional[int] = None
    source_col: Optional[int] = None
    source_end_line: Optional[int] = None
    source_end_col: Optional[int] = None
    macro_generated: bool = False


STATEMENT_STARTERS: Set[TokenType] = {
    # Type keywords
    TokenType.INT,
    TokenType.FLOAT,
    TokenType.DOUBLE,
    TokenType.VOID,
    TokenType.CHAR,
    TokenType.BOOL,
    TokenType.AUTO,
    TokenType.STRUCT,
    TokenType.CLASS,
    TokenType.ENUM,
    TokenType.CONSTEXPR,
    TokenType.CONST,
    # Control flow keywords
    TokenType.IF,
    TokenType.ELSE,
    TokenType.WHILE,
    TokenType.DO,
    TokenType.FOR,
    TokenType.RETURN,
    TokenType.BREAK,
    TokenType.CONTINUE,
    TokenType.SWITCH,
    TokenType.CASE,
    TokenType.DEFAULT,
    TokenType.TRY,
    TokenType.CATCH,
    TokenType.THROW,
    TokenType.USING,
    TokenType.NAMESPACE,
    TokenType.DELETE,
    # Identifiers (can start variable declaration, assignment, or function call)
    TokenType.IDENTIFIER,
}


def compute_line_indents(source: str) -> Dict[int, int]:
    """Computes the indentation (leading spaces) for each line in the source."""
    indents = {}
    for idx, line in enumerate(source.splitlines(), start=1):
        expanded = line.expandtabs(4)
        indents[idx] = len(expanded) - len(expanded.lstrip(' '))
    return indents


class DelimiterRepairEngine:
    """
    Intelligent engine for detecting missing semicolons, unbalanced delimiters,
    and inferring missing closing braces based on indentation depth.
    """

    def __init__(self, source: str = "", filename: str = "<stdin>"):
        self.source = source
        self.filename = filename
        self.line_indents = compute_line_indents(source)

    def count_delimiters(self, tokens: List[Token]) -> Dict[str, int]:
        """Counts occurrences of opening and closing delimiters in tokens."""
        counts = {
            "{": 0, "}": 0,
            "(": 0, ")": 0,
            "[": 0, "]": 0
        }
        for tok in tokens:
            if tok.lexeme in counts:
                counts[tok.lexeme] += 1
        return counts

    def is_missing_semicolon(
        self,
        prev: Token,
        curr: Token,
        in_class_or_struct: bool = False,
        in_for_header: bool = False,
    ) -> Tuple[bool, str]:
        """
        Determines whether a semicolon is missing between prev and curr.
        Returns (True, context_description) if missing semicolon is inferred.
        """
        # 1. Right after class or struct definition closing brace '}'
        if in_class_or_struct:
            return True, "class or struct definition"

        # 2. Before closing brace '}' of a block: e.g. { int a = 10 } or { return x }
        if curr.type == TokenType.RBRACE:
            return True, "statement before '}'"

        # 3. Newline boundary between statements: e.g.
        #    int a = 10
        #    int b = 20;
        if curr.line > prev.line:
            return True, "statement"

        # 4. Same line statement starter: e.g.
        #    int a = 10 int b = 20;
        if curr.type in STATEMENT_STARTERS:
            return True, "statement"

        # 5. Inside for loop init clause: e.g.
        #    for (int i = 0 i < 10; i++)
        if in_for_header:
            return True, "loop header clause"

        # 6. Reached EOF while expecting semicolon
        if curr.type == TokenType.EOF:
            return True, "statement at end of file"

        return False, ""

    def is_missing_rparen_in_header(
        self,
        prev: Token,
        curr: Token,
        header_name: str = "condition"
    ) -> Tuple[bool, str]:
        """Backward compatible alias for is_missing_rparen."""
        return self.is_missing_rparen(prev, curr, context_name=header_name)

    def is_missing_rparen(
        self,
        prev: Token,
        curr: Token,
        context_name: str = "expression or call"
    ) -> Tuple[bool, str]:
        """
        Checks if a closing ')' was omitted in a header, parameter list, or function call.
        e.g., if (x > 10 { or foo(a, b; or compute(int x, int y {
        """
        # 1. Before opening brace '{' (e.g. in if/while/func header)
        if curr.type == TokenType.LBRACE:
            return True, f"before '{{' in {context_name}"

        # 2. Before semicolon ';' (e.g. foo(x, y; or return (x + y;)
        if curr.type == TokenType.SEMICOLON:
            return True, f"before ';' in {context_name}"

        # 3. On a new line
        if curr.line > prev.line:
            return True, f"in {context_name}"

        # 4. Before statement starter or block closer
        if curr.type in STATEMENT_STARTERS or curr.type == TokenType.RBRACE:
            return True, f"in {context_name}"

        return False, ""

    def is_missing_rbracket(
        self,
        prev: Token,
        curr: Token,
        context_name: str = "array index or bounds"
    ) -> Tuple[bool, str]:
        """
        Checks if a closing ']' was omitted.
        e.g., int arr[10; or x = arr[i;
        """
        if curr.type == TokenType.SEMICOLON:
            return True, f"before ';' in {context_name}"
        if curr.type in (TokenType.ASSIGN, TokenType.LBRACE, TokenType.RBRACE):
            return True, f"in {context_name}"
        if curr.line > prev.line or curr.type in STATEMENT_STARTERS:
            return True, f"in {context_name}"
        return False, ""

    def should_close_block_due_to_indentation(
        self,
        block_stack: List[DelimiterEntry],
        prev: Token,
        curr: Token,
        tokens: List[Token],
    ) -> Tuple[bool, Optional[DelimiterEntry]]:
        """
        Inspects indentation depth of statements following an inner block.
        If statement has de-indented to <= header indentation of the inner block,
        and there is a deficit of closing braces in the token stream, infer that
        the inner block should have been closed.
        """
        if not block_stack:
            return False, None

        current_block = block_stack[-1]

        # Do not trigger if current token is already a closing brace or EOF
        if curr.type in (TokenType.RBRACE, TokenType.EOF):
            return False, None

        # Check delimiter counts: are there unclosed braces?
        counts = self.count_delimiters(tokens)
        brace_deficit = counts["{"] - counts["}"]
        if brace_deficit <= 0:
            return False, None

        # If a block was opened in an included file and the token stream has moved
        # into a different physical file, the included file left this block unclosed.
        curr_file = getattr(curr, "file", None)
        if current_block.file and curr_file and current_block.file != curr_file:
            return True, current_block

        if len(block_stack) <= 1:
            return False, None

        if current_block.statement_count < 1:
            return False, None

        # Statement must be on a new line after the previous token
        if curr.line <= prev.line:
            return False, None

        # Indentation of current statement
        curr_indent = self.line_indents.get(curr.line, getattr(curr, 'indent', 0))

        # If curr_indent is <= current_block.indent and there is a brace deficit
        if curr_indent <= current_block.indent and brace_deficit > 0:
            return True, current_block

        return False, None
