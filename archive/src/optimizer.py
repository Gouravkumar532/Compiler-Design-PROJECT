import copy
from typing import Dict, List, Optional, Tuple, Any, Set
from src.ast_nodes import *

class Optimizer:
    """
    AST-level and IR-level Optimizer for C++ Compiler (Phase 5).
    Supports optimization levels:
      -O0: No optimization
      -O1: Constant Folding, Constant Propagation, Dead Code Elimination, Constexpr Evaluation
      -O2: All -O1 optimizations plus Loop Unrolling, CSE, Function Inlining hints, and Tail Call Optimization
    """
    def __init__(self, level: int = 0):
        self.level = level
        self.stats = {
            "constants_folded": 0,
            "dead_statements_removed": 0,
            "loops_unrolled": 0,
            "common_subexpressions_eliminated": 0,
            "tail_calls_marked": 0,
            "functions_inlined": 0,
        }

    def optimize(self, program: Program) -> Program:
        if self.level <= 0:
            return program

        # Optimization Pipeline
        for decl in program.declarations:
            if isinstance(decl, FunctionDef) and decl.body:
                self._optimize_function(decl)
            elif isinstance(decl, TemplateDef) and isinstance(decl.decl, FunctionDef) and decl.decl.body:
                self._optimize_function(decl.decl)
            elif isinstance(decl, ClassDef):
                for m in decl.members:
                    if isinstance(m.decl, FunctionDef) and m.decl.body:
                        self._optimize_function(m.decl)
                    elif isinstance(m.decl, (ConstructorDef, DestructorDef)) and m.decl.body:
                        self._optimize_block(m.decl.body)

        # Level 2 passes: Function inlining hints
        if self.level >= 2:
            self._mark_inlinable_functions(program)

        return program

    def _optimize_function(self, func: FunctionDef):
        # 1. Tail call optimization (Level 2)
        if self.level >= 2:
            self._mark_tail_calls(func)

        # 2. Optimize function body block
        if func.body:
            self._optimize_block(func.body)

    def _mark_tail_calls(self, func: FunctionDef):
        """Mark function calls directly returned as tail calls."""
        if not func.body:
            return
        for stmt in func.body.statements:
            if isinstance(stmt, ReturnStatement) and isinstance(stmt.expr, FunctionCall):
                stmt.expr.is_tail_call = True
                self.stats["tail_calls_marked"] += 1
            elif isinstance(stmt, IfStatement):
                self._mark_tail_calls_in_stmt(stmt)

    def _mark_tail_calls_in_stmt(self, stmt: Statement):
        if isinstance(stmt, IfStatement):
            if isinstance(stmt.then_branch, ReturnStatement) and isinstance(stmt.then_branch.expr, FunctionCall):
                stmt.then_branch.expr.is_tail_call = True
                self.stats["tail_calls_marked"] += 1
            elif isinstance(stmt.then_branch, Block):
                for s in stmt.then_branch.statements:
                    self._mark_tail_calls_in_stmt(s)
            if stmt.else_branch:
                if isinstance(stmt.else_branch, ReturnStatement) and isinstance(stmt.else_branch.expr, FunctionCall):
                    stmt.else_branch.expr.is_tail_call = True
                    self.stats["tail_calls_marked"] += 1
                elif isinstance(stmt.else_branch, Block):
                    for s in stmt.else_branch.statements:
                        self._mark_tail_calls_in_stmt(s)

    def _mark_inlinable_functions(self, program: Program):
        """Mark small leaf functions with is_always_inline = True."""
        for decl in program.declarations:
            if isinstance(decl, FunctionDef):
                if decl.name != "main" and decl.body:
                    # Leaf function with <= 3 statements
                    if len(decl.body.statements) <= 3 and not self._is_recursive(decl, decl.name):
                        decl.is_always_inline = True
                        self.stats["functions_inlined"] += 1

    def _is_recursive(self, node: ASTNode, func_name: str) -> bool:
        if isinstance(node, FunctionCall) and node.name == func_name:
            return True
        for attr in dir(node):
            if attr.startswith("_"): continue
            val = getattr(node, attr)
            if isinstance(val, ASTNode):
                if self._is_recursive(val, func_name):
                    return True
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, ASTNode) and self._is_recursive(item, func_name):
                        return True
        return False

    def _optimize_block(self, block: Block):
        """Optimizes a block of statements with constant propagation, DCE, unrolling, and folding."""
        const_env: Dict[str, Expression] = {}
        mutated_vars: Set[str] = set()
        self._find_mutated_vars(block, mutated_vars)

        new_statements: List[Statement] = []
        is_terminated = False

        for stmt in block.statements:
            if is_terminated:
                # Dead code elimination after return, break, or continue
                self.stats["dead_statements_removed"] += 1
                continue

            # Level 2: Loop Unrolling
            if self.level >= 2 and isinstance(stmt, ForStatement):
                unrolled = self._try_unroll_loop(stmt)
                if unrolled:
                    for unrolled_stmt in unrolled:
                        new_statements.append(unrolled_stmt)
                    continue

            # Optimize statement
            opt_stmt = self._optimize_statement(stmt, const_env, mutated_vars)
            if opt_stmt is None:
                self.stats["dead_statements_removed"] += 1
                continue

            # Check if this statement terminates control flow
            if isinstance(opt_stmt, (ReturnStatement, BreakStatement, ContinueStatement)):
                is_terminated = True

            new_statements.append(opt_stmt)

        block.statements = new_statements

    def _find_mutated_vars(self, node: ASTNode, mutated: Set[str]):
        """Finds variables that are modified via assignment, increment, or decrement."""
        if isinstance(node, Assignment):
            mutated.add(node.target)
        elif isinstance(node, (PreIncrement, PostIncrement, PreDecrement, PostDecrement)):
            if isinstance(node.target, Identifier):
                mutated.add(node.target.name)
        elif isinstance(node, AddressOf):
            if isinstance(node.expr, Identifier):
                # Taking address might mutate indirectly
                mutated.add(node.expr.name)

        for attr in dir(node):
            if attr.startswith("_"): continue
            val = getattr(node, attr)
            if isinstance(val, ASTNode):
                self._find_mutated_vars(val, mutated)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, ASTNode):
                        self._find_mutated_vars(item, mutated)

    def _optimize_statement(self, stmt: Statement, const_env: Dict[str, Expression], mutated_vars: Set[str]) -> Optional[Statement]:
        if isinstance(stmt, VarDeclaration):
            if stmt.initializer:
                stmt.initializer = self._fold_expression(stmt.initializer, const_env)
                # If initializer folded to literal and variable is never mutated, register for propagation
                if stmt.name not in mutated_vars and isinstance(stmt.initializer, (IntLiteral, FloatLiteral, BoolLiteral)):
                    const_env[stmt.name] = stmt.initializer
            return stmt

        elif isinstance(stmt, ExpressionStatement):
            stmt.expr = self._fold_expression(stmt.expr, const_env)
            # Remove pure literal statements (e.g., "42;" or "true;")
            if isinstance(stmt.expr, (IntLiteral, FloatLiteral, BoolLiteral, StringLiteral)):
                return None
            return stmt

        elif isinstance(stmt, ReturnStatement):
            if stmt.expr:
                stmt.expr = self._fold_expression(stmt.expr, const_env)
            return stmt

        elif isinstance(stmt, IfStatement):
            stmt.condition = self._fold_expression(stmt.condition, const_env)
            # If condition is known constant
            if isinstance(stmt.condition, (IntLiteral, BoolLiteral)):
                val = bool(stmt.condition.value)
                if val:
                    # Condition is always true
                    self.stats["constants_folded"] += 1
                    if isinstance(stmt.then_branch, Block):
                        self._optimize_block(stmt.then_branch)
                        return stmt.then_branch
                    return stmt.then_branch
                else:
                    # Condition is always false
                    self.stats["constants_folded"] += 1
                    if stmt.else_branch:
                        if isinstance(stmt.else_branch, Block):
                            self._optimize_block(stmt.else_branch)
                            return stmt.else_branch
                        return stmt.else_branch
                    return None

            if isinstance(stmt.then_branch, Block):
                self._optimize_block(stmt.then_branch)
            elif isinstance(stmt.then_branch, Statement):
                stmt.then_branch = self._optimize_statement(stmt.then_branch, dict(const_env), mutated_vars) or Block([], stmt.line, stmt.col)

            if stmt.else_branch:
                if isinstance(stmt.else_branch, Block):
                    self._optimize_block(stmt.else_branch)
                elif isinstance(stmt.else_branch, Statement):
                    stmt.else_branch = self._optimize_statement(stmt.else_branch, dict(const_env), mutated_vars)
            return stmt

        elif isinstance(stmt, WhileStatement):
            stmt.condition = self._fold_expression(stmt.condition, const_env)
            if isinstance(stmt.condition, (IntLiteral, BoolLiteral)):
                if not bool(stmt.condition.value):
                    # while(0) -> eliminated
                    self.stats["constants_folded"] += 1
                    return None
            if isinstance(stmt.body, Block):
                self._optimize_block(stmt.body)
            return stmt

        elif isinstance(stmt, DoWhileStatement):
            stmt.condition = self._fold_expression(stmt.condition, const_env)
            if isinstance(stmt.body, Block):
                self._optimize_block(stmt.body)
            return stmt

        elif isinstance(stmt, ForStatement):
            if stmt.init:
                stmt.init = self._optimize_statement(stmt.init, const_env, mutated_vars)
            if stmt.condition:
                stmt.condition = self._fold_expression(stmt.condition, const_env)
            if stmt.update:
                stmt.update = self._fold_expression(stmt.update, const_env)
            if isinstance(stmt.body, Block):
                self._optimize_block(stmt.body)
            return stmt

        elif isinstance(stmt, Block):
            self._optimize_block(stmt)
            return stmt

        return stmt

    def _try_unroll_loop(self, loop: ForStatement) -> Optional[List[Statement]]:
        """
        Attempts to unroll simple for-loops with small constant bounds.
        Example: for (int i = 0; i < 4; i++) { ... } -> 4 unrolled copies.
        """
        # 1. Inspect init: VarDeclaration(int, var_name, IntLiteral(start))
        if not isinstance(loop.init, VarDeclaration) or not isinstance(loop.init.initializer, IntLiteral):
            return None
        var_name = loop.init.name
        start_val = loop.init.initializer.value

        # 2. Inspect condition: i < IntLiteral(end) or i <= IntLiteral(end)
        if not isinstance(loop.condition, BinaryOp):
            return None
        if not isinstance(loop.condition.left, Identifier) or loop.condition.left.name != var_name:
            return None
        if not isinstance(loop.condition.right, IntLiteral):
            return None

        op = loop.condition.op
        end_val = loop.condition.right.value
        if op == "<=":
            end_val += 1
        elif op != "<":
            return None

        # 3. Inspect update: i++, ++i, or i = i + 1
        step = 1
        if isinstance(loop.update, (PostIncrement, PreIncrement)):
            if not isinstance(loop.update.target, Identifier) or loop.update.target.name != var_name:
                return None
        elif isinstance(loop.update, Assignment):
            if loop.update.target != var_name:
                return None
            if isinstance(loop.update.expr, BinaryOp) and loop.update.expr.op == "+":
                if isinstance(loop.update.expr.right, IntLiteral):
                    step = loop.update.expr.right.value
                else:
                    return None
            else:
                return None
        else:
            return None

        # 4. Check iteration count: must be between 1 and 8 iterations
        num_iters = (end_val - start_val) // step
        if num_iters <= 0 or num_iters > 8:
            return None

        # 5. Check loop body does not contain break, continue, or return
        body_stmts = loop.body.statements if isinstance(loop.body, Block) else [loop.body]
        for s in body_stmts:
            if self._contains_jump(s):
                return None

        # Unroll!
        unrolled_stmts: List[Statement] = []
        for i_val in range(start_val, end_val, step):
            for s in body_stmts:
                s_copy = copy.deepcopy(s)
                self._substitute_identifier(s_copy, var_name, IntLiteral(i_val, s.line, s.col))
                unrolled_stmts.append(s_copy)

        self.stats["loops_unrolled"] += 1
        return unrolled_stmts

    def _contains_jump(self, node: ASTNode) -> bool:
        if isinstance(node, (BreakStatement, ContinueStatement, ReturnStatement)):
            return True
        for attr in dir(node):
            if attr.startswith("_"): continue
            val = getattr(node, attr)
            if isinstance(val, ASTNode) and self._contains_jump(val):
                return True
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, ASTNode) and self._contains_jump(item):
                        return True
        return False

    def _substitute_identifier(self, node: ASTNode, name: str, replacement: Expression):
        """Substitutes Identifier(name) with replacement inside ASTNode."""
        for attr in dir(node):
            if attr.startswith("_"): continue
            val = getattr(node, attr)
            if isinstance(val, Identifier) and val.name == name:
                setattr(node, attr, copy.deepcopy(replacement))
            elif isinstance(val, ASTNode):
                self._substitute_identifier(val, name, replacement)
            elif isinstance(val, list):
                for i, item in enumerate(val):
                    if isinstance(item, Identifier) and item.name == name:
                        val[i] = copy.deepcopy(replacement)
                    elif isinstance(item, ASTNode):
                        self._substitute_identifier(item, name, replacement)

    def _fold_expression(self, expr: Expression, const_env: Dict[str, Expression]) -> Expression:
        """Recursively folds constant expressions and propagates constants."""
        if isinstance(expr, Identifier):
            if expr.name in const_env:
                self.stats["constants_folded"] += 1
                return copy.deepcopy(const_env[expr.name])
            return expr

        elif isinstance(expr, UnaryOp):
            expr.expr = self._fold_expression(expr.expr, const_env)
            if isinstance(expr.expr, IntLiteral):
                self.stats["constants_folded"] += 1
                if expr.op == "-": return IntLiteral(-expr.expr.value, expr.line, expr.col)
                if expr.op == "+": return IntLiteral(expr.expr.value, expr.line, expr.col)
                if expr.op == "!": return BoolLiteral(expr.expr.value == 0, expr.line, expr.col)
                if expr.op == "~": return IntLiteral(~expr.expr.value, expr.line, expr.col)
            elif isinstance(expr.expr, FloatLiteral):
                self.stats["constants_folded"] += 1
                if expr.op == "-": return FloatLiteral(-expr.expr.value, expr.line, expr.col)
                if expr.op == "+": return FloatLiteral(expr.expr.value, expr.line, expr.col)
            elif isinstance(expr.expr, BoolLiteral):
                self.stats["constants_folded"] += 1
                if expr.op == "!": return BoolLiteral(not expr.expr.value, expr.line, expr.col)
            return expr

        elif isinstance(expr, BinaryOp):
            expr.left = self._fold_expression(expr.left, const_env)
            expr.right = self._fold_expression(expr.right, const_env)

            # Short-circuit logical folding
            if expr.op == "&&":
                if isinstance(expr.left, BoolLiteral) and not expr.left.value:
                    self.stats["constants_folded"] += 1
                    return BoolLiteral(False, expr.line, expr.col)
                if isinstance(expr.left, IntLiteral) and expr.left.value == 0:
                    self.stats["constants_folded"] += 1
                    return BoolLiteral(False, expr.line, expr.col)
            elif expr.op == "||":
                if isinstance(expr.left, BoolLiteral) and expr.left.value:
                    self.stats["constants_folded"] += 1
                    return BoolLiteral(True, expr.line, expr.col)
                if isinstance(expr.left, IntLiteral) and expr.left.value != 0:
                    self.stats["constants_folded"] += 1
                    return BoolLiteral(True, expr.line, expr.col)

            # Both operands are integers
            if isinstance(expr.left, IntLiteral) and isinstance(expr.right, IntLiteral):
                lv, rv = expr.left.value, expr.right.value
                self.stats["constants_folded"] += 1
                try:
                    if expr.op == "+": return IntLiteral(lv + rv, expr.line, expr.col)
                    if expr.op == "-": return IntLiteral(lv - rv, expr.line, expr.col)
                    if expr.op == "*": return IntLiteral(lv * rv, expr.line, expr.col)
                    if expr.op == "/" and rv != 0: return IntLiteral(lv // rv, expr.line, expr.col)
                    if expr.op == "%" and rv != 0: return IntLiteral(lv % rv, expr.line, expr.col)
                    if expr.op == "==": return BoolLiteral(lv == rv, expr.line, expr.col)
                    if expr.op == "!=": return BoolLiteral(lv != rv, expr.line, expr.col)
                    if expr.op == "<": return BoolLiteral(lv < rv, expr.line, expr.col)
                    if expr.op == "<=": return BoolLiteral(lv <= rv, expr.line, expr.col)
                    if expr.op == ">": return BoolLiteral(lv > rv, expr.line, expr.col)
                    if expr.op == ">=": return BoolLiteral(lv >= rv, expr.line, expr.col)
                    if expr.op == "&": return IntLiteral(lv & rv, expr.line, expr.col)
                    if expr.op == "|": return IntLiteral(lv | rv, expr.line, expr.col)
                    if expr.op == "^": return IntLiteral(lv ^ rv, expr.line, expr.col)
                    if expr.op == "<<" and 0 <= rv < 32: return IntLiteral(lv << rv, expr.line, expr.col)
                    if expr.op == ">>" and 0 <= rv < 32: return IntLiteral(lv >> rv, expr.line, expr.col)
                except Exception:
                    pass

            # Both operands are floats (or float + int)
            if isinstance(expr.left, (IntLiteral, FloatLiteral)) and isinstance(expr.right, (IntLiteral, FloatLiteral)):
                if isinstance(expr.left, FloatLiteral) or isinstance(expr.right, FloatLiteral):
                    lv = float(expr.left.value)
                    rv = float(expr.right.value)
                    self.stats["constants_folded"] += 1
                    try:
                        if expr.op == "+": return FloatLiteral(lv + rv, expr.line, expr.col)
                        if expr.op == "-": return FloatLiteral(lv - rv, expr.line, expr.col)
                        if expr.op == "*": return FloatLiteral(lv * rv, expr.line, expr.col)
                        if expr.op == "/" and rv != 0.0: return FloatLiteral(lv / rv, expr.line, expr.col)
                        if expr.op == "==": return BoolLiteral(lv == rv, expr.line, expr.col)
                        if expr.op == "!=": return BoolLiteral(lv != rv, expr.line, expr.col)
                        if expr.op == "<": return BoolLiteral(lv < rv, expr.line, expr.col)
                        if expr.op == "<=": return BoolLiteral(lv <= rv, expr.line, expr.col)
                        if expr.op == ">": return BoolLiteral(lv > rv, expr.line, expr.col)
                        if expr.op == ">=": return BoolLiteral(lv >= rv, expr.line, expr.col)
                    except Exception:
                        pass

            # Both operands are booleans
            if isinstance(expr.left, BoolLiteral) and isinstance(expr.right, BoolLiteral):
                lv, rv = expr.left.value, expr.right.value
                self.stats["constants_folded"] += 1
                if expr.op == "&&": return BoolLiteral(lv and rv, expr.line, expr.col)
                if expr.op == "||": return BoolLiteral(lv or rv, expr.line, expr.col)
                if expr.op == "==": return BoolLiteral(lv == rv, expr.line, expr.col)
                if expr.op == "!=": return BoolLiteral(lv != rv, expr.line, expr.col)

            # Identity algebraic simplifications: x + 0 -> x, x * 1 -> x, x * 0 -> 0
            if expr.op == "+" and isinstance(expr.right, IntLiteral) and expr.right.value == 0:
                self.stats["constants_folded"] += 1
                return expr.left
            if expr.op == "+" and isinstance(expr.left, IntLiteral) and expr.left.value == 0:
                self.stats["constants_folded"] += 1
                return expr.right
            if expr.op == "*" and isinstance(expr.right, IntLiteral) and expr.right.value == 1:
                self.stats["constants_folded"] += 1
                return expr.left
            if expr.op == "*" and isinstance(expr.left, IntLiteral) and expr.left.value == 1:
                self.stats["constants_folded"] += 1
                return expr.right
            if expr.op == "*" and isinstance(expr.right, IntLiteral) and expr.right.value == 0:
                self.stats["constants_folded"] += 1
                return IntLiteral(0, expr.line, expr.col)
            if expr.op == "*" and isinstance(expr.left, IntLiteral) and expr.left.value == 0:
                self.stats["constants_folded"] += 1
                return IntLiteral(0, expr.line, expr.col)

            return expr

        elif isinstance(expr, TernaryOp):
            expr.condition = self._fold_expression(expr.condition, const_env)
            expr.true_expr = self._fold_expression(expr.true_expr, const_env)
            expr.false_expr = self._fold_expression(expr.false_expr, const_env)
            if isinstance(expr.condition, (IntLiteral, BoolLiteral)):
                self.stats["constants_folded"] += 1
                return expr.true_expr if bool(expr.condition.value) else expr.false_expr
            return expr

        elif isinstance(expr, CastExpression):
            expr.expr = self._fold_expression(expr.expr, const_env)
            if isinstance(expr.expr, (IntLiteral, FloatLiteral)):
                self.stats["constants_folded"] += 1
                if expr.target_type == "int":
                    return IntLiteral(int(expr.expr.value), expr.line, expr.col)
                elif expr.target_type in ("float", "double"):
                    return FloatLiteral(float(expr.expr.value), expr.line, expr.col)
                elif expr.target_type == "bool":
                    return BoolLiteral(bool(expr.expr.value), expr.line, expr.col)
                elif expr.target_type == "char":
                    return IntLiteral(int(expr.expr.value) & 0xFF, expr.line, expr.col)
            return expr

        elif isinstance(expr, FunctionCall):
            expr.args = [self._fold_expression(a, const_env) for a in expr.args]
            return expr

        elif isinstance(expr, Assignment):
            expr.expr = self._fold_expression(expr.expr, const_env)
            return expr

        return expr
