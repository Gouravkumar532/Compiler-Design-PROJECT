from dataclasses import dataclass, field
from typing import List, Set, Optional, Tuple, Any
from copy import deepcopy

from src.tokens import Token, TokenType
from src.ast_nodes import Expression


@dataclass
class RepairSuggestion:
    repaired_tokens: List[Token]
    repaired_code: str
    explanation: List[str]
    ast_node: Optional[Any] = None
    edit_distance: int = 0


def tokens_to_code(tokens: List[Token]) -> str:
    """Format a list of tokens into clean C++ expression code."""
    res = []
    for i, tok in enumerate(tokens):
        if i > 0:
            prev = tokens[i - 1]
            # No space before closing delimiter
            if tok.lexeme in (")", "]", ",", ";"):
                pass
            # No space after opening delimiter
            elif prev.lexeme in ("(", "["):
                pass
            # No space between member access operators
            elif tok.lexeme in (".", "->") or prev.lexeme in (".", "->"):
                pass
            else:
                res.append(" ")
        res.append(tok.lexeme)
    return "".join(res)


def find_symbol_partition(name: str, symbols: Set[str]) -> Optional[List[str]]:
    """
    Partitions `name` into 2 or more substrings that all belong to `symbols`.
    Returns the partition with the fewest components, or None if no valid partition exists.
    """
    if len(name) < 2 or not symbols:
        return None

    memo = {}

    def search(start: int) -> Optional[List[str]]:
        if start == len(name):
            return []
        if start in memo:
            return memo[start]

        best = None
        for end in range(start + 1, len(name) + 1):
            sub = name[start:end]
            if sub in symbols:
                sub_res = search(end)
                if sub_res is not None:
                    candidate = [sub] + sub_res
                    if best is None or len(candidate) < len(best):
                        best = candidate

        memo[start] = best
        return best

    res = search(0)
    if res and len(res) >= 2:
        return res
    return None


def is_operand_token(tok: Token) -> bool:
    """Returns True if the token represents a value/operand."""
    return tok.type in (
        TokenType.IDENTIFIER,
        TokenType.INT_LIT,
        TokenType.FLOAT_LIT,
        TokenType.STRING_LIT,
        TokenType.CHAR_LIT,
        TokenType.TRUE,
        TokenType.FALSE,
    )


def is_binary_op_token(tok: Token) -> bool:
    """Returns True if the token is a standard binary arithmetic/comparison/bitwise operator."""
    return tok.type in (
        TokenType.PLUS,
        TokenType.MINUS,
        TokenType.STAR,
        TokenType.SLASH,
        TokenType.MOD,
        TokenType.SHL,
        TokenType.SHR,
        TokenType.AMP,
        TokenType.PIPE,
        TokenType.CARET,
        TokenType.EQ,
        TokenType.NEQ,
        TokenType.LT,
        TokenType.GT,
        TokenType.LE,
        TokenType.GE,
        TokenType.AND,
        TokenType.OR,
    )


class ExpressionRepairEngine:
    """
    Intelligent expression auto-correction and repair engine.
    Diagnoses malformed expressions, decomposes undeclared multi-character identifiers,
    relocates misplaced operators, balances delimiters, and validates candidate repairs.
    """

    EXPR_DELIMITERS = {
        TokenType.SEMICOLON,
        TokenType.COMMA,
        TokenType.RPAREN,
        TokenType.RBRACKET,
        TokenType.COLON,
        TokenType.RBRACE,
        TokenType.LBRACE,
        TokenType.EOF,
    }

    def __init__(
        self,
        known_symbols: Optional[Set[str]] = None,
        source: str = "",
        filename: str = "<stdin>",
    ):
        self.known_symbols = set(known_symbols) if known_symbols else set()
        self.source = source
        self.filename = filename

    def add_symbols(self, symbols: Set[str]):
        """Register additional known identifiers."""
        self.known_symbols.update(symbols)

    def collect_expression_tokens(
        self,
        tokens: List[Token],
        start_pos: int,
        stop_types: Optional[Set[TokenType]] = None,
    ) -> Tuple[List[Token], int]:
        """
        Collects tokens belonging to an expression starting from `start_pos` up to the
        enclosing statement or expression delimiter.
        """
        if stop_types is None:
            stop_types = {TokenType.SEMICOLON, TokenType.EOF}

        expr_tokens = []
        pos = start_pos
        depth_paren = 0
        depth_bracket = 0
        depth_brace = 0

        while pos < len(tokens):
            tok = tokens[pos]

            # A new statement on a later line is not part of the malformed
            # expression.  Stopping here lets the parser repair/recover the
            # expression and then independently diagnose a missing semicolon.
            if expr_tokens and tok.line > expr_tokens[0].line and tok.type in {
                TokenType.RETURN,
                TokenType.IF,
                TokenType.WHILE,
                TokenType.FOR,
                TokenType.DO,
                TokenType.BREAK,
                TokenType.CONTINUE,
                TokenType.INT,
                TokenType.FLOAT,
                TokenType.DOUBLE,
                TokenType.CHAR,
                TokenType.BOOL,
                TokenType.AUTO,
            }:
                break

            if tok.type == TokenType.LPAREN:
                depth_paren += 1
            elif tok.type == TokenType.RPAREN:
                if depth_paren > 0:
                    depth_paren -= 1
                elif TokenType.RPAREN in stop_types:
                    break
            elif tok.type == TokenType.LBRACKET:
                depth_bracket += 1
            elif tok.type == TokenType.RBRACKET:
                if depth_bracket > 0:
                    depth_bracket -= 1
                elif TokenType.RBRACKET in stop_types:
                    break
            elif tok.type == TokenType.LBRACE:
                depth_brace += 1
            elif tok.type == TokenType.RBRACE:
                if depth_brace > 0:
                    depth_brace -= 1
                elif TokenType.RBRACE in stop_types:
                    break
            elif tok.type == TokenType.SEMICOLON:
                # Semicolon unconditionally terminates any expression statement
                break
            elif tok.type == TokenType.COMMA and depth_paren == 0 and depth_bracket == 0 and depth_brace == 0:
                if TokenType.COMMA in stop_types:
                    break
            elif tok.type == TokenType.EOF:
                break

            expr_tokens.append(tok)
            pos += 1

        return expr_tokens, pos

    def decompose_identifiers(
        self, tokens: List[Token]
    ) -> Tuple[List[Token], List[str]]:
        """
        Symbol-aware identifier decomposition:
        If an identifier is undeclared, decomposes it into known active symbols (e.g. 'ab' -> 'a', 'b').
        """
        new_tokens = []
        explanations = []

        # If known_symbols is empty, populate with single lowercase and uppercase letters as a fallback
        active_symbols = set(self.known_symbols)
        if not active_symbols:
            # Common variable names
            active_symbols.update(chr(c) for c in range(ord('a'), ord('z') + 1))
            active_symbols.update(chr(c) for c in range(ord('A'), ord('Z') + 1))

        for tok in tokens:
            if tok.type == TokenType.IDENTIFIER:
                if tok.lexeme in active_symbols:
                    new_tokens.append(tok)
                else:
                    parts = find_symbol_partition(tok.lexeme, active_symbols)
                    if parts:
                        col_offset = 0
                        for part in parts:
                            new_tok = Token(
                                TokenType.IDENTIFIER,
                                part,
                                tok.line,
                                tok.col + col_offset,
                            )
                            new_tokens.append(new_tok)
                            col_offset += len(part)
                        parts_str = " and ".join(repr(p) for p in parts)
                        explanations.append(
                            f"split undeclared identifier '{tok.lexeme}' into {parts_str}"
                        )
                    else:
                        new_tokens.append(tok)
            else:
                new_tokens.append(tok)

        return new_tokens, explanations

    def _clone_tokens(self, tokens: List[Token]) -> List[Token]:
        return [Token(t.type, t.lexeme, t.line, t.col) for t in tokens]

    def _make_op_token(self, op_char: str, ref_tok: Token) -> Token:
        op_types = {
            "+": TokenType.PLUS,
            "-": TokenType.MINUS,
            "*": TokenType.STAR,
            "/": TokenType.SLASH,
            "%": TokenType.MOD,
        }
        tok_type = op_types.get(op_char, TokenType.STAR)
        return Token(tok_type, op_char, ref_tok.line, ref_tok.col)

    def generate_candidate_repairs(
        self, tokens: List[Token], initial_explanations: List[str]
    ) -> List[Tuple[List[Token], List[str], int]]:
        """
        Generates repaired candidate token streams by applying heuristic transformations.
        Returns a list of tuples: (candidate_tokens, explanations, edit_score).
        """
        candidates: List[Tuple[List[Token], List[str], int]] = []

        if not tokens:
            return candidates

        # 1. Pipeline combination: deduplicate + relocate dangling / postfix + missing * + balance paren
        pipe_tokens = self._clone_tokens(tokens)
        pipe_explanations = list(initial_explanations)
        pipe_score = len(initial_explanations)

        # 1a. Deduplicate consecutive identical binary operators: 'a + + b' -> 'a + b'
        dedup_tokens = []
        i = 0
        while i < len(pipe_tokens):
            tok = pipe_tokens[i]
            if (
                is_binary_op_token(tok)
                and i + 1 < len(pipe_tokens)
                and pipe_tokens[i + 1].type == tok.type
            ):
                pipe_explanations.append(
                    f"deduplicated consecutive '{tok.lexeme}' operators"
                )
                pipe_score += 1
                dedup_tokens.append(tok)
                i += 2
                continue
            dedup_tokens.append(tok)
            i += 1
        pipe_tokens = dedup_tokens
        if len(dedup_tokens) != len(tokens):
            candidates.append((self._clone_tokens(pipe_tokens), list(pipe_explanations), pipe_score))

        # 1b. Check for dangling operators at the end or before a closing paren
        # Example 1: 'a b +' -> relocate '+' between 'a' and 'b'
        # Example 2: '( a + b c * )' -> relocate '*' between 'b' and 'c'
        # Example 3: 'a * b + c d *' -> relocate '*' between 'c' and 'd'
        relocated_tokens = self._relocate_dangling_operators(pipe_tokens)
        if relocated_tokens is not None:
            cand_tokens, reloc_expls = relocated_tokens
            cand_expls = pipe_explanations + reloc_expls
            cand_score = pipe_score + len(reloc_expls)
            
            # Balance parentheses on candidate
            bal_tokens, bal_expls = self._balance_parentheses(cand_tokens)
            cand_expls += bal_expls
            cand_score += len(bal_expls)

            candidates.append((bal_tokens, cand_expls, cand_score))

        # 1c. Juxtaposition / Missing '*' Operator (e.g. '2(a + b)' -> '2 * (a + b)', 'x y' -> 'x * y')
        inserted_tokens, insert_expls = self._insert_missing_multiplication(pipe_tokens)
        if insert_expls:
            cand_expls = pipe_explanations + insert_expls
            cand_score = pipe_score + len(insert_expls)
            bal_tokens, bal_expls = self._balance_parentheses(inserted_tokens)
            cand_expls += bal_expls
            cand_score += len(bal_expls)
            candidates.append((bal_tokens, cand_expls, cand_score))

        # 1d. Balance parentheses directly on decomposed tokens
        bal_tokens, bal_expls = self._balance_parentheses(pipe_tokens)
        if bal_expls:
            cand_expls = pipe_explanations + bal_expls
            cand_score = pipe_score + len(bal_expls)
            candidates.append((bal_tokens, cand_expls, cand_score))

        # 1e. Full RPN (Postfix) to Infix Transformation (e.g. 'a b +', 'a b c * +')
        rpn_candidate = self._rpn_to_infix(pipe_tokens)
        if rpn_candidate is not None:
            rpn_toks, rpn_expls = rpn_candidate
            cand_expls = pipe_explanations + rpn_expls
            cand_score = pipe_score + len(rpn_expls) + 1
            candidates.append((rpn_toks, cand_expls, cand_score))

        # 1f. Trailing dangling operator removal: 'a + b +' -> 'a + b'
        if pipe_tokens and is_binary_op_token(pipe_tokens[-1]):
            trimmed = pipe_tokens[:-1]
            cand_expls = pipe_explanations + [
                f"removed dangling trailing operator '{pipe_tokens[-1].lexeme}'"
            ]
            candidates.append((trimmed, cand_expls, pipe_score + 1))

        return candidates

    def _relocate_dangling_operators(
        self, tokens: List[Token]
    ) -> Optional[Tuple[List[Token], List[str]]]:
        """
        Detects dangling operators (at the end of expression or right before ')')
        and relocates each operator into the adjacent operand gap preceding it.
        """
        res = []
        explanations = []
        modified = False
        i = 0

        while i < len(tokens):
            # Check if this position has adjacent operands followed by dangling operator
            # Pattern: Op1, Op2, [Op3...], Operator, followed by ')' or end of tokens
            # Or general: find adjacent operands with no operator between them,
            # and a trailing operator nearby.
            if i + 2 < len(tokens):
                t1 = tokens[i]
                t2 = tokens[i + 1]
                t3 = tokens[i + 2]

                # Case: Op1 Op2 Operator (where Operator is trailing or followed by ')')
                is_trailing = (i + 3 == len(tokens)) or (
                    i + 3 < len(tokens) and tokens[i + 3].type == TokenType.RPAREN
                )
                if is_operand_token(t1) and is_operand_token(t2) and is_binary_op_token(t3) and is_trailing:
                    # Relocate t3 between t1 and t2: Op1 Operator Op2
                    res.append(t1)
                    res.append(self._make_op_token(t3.lexeme, t2))
                    res.append(t2)
                    explanations.append(
                        f"relocated operator '{t3.lexeme}' between '{t1.lexeme}' and '{t2.lexeme}'"
                    )
                    modified = True
                    i += 3
                    continue

            # Case: Subexpression like '( ... Op1 Op2 Operator )'
            res.append(tokens[i])
            i += 1

        # Check for trailing operator at the very end of res with an adjacent operand gap earlier
        if len(res) >= 3 and is_binary_op_token(res[-1]):
            trailing_op = res[-1]
            # Look backwards for the last two adjacent operands without an operator
            gap_idx = -1
            for j in range(len(res) - 2, 0, -1):
                if is_operand_token(res[j - 1]) and is_operand_token(res[j]):
                    gap_idx = j
                    break
            if gap_idx != -1:
                t1 = res[gap_idx - 1]
                t2 = res[gap_idx]
                new_res = res[:gap_idx] + [self._make_op_token(trailing_op.lexeme, t2)] + res[gap_idx:-1]
                explanations.append(
                    f"relocated operator '{trailing_op.lexeme}' between '{t1.lexeme}' and '{t2.lexeme}'"
                )
                return new_res, explanations

        if modified:
            return res, explanations
        return None

    def _insert_missing_multiplication(
        self, tokens: List[Token]
    ) -> Tuple[List[Token], List[str]]:
        """
        Inserts multiplication '*' between adjacent operands or literal and paren (e.g. '2(a + b)').
        """
        res = []
        explanations = []
        for i, tok in enumerate(tokens):
            res.append(tok)
            if i + 1 < len(tokens):
                nxt = tokens[i + 1]
                # Literal or Identifier followed by '('
                if (tok.type in (TokenType.INT_LIT, TokenType.FLOAT_LIT) or tok.type == TokenType.RPAREN) and nxt.type == TokenType.LPAREN:
                    res.append(self._make_op_token("*", nxt))
                    explanations.append(
                        f"inserted missing '*' between '{tok.lexeme}' and '{nxt.lexeme}'"
                    )
                # Two adjacent operands
                elif is_operand_token(tok) and is_operand_token(nxt):
                    res.append(self._make_op_token("*", nxt))
                    explanations.append(
                        f"inserted missing '*' between '{tok.lexeme}' and '{nxt.lexeme}'"
                    )
        return res, explanations

    def _balance_parentheses(
        self, tokens: List[Token]
    ) -> Tuple[List[Token], List[str]]:
        """Balances unclosed or unopened parentheses in the expression."""
        res = list(tokens)
        explanations = []

        open_parens = sum(1 for t in tokens if t.type == TokenType.LPAREN)
        close_parens = sum(1 for t in tokens if t.type == TokenType.RPAREN)

        if open_parens > close_parens:
            diff = open_parens - close_parens
            ref_tok = tokens[-1] if tokens else Token(TokenType.RPAREN, ")", 1, 1)
            for _ in range(diff):
                res.append(Token(TokenType.RPAREN, ")", ref_tok.line, ref_tok.col + 1))
            explanations.append("closed unclosed '(' with ')'")
        elif close_parens > open_parens:
            diff = close_parens - open_parens
            ref_tok = tokens[0] if tokens else Token(TokenType.LPAREN, "(", 1, 1)
            for _ in range(diff):
                res.insert(0, Token(TokenType.LPAREN, "(", ref_tok.line, ref_tok.col))
            explanations.append("added missing opening '('")

        return res, explanations

    def _rpn_to_infix(
        self, tokens: List[Token]
    ) -> Optional[Tuple[List[Token], List[str]]]:
        """
        Attempts to parse tokens as pure Reverse Polish Notation (postfix) and convert to infix.
        """
        stack: List[List[Token]] = []
        op_count = 0

        for tok in tokens:
            if is_operand_token(tok):
                stack.append([tok])
            elif is_binary_op_token(tok):
                if len(stack) < 2:
                    return None
                right = stack.pop()
                left = stack.pop()
                combined = []
                if len(left) > 1:
                    combined.extend([Token(TokenType.LPAREN, "(", tok.line, tok.col)] + left + [Token(TokenType.RPAREN, ")", tok.line, tok.col)])
                else:
                    combined.extend(left)
                combined.append(tok)
                if len(right) > 1:
                    combined.extend([Token(TokenType.LPAREN, "(", tok.line, tok.col)] + right + [Token(TokenType.RPAREN, ")", tok.line, tok.col)])
                else:
                    combined.extend(right)
                stack.append(combined)
                op_count += 1
            else:
                return None

        if len(stack) == 1 and op_count > 0:
            return stack[0], ["converted postfix (RPN) expression to infix notation"]
        return None

    def validate_candidate(self, candidate_tokens: List[Token]) -> Optional[Expression]:
        """
        Validates candidate tokens by trial-parsing them in an isolated Parser sandbox.
        Returns the parsed Expression AST node if valid, or None if invalid.
        """
        if not candidate_tokens:
            return None

        code = tokens_to_code(candidate_tokens)
        from src.lexer import Lexer
        from src.parser import Parser

        try:
            from src.diagnostics import DiagnosticSink
            silent_sink = DiagnosticSink(emit=False)
            # Tokenize through Lexer to obtain pristine tokens with standard positioning
            lexer_tokens = Lexer(code, "<repair_sandbox>", diag_sink=silent_sink).tokenize()
            sandbox_parser = Parser(
                lexer_tokens,
                code,
                "<repair_sandbox>",
                enable_repair=False,
                diag_sink=silent_sink,
            )
            sandbox_parser._in_repair = True

            ast_node = sandbox_parser.parse_expression()
            # The trial expression must consume the entire stream up to EOF
            if sandbox_parser.is_at_end():
                return ast_node
            return None
        except Exception:
            return None

    def rank_candidates(
        self,
        original_tokens: List[Token],
        candidates: List[RepairSuggestion],
    ) -> List[RepairSuggestion]:
        """Ranks candidates by minimum edit distance and transformation simplicity."""
        # Deduplicate candidates with identical repaired code
        seen_codes = set()
        unique_candidates = []
        for cand in candidates:
            if cand.repaired_code not in seen_codes:
                seen_codes.add(cand.repaired_code)
                unique_candidates.append(cand)

        # Sort by edit distance / score ascending
        unique_candidates.sort(key=lambda c: (c.edit_distance, len(c.repaired_code)))
        return unique_candidates

    def repair(self, tokens: List[Token]) -> List[RepairSuggestion]:
        """
        Full repair pipeline:
        1. Decomposes undeclared multi-character identifiers.
        2. Generates candidate syntax repairs via heuristics.
        3. Trial-parses each candidate in a sandbox.
        4. Ranks surviving candidates by edit distance.
        """
        if not tokens:
            return []

        # Step 1: Identifier decomposition
        decomposed_tokens, decomp_explanations = self.decompose_identifiers(tokens)

        # Step 2: Candidate generation
        raw_candidates = self.generate_candidate_repairs(
            decomposed_tokens, decomp_explanations
        )

        # Step 3: Validate each candidate via trial-parsing
        valid_suggestions: List[RepairSuggestion] = []
        orig_code = tokens_to_code(tokens)

        for cand_toks, cand_expls, score in raw_candidates:
            cand_code = tokens_to_code(cand_toks)
            if cand_code == orig_code:
                continue

            ast_node = self.validate_candidate(cand_toks)
            if ast_node is not None:
                suggestion = RepairSuggestion(
                    repaired_tokens=cand_toks,
                    repaired_code=cand_code,
                    explanation=cand_expls,
                    ast_node=ast_node,
                    edit_distance=score,
                )
                valid_suggestions.append(suggestion)

        # Step 4: Rank candidates
        return self.rank_candidates(tokens, valid_suggestions)
