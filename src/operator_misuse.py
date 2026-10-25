"""
Context-Aware Operator Misuse Detector and Semantic Repair Subsystem (Idea 6)

Detects common semantic hazards and subtle operator confusion bugs:
  - W002: Accidental assignment '=' inside condition headers (if, while, for, do-while)
          instead of equality '==', while allowing intentional '((x = func()))'.
  - W003: Bitwise XOR '^' used where mathematical exponentiation was intended
          (e.g., 2 ^ 8 -> 1 << 8 or pow(2, 8); x ^ 2 -> x * x).
  - W004: Chained mathematical comparisons (e.g., 10 <= score <= 100)
          which evaluate left-to-right to a boolean in C++.
  - W005: Bitwise '&' or '|' used with boolean operands instead of logical '&&' or '||'.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple, Any, Set
import re

from src.ast_nodes import (
    ASTNode,
    Expression,
    Statement,
    IfStatement,
    WhileStatement,
    DoWhileStatement,
    ForStatement,
    BinaryOp,
    Assignment,
    MemberAssignment,
    ArrowAssignment,
    ArrayAssignment,
    DerefAssignment,
    Identifier,
    IntLiteral,
    FloatLiteral,
    BoolLiteral,
    StringLiteral,
    FunctionCall,
    MethodCall,
    MemberAccess,
    ArrowAccess,
    ArrayAccess,
    UnaryOp,
    TernaryOp,
    CastExpression,
    AddressOf,
    Deref,
    PreIncrement,
    PreDecrement,
    PostIncrement,
    PostDecrement,
    ScopeResolution,
    ThisExpr,
    NewExpr,
    VarDeclaration,
)
@dataclass
class OperatorDiagnostic:
    """Represents a detected operator misuse or semantic hazard."""
    code: str                   # W002, W003, W004, W005
    message: str                # Diagnostic description
    help_text: str              # Explanatory suggestion
    line: int                   # 1-based line number
    col: int                    # 1-based column number
    length: int                 # Underline length for caret display
    original_snippet: str       # Exact source text segment
    repaired_snippet: str       # Replacement source text
    node: Any                   # AST node reference
    left_code: str = ""         # Sub-expression left component
    right_code: str = ""        # Sub-expression right component


def expr_to_code(expr: Any) -> str:
    """Converts any AST expression node back to clean C++ source code."""
    if expr is None:
        return ""
    if isinstance(expr, BoolLiteral):
        return "true" if expr.value else "false"
    if isinstance(expr, IntLiteral):
        return str(expr.value)
    if isinstance(expr, FloatLiteral):
        return str(expr.value)
    if isinstance(expr, StringLiteral):
        return f'"{expr.value}"'
    if isinstance(expr, Identifier):
        return expr.name
    if isinstance(expr, ThisExpr):
        return "this"
    if isinstance(expr, BinaryOp):
        left_str = expr_to_code(expr.left)
        right_str = expr_to_code(expr.right)
        return f"{left_str} {expr.op} {right_str}"
    if isinstance(expr, UnaryOp):
        return f"{expr.op}{expr_to_code(expr.expr)}"
    if isinstance(expr, AddressOf):
        return f"&{expr_to_code(expr.expr)}"
    if isinstance(expr, Deref):
        return f"*{expr_to_code(expr.expr)}"
    if isinstance(expr, PreIncrement):
        return f"++{expr_to_code(expr.target)}"
    if isinstance(expr, PreDecrement):
        return f"--{expr_to_code(expr.target)}"
    if isinstance(expr, PostIncrement):
        return f"{expr_to_code(expr.target)}++"
    if isinstance(expr, PostDecrement):
        return f"{expr_to_code(expr.target)}--"
    if isinstance(expr, ScopeResolution):
        return f"{expr.namespace}::{expr.member}"
    if isinstance(expr, MethodCall):
        args_str = ", ".join(expr_to_code(a) for a in expr.args)
        return f"{expr_to_code(expr.object_expr)}.{expr.method_name}({args_str})"
    if isinstance(expr, FunctionCall):
        args_str = ", ".join(expr_to_code(a) for a in expr.args)
        return f"{expr.name}({args_str})"
    if isinstance(expr, MemberAccess):
        return f"{expr_to_code(expr.object_expr)}.{expr.member}"
    if isinstance(expr, ArrowAccess):
        return f"{expr_to_code(expr.object_expr)}->{expr.member}"
    if isinstance(expr, ArrayAccess):
        return f"{expr.name}[{expr_to_code(expr.index)}]"
    if isinstance(expr, TernaryOp):
        return f"{expr_to_code(expr.condition)} ? {expr_to_code(expr.true_expr)} : {expr_to_code(expr.false_expr)}"
    if isinstance(expr, CastExpression):
        return f"({expr.target_type}){expr_to_code(expr.expr)}"
    if isinstance(expr, NewExpr):
        args_str = ", ".join(expr_to_code(a) for a in expr.args)
        return f"new {expr.type_name}({args_str})"
    if isinstance(expr, Assignment):
        return f"{expr.target} = {expr_to_code(expr.expr)}"
    if isinstance(expr, MemberAssignment):
        return f"{expr_to_code(expr.object_expr)}.{expr.member} = {expr_to_code(expr.expr)}"
    if isinstance(expr, ArrowAssignment):
        return f"{expr_to_code(expr.object_expr)}->{expr.member} = {expr_to_code(expr.expr)}"
    if isinstance(expr, ArrayAssignment):
        return f"{expr.name}[{expr_to_code(expr.index)}] = {expr_to_code(expr.expr)}"
    if isinstance(expr, DerefAssignment):
        return f"*{expr_to_code(expr.target)} = {expr_to_code(expr.expr)}"
    return ""


class OperatorMisuseEngine:
    """
    Context-aware detector and auto-repair synthesizer for operator confusion hazards.
    """

    def __init__(
        self,
        source: str,
        filename: str = "<stdin>",
        enable_repair: bool = True,
        warn_as_error: bool = False,
    ):
        self.source = source
        self.filename = filename
        self.enable_repair = enable_repair
        self.warn_as_error = warn_as_error
        self.diagnostics: List[OperatorDiagnostic] = []
        self._reported_keys: Set[Tuple[str, int, int]] = set()

    def scan(self, ast: Any, semantic_analyzer: Optional[Any] = None) -> List[OperatorDiagnostic]:
        """Scans the translation unit AST for operator misuse diagnostics."""
        self.diagnostics.clear()
        self._reported_keys.clear()
        self._walk_ast(ast, semantic_analyzer)
        return self.diagnostics

    def _walk_ast(self, node: Any, sem: Optional[Any]):
        """Recursively traverses the AST to detect operator hazards."""
        if node is None:
            return

        # 1. Condition header checks: if, while, do-while, for
        if isinstance(node, IfStatement):
            self._check_assignment_in_condition(node.condition, sem)
            self._walk_ast(node.condition, sem)
            self._walk_ast(node.then_branch, sem)
            if node.else_branch:
                self._walk_ast(node.else_branch, sem)
            return

        if isinstance(node, WhileStatement):
            self._check_assignment_in_condition(node.condition, sem)
            self._walk_ast(node.condition, sem)
            self._walk_ast(node.body, sem)
            return

        if isinstance(node, DoWhileStatement):
            self._check_assignment_in_condition(node.condition, sem)
            self._walk_ast(node.body, sem)
            self._walk_ast(node.condition, sem)
            return

        if isinstance(node, ForStatement):
            if node.condition:
                self._check_assignment_in_condition(node.condition, sem)
                self._walk_ast(node.condition, sem)
            if node.init:
                self._walk_ast(node.init, sem)
            if node.update:
                self._walk_ast(node.update, sem)
            self._walk_ast(node.body, sem)
            return

        # 2. Expression-level checks
        if isinstance(node, BinaryOp):
            # Check XOR vs Exponentiation (W003)
            if node.op == "^":
                self._check_exponentiation_vs_xor(node)

            # Check Chained Relational Comparisons (W004)
            if node.op in ("<", "<=", ">", ">="):
                self._check_chained_comparison(node)

            # Check Bitwise in Boolean Context (W005)
            if node.op in ("&", "|"):
                self._check_bitwise_in_boolean_context(node, sem)

            self._walk_ast(node.left, sem)
            self._walk_ast(node.right, sem)
            return

        # Generic AST traversal
        for attr in ["statements", "declarations", "members", "elements", "cases", "args", "init_list"]:
            if hasattr(node, attr):
                val = getattr(node, attr)
                if isinstance(val, list):
                    for item in val:
                        self._walk_ast(item, sem)

        for attr in ["expr", "initializer", "target", "body", "left", "right", "condition", "true_expr", "false_expr", "init", "update", "then_branch", "else_branch", "index", "iterable"]:
            if hasattr(node, attr):
                val = getattr(node, attr)
                if isinstance(val, (ASTNode, Statement, Expression)):
                    self._walk_ast(val, sem)

    # -------------------------------------------------------------------------
    # Pattern 1: Assignment in Condition (W002)
    # -------------------------------------------------------------------------
    def _check_assignment_in_condition(self, cond: Any, sem: Optional[Any]):
        if cond is None:
            return

        # Check if the condition itself is an assignment expression
        if isinstance(cond, (Assignment, MemberAssignment, ArrowAssignment, ArrayAssignment, DerefAssignment)):
            # Respect intentional assignment idiom: extra parentheses `((x = func()))`
            if getattr(cond, "is_parenthesized", False):
                return

            key = ("W002", cond.line, cond.col)
            if key in self._reported_keys:
                return
            self._reported_keys.add(key)

            orig_code = expr_to_code(cond)
            # Replace the single '=' assignment operator with equality '=='
            repaired_code = orig_code.replace(" = ", " == ", 1)
            if repaired_code == orig_code and "=" in orig_code:
                repaired_code = re.sub(r'(?<![=!<>\+\-\*/%&|^])=(?!=)', '==', orig_code, count=1)

            # Locate assignment operator column in physical file source line
            op_col = cond.col
            src_for_cond = self.source
            if sem is not None and hasattr(sem, "_get_file_and_source"):
                _, src_for_cond = sem._get_file_and_source(cond)
            lines = src_for_cond.splitlines()
            if 0 <= cond.line - 1 < len(lines):
                line_str = lines[cond.line - 1]
                match = re.search(r'(?<![=!<>\+\-\*/%&|^])=(?!=)', line_str[cond.col - 1:])
                if match:
                    op_col = cond.col + match.start()

            diag = OperatorDiagnostic(
                code="W002",
                message="using the result of an assignment as a condition without parentheses",
                help_text="use '==' to check for equality, or extra parentheses '((...))' if assignment is intentional",
                line=cond.line,
                col=op_col,
                length=1,
                original_snippet=orig_code,
                repaired_snippet=repaired_code,
                node=cond,
            )
            self.diagnostics.append(diag)

    # -------------------------------------------------------------------------
    # Pattern 2: Exponentiation vs Bitwise XOR (W003)
    # -------------------------------------------------------------------------
    def _check_exponentiation_vs_xor(self, node: BinaryOp):
        key = ("W003", node.line, node.col)
        if key in self._reported_keys:
            return

        left = node.left
        right = node.right

        left_code = expr_to_code(left).strip()
        right_code = expr_to_code(right).strip()

        # Exclude bitwise contexts: bit masks, flags, hex literals (0x...), bitwise inversion (~)
        combined_text = f"{left_code} {right_code}".lower()
        if any(kw in combined_text for kw in ["mask", "flag", "bit", "hash", "key", "iv", "cipher", "0x", "~"]):
            return

        is_power = False
        repaired = ""
        help_msg = ""

        # Case A: Base is literal 2 (e.g. 2 ^ 8, 2 ^ k)
        if isinstance(left, IntLiteral) and left.value == 2:
            is_power = True
            if isinstance(right, IntLiteral):
                repaired = f"1 << {right.value}"
                help_msg = f"in C++, '^' is bitwise XOR; for 2^{right.value}, use bit shift '(1 << {right.value})' or 'pow(2, {right.value})'"
            else:
                repaired = f"1 << {right_code}"
                help_msg = f"in C++, '^' is bitwise XOR; for 2^{right_code}, use bit shift '(1 << {right_code})' or 'pow(2, {right_code})'"

        # Case B: Base is literal 10 (e.g. 10 ^ 3)
        elif isinstance(left, IntLiteral) and left.value == 10:
            is_power = True
            repaired = f"pow(10, {right_code})"
            help_msg = f"in C++, '^' is bitwise XOR; for 10^{right_code}, use 'pow(10, {right_code})'"

        # Case C: Exponent is literal 2 (squaring: x ^ 2, r ^ 2, radius ^ 2)
        elif isinstance(right, IntLiteral) and right.value == 2:
            is_power = True
            repaired = f"{left_code} * {left_code}"
            help_msg = f"in C++, '^' is bitwise XOR; to square a value, use '{left_code} * {left_code}' or 'pow({left_code}, 2)'"

        # Case D: Variable name hints at exponentiation (power, square, cube, area, exp, pow)
        elif any(hint in combined_text for hint in ["power", "square", "cube", "area", "exp", "pow", "radius"]):
            is_power = True
            repaired = f"pow({left_code}, {right_code})"
            help_msg = f"in C++, '^' is bitwise XOR; for exponentiation, use 'pow({left_code}, {right_code})'"

        if is_power:
            self._reported_keys.add(key)
            orig_snippet = f"{left_code} ^ {right_code}"
            diag = OperatorDiagnostic(
                code="W003",
                message="result of '^' is bitwise XOR, not mathematical exponentiation",
                help_text=help_msg,
                line=node.line,
                col=node.col,
                length=len(orig_snippet),
                original_snippet=orig_snippet,
                repaired_snippet=repaired,
                node=node,
                left_code=left_code,
                right_code=right_code,
            )
            self.diagnostics.append(diag)

    # -------------------------------------------------------------------------
    # Pattern 3: Chained Mathematical Comparisons (W004)
    # -------------------------------------------------------------------------
    def _check_chained_comparison(self, node: BinaryOp):
        # Detect if left operand is also a comparison: (a < b) < c
        if not isinstance(node.left, BinaryOp) or node.left.op not in ("<", "<=", ">", ">="):
            return

        key = ("W004", node.line, node.col)
        if key in self._reported_keys:
            return
        self._reported_keys.add(key)

        left_op = node.left.op
        right_op = node.op

        a_code = expr_to_code(node.left.left)
        b_code = expr_to_code(node.left.right)
        c_code = expr_to_code(node.right)

        orig_snippet = f"{a_code} {left_op} {b_code} {right_op} {c_code}"
        repaired_snippet = f"{a_code} {left_op} {b_code} && {b_code} {right_op} {c_code}"

        diag = OperatorDiagnostic(
            code="W004",
            message=f"chained comparison '{left_op} ... {right_op}' does not evaluate mathematically in C++",
            help_text=f"comparisons in C++ associate left-to-right into a boolean (0 or 1); split into logical AND: '{repaired_snippet}'",
            line=node.left.line,
            col=node.left.col,
            length=len(orig_snippet),
            original_snippet=orig_snippet,
            repaired_snippet=repaired_snippet,
            node=node,
            left_code=a_code,
            right_code=c_code,
        )
        self.diagnostics.append(diag)

    # -------------------------------------------------------------------------
    # Pattern 4: Bitwise vs Logical Operator in Boolean Context (W005)
    # -------------------------------------------------------------------------
    def _check_bitwise_in_boolean_context(self, node: BinaryOp, sem: Optional[Any]):
        key = ("W005", node.line, node.col)
        if key in self._reported_keys:
            return

        left_is_bool = self._is_boolean_expr(node.left, sem)
        right_is_bool = self._is_boolean_expr(node.right, sem)

        if left_is_bool and right_is_bool:
            self._reported_keys.add(key)
            suggested_op = "&&" if node.op == "&" else "||"

            left_code = expr_to_code(node.left)
            right_code = expr_to_code(node.right)
            orig_snippet = f"{left_code} {node.op} {right_code}"
            repaired_snippet = f"{left_code} {suggested_op} {right_code}"

            diag = OperatorDiagnostic(
                code="W005",
                message=f"use of bitwise '{node.op}' on boolean operands; did you mean '{suggested_op}'?",
                help_text=f"bitwise '{node.op}' evaluates both operands without short-circuiting; use logical '{suggested_op}' for boolean logic",
                line=node.line,
                col=node.col,
                length=len(orig_snippet),
                original_snippet=orig_snippet,
                repaired_snippet=repaired_snippet,
                node=node,
                left_code=left_code,
                right_code=right_code,
            )
            self.diagnostics.append(diag)

    def _is_boolean_expr(self, expr: Any, sem: Optional[Any]) -> bool:
        """Determines if an expression is explicitly or semantically boolean."""
        if expr is None:
            return False
        if isinstance(expr, BoolLiteral):
            return True
        if isinstance(expr, BinaryOp) and expr.op in ("==", "!=", "<", "<=", ">", ">=", "&&", "||"):
            return True
        if isinstance(expr, BinaryOp) and expr.op in ("&", "|"):
            if self._is_boolean_expr(expr.left, sem) and self._is_boolean_expr(expr.right, sem):
                return True
        if isinstance(expr, UnaryOp) and expr.op == "!":
            return True
        if isinstance(expr, Identifier):
            if expr.name in ("true", "false"):
                return True
            if sem:
                # 1. Try current_scope
                if hasattr(sem, "current_scope"):
                    sym = sem.current_scope.resolve(expr.name)
                    if sym and sem.normalize_type(sym.s_type) == "bool":
                        return True
                # 2. Try tracked_variables across all scopes
                if hasattr(sem, "tracked_variables"):
                    for sym in reversed(sem.tracked_variables):
                        if sym.name == expr.name and sem.normalize_type(sym.s_type) == "bool":
                            return True
        if sem and hasattr(sem, "get_expr_type") and isinstance(expr, Expression):
            try:
                t = sem.get_expr_type(expr)
                if sem.normalize_type(t) == "bool":
                    return True
            except (AttributeError, TypeError, ValueError, KeyError):
                return False
        return False
