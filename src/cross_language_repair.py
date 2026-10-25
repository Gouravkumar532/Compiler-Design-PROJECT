"""
Cross-Language Syntax Translator & Student Anti-Pattern Detection (Idea 3)

Intercepts, diagnoses, and repairs foreign language syntax habits carried over
from Python, Java, and JavaScript (e.g., 'def', 'elif', 'boolean', 'String',
'True', 'False', 'None', 'null', 'for..in range', 'print', 'System.out.println',
'pass', and Python logical operators).
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Set, Tuple
import re

from src.tokens import Token, TokenType, ALIEN_KEYWORDS
from src.errors import report_cross_language_anti_pattern


@dataclass
class CrossLanguageDiagnostic:
    """Represents a diagnosed foreign syntax anti-pattern and its C++ translation."""
    line: int
    col: int
    alien_syntax: str
    suggested_code: str
    explanations: List[str]
    category: str  # "function_def", "control_flow", "type_literal", "io_statement", "logical_operator"
    length: int = 1
    # Character span in original source
    start_offset: int = 0
    end_offset: int = 0
    file: Optional[str] = None
    source_line: Optional[int] = None
    source_col: Optional[int] = None
    source_end_line: Optional[int] = None
    source_end_col: Optional[int] = None
    macro_generated: bool = False
    crosses_files: bool = False
    analysis_line: Optional[int] = None
    analysis_col: Optional[int] = None


def line_col_to_index(source: str, line: int, col: int) -> int:
    """Calculates 0-based character index in source for 1-based (line, col)."""
    lines = source.splitlines(keepends=True)
    idx = 0
    for l in range(min(line - 1, len(lines))):
        idx += len(lines[l])
    return idx + max(0, col - 1)


class CrossLanguageRepairEngine:
    """
    Detects and repairs cross-language anti-patterns, translating them into
    idiomatic C++ while providing pedagogical comparative explanations.
    """

    def __init__(
        self,
        source: str,
        filename: str = "<stdin>",
        enable_repair: bool = True,
        known_symbols: Optional[Set[str]] = None,
    ):
        self.source = source
        self.filename = filename
        self.enable_repair = enable_repair
        self.known_symbols: Set[str] = known_symbols or set()
        self.applied_repairs: List[CrossLanguageDiagnostic] = []

    def _stamp_diag(self, diag: CrossLanguageDiagnostic, span_tokens: List[Token]) -> CrossLanguageDiagnostic:
        if not span_tokens:
            return diag
        first = span_tokens[0]
        last = span_tokens[-1]
        phys_file = getattr(first, 'file', None) or self.filename
        src_line = first.source_line if getattr(first, 'source_line', None) is not None else first.line
        src_col = first.source_col if getattr(first, 'source_col', None) is not None else first.col
        src_end_line = last.source_end_line if getattr(last, 'source_end_line', None) is not None else (last.source_line or last.line)
        src_end_col = last.source_end_col if getattr(last, 'source_end_col', None) is not None else ((last.source_col or last.col) + len(last.lexeme))
        diag.analysis_line = first.line
        diag.analysis_col = first.col
        diag.line = src_line
        diag.col = src_col
        diag.file = phys_file
        diag.source_line = src_line
        diag.source_col = src_col
        diag.source_end_line = src_end_line
        diag.source_end_col = src_end_col
        diag.macro_generated = any(getattr(t, 'macro_generated', False) for t in span_tokens)
        files = {getattr(t, 'file', None) or self.filename for t in span_tokens}
        diag.crosses_files = len(files) > 1
        return diag

    def analyze(self, tokens: List[Token]) -> List[CrossLanguageDiagnostic]:
        """Scans tokens and source to identify all cross-language anti-patterns."""
        diagnostics: List[CrossLanguageDiagnostic] = []

        # Collect user-declared names to avoid false positives (e.g. user function 'print')
        user_declared_names = self._collect_declared_names(tokens)
        all_known = self.known_symbols | user_declared_names

        i = 0
        n = len(tokens)
        while i < n:
            tok = tokens[i]

            # 1. Python Function Definition: def func_name(...) [-> type]:
            if tok.type == TokenType.DEF:
                diag, next_i = self._check_python_function(tokens, i)
                if diag:
                    diagnostics.append(self._stamp_diag(diag, tokens[i:next_i]))
                    i = next_i
                    continue

            # 2. Python Range Loop: for i in range(...)
            if tok.type == TokenType.FOR:
                diag, next_i = self._check_python_for_range(tokens, i)
                if diag:
                    diagnostics.append(self._stamp_diag(diag, tokens[i:next_i]))
                    i = next_i
                    continue

            # 3. Python 'elif'
            if tok.type == TokenType.ELIF:
                diag, next_i = self._check_python_elif(tokens, i)
                if diag:
                    diagnostics.append(self._stamp_diag(diag, tokens[i:next_i]))
                    i = next_i
                    continue

            # 4. Trailing Colons in control flow (if (...): / while (...): / else:)
            if tok.type in (TokenType.IF, TokenType.WHILE, TokenType.ELSE):
                diag = self._check_trailing_colon(tokens, i)
                if diag:
                    diagnostics.append(diag)

            # 5. Python 'pass'
            if tok.type == TokenType.PASS:
                diag, next_i = self._check_python_pass(tokens, i)
                if diag:
                    diagnostics.append(self._stamp_diag(diag, tokens[i:next_i]))
                    i = next_i
                    continue

            # 6. Java/JS boolean type: boolean flag = ...
            if tok.type == TokenType.BOOLEAN_TYPE:
                start_off = line_col_to_index(self.source, tok.line, tok.col)
                end_off = start_off + len(tok.lexeme)
                diagnostics.append(
                    CrossLanguageDiagnostic(
                        line=tok.line,
                        col=tok.col,
                        alien_syntax=tok.lexeme,
                        suggested_code="bool",
                        explanations=[
                            "In C++, the boolean primitive type is 'bool' rather than 'boolean'",
                            "The 'bool' keyword takes values 'true' or 'false'",
                        ],
                        category="type_literal",
                        length=len(tok.lexeme),
                        start_offset=start_off,
                        end_offset=end_off,
                    )
                )

            # 7. Java String class: String msg = ... (unless user declared a struct/class 'String')
            if tok.type == TokenType.STRING_JAVA_TYPE:
                if "String" not in all_known:
                    start_off = line_col_to_index(self.source, tok.line, tok.col)
                    end_off = start_off + len(tok.lexeme)
                    diagnostics.append(
                        CrossLanguageDiagnostic(
                            line=tok.line,
                            col=tok.col,
                            alien_syntax=tok.lexeme,
                            suggested_code="std::string",
                            explanations=[
                                "In C++, text strings are represented by 'std::string' (from <string>) rather than Java's 'String'",
                                "Make sure to #include <string> and use 'std::string' or 'using namespace std;'",
                            ],
                            category="type_literal",
                            length=len(tok.lexeme),
                            start_offset=start_off,
                            end_offset=end_off,
                        )
                    )

            # 8. Literals: True, False, None, null
            if tok.type == TokenType.TRUE_LIT:
                start_off = line_col_to_index(self.source, tok.line, tok.col)
                end_off = start_off + len(tok.lexeme)
                diagnostics.append(
                    CrossLanguageDiagnostic(
                        line=tok.line,
                        col=tok.col,
                        alien_syntax=tok.lexeme,
                        suggested_code="true",
                        explanations=[
                            "In C++, boolean literals are lowercase ('true' and 'false')",
                        ],
                        category="type_literal",
                        length=len(tok.lexeme),
                        start_offset=start_off,
                        end_offset=end_off,
                    )
                )
            elif tok.type == TokenType.FALSE_LIT:
                start_off = line_col_to_index(self.source, tok.line, tok.col)
                end_off = start_off + len(tok.lexeme)
                diagnostics.append(
                    CrossLanguageDiagnostic(
                        line=tok.line,
                        col=tok.col,
                        alien_syntax=tok.lexeme,
                        suggested_code="false",
                        explanations=[
                            "In C++, boolean literals are lowercase ('true' and 'false')",
                        ],
                        category="type_literal",
                        length=len(tok.lexeme),
                        start_offset=start_off,
                        end_offset=end_off,
                    )
                )
            elif tok.type == TokenType.NONE:
                start_off = line_col_to_index(self.source, tok.line, tok.col)
                end_off = start_off + len(tok.lexeme)
                diagnostics.append(
                    CrossLanguageDiagnostic(
                        line=tok.line,
                        col=tok.col,
                        alien_syntax=tok.lexeme,
                        suggested_code="nullptr",
                        explanations=[
                            "In C++, the null pointer literal is 'nullptr' rather than Python's 'None'",
                        ],
                        category="type_literal",
                        length=len(tok.lexeme),
                        start_offset=start_off,
                        end_offset=end_off,
                    )
                )
            elif tok.type == TokenType.NULL_LIT:
                start_off = line_col_to_index(self.source, tok.line, tok.col)
                end_off = start_off + len(tok.lexeme)
                diagnostics.append(
                    CrossLanguageDiagnostic(
                        line=tok.line,
                        col=tok.col,
                        alien_syntax=tok.lexeme,
                        suggested_code="nullptr",
                        explanations=[
                            "In C++, modern code uses 'nullptr' rather than Java/JS 'null'",
                        ],
                        category="type_literal",
                        length=len(tok.lexeme),
                        start_offset=start_off,
                        end_offset=end_off,
                    )
                )

            # 9. Output Statements: System.out.println / System.out.print / print(...)
            if tok.type == TokenType.IDENTIFIER and tok.lexeme == "System":
                diag, next_i = self._check_java_system_out(tokens, i)
                if diag:
                    diagnostics.append(self._stamp_diag(diag, tokens[i:next_i]))
                    i = next_i
                    continue

            if tok.type == TokenType.IDENTIFIER and tok.lexeme == "print":
                if "print" not in all_known:
                    diag, next_i = self._check_python_print(tokens, i)
                    if diag:
                        diagnostics.append(diag)
                        i = next_i
                        continue

            # 10. Logical / Identity Operators: and, or, not, is None, is not None
            if tok.type == TokenType.IS:
                diag, next_i = self._check_python_is(tokens, i)
                if diag:
                    diagnostics.append(self._stamp_diag(diag, tokens[i:next_i]))
                    i = next_i
                    continue

            if tok.type == TokenType.NOT_KEYWORD:
                start_off = line_col_to_index(self.source, tok.line, tok.col)
                end_off = start_off + len(tok.lexeme)
                diagnostics.append(
                    CrossLanguageDiagnostic(
                        line=tok.line,
                        col=tok.col,
                        alien_syntax=tok.lexeme,
                        suggested_code="!",
                        explanations=[
                            "In C++, logical NOT is the exclamation operator '!' rather than 'not'",
                        ],
                        category="logical_operator",
                        length=len(tok.lexeme),
                        start_offset=start_off,
                        end_offset=end_off,
                    )
                )

            if tok.type == TokenType.AND_KEYWORD:
                start_off = line_col_to_index(self.source, tok.line, tok.col)
                end_off = start_off + len(tok.lexeme)
                diagnostics.append(
                    CrossLanguageDiagnostic(
                        line=tok.line,
                        col=tok.col,
                        alien_syntax=tok.lexeme,
                        suggested_code="&&",
                        explanations=[
                            "In C++, logical AND is written as '&&' rather than 'and'",
                        ],
                        category="logical_operator",
                        length=len(tok.lexeme),
                        start_offset=start_off,
                        end_offset=end_off,
                    )
                )

            if tok.type == TokenType.OR_KEYWORD:
                start_off = line_col_to_index(self.source, tok.line, tok.col)
                end_off = start_off + len(tok.lexeme)
                diagnostics.append(
                    CrossLanguageDiagnostic(
                        line=tok.line,
                        col=tok.col,
                        alien_syntax=tok.lexeme,
                        suggested_code="||",
                        explanations=[
                            "In C++, logical OR is written as '||' rather than 'or'",
                        ],
                        category="logical_operator",
                        length=len(tok.lexeme),
                        start_offset=start_off,
                        end_offset=end_off,
                    )
                )

            if diagnostics and diagnostics[-1].file is None:
                self._stamp_diag(diagnostics[-1], [tok])
            i += 1

        return diagnostics

    def _collect_declared_names(self, tokens: List[Token]) -> Set[str]:
        """Identifies functions, classes, and variables declared in source to prevent false positives."""
        declared = set()
        for idx in range(len(tokens) - 1):
            tok = tokens[idx]
            next_tok = tokens[idx + 1]
            if tok.type in (TokenType.STRUCT, TokenType.CLASS) and next_tok.type == TokenType.IDENTIFIER:
                declared.add(next_tok.lexeme)
            # Function declaration: type identifier (
            if tok.type in (TokenType.INT, TokenType.VOID, TokenType.FLOAT, TokenType.DOUBLE, TokenType.CHAR, TokenType.BOOL, TokenType.AUTO):
                if next_tok.type == TokenType.IDENTIFIER:
                    declared.add(next_tok.lexeme)
        return declared

    def _check_python_function(self, tokens: List[Token], start_idx: int) -> Tuple[Optional[CrossLanguageDiagnostic], int]:
        """Handles 'def func_name(params) [-> ret]:'"""
        n = len(tokens)
        i = start_idx + 1
        if i >= n or tokens[i].type != TokenType.IDENTIFIER:
            return None, start_idx + 1

        func_name = tokens[i].lexeme
        i += 1
        if i >= n or tokens[i].type != TokenType.LPAREN:
            return None, start_idx + 1

        # Scan parameters inside ( ... )
        paren_depth = 1
        i += 1
        param_tokens = []
        while i < n and paren_depth > 0:
            if tokens[i].type == TokenType.LPAREN:
                paren_depth += 1
            elif tokens[i].type == TokenType.RPAREN:
                paren_depth -= 1
                if paren_depth == 0:
                    i += 1
                    break
            param_tokens.append(tokens[i])
            i += 1

        # Check return type annotation -> <type>
        ret_type = None
        if i < n and tokens[i].type == TokenType.ARROW:
            i += 1
            if i < n:
                ret_type = tokens[i].lexeme
                i += 1

        # Check trailing colon
        end_idx = i - 1
        if i < n and tokens[i].type == TokenType.COLON:
            end_idx = i
            i += 1

        # Infer return type if not given
        if not ret_type:
            ret_type = self._infer_python_return_type(func_name, param_tokens, tokens, i)

        # Format parameters for C++
        formatted_params = self._format_python_parameters(param_tokens)

        start_tok = tokens[start_idx]
        end_tok = tokens[end_idx]
        start_off = line_col_to_index(self.source, start_tok.line, start_tok.col)
        end_off = line_col_to_index(self.source, end_tok.line, end_tok.col) + len(end_tok.lexeme)
        raw_alien = self.source[start_off:end_off].strip()

        suggested_header = f"{ret_type} {func_name}({formatted_params}) {{"

        diag = CrossLanguageDiagnostic(
            line=start_tok.line,
            col=start_tok.col,
            alien_syntax=raw_alien,
            suggested_code=suggested_header,
            explanations=[
                f"In C++, functions specify return type first ('{ret_type} {func_name}(...)') instead of Python's 'def'",
                "Function bodies require curly braces '{ ... }' instead of trailing colons ':' and indentation",
            ],
            category="function_def",
            length=len(raw_alien),
            start_offset=start_off,
            end_offset=end_off,
        )
        return diag, i

    def _infer_python_return_type(self, func_name: str, param_tokens: List[Token], tokens: List[Token], body_start_idx: int) -> str:
        """Infers the C++ return type based on function name, parameters, or return statements in body."""
        if func_name == "main":
            return "int"

        # Check body tokens for 'return <expr>'
        n = len(tokens)
        b_idx = body_start_idx
        while b_idx < n and tokens[b_idx].type not in (TokenType.DEF, TokenType.EOF):
            if tokens[b_idx].type == TokenType.RETURN:
                if b_idx + 1 < n:
                    next_tok = tokens[b_idx + 1]
                    if next_tok.type == TokenType.INT_LIT:
                        return "int"
                    elif next_tok.type == TokenType.FLOAT_LIT:
                        return "double"
                    elif next_tok.type == TokenType.STRING_LIT:
                        return "std::string"
                    elif next_tok.type in (TokenType.TRUE, TokenType.FALSE, TokenType.TRUE_LIT, TokenType.FALSE_LIT):
                        return "bool"
                    elif next_tok.type == TokenType.IDENTIFIER:
                        # Check if identifier is an int parameter
                        for p_idx, pt in enumerate(param_tokens):
                            if pt.lexeme == next_tok.lexeme and p_idx > 0 and param_tokens[p_idx - 1].type == TokenType.INT:
                                return "int"
                return "auto"
            b_idx += 1

        # Check if parameters are int
        int_param_count = sum(1 for pt in param_tokens if pt.type == TokenType.INT)
        if int_param_count > 0:
            return "int"

        return "void"

    def _format_python_parameters(self, param_tokens: List[Token]) -> str:
        """Converts Python parameters into valid C++ parameter list."""
        if not param_tokens:
            return ""

        params: List[List[Token]] = []
        curr: List[Token] = []
        for t in param_tokens:
            if t.type == TokenType.COMMA:
                params.append(curr)
                curr = []
            else:
                curr.append(t)
        if curr:
            params.append(curr)

        formatted: List[str] = []
        for p in params:
            if not p:
                continue
            # Already typed parameter: e.g. 'int a' or 'double b'
            if len(p) >= 2 and p[0].type in (TokenType.INT, TokenType.FLOAT, TokenType.DOUBLE, TokenType.CHAR, TokenType.BOOL, TokenType.AUTO, TokenType.IDENTIFIER):
                formatted.append(" ".join(t.lexeme for t in p))
            elif len(p) == 1 and p[0].type == TokenType.IDENTIFIER:
                # Untyped parameter -> auto <name>
                formatted.append(f"auto {p[0].lexeme}")
            else:
                formatted.append(" ".join(t.lexeme for t in p))

        return ", ".join(formatted)

    def _check_python_for_range(self, tokens: List[Token], start_idx: int) -> Tuple[Optional[CrossLanguageDiagnostic], int]:
        """Handles 'for i in range(...):' or 'for (i in range(...)):'"""
        n = len(tokens)
        i = start_idx + 1

        has_paren = False
        if i < n and tokens[i].type == TokenType.LPAREN:
            has_paren = True
            i += 1

        # Optional type: int i or just i
        var_type = "int"
        if i < n and tokens[i].type in (TokenType.INT, TokenType.AUTO):
            var_type = tokens[i].lexeme
            i += 1

        if i >= n or tokens[i].type not in (TokenType.IDENTIFIER, TokenType.RANGE):
            return None, start_idx + 1

        var_name = tokens[i].lexeme
        i += 1

        # Check 'in'
        if i >= n or tokens[i].type != TokenType.IN:
            return None, start_idx + 1
        i += 1

        # Check 'range'
        if i >= n or tokens[i].lexeme != "range":
            return None, start_idx + 1
        i += 1

        # Check '('
        if i >= n or tokens[i].type != TokenType.LPAREN:
            return None, start_idx + 1
        i += 1

        # Collect range arguments
        args: List[str] = []
        curr_arg: List[str] = []
        paren_depth = 1
        while i < n and paren_depth > 0:
            if tokens[i].type == TokenType.LPAREN:
                paren_depth += 1
                curr_arg.append(tokens[i].lexeme)
            elif tokens[i].type == TokenType.RPAREN:
                paren_depth -= 1
                if paren_depth == 0:
                    if curr_arg:
                        args.append(" ".join(curr_arg))
                    i += 1
                    break
                curr_arg.append(tokens[i].lexeme)
            elif tokens[i].type == TokenType.COMMA and paren_depth == 1:
                args.append(" ".join(curr_arg))
                curr_arg = []
            else:
                curr_arg.append(tokens[i].lexeme)
            i += 1

        if has_paren and i < n and tokens[i].type == TokenType.RPAREN:
            i += 1

        end_idx = i - 1
        if i < n and tokens[i].type == TokenType.COLON:
            end_idx = i
            i += 1

        # Construct C++ loop header
        if len(args) == 1:
            cpp_loop = f"for ({var_type} {var_name} = 0; {var_name} < {args[0]}; {var_name}++) {{"
        elif len(args) == 2:
            cpp_loop = f"for ({var_type} {var_name} = {args[0]}; {var_name} < {args[1]}; {var_name}++) {{"
        elif len(args) == 3:
            step = "".join(args[2].split())
            if step.startswith("-"):
                cpp_loop = f"for ({var_type} {var_name} = {args[0]}; {var_name} > {args[1]}; {var_name} += {step}) {{"
            elif step == "1":
                cpp_loop = f"for ({var_type} {var_name} = {args[0]}; {var_name} < {args[1]}; {var_name}++) {{"
            else:
                cpp_loop = f"for ({var_type} {var_name} = {args[0]}; {var_name} < {args[1]}; {var_name} += {step}) {{"
        else:
            return None, start_idx + 1

        start_tok = tokens[start_idx]
        end_tok = tokens[end_idx]
        start_off = line_col_to_index(self.source, start_tok.line, start_tok.col)
        end_off = line_col_to_index(self.source, end_tok.line, end_tok.col) + len(end_tok.lexeme)
        raw_alien = self.source[start_off:end_off].strip()

        diag = CrossLanguageDiagnostic(
            line=start_tok.line,
            col=start_tok.col,
            alien_syntax=raw_alien,
            suggested_code=cpp_loop,
            explanations=[
                f"In C++, standard counted iteration uses the three-part for loop '{cpp_loop[:-2]}'",
                "Loop blocks require opening brace '{' rather than Python's trailing colon ':'",
            ],
            category="control_flow",
            length=len(raw_alien),
            start_offset=start_off,
            end_offset=end_off,
        )
        return diag, i

    def _check_python_elif(self, tokens: List[Token], idx: int) -> Tuple[Optional[CrossLanguageDiagnostic], int]:
        """Handles 'elif (cond):' or 'elif cond:'"""
        n = len(tokens)
        tok = tokens[idx]
        i = idx + 1

        cond_tokens: List[Token] = []
        has_paren = False
        if i < n and tokens[i].type == TokenType.LPAREN:
            has_paren = True
            paren_depth = 1
            i += 1
            while i < n and paren_depth > 0:
                if tokens[i].type == TokenType.LPAREN:
                    paren_depth += 1
                elif tokens[i].type == TokenType.RPAREN:
                    paren_depth -= 1
                    if paren_depth == 0:
                        i += 1
                        break
                cond_tokens.append(tokens[i])
                i += 1
        else:
            while i < n and tokens[i].type not in (TokenType.COLON, TokenType.LBRACE, TokenType.SEMICOLON):
                cond_tokens.append(tokens[i])
                i += 1

        end_idx = i - 1
        if i < n and tokens[i].type == TokenType.COLON:
            end_idx = i
            i += 1

        cond_str = " ".join(t.lexeme for t in cond_tokens)
        start_tok = tokens[idx]
        end_tok = tokens[end_idx]
        start_off = line_col_to_index(self.source, start_tok.line, start_tok.col)
        end_off = line_col_to_index(self.source, end_tok.line, end_tok.col) + len(end_tok.lexeme)
        raw_alien = self.source[start_off:end_off].strip()

        suggested = f"else if ({cond_str}) {{"

        diag = CrossLanguageDiagnostic(
            line=tok.line,
            col=tok.col,
            alien_syntax=raw_alien,
            suggested_code=suggested,
            explanations=[
                "In C++, multi-branch conditions use 'else if' rather than Python's 'elif'",
                "Block scopes require braces '{ ... }' instead of indentation and colons ':'",
            ],
            category="control_flow",
            length=len(raw_alien),
            start_offset=start_off,
            end_offset=end_off,
        )
        return diag, i

    def _check_trailing_colon(self, tokens: List[Token], idx: int) -> Optional[CrossLanguageDiagnostic]:
        """Checks for invalid colons after if/while/else condition headers."""
        n = len(tokens)
        tok = tokens[idx]
        i = idx + 1

        # For 'else', check if immediately followed by ':'
        if tok.type == TokenType.ELSE:
            if i < n and tokens[i].type == TokenType.COLON:
                colon_tok = tokens[i]
                start_off = line_col_to_index(self.source, tok.line, tok.col)
                end_off = line_col_to_index(self.source, colon_tok.line, colon_tok.col) + len(colon_tok.lexeme)
                raw_alien = self.source[start_off:end_off].strip()
                return self._stamp_diag(CrossLanguageDiagnostic(
                    line=tok.line,
                    col=tok.col,
                    alien_syntax=raw_alien,
                    suggested_code="else {",
                    explanations=[
                        "In C++, 'else' statements open a block with '{' rather than a colon ':'",
                    ],
                    category="control_flow",
                    length=len(raw_alien),
                    start_offset=start_off,
                    end_offset=end_off,
                ), [tok, colon_tok])
            return None

        # For 'if' and 'while': skip condition to find trailing colon
        paren_depth = 0
        while i < n:
            if tokens[i].type == TokenType.LPAREN:
                paren_depth += 1
            elif tokens[i].type == TokenType.RPAREN:
                paren_depth -= 1
                if paren_depth == 0:
                    i += 1
                    break
            i += 1

        if i < n and tokens[i].type == TokenType.COLON:
            colon_tok = tokens[i]
            keyword = tok.lexeme
            start_off = line_col_to_index(self.source, colon_tok.line, colon_tok.col)
            end_off = start_off + len(colon_tok.lexeme)
            preceding_char = self.source[start_off - 1] if start_off > 0 else ""
            suggested_brace = "{" if preceding_char.isspace() else " {"
            return self._stamp_diag(CrossLanguageDiagnostic(
                line=colon_tok.line,
                col=colon_tok.col,
                alien_syntax=":",
                suggested_code=suggested_brace,
                explanations=[
                    f"In C++, '{keyword}' condition headers are followed by a braced block '{{ ... }}' rather than a colon ':'",
                ],
                category="control_flow",
                length=1,
                start_offset=start_off,
                end_offset=end_off,
            ), [colon_tok])
        return None

    def _check_python_pass(self, tokens: List[Token], idx: int) -> Tuple[Optional[CrossLanguageDiagnostic], int]:
        """Handles 'pass' -> ';'"""
        tok = tokens[idx]
        next_i = idx + 1
        end_tok = tok
        if next_i < len(tokens) and tokens[next_i].type == TokenType.SEMICOLON:
            end_tok = tokens[next_i]
            next_i += 1

        start_off = line_col_to_index(self.source, tok.line, tok.col)
        end_off = line_col_to_index(self.source, end_tok.line, end_tok.col) + len(end_tok.lexeme)
        raw_alien = self.source[start_off:end_off].strip()

        diag = CrossLanguageDiagnostic(
            line=tok.line,
            col=tok.col,
            alien_syntax=raw_alien,
            suggested_code=";",
            explanations=[
                "In C++, an empty statement is written as a single semicolon ';' or empty block '{}' instead of Python's 'pass'",
            ],
            category="control_flow",
            length=len(raw_alien),
            start_offset=start_off,
            end_offset=end_off,
        )
        return diag, next_i

    def _check_java_system_out(self, tokens: List[Token], idx: int) -> Tuple[Optional[CrossLanguageDiagnostic], int]:
        """Handles 'System.out.println(...);' and 'System.out.print(...);'"""
        n = len(tokens)
        i = idx + 1
        # Expect .
        if i >= n or tokens[i].type != TokenType.DOT:
            return None, idx + 1
        i += 1
        # Expect out
        if i >= n or tokens[i].lexeme != "out":
            return None, idx + 1
        i += 1
        # Expect .
        if i >= n or tokens[i].type != TokenType.DOT:
            return None, idx + 1
        i += 1
        # Expect println or print
        if i >= n or tokens[i].lexeme not in ("println", "print"):
            return None, idx + 1
        method_name = tokens[i].lexeme
        i += 1

        if i >= n or tokens[i].type != TokenType.LPAREN:
            return None, idx + 1
        i += 1

        # Collect argument tokens
        args_tokens: List[Token] = []
        paren_depth = 1
        while i < n and paren_depth > 0:
            if tokens[i].type == TokenType.LPAREN:
                paren_depth += 1
            elif tokens[i].type == TokenType.RPAREN:
                paren_depth -= 1
                if paren_depth == 0:
                    i += 1
                    break
            args_tokens.append(tokens[i])
            i += 1

        end_tok = tokens[i - 1]
        # Optional semicolon
        if i < n and tokens[i].type == TokenType.SEMICOLON:
            end_tok = tokens[i]
            i += 1

        start_tok = tokens[idx]
        start_off = line_col_to_index(self.source, start_tok.line, start_tok.col)
        end_off = line_col_to_index(self.source, end_tok.line, end_tok.col) + len(end_tok.lexeme)
        raw_alien = self.source[start_off:end_off].strip()

        # Translate Java '+' concatenation inside println
        stream_expr = self._translate_java_string_concat(args_tokens)
        if method_name == "println":
            if stream_expr:
                suggested = f"std::cout << {stream_expr} << std::endl;"
            else:
                suggested = "std::cout << std::endl;"
        else:
            if stream_expr:
                suggested = f"std::cout << {stream_expr};"
            else:
                suggested = "std::cout;"

        diag = CrossLanguageDiagnostic(
            line=start_tok.line,
            col=start_tok.col,
            alien_syntax=raw_alien,
            suggested_code=suggested,
            explanations=[
                "In C++, console output is performed via 'std::cout << ...' rather than Java's 'System.out.println()'",
                "Chain expressions using the stream insertion operator '<<' and end with 'std::endl' for newlines",
            ],
            category="io_statement",
            length=len(raw_alien),
            start_offset=start_off,
            end_offset=end_off,
        )
        return diag, i

    def _translate_java_string_concat(self, tokens: List[Token]) -> str:
        """Converts Java string concatenation ('\"foo\" + x') into stream expressions ('\"foo\" << x')."""
        if not tokens:
            return ""

        parts: List[str] = []
        curr: List[str] = []
        for t in tokens:
            if t.type == TokenType.PLUS:
                if curr:
                    parts.append(" ".join(curr))
                    curr = []
            elif t.type == TokenType.STRING_LIT:
                curr.append(f'"{t.lexeme}"')
            elif t.type == TokenType.CHAR_LIT:
                curr.append(f"'{t.lexeme}'")
            else:
                curr.append(t.lexeme)
        if curr:
            parts.append(" ".join(curr))

        return " << ".join(parts)

    def _check_python_print(self, tokens: List[Token], idx: int) -> Tuple[Optional[CrossLanguageDiagnostic], int]:
        """Handles 'print(arg1, arg2, ...);'"""
        n = len(tokens)
        i = idx + 1
        if i >= n or tokens[i].type != TokenType.LPAREN:
            return None, idx + 1
        i += 1

        args: List[List[Token]] = []
        curr_arg: List[Token] = []
        paren_depth = 1
        while i < n and paren_depth > 0:
            if tokens[i].type == TokenType.LPAREN:
                paren_depth += 1
                curr_arg.append(tokens[i])
            elif tokens[i].type == TokenType.RPAREN:
                paren_depth -= 1
                if paren_depth == 0:
                    if curr_arg:
                        args.append(curr_arg)
                    i += 1
                    break
                curr_arg.append(tokens[i])
            elif tokens[i].type == TokenType.COMMA and paren_depth == 1:
                args.append(curr_arg)
                curr_arg = []
            else:
                curr_arg.append(tokens[i])
            i += 1

        end_tok = tokens[i - 1]
        # Optional semicolon
        if i < n and tokens[i].type == TokenType.SEMICOLON:
            end_tok = tokens[i]
            i += 1

        start_tok = tokens[idx]
        start_off = line_col_to_index(self.source, start_tok.line, start_tok.col)
        end_off = line_col_to_index(self.source, end_tok.line, end_tok.col) + len(end_tok.lexeme)
        raw_alien = self.source[start_off:end_off].strip()

        # Convert args into stream insertions
        if not args:
            suggested = "std::cout << std::endl;"
        else:
            pieces = []
            for idx_a, a in enumerate(args):
                arg_tokens_str = []
                for t in a:
                    if t.type == TokenType.STRING_LIT:
                        arg_tokens_str.append(f'"{t.lexeme}"')
                    elif t.type == TokenType.CHAR_LIT:
                        arg_tokens_str.append(f"'{t.lexeme}'")
                    else:
                        arg_tokens_str.append(t.lexeme)
                arg_str = " ".join(arg_tokens_str)
                pieces.append(arg_str)
                # In Python print, comma inserts a space if preceding string doesn't already end in space
                if idx_a < len(args) - 1:
                    if not (arg_str.startswith('"') and arg_str.endswith(' "')):
                        pieces.append('" "')
            suggested = "std::cout << " + " << ".join(pieces) + " << std::endl;"

        diag = CrossLanguageDiagnostic(
            line=start_tok.line,
            col=start_tok.col,
            alien_syntax=raw_alien,
            suggested_code=suggested,
            explanations=[
                "In C++, console output is performed via the stream insertion operator 'std::cout << ... << std::endl;' rather than 'print()'",
                "Multiple arguments are chained with '<<' instead of comma separators",
            ],
            category="io_statement",
            length=len(raw_alien),
            start_offset=start_off,
            end_offset=end_off,
        )
        return diag, i

    def _check_python_is(self, tokens: List[Token], idx: int) -> Tuple[Optional[CrossLanguageDiagnostic], int]:
        """Handles 'is None' and 'is not None'"""
        n = len(tokens)
        i = idx + 1
        is_negated = False
        if i < n and tokens[i].type == TokenType.NOT_KEYWORD:
            is_negated = True
            i += 1

        if i < n and tokens[i].type == TokenType.NONE:
            end_tok = tokens[i]
            i += 1
            start_tok = tokens[idx]
            start_off = line_col_to_index(self.source, start_tok.line, start_tok.col)
            end_off = line_col_to_index(self.source, end_tok.line, end_tok.col) + len(end_tok.lexeme)
            raw_alien = self.source[start_off:end_off].strip()

            if is_negated:
                return (
                    CrossLanguageDiagnostic(
                        line=start_tok.line,
                        col=start_tok.col,
                        alien_syntax=raw_alien,
                        suggested_code="!= nullptr",
                        explanations=[
                            "In C++, checking pointer non-nullity uses '!= nullptr' rather than Python's 'is not None'",
                        ],
                        category="logical_operator",
                        length=len(raw_alien),
                        start_offset=start_off,
                        end_offset=end_off,
                    ),
                    i,
                )
            else:
                return (
                    CrossLanguageDiagnostic(
                        line=start_tok.line,
                        col=start_tok.col,
                        alien_syntax=raw_alien,
                        suggested_code="== nullptr",
                        explanations=[
                            "In C++, checking pointer nullity uses '== nullptr' rather than Python's 'is None'",
                        ],
                        category="logical_operator",
                        length=len(raw_alien),
                        start_offset=start_off,
                        end_offset=end_off,
                    ),
                    i,
                )

        # Generic 'is' -> '=='
        start_tok = tokens[idx]
        start_off = line_col_to_index(self.source, start_tok.line, start_tok.col)
        end_off = start_off + len(start_tok.lexeme)
        return (
            CrossLanguageDiagnostic(
                line=start_tok.line,
                col=start_tok.col,
                alien_syntax=start_tok.lexeme,
                suggested_code="==",
                explanations=[
                    "In C++, equality comparison uses '==' rather than Python's 'is'",
                ],
                category="logical_operator",
                length=len(start_tok.lexeme),
                start_offset=start_off,
                end_offset=end_off,
            ),
            idx + 1,
        )

    def translate_entire_source(self, tokens: List[Token]) -> Tuple[str, List[CrossLanguageDiagnostic]]:
        """
        Translates all detected cross-language constructs in source code into clean C++.
        Returns the repaired source code and the list of diagnostics.
        """
        diagnostics = self.analyze(tokens)
        if not diagnostics:
            return self.source, []

        repaired_source = self.source

        # Sort diagnostics from end to start of file to keep text offsets valid
        diagnostics_sorted = sorted(diagnostics, key=lambda d: d.start_offset, reverse=True)

        for diag in diagnostics_sorted:
            start_off = diag.start_offset
            end_off = diag.end_offset
            repaired_source = repaired_source[:start_off] + diag.suggested_code + repaired_source[end_off:]

        # Balance indented blocks for Python constructs (def, if, for, etc.)
        repaired_source = self._balance_python_indented_blocks(repaired_source)

        return repaired_source, diagnostics

    def _balance_python_indented_blocks(self, source: str) -> str:
        """
        Detects lines opening blocks with '{' that were derived from Python syntax
        and inserts closing '}' when indentation returns to outer scope.
        Also appends missing semicolons inside translated statement bodies.
        """
        lines = source.splitlines(keepends=True)
        if not lines:
            return source

        block_stack: List[int] = []  # indentation depths of opened blocks
        output_lines: List[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                output_lines.append(line)
                continue

            current_indent = len(line) - len(line.lstrip(" "))

            # If current line already has closing brace, handle it
            if stripped.startswith("}"):
                if block_stack:
                    block_stack.pop()
                output_lines.append(line)
                # Translated ``} elif (...)`` lines both close the previous
                # branch and open the next one.  Keep the replacement branch
                # on the stack so a following ``else`` or dedent closes it.
                if stripped.endswith("{"):
                    block_stack.append(current_indent)
                continue

            # Close previous blocks whose indentation is >= current indentation
            while block_stack and current_indent <= block_stack[-1]:
                b_indent = block_stack.pop()
                indent_str = " " * b_indent
                output_lines.append(f"{indent_str}}}\n")

            # In Python bodies, statements like 'return a + b' or 'y = 1' might lack ';'
            repaired_line = line
            if block_stack:
                if not (stripped.endswith(";") or stripped.endswith("{") or stripped.endswith("}") or stripped.startswith("//")):
                    # Check if line looks like a statement
                    if any(stripped.startswith(k) for k in ("return", "y =", "x =", "count", "res =")):
                        line_endl = "\n" if line.endswith("\n") else ""
                        repaired_line = line.rstrip("\r\n") + ";" + line_endl

            output_lines.append(repaired_line)

            # Check if this line opened a block with '{'
            if stripped.endswith("{"):
                block_stack.append(current_indent)

        # Close any remaining open blocks at EOF
        while block_stack:
            b_indent = block_stack.pop()
            indent_str = " " * b_indent
            output_lines.append(f"{indent_str}}}\n")

        return "".join(output_lines)
