from abc import ABC
from typing import List, Optional, Any

class ASTNode(ABC):
    """Base AST node.

    ``line``/``col`` are the node's *original* (physical) coordinates inside
    ``file``; they are what diagnostics, engines and patches use.  The parser
    stamps ``analysis_line``/``analysis_col`` (coordinates in the expanded
    analysis text) and ``macro_generated`` when it finishes parsing.
    """
    def __init__(self, line: int, col: int, file: Optional[str] = None):
        self.line = line
        self.col = col
        self.file = file
        self.analysis_line = line
        self.analysis_col = col
        self.macro_generated = False

    @property
    def source_line(self) -> int:
        return self.line

    @source_line.setter
    def source_line(self, value: int) -> None:
        self.line = value

    @property
    def source_col(self) -> int:
        return self.col

    @source_col.setter
    def source_col(self, value: int) -> None:
        self.col = value

class Expression(ASTNode):
    is_parenthesized: bool = False

class Statement(ASTNode):
    pass

# --- Expressions ---
class IntLiteral(Expression):
    def __init__(self, value: int, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.value = value

class FloatLiteral(Expression):
    def __init__(self, value: float, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.value = value

class StringLiteral(Expression):
    def __init__(self, value: str, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.value = value

class Identifier(Expression):
    def __init__(self, name: str, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.name = name

class BinaryOp(Expression):
    def __init__(self, left: Expression, op: str, right: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.left = left
        self.op = op
        self.right = right

class UnaryOp(Expression):
    def __init__(self, op: str, expr: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.op = op
        self.expr = expr

class FunctionCall(Expression):
    def __init__(self, name: str, args: List[Expression], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.name = name
        self.args = args

class Assignment(Expression):
    def __init__(self, target: str, expr: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.target = target
        self.expr = expr

class ArrayAccess(Expression):
    def __init__(self, name: str, index: Expression, line: int, col: int, indices: Optional[List[Expression]] = None, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.name = name
        self.index = index
        self.indices = indices if indices is not None else [index]

class ArrayAssignment(Expression):
    def __init__(self, name: str, index: Expression, expr: Expression, line: int, col: int, indices: Optional[List[Expression]] = None, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.name = name
        self.index = index
        self.expr = expr
        self.indices = indices if indices is not None else [index]

class CastExpression(Expression):
    def __init__(self, target_type: str, expr: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.target_type = target_type
        self.expr = expr

class MemberAccess(Expression):
    def __init__(self, object_expr: Expression, member: str, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.object_expr = object_expr
        self.member = member

class MemberAssignment(Expression):
    def __init__(self, object_expr: Expression, member: str, expr: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.object_expr = object_expr
        self.member = member
        self.expr = expr

class PreIncrement(Expression):
    def __init__(self, target: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.target = target

class PreDecrement(Expression):
    def __init__(self, target: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.target = target

class PostIncrement(Expression):
    def __init__(self, target: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.target = target

class PostDecrement(Expression):
    def __init__(self, target: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.target = target

class TernaryOp(Expression):
    def __init__(self, condition: Expression, true_expr: Expression, false_expr: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.condition = condition
        self.true_expr = true_expr
        self.false_expr = false_expr

class AddressOf(Expression):
    def __init__(self, expr: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.expr = expr

class Deref(Expression):
    def __init__(self, expr: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.expr = expr

class DerefAssignment(Expression):
    def __init__(self, target: Expression, expr: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.target = target
        self.expr = expr

class BoolLiteral(Expression):
    def __init__(self, value: bool, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.value = value

class ThisExpr(Expression):
    def __init__(self, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)

class NewExpr(Expression):
    def __init__(self, type_name: str, args: List[Expression], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.type_name = type_name
        self.args = args

class MethodCall(Expression):
    def __init__(self, object_expr: Expression, method_name: str, args: List[Expression], is_arrow: bool = False, line: int = 1, col: int = 1, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.object_expr = object_expr
        self.method_name = method_name
        self.args = args
        self.is_arrow = is_arrow

class ArrowAccess(Expression):
    def __init__(self, object_expr: Expression, member: str, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.object_expr = object_expr
        self.member = member

class ArrowAssignment(Expression):
    def __init__(self, object_expr: Expression, member: str, expr: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.object_expr = object_expr
        self.member = member
        self.expr = expr

class ScopeResolution(Expression):
    def __init__(self, namespace: str, member: str, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.namespace = namespace
        self.member = member

# --- Statements ---
class Block(Statement):
    def __init__(self, statements: List[Statement], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.statements = statements

class VarDeclaration(Statement):
    def __init__(self, var_type: str, name: str, initializer: Optional[Expression], line: int, col: int, is_const: bool = False, is_reference: bool = False, is_constexpr: bool = False, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.var_type = var_type
        self.name = name
        self.initializer = initializer
        self.is_const = is_const
        self.is_reference = is_reference
        self.is_constexpr = is_constexpr

class MultiVarDeclaration(Statement):
    """A single C++ declaration statement containing multiple declarators."""
    def __init__(self, declarations: List[VarDeclaration], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.declarations = declarations

class ExpressionStatement(Statement):
    def __init__(self, expr: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.expr = expr

class IfStatement(Statement):
    def __init__(self, condition: Expression, then_branch: Statement, else_branch: Optional[Statement], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.condition = condition
        self.then_branch = then_branch
        self.else_branch = else_branch

class WhileStatement(Statement):
    def __init__(self, condition: Expression, body: Statement, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.condition = condition
        self.body = body

class ForStatement(Statement):
    def __init__(self, init: Optional[Statement], condition: Optional[Expression], update: Optional[Expression], body: Statement, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.init = init
        self.condition = condition
        self.update = update
        self.body = body

class ReturnStatement(Statement):
    def __init__(self, expr: Optional[Expression], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.expr = expr

class ArrayDeclaration(Statement):
    def __init__(self, var_type: str, name: str, size: Optional[int], elements: Optional[List[Expression]], line: int, col: int, dimensions: Optional[List[int]] = None, size_expr: Optional[Expression] = None, dim_exprs: Optional[List[Expression]] = None, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.var_type = var_type
        self.name = name
        self.size = size
        self.elements = elements
        self.size_expr = size_expr
        self.dim_exprs = dim_exprs if dim_exprs is not None else ([size_expr] if size_expr is not None else [])
        if dimensions is not None:
            self.dimensions = dimensions
            if self.size is None and len(dimensions) > 0:
                self.size = dimensions[0]
        else:
            self.dimensions = [size] if size is not None else []

class DoWhileStatement(Statement):
    def __init__(self, body: Statement, condition: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.body = body
        self.condition = condition

class BreakStatement(Statement):
    pass

class ContinueStatement(Statement):
    pass

class CaseClause(ASTNode):
    def __init__(self, value: Optional[Expression], statements: List[Statement], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.value = value
        self.statements = statements

class SwitchStatement(Statement):
    def __init__(self, expr: Expression, cases: List[CaseClause], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.expr = expr
        self.cases = cases

class StructDef(Statement):
    def __init__(self, name: str, members: List['Parameter'], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.name = name
        self.members = members

class StructDeclaration(Statement):
    def __init__(self, struct_name: str, name: str, elements: Optional[List[Expression]], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.struct_name = struct_name
        self.name = name
        self.elements = elements

class EnumDef(Statement):
    def __init__(self, name: str, enumerators: List[tuple], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.name = name
        self.enumerators = enumerators

class DeleteStatement(Statement):
    def __init__(self, expr: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.expr = expr

class ClassMember(ASTNode):
    def __init__(self, decl: ASTNode, access: str, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.decl = decl
        self.access = access # "public", "private", "protected"

class ConstructorDef(ASTNode):
    def __init__(self, class_name: str, params: List['Parameter'], body: Optional['Block'], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.class_name = class_name
        self.params = params
        self.body = body

class DestructorDef(ASTNode):
    def __init__(self, class_name: str, body: Optional['Block'], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.class_name = class_name
        self.body = body

class ClassDef(Statement):
    def __init__(self, name: str, members: List[ClassMember], line: int, col: int, base_class: Optional[str] = None, base_access: str = "public", file: Optional[str] = None):
        super().__init__(line, col, file)
        self.name = name
        self.members = members
        self.base_class = base_class
        self.base_access = base_access

class ClassInstanceDeclaration(Statement):
    def __init__(self, class_name: str, name: str, args: List[Expression], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.class_name = class_name
        self.name = name
        self.args = args

class NamespaceDef(ASTNode):
    def __init__(self, name: str, declarations: List[ASTNode], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.name = name
        self.declarations = declarations

class UsingNamespace(Statement):
    def __init__(self, name: str, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.name = name

class UsingDeclaration(Statement):
    def __init__(self, namespace: str, member: str, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.namespace = namespace
        self.member = member

class TemplateDef(ASTNode):
    def __init__(self, template_params: List[str], decl: ASTNode, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.template_params = template_params
        self.decl = decl

class TryCatchStatement(Statement):
    def __init__(self, try_block: 'Block', catch_clauses: List['CatchClause'], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.try_block = try_block
        self.catch_clauses = catch_clauses

class CatchClause(ASTNode):
    def __init__(self, param_type: str, param_name: str, body: 'Block', line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.param_type = param_type
        self.param_name = param_name
        self.body = body

class ThrowStatement(Statement):
    def __init__(self, expr: Expression, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.expr = expr

class RangeForStatement(Statement):
    def __init__(self, var_type: str, var_name: str, iterable: Expression, body: Statement, line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.var_type = var_type
        self.var_name = var_name
        self.iterable = iterable
        self.body = body

class LambdaExpr(Expression):
    def __init__(self, captures: List[str], params: List['Parameter'], return_type: Optional[str], body: 'Block', line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.captures = captures
        self.params = params
        self.return_type = return_type
        self.body = body

# --- Top Level ---
class Parameter(ASTNode):
    def __init__(self, param_type: str, name: str, line: int, col: int, is_const: bool = False, is_reference: bool = False, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.param_type = param_type
        self.name = name
        self.is_const = is_const
        self.is_reference = is_reference

class FunctionDef(ASTNode):
    def __init__(self, return_type: str, name: str, params: List[Parameter], body: Optional['Block'] = None, line: int = 1, col: int = 1, is_method: bool = False, class_name: Optional[str] = None, is_virtual: bool = False, is_pure_virtual: bool = False, is_override: bool = False, is_constexpr: bool = False, is_always_inline: bool = False, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.return_type = return_type
        self.name = name
        self.params = params
        self.body = body
        self.is_method = is_method
        self.class_name = class_name
        self.is_virtual = is_virtual
        self.is_pure_virtual = is_pure_virtual
        self.is_override = is_override
        self.is_constexpr = is_constexpr
        self.is_always_inline = is_always_inline

class Program(ASTNode):
    def __init__(self, declarations: List[ASTNode], line: int, col: int, file: Optional[str] = None):
        super().__init__(line, col, file)
        self.declarations = declarations  # functions, classes, namespaces, global vars, templates

    @property
    def functions(self):
        return [d for d in self.declarations if isinstance(d, FunctionDef)]

    @property
    def classes(self):
        return [d for d in self.declarations if isinstance(d, ClassDef)]

    @property
    def namespaces(self):
        return [d for d in self.declarations if isinstance(d, NamespaceDef)]

    @property
    def templates(self):
        return [d for d in self.declarations if isinstance(d, TemplateDef)]


