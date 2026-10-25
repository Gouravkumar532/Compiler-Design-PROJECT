"""
Static Array Bounds & Off-By-One Index Diagnostics and Auto-Repair Subsystem (Idea 8)

Detects:
  - W006: Constant Literal Array Index Out of Bounds (K >= size OR K < 0 / negative indexing)
  - W007: Loop Boundary Off-by-One Array Hazards (e.g. 'for (int i = 0; i <= size; i++)')
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple, Any, Set, Dict
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
    ArrayDeclaration,
    Block,
    ExpressionStatement,
    FunctionDef,
)
from src.tokens import TokenType


@dataclass
class ArrayBoundsDiagnostic:
    """Represents an array boundary violation or off-by-one hazard."""
    code: str                   # W006 or W007
    message: str                # Diagnostic description
    help_text: str              # Explanatory suggestion
    line: int                   # 1-based line number
    col: int                    # 1-based column number
    length: int                 # Underline length for caret display
    original_snippet: str       # Exact source text segment
    repaired_snippet: str       # Replacement source text
    node: Any                   # AST node reference
    array_name: str = ""        # Name of array involved
    array_size: Optional[int] = None  # Declared size of array
    accessed_index: Optional[int] = None  # Problematic index reached
    var_name: str = ""          # Loop variable name if applicable


@dataclass
class ArrayInfo:
    name: str
    size: Optional[int]
    dimensions: List[Optional[int]]
    line: int
    col: int


@dataclass
class VarInfo:
    name: str
    val: Optional[int]
    is_const: bool


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
        indices = getattr(expr, "indices", None)
        if indices and len(indices) > 1:
            return f"{expr.name}" + "".join(f"[{expr_to_code(i)}]" for i in indices)
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
        indices = getattr(expr, "indices", None)
        if indices and len(indices) > 1:
            return f"{expr.name}" + "".join(f"[{expr_to_code(i)}]" for i in indices) + f" = {expr_to_code(expr.expr)}"
        return f"{expr.name}[{expr_to_code(expr.index)}] = {expr_to_code(expr.expr)}"
    if isinstance(expr, DerefAssignment):
        return f"*{expr_to_code(expr.target)} = {expr_to_code(expr.expr)}"
    return ""


class ArrayBoundsEngine:
    """
    Static array bounds verifier and off-by-one boundary condition diagnostic engine.
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
        self.diagnostics: List[ArrayBoundsDiagnostic] = []
        self._reported_keys: Set[Tuple[str, int, int]] = set()
        self.scopes: List[Dict[str, Any]] = [{}]

    def push_scope(self):
        self.scopes.append({})

    def pop_scope(self):
        if len(self.scopes) > 1:
            self.scopes.pop()

    def define_array(self, name: str, size: Optional[int], dimensions: List[Optional[int]], line: int, col: int):
        self.scopes[-1][name] = ArrayInfo(name, size, dimensions, line, col)

    def define_var(self, name: str, val: Optional[int], is_const: bool = False):
        self.scopes[-1][name] = VarInfo(name, val, is_const)

    def resolve(self, name: str, sem: Optional[Any] = None) -> Optional[Any]:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        if sem is not None and hasattr(sem, "global_scope"):
            sym = sem.global_scope.resolve(name)
            if sym:
                if getattr(sym, "array_size", None) is not None or getattr(sym, "array_dimensions", None):
                    dims = getattr(sym, "array_dimensions", [])
                    return ArrayInfo(name, sym.array_size, dims if dims else ([sym.array_size] if sym.array_size is not None else []), sym.line, sym.col)
                if getattr(sym, "const_value", None) is not None:
                    return VarInfo(name, sym.const_value, getattr(sym, "is_const", False))
        return None
    def scan(self, ast: Any, semantic_analyzer: Optional[Any] = None) -> List[ArrayBoundsDiagnostic]:
        """Scans the translation unit AST for array bounds violations."""
        self.diagnostics.clear()
        self._reported_keys.clear()
        self.scopes = [{}]

        # Pre-seed globals if semantic analyzer is provided
        if semantic_analyzer is not None and hasattr(semantic_analyzer, "global_scope"):
            for s_name, sym in semantic_analyzer.global_scope.symbols.items():
                if getattr(sym, "array_size", None) is not None or getattr(sym, "array_dimensions", None):
                    dims = getattr(sym, "array_dimensions", [])
                    self.define_array(s_name, sym.array_size, dims if dims else ([sym.array_size] if sym.array_size is not None else []), sym.line, sym.col)
                elif getattr(sym, "const_value", None) is not None:
                    self.define_var(s_name, sym.const_value, getattr(sym, "is_const", False))

        self._walk_ast(ast, semantic_analyzer)
        return self.diagnostics

    def _eval_int(self, expr: Any, sem: Optional[Any]) -> Tuple[Optional[int], bool]:
        """Statically evaluates an expression to an integer constant if possible."""
        if expr is None:
            return None, False
        if isinstance(expr, IntLiteral):
            return expr.value, True
        if isinstance(expr, UnaryOp):
            val, ok = self._eval_int(expr.expr, sem)
            if ok and val is not None:
                if expr.op == "-":
                    return -val, True
                if expr.op == "+":
                    return val, True
                if expr.op == "~":
                    return ~val, True
            return None, False
        if isinstance(expr, BinaryOp):
            l_val, l_ok = self._eval_int(expr.left, sem)
            r_val, r_ok = self._eval_int(expr.right, sem)
            if l_ok and r_ok and l_val is not None and r_val is not None:
                try:
                    if expr.op == "+":
                        return l_val + r_val, True
                    if expr.op == "-":
                        return l_val - r_val, True
                    if expr.op == "*":
                        return l_val * r_val, True
                    if expr.op == "/" and r_val != 0:
                        return l_val // r_val, True
                    if expr.op == "%" and r_val != 0:
                        return l_val % r_val, True
                    if expr.op == "<<":
                        return l_val << r_val, True
                    if expr.op == ">>":
                        return l_val >> r_val, True
                except (ArithmeticError, TypeError, ValueError):
                    return None, False
            return None, False
        if isinstance(expr, Identifier):
            res = self.resolve(expr.name, sem)
            if isinstance(res, VarInfo) and res.val is not None:
                return res.val, True
            if isinstance(res, ArrayInfo) and res.size is not None:
                return res.size, True
        if sem is not None and hasattr(sem, "eval_constexpr_expr"):
            val, ok = sem.eval_constexpr_expr(expr)
            if ok and isinstance(val, int):
                return val, True
        return None, False

    def _resolve_array_symbol(self, name: str, sem: Optional[Any]) -> Optional[ArrayInfo]:
        """Resolves an array by name in local scopes or semantic analyzer."""
        res = self.resolve(name, sem)
        if isinstance(res, ArrayInfo):
            return res
        return None

    def _walk_ast(self, node: Any, sem: Optional[Any]):
        """Recursively walks the AST to find literal array access and loop bounds bugs."""
        if node is None:
            return

        # Handle Function Definition Scope
        if isinstance(node, FunctionDef):
            self.push_scope()
            if hasattr(node, "params"):
                for p in node.params:
                    self._walk_ast(p, sem)
            if hasattr(node, "body") and node.body:
                self._walk_ast(node.body, sem)
            self.pop_scope()
            return

        # Handle Block Scope
        if isinstance(node, Block):
            self.push_scope()
            for stmt in node.statements:
                self._walk_ast(stmt, sem)
            self.pop_scope()
            return

        # Handle Array Declaration
        if isinstance(node, ArrayDeclaration):
            dims: List[Optional[int]] = []
            if getattr(node, "dim_exprs", None):
                for de in node.dim_exprs:
                    if de is not None:
                        v, ok = self._eval_int(de, sem)
                        dims.append(v if ok else None)
                    else:
                        dims.append(None)
            elif getattr(node, "dimensions", None):
                dims = list(node.dimensions)
            else:
                dims = [node.size]

            size = dims[0] if dims else node.size
            if size is None and node.elements:
                size = len(node.elements)
                if not dims:
                    dims = [size]
                else:
                    dims[0] = size
            self.define_array(node.name, size, dims, node.line, node.col)
            if node.elements:
                for el in node.elements:
                    self._walk_ast(el, sem)
            return

        # Handle Variable Declaration
        if isinstance(node, VarDeclaration):
            val, ok = self._eval_int(node.initializer, sem)
            is_const = node.is_const or getattr(node, "is_constexpr", False)
            self.define_var(node.name, val if ok else None, is_const)
            if node.initializer:
                self._walk_ast(node.initializer, sem)
            return

        # Handle For Loops
        if isinstance(node, ForStatement):
            self.push_scope()
            if node.init:
                self._walk_ast(node.init, sem)
            self._check_for_loop_bounds(node, sem)
            if node.condition:
                self._walk_ast(node.condition, sem)
            if node.update:
                self._walk_ast(node.update, sem)
            if node.body:
                self._walk_ast(node.body, sem)
            self.pop_scope()
            return

        # Handle While and Do-While Loops
        if isinstance(node, (WhileStatement, DoWhileStatement)):
            self._check_while_loop_bounds(node, sem)
            if node.condition:
                self._walk_ast(node.condition, sem)
            if node.body:
                self._walk_ast(node.body, sem)
            return

        # Handle Array Access & Assignment
        if isinstance(node, (ArrayAccess, ArrayAssignment)):
            self._check_literal_array_bounds(node, sem)

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
    # Pattern 1: Literal Constant Array Index Out of Bounds (W006)
    # -------------------------------------------------------------------------
    def _check_literal_array_bounds(self, node: Any, sem: Optional[Any]):
        name = getattr(node, "name", None)
        if not name or not isinstance(name, str):
            return

        arr_info = self._resolve_array_symbol(name, sem)
        if not arr_info:
            return

        array_size = arr_info.size
        array_dims = arr_info.dimensions
        if array_size is None and not array_dims:
            return

        indices = getattr(node, "indices", [node.index])
        for dim_idx, idx_expr in enumerate(indices):
            dim_size = array_dims[dim_idx] if dim_idx < len(array_dims) else (array_size if dim_idx == 0 else None)
            if dim_size is None:
                continue

            idx_val, is_const = self._eval_int(idx_expr, sem)
            if not is_const or idx_val is None:
                continue

            # Case A: Negative Index (Python habit: arr[-1])
            if idx_val < 0:
                key = ("W006_NEG", idx_expr.line, idx_expr.col)
                if key in self._reported_keys:
                    continue
                self._reported_keys.add(key)

                last_idx = max(0, dim_size + idx_val)
                idx_str = expr_to_code(idx_expr)
                orig_access = f"{name}[{idx_str}]"
                repaired_access = f"{name}[{last_idx}]"

                diag = ArrayBoundsDiagnostic(
                    code="W006",
                    message=f"array index {idx_val} is negative; C++ does not support Python negative indexing",
                    help_text=f"to access an element from the end, use '{name}[{last_idx}]' (valid indices: 0..{dim_size - 1})",
                    line=idx_expr.line,
                    col=idx_expr.col,
                    length=len(idx_str),
                    original_snippet=orig_access,
                    repaired_snippet=repaired_access,
                    node=node,
                    array_name=name,
                    array_size=dim_size,
                    accessed_index=idx_val,
                )
                self.diagnostics.append(diag)
                return

            # Case B: Literal Index >= Declared Dimension Size
            if idx_val >= dim_size:
                key = ("W006_OOB", idx_expr.line, idx_expr.col)
                if key in self._reported_keys:
                    continue
                self._reported_keys.add(key)

                max_valid_idx = max(0, dim_size - 1)
                idx_str = expr_to_code(idx_expr)
                orig_access = f"{name}[{idx_str}]"
                repaired_access = f"{name}[{max_valid_idx}]"

                dim_msg = f" on dimension {dim_idx + 1}" if len(array_dims) > 1 else ""
                diag = ArrayBoundsDiagnostic(
                    code="W006",
                    message=f"array index {idx_val} is out of bounds for array '{name}' of size {dim_size}{dim_msg} (valid indices: 0..{max_valid_idx})",
                    help_text=f"array '{name}' has {dim_size} elements; the maximum valid index is {max_valid_idx}",
                    line=idx_expr.line,
                    col=idx_expr.col,
                    length=len(idx_str),
                    original_snippet=orig_access,
                    repaired_snippet=repaired_access,
                    node=node,
                    array_name=name,
                    array_size=dim_size,
                    accessed_index=idx_val,
                )
                self.diagnostics.append(diag)
                return

    # -------------------------------------------------------------------------
    # Pattern 2: Loop Boundary Off-by-One Diagnostics (W007)
    # -------------------------------------------------------------------------
    def _check_for_loop_bounds(self, node: ForStatement, sem: Optional[Any]):
        if not node.condition or not isinstance(node.condition, BinaryOp):
            return

        cond = node.condition
        var_name, op, limit_expr = self._extract_loop_condition(cond)
        if not var_name or op not in ("<=", "<", ">=", ">"):
            return

        # Determine induction variable start value
        start_val = self._extract_loop_init_value(node.init, var_name, sem)
        if start_val is None:
            start_val = 0

        # Determine step direction from update
        step = self._extract_loop_step(node.update, var_name)
        if step == 0:
            step = 1

        # Evaluate upper bound limit
        limit_val, limit_ok = self._eval_int(limit_expr, sem)

        # Collect array accesses inside loop body that use var_name
        array_accesses = self._find_array_accesses_using_var(node.body, var_name)
        if not array_accesses:
            return

        # Prioritize smallest array capacity to ensure the most restrictive hazard is diagnosed
        def get_effective_capacity(item):
            info = self._resolve_array_symbol(item["name"], sem)
            return (info.size - item["offset"]) if (info and info.size is not None) else 999999
        array_accesses.sort(key=get_effective_capacity)

        for acc in array_accesses:
            arr_name = acc["name"]
            arr_info = self._resolve_array_symbol(arr_name, sem)
            if not arr_info or arr_info.size is None:
                continue

            arr_size = arr_info.size
            offset = acc["offset"]

            # If limit_val wasn't evaluated directly, check if limit_expr identifier matches size
            eff_limit_val = limit_val
            if eff_limit_val is None and isinstance(limit_expr, Identifier):
                res = self.resolve(limit_expr.name, sem)
                if isinstance(res, VarInfo) and res.val is not None:
                    eff_limit_val = res.val
                elif limit_expr.name in (f"{arr_name}_size", "size", "N", "SIZE", "LENGTH"):
                    eff_limit_val = arr_size

            # Evaluate max value of induction variable inside the loop
            if step > 0:
                if eff_limit_val is not None:
                    max_i = eff_limit_val if op in ("<=", ">=") else eff_limit_val - 1
                    min_i = start_val
                else:
                    continue

                min_idx = min_i + offset
                max_idx = max_i + offset

                # Check if safe: e.g. for (int i = 1; i <= size; i++) arr[i - 1] -> min=0, max=size-1 (SAFE!)
                if min_idx >= 0 and max_idx < arr_size:
                    continue

                # Off-by-one upper bound violation
                if max_idx >= arr_size:
                    key = ("W007", cond.line, cond.col)
                    if key in self._reported_keys:
                        continue
                    self._reported_keys.add(key)

                    orig_cond_str = expr_to_code(cond)
                    limit_str = expr_to_code(limit_expr)

                    # Build clean repair
                    if op == "<=":
                        repaired_cond_str = f"{var_name} < {limit_str}"
                    elif op == ">=":
                        repaired_cond_str = f"{limit_str} > {var_name}"
                    else:
                        repaired_cond_str = f"{var_name} < {arr_size}"

                    # Locate condition column in physical file source
                    cond_col = cond.col
                    cond_len = len(orig_cond_str)
                    src_for_cond = self.source
                    if sem is not None and hasattr(sem, "_get_file_and_source"):
                        _, src_for_cond = sem._get_file_and_source(cond)
                    lines = src_for_cond.splitlines()
                    if 0 <= cond.line - 1 < len(lines):
                        line_text = lines[cond.line - 1]
                        idx = line_text.find(orig_cond_str)
                        if idx != -1:
                            cond_col = idx + 1
                        else:
                            m = re.search(re.escape(var_name) + r'\s*<=\s*' + re.escape(limit_str), line_text)
                            if m:
                                cond_col = m.start() + 1
                                cond_len = len(m.group(0))
                                orig_cond_str = m.group(0)

                    # Determine specific pedagogical message
                    if op in ("<=", ">=") and eff_limit_val == arr_size and offset == 0 and start_val == 0:
                        msg = f"array index will exceed bounds in loop; off-by-one error (index '{var_name}' reaches {max_idx}, max valid index is {arr_size - 1})"
                        help_msg = f"change loop condition from '<=' to '<': 'for (...; {repaired_cond_str}; ...)'"
                    elif start_val == 1 and offset == 0 and eff_limit_val == arr_size:
                        msg = f"array index will exceed bounds in loop; 1-based indexing on 0-based array '{arr_name}'"
                        help_msg = f"in C++, arrays are 0-indexed (valid indices: 0..{arr_size - 1}); start from 0: 'for (int {var_name} = 0; {var_name} < {arr_size}; {var_name}++)'"
                    else:
                        msg = f"array index '{var_name}' in loop will reach {max_idx}, exceeding bounds for array '{arr_name}' of size {arr_size}"
                        help_msg = f"array '{arr_name}' has {arr_size} elements (valid indices: 0..{arr_size - 1}); change loop condition to '{var_name} < {arr_size}'"

                    diag = ArrayBoundsDiagnostic(
                        code="W007",
                        message=msg,
                        help_text=help_msg,
                        line=cond.line,
                        col=cond_col,
                        length=cond_len,
                        original_snippet=orig_cond_str,
                        repaired_snippet=repaired_cond_str,
                        node=cond,
                        array_name=arr_name,
                        array_size=arr_size,
                        accessed_index=max_idx,
                        var_name=var_name,
                    )
                    self.diagnostics.append(diag)
                    break

            elif step < 0:
                # Reverse loop: e.g. for (int i = 10; i >= 0; i--) arr[i]
                start_idx = start_val + offset
                if start_idx >= arr_size:
                    key = ("W007_REV", cond.line, cond.col)
                    if key in self._reported_keys:
                        continue
                    self._reported_keys.add(key)

                    orig_init = f"{var_name} = {start_val}"
                    repaired_init = f"{var_name} = {arr_size - 1}"
                    diag = ArrayBoundsDiagnostic(
                        code="W007",
                        message=f"array index in reverse loop starts at {start_idx}, which is out of bounds for array '{arr_name}' of size {arr_size}",
                        help_text=f"start reverse loop from size - 1: '{var_name} = {arr_size - 1}'",
                        line=cond.line,
                        col=cond.col,
                        length=len(expr_to_code(cond)),
                        original_snippet=orig_init,
                        repaired_snippet=repaired_init,
                        node=cond,
                        array_name=arr_name,
                        array_size=arr_size,
                        accessed_index=start_idx,
                        var_name=var_name,
                    )
                    self.diagnostics.append(diag)
                    break

    def _check_while_loop_bounds(self, node: WhileStatement, sem: Optional[Any]):
        if not node.condition or not isinstance(node.condition, BinaryOp):
            return

        cond = node.condition
        var_name, op, limit_expr = self._extract_loop_condition(cond)
        if not var_name or op not in ("<=", "<", ">=", ">"):
            return

        limit_val, limit_ok = self._eval_int(limit_expr, sem)
        if not limit_ok or limit_val is None:
            return

        # Check array accesses in while body
        array_accesses = self._find_array_accesses_using_var(node.body, var_name)
        if not array_accesses:
            return

        for acc in array_accesses:
            arr_name = acc["name"]
            arr_info = self._resolve_array_symbol(arr_name, sem)
            if not arr_info or arr_info.size is None:
                continue

            arr_size = arr_info.size
            offset = acc["offset"]
            max_idx = (limit_val if op in ("<=", ">=") else limit_val - 1) + offset

            if max_idx >= arr_size and op in ("<=", ">="):
                key = ("W007_WHILE", cond.line, cond.col)
                if key in self._reported_keys:
                    continue
                self._reported_keys.add(key)

                orig_cond_str = expr_to_code(cond)
                limit_str = expr_to_code(limit_expr)
                repaired_cond_str = f"{var_name} < {limit_str}" if op == "<=" else f"{limit_str} > {var_name}"

                diag = ArrayBoundsDiagnostic(
                    code="W007",
                    message=f"array index will exceed bounds in while loop; off-by-one condition '{orig_cond_str}'",
                    help_text=f"change while condition from '<=' to '<': 'while ({repaired_cond_str})'",
                    line=cond.line,
                    col=cond.col,
                    length=len(orig_cond_str),
                    original_snippet=orig_cond_str,
                    repaired_snippet=repaired_cond_str,
                    node=cond,
                    array_name=arr_name,
                    array_size=arr_size,
                    accessed_index=max_idx,
                    var_name=var_name,
                )
                self.diagnostics.append(diag)
                break

    def _extract_loop_condition(self, cond: BinaryOp) -> Tuple[Optional[str], str, Optional[Expression]]:
        """Extracts (induction_var_name, op, limit_expr) from a loop condition."""
        if isinstance(cond.left, Identifier):
            return cond.left.name, cond.op, cond.right
        if isinstance(cond.right, Identifier):
            reversed_ops = {"<=": ">=", ">=": "<=", "<": ">", ">": "<"}
            rev_op = reversed_ops.get(cond.op, cond.op)
            return cond.right.name, rev_op, cond.left
        return None, cond.op, None

    def _extract_loop_init_value(self, init: Any, var_name: str, sem: Optional[Any]) -> Optional[int]:
        """Extracts initial integer value of induction variable from loop init."""
        if init is None:
            return None
        if isinstance(init, VarDeclaration) and init.name == var_name:
            val, ok = self._eval_int(init.initializer, sem)
            return val if ok else None
        if isinstance(init, ExpressionStatement):
            expr = init.expr
            if isinstance(expr, Assignment) and expr.target == var_name:
                val, ok = self._eval_int(expr.expr, sem)
                return val if ok else None
        if isinstance(init, Assignment) and init.target == var_name:
            val, ok = self._eval_int(init.expr, sem)
            return val if ok else None
        return None

    def _extract_loop_step(self, update: Any, var_name: str) -> int:
        """Determines the loop increment/decrement step from update expression."""
        if update is None:
            return 1
        if isinstance(update, (PostIncrement, PreIncrement)):
            target = getattr(update, "target", None)
            if isinstance(target, Identifier) and target.name == var_name:
                return 1
        if isinstance(update, (PostDecrement, PreDecrement)):
            target = getattr(update, "target", None)
            if isinstance(target, Identifier) and target.name == var_name:
                return -1
        if isinstance(update, Assignment) and update.target == var_name:
            if isinstance(update.expr, BinaryOp):
                if update.expr.op == "+":
                    return 1
                if update.expr.op == "-":
                    return -1
        return 1

    def _find_array_accesses_using_var(self, body: Any, var_name: str) -> List[Dict[str, Any]]:
        """Finds all array accesses inside the loop body that use var_name in their index."""
        results: List[Dict[str, Any]] = []

        def recurse(node: Any):
            if node is None:
                return
            if isinstance(node, (ArrayAccess, ArrayAssignment)):
                indices = getattr(node, "indices", [node.index])
                for idx_expr in indices:
                    offset = self._get_var_offset(idx_expr, var_name)
                    if offset is not None:
                        results.append({
                            "name": node.name,
                            "offset": offset,
                            "node": node,
                            "idx_expr": idx_expr,
                        })

            for attr in ["statements", "declarations", "members", "elements", "cases", "args"]:
                if hasattr(node, attr):
                    val = getattr(node, attr)
                    if isinstance(val, list):
                        for item in val:
                            recurse(item)
            for attr in ["expr", "initializer", "target", "body", "left", "right", "condition", "true_expr", "false_expr", "init", "update", "then_branch", "else_branch"]:
                if hasattr(node, attr):
                    val = getattr(node, attr)
                    if isinstance(val, (ASTNode, Statement, Expression)):
                        recurse(val)

        recurse(body)
        return results

    def _get_var_offset(self, expr: Any, var_name: str) -> Optional[int]:
        """Returns K if expr is 'var_name + K' or 'var_name - K' (or 0 if exactly var_name)."""
        if isinstance(expr, Identifier) and expr.name == var_name:
            return 0
        if isinstance(expr, BinaryOp):
            if expr.op == "+" and isinstance(expr.left, Identifier) and expr.left.name == var_name:
                val, ok = self._eval_int(expr.right, None)
                if ok and val is not None:
                    return val
            if expr.op == "+" and isinstance(expr.right, Identifier) and expr.right.name == var_name:
                val, ok = self._eval_int(expr.left, None)
                if ok and val is not None:
                    return val
            if expr.op == "-" and isinstance(expr.left, Identifier) and expr.left.name == var_name:
                val, ok = self._eval_int(expr.right, None)
                if ok and val is not None:
                    return -val
        return None
