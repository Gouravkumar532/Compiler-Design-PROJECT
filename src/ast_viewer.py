"""AST Tree Viewer / Pretty Printer for the C++ compiler.

Renders AST hierarchies in visual ASCII/Unicode trees with colors,
node types, identifiers, literals, and exact source line/column spans.
"""

from typing import List, Tuple, Any, Optional
from src.ast_nodes import *
from src.errors import Colors

def format_ast(node: ASTNode, use_color: bool = True) -> str:
    """Formats an AST hierarchy into an indented tree string."""
    lines: List[str] = []
    _build_tree(node, lines, prefix="", is_last=True, is_root=True, use_color=use_color)
    return "\n".join(lines)

import sys

def _can_encode_unicode() -> bool:
    try:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        "└── ├── │".encode(encoding)
        return True
    except Exception:
        return False

UNICODE_BOX = _can_encode_unicode()
BRANCH_LAST = "└── " if UNICODE_BOX else "`-- "
BRANCH_MID = "├── " if UNICODE_BOX else "|-- "
BRANCH_PIPE = "│   " if UNICODE_BOX else "|   "

def _build_tree(
    node: Any,
    lines: List[str],
    prefix: str = "",
    is_last: bool = True,
    is_root: bool = False,
    use_color: bool = True,
    edge_label: Optional[str] = None
):
    if node is None:
        return

    # Branch indicator
    if is_root:
        branch = ""
    else:
        branch = BRANCH_LAST if is_last else BRANCH_MID

    label, children = _get_node_info(node)

    # Edge label if any (e.g., 'cond:', 'then:', 'body:')
    edge_str = f"{Colors.DIM}{edge_label} -> {Colors.RESET}" if (edge_label and use_color) else (f"{edge_label} -> " if edge_label else "")

    # Line & column tag
    loc_str = ""
    if hasattr(node, "line") and hasattr(node, "col") and node.line is not None:
        if use_color:
            loc_str = f" {Colors.DIM}[line {node.line}:{node.col}]{Colors.RESET}"
        else:
            loc_str = f" [line {node.line}:{node.col}]"

    lines.append(f"{prefix}{branch}{edge_str}{label}{loc_str}")

    # Child prefix
    if is_root:
        new_prefix = prefix
    else:
        new_prefix = prefix + ("    " if is_last else BRANCH_PIPE)

    for i, (child_edge, child_node) in enumerate(children):
        is_last_child = (i == len(children) - 1)
        _build_tree(child_node, lines, new_prefix, is_last_child, is_root=False, use_color=use_color, edge_label=child_edge)

def _get_node_info(node: Any) -> Tuple[str, List[Tuple[Optional[str], Any]]]:
    if not isinstance(node, ASTNode):
        return str(node), []

    name = node.__class__.__name__
    children: List[Tuple[Optional[str], Any]] = []

    # Node-specific extraction
    if isinstance(node, Program):
        label = f"{Colors.BOLD}{Colors.CYAN}Program{Colors.RESET}"
        for d in node.declarations:
            children.append((None, d))
        return label, children

    if isinstance(node, UsingNamespace):
        label = f"{Colors.CYAN}UsingNamespace{Colors.RESET}: {Colors.GREEN}{node.name}{Colors.RESET}"
        return label, []

    if isinstance(node, UsingDeclaration):
        label = f"{Colors.CYAN}UsingDeclaration{Colors.RESET}: {Colors.GREEN}{node.namespace}::{node.member}{Colors.RESET}"
        return label, []

    if isinstance(node, NamespaceDef):
        label = f"{Colors.CYAN}NamespaceDef{Colors.RESET}: {Colors.GREEN}{node.name}{Colors.RESET}"
        for d in node.declarations:
            children.append((None, d))
        return label, children

    if isinstance(node, FunctionDef):
        params_str = ", ".join(f"{p.param_type} {p.name}" for p in node.params)
        inline_tag = " [inline]" if getattr(node, "is_always_inline", False) else ""
        constexpr_tag = " [constexpr]" if getattr(node, "is_constexpr", False) else ""
        label = f"{Colors.BOLD}{Colors.YELLOW}FunctionDef{Colors.RESET}: {Colors.CYAN}{node.return_type}{Colors.RESET} {Colors.GREEN}{node.name}{Colors.RESET}({params_str}){inline_tag}{constexpr_tag}"
        if node.body:
            children.append(("body", node.body))
        return label, children

    if isinstance(node, Block):
        label = f"{Colors.CYAN}Block{Colors.RESET} ({len(node.statements)} stmt{'s' if len(node.statements) != 1 else ''})"
        for s in node.statements:
            children.append((None, s))
        return label, children

    if isinstance(node, VarDeclaration):
        label = f"{Colors.YELLOW}VarDecl{Colors.RESET}: {Colors.CYAN}{node.var_type}{Colors.RESET} {Colors.GREEN}{node.name}{Colors.RESET}"
        if node.initializer:
            children.append(("init", node.initializer))
        return label, children

    if isinstance(node, ArrayDeclaration):
        if getattr(node, "dimensions", None) and len(node.dimensions) > 1:
            dims_str = "".join(f"[{d}]" for d in node.dimensions)
        else:
            dims_str = f"[{node.size}]"
        label = f"{Colors.YELLOW}ArrayDecl{Colors.RESET}: {Colors.CYAN}{node.var_type}{dims_str}{Colors.RESET} {Colors.GREEN}{node.name}{Colors.RESET}"
        if node.elements:
            for idx, el in enumerate(node.elements):
                children.append((f"[{idx}]", el))
        return label, children

    if isinstance(node, StructDef):
        label = f"{Colors.BOLD}{Colors.MAGENTA}StructDef{Colors.RESET}: {Colors.GREEN}{node.name}{Colors.RESET}"
        for m in node.members:
            label += f"\n  - {m.param_type} {m.name}"
        return label, []

    if isinstance(node, ClassDef):
        base_info = f" : {node.base_access} {node.base_class}" if getattr(node, "base_class", None) else ""
        label = f"{Colors.BOLD}{Colors.MAGENTA}ClassDef{Colors.RESET}: {Colors.GREEN}{node.name}{Colors.RESET}{base_info}"
        for m in node.members:
            children.append((f"{m.access}", m.decl))
        return label, children

    if isinstance(node, TemplateDef):
        params_str = ", ".join(f"typename {p}" for p in node.template_params)
        label = f"{Colors.MAGENTA}TemplateDef{Colors.RESET} <{params_str}>"
        children.append(("decl", node.decl))
        return label, children

    if isinstance(node, EnumDef):
        if hasattr(node, "enumerators") and isinstance(node.enumerators, list):
            variants_str = ", ".join(f"{item[0]}={item[1]}" if isinstance(item, tuple) and len(item) > 1 and item[1] is not None else (item[0] if isinstance(item, tuple) else str(item)) for item in node.enumerators)
        elif hasattr(node, "variants") and isinstance(node.variants, dict):
            variants_str = ", ".join(f"{k}={v}" if v is not None else k for k, v in node.variants.items())
        else:
            variants_str = ""
        label = f"{Colors.MAGENTA}EnumDef{Colors.RESET}: {Colors.GREEN}{node.name}{Colors.RESET} {{{variants_str}}}"
        return label, []

    if isinstance(node, IfStatement):
        label = f"{Colors.BOLD}{Colors.BLUE}IfStatement{Colors.RESET}"
        children.append(("condition", node.condition))
        children.append(("then", node.then_branch))
        if node.else_branch:
            children.append(("else", node.else_branch))
        return label, children

    if isinstance(node, WhileStatement):
        label = f"{Colors.BOLD}{Colors.BLUE}WhileStatement{Colors.RESET}"
        children.append(("condition", node.condition))
        children.append(("body", node.body))
        return label, children

    if isinstance(node, DoWhileStatement):
        label = f"{Colors.BOLD}{Colors.BLUE}DoWhileStatement{Colors.RESET}"
        children.append(("body", node.body))
        children.append(("condition", node.condition))
        return label, children

    if isinstance(node, ForStatement):
        label = f"{Colors.BOLD}{Colors.BLUE}ForStatement{Colors.RESET}"
        if node.init:
            children.append(("init", node.init))
        if node.condition:
            children.append(("cond", node.condition))
        if getattr(node, "update", None):
            children.append(("update", node.update))
        elif getattr(node, "step", None):
            children.append(("step", node.step))
        if node.body:
            children.append(("body", node.body))
        return label, children

    if isinstance(node, RangeForStatement):
        label = f"{Colors.BOLD}{Colors.BLUE}RangeForStatement{Colors.RESET}: {Colors.CYAN}{node.var_type}{Colors.RESET} {Colors.GREEN}{node.var_name}{Colors.RESET}"
        children.append(("in", node.iterable))
        children.append(("body", node.body))
        return label, children

    if isinstance(node, SwitchStatement):
        label = f"{Colors.BOLD}{Colors.BLUE}SwitchStatement{Colors.RESET}"
        children.append(("expr", node.expr))
        for c in node.cases:
            children.append(("case", c))
        return label, children

    if isinstance(node, CaseClause):
        if node.value is None:
            val_str = "default"
        elif hasattr(node.value, "value"):
            val_str = f"case {node.value.value}"
        else:
            val_str = f"case {node.value}"
        label = f"{Colors.BLUE}{val_str}{Colors.RESET}"
        stmts = getattr(node, "statements", None) or getattr(node, "body", [])
        for s in stmts:
            children.append((None, s))
        return label, children

    if isinstance(node, BreakStatement):
        return f"{Colors.RED}BreakStatement{Colors.RESET}", []

    if isinstance(node, ContinueStatement):
        return f"{Colors.RED}ContinueStatement{Colors.RESET}", []

    if isinstance(node, ReturnStatement):
        label = f"{Colors.BOLD}{Colors.RED}ReturnStatement{Colors.RESET}"
        if node.expr:
            children.append(("val", node.expr))
        return label, children

    if isinstance(node, ExpressionStatement):
        label = f"{Colors.DIM}ExprStatement{Colors.RESET}"
        children.append((None, node.expr))
        return label, children

    if isinstance(node, TryCatchStatement):
        label = f"{Colors.MAGENTA}TryCatchStatement{Colors.RESET}"
        children.append(("try", node.try_block))
        for c in node.catch_clauses:
            children.append(("catch", c))
        return label, children

    if isinstance(node, CatchClause):
        label = f"{Colors.MAGENTA}CatchClause{Colors.RESET} ({node.param_type} {node.param_name})"
        children.append(("body", node.body))
        return label, children

    if isinstance(node, ThrowStatement):
        label = f"{Colors.RED}ThrowStatement{Colors.RESET}"
        children.append(("expr", node.expr))
        return label, children

    if isinstance(node, Assignment):
        label = f"{Colors.YELLOW}Assignment{Colors.RESET}: {Colors.GREEN}{node.target}{Colors.RESET} ="
        children.append((None, node.expr))
        return label, children

    if isinstance(node, BinaryOp):
        label = f"{Colors.CYAN}BinaryOp{Colors.RESET} '{Colors.BOLD}{node.op}{Colors.RESET}'"
        children.append(("left", node.left))
        children.append(("right", node.right))
        return label, children

    if isinstance(node, UnaryOp):
        label = f"{Colors.CYAN}UnaryOp{Colors.RESET} '{Colors.BOLD}{node.op}{Colors.RESET}'"
        children.append(("expr", node.expr))
        return label, children

    if isinstance(node, TernaryOp):
        label = f"{Colors.CYAN}TernaryOp{Colors.RESET} (? :)"
        children.append(("cond", node.condition))
        children.append(("true", node.true_expr))
        children.append(("false", node.false_expr))
        return label, children

    if isinstance(node, Identifier):
        return f"{Colors.GREEN}Identifier{Colors.RESET}: {node.name}", []

    if isinstance(node, IntLiteral):
        return f"{Colors.MAGENTA}IntLiteral{Colors.RESET}: {node.value}", []

    if isinstance(node, FloatLiteral):
        return f"{Colors.MAGENTA}FloatLiteral{Colors.RESET}: {node.value}", []


    if isinstance(node, StringLiteral):
        escaped = node.value.replace("\n", "\\n").replace("\t", "\\t")
        return f"{Colors.MAGENTA}StringLiteral{Colors.RESET}: \"{escaped}\"", []

    if isinstance(node, BoolLiteral):
        return f"{Colors.MAGENTA}BoolLiteral{Colors.RESET}: {str(node.value).lower()}", []

    if isinstance(node, FunctionCall):
        label = f"{Colors.CYAN}Call{Colors.RESET}: {Colors.GREEN}{node.name}{Colors.RESET}()"
        for idx, arg in enumerate(node.args):
            children.append((f"arg[{idx}]", arg))
        return label, children

    if isinstance(node, MethodCall):
        label = f"{Colors.CYAN}MethodCall{Colors.RESET}: .{Colors.GREEN}{node.method_name}{Colors.RESET}()"
        obj = getattr(node, "object_expr", None) or getattr(node, "obj", None)
        if obj:
            children.append(("obj", obj))
        for idx, arg in enumerate(node.args):
            children.append((f"arg[{idx}]", arg))
        return label, children

    if isinstance(node, ArrayAccess):
        label = f"{Colors.CYAN}ArrayAccess{Colors.RESET}: {Colors.GREEN}{node.name}{Colors.RESET}[]"
        if getattr(node, "indices", None) and len(node.indices) > 1:
            for idx_i, idx_node in enumerate(node.indices):
                children.append((f"index[{idx_i}]", idx_node))
        else:
            children.append(("index", node.index))
        return label, children

    if isinstance(node, ArrayAssignment):
        label = f"{Colors.YELLOW}ArrayAssignment{Colors.RESET}: {Colors.GREEN}{node.name}{Colors.RESET}[] ="
        if getattr(node, "indices", None) and len(node.indices) > 1:
            for idx_i, idx_node in enumerate(node.indices):
                children.append((f"index[{idx_i}]", idx_node))
        else:
            children.append(("index", node.index))
        children.append(("val", node.expr))
        return label, children

    if isinstance(node, MemberAccess):
        label = f"{Colors.CYAN}MemberAccess{Colors.RESET}: .{node.member}"
        children.append(("obj", node.object_expr))
        return label, children

    if isinstance(node, MemberAssignment):
        label = f"{Colors.YELLOW}MemberAssignment{Colors.RESET}: .{node.member} ="
        children.append(("obj", node.object_expr))
        children.append(("val", node.expr))
        return label, children

    if isinstance(node, PreIncrement):
        label = f"{Colors.CYAN}PreIncrement{Colors.RESET} (++x)"
        children.append((None, node.target))
        return label, children

    if isinstance(node, PreDecrement):
        label = f"{Colors.CYAN}PreDecrement{Colors.RESET} (--x)"
        children.append((None, node.target))
        return label, children

    if isinstance(node, PostIncrement):
        label = f"{Colors.CYAN}PostIncrement{Colors.RESET} (x++)"
        children.append((None, node.target))
        return label, children

    if isinstance(node, PostDecrement):
        label = f"{Colors.CYAN}PostDecrement{Colors.RESET} (x--)"
        children.append((None, node.target))
        return label, children

    if isinstance(node, CastExpression):
        label = f"{Colors.CYAN}Cast{Colors.RESET} to {Colors.YELLOW}{node.target_type}{Colors.RESET}"
        children.append((None, node.expr))
        return label, children

    if isinstance(node, ScopeResolution):
        return f"{Colors.CYAN}ScopeResolution{Colors.RESET}: {node.namespace}::{node.member}", []

    # Fallback generic AST Node reflection
    label = f"{Colors.CYAN}{name}{Colors.RESET}"
    for k, v in vars(node).items():
        if k in ("line", "col"):
            continue
        if isinstance(v, ASTNode):
            children.append((k, v))
        elif isinstance(v, list) and v and isinstance(v[0], ASTNode):
            for idx, item in enumerate(v):
                children.append((f"{k}[{idx}]", item))
        elif not isinstance(v, (ASTNode, list, dict)):
            label += f" {Colors.DIM}{k}={v}{Colors.RESET}"

    return label, children
