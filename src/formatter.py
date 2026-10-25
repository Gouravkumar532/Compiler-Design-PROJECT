"""Built-in code formatter for C++ source files (Phases 0, 1, 2, and 3)."""

from typing import List
from src.ast_nodes import *

class Formatter:
    def __init__(self, indent_size: int = 4):
        self.indent_size = indent_size
        self.indent_level = 0
        self.lines: List[str] = []

    def format(self, program: Program) -> str:
        self.lines = []
        for i, decl in enumerate(program.declarations):
            if isinstance(decl, StructDef):
                self.format_struct_def(decl)
                self.lines.append("")
            elif isinstance(decl, ClassDef):
                self.format_class_def(decl)
                self.lines.append("")
            elif isinstance(decl, TemplateDef):
                self.format_template_def(decl)
                self.lines.append("")
            elif isinstance(decl, NamespaceDef):
                self.format_namespace_def(decl)
                self.lines.append("")
            elif isinstance(decl, EnumDef):
                self.format_enum_def(decl)
                self.lines.append("")
            elif isinstance(decl, FunctionDef):
                self.format_function_def(decl)
                if i < len(program.declarations) - 1:
                    self.lines.append("")
            elif isinstance(decl, Statement):
                self.lines.append(self._indent() + self.format_statement(decl))
        return "\n".join(self.lines).rstrip() + "\n"

    def format_source(self, source: str, filename: str = "main.cpp") -> str:
        """Formats a full C++ source file, safely preserving preprocessor directives."""
        from src.preprocessor import Preprocessor
        from src.lexer import Lexer
        from src.parser import Parser
        from src.diagnostics import DiagnosticSink

        directives = []
        for line in source.splitlines():
            s = line.strip()
            if s.startswith("#include") or s.startswith("#define") or s.startswith("#pragma"):
                directives.append(s)

        silent_sink = DiagnosticSink(emit=False)
        prep = Preprocessor()
        preproc_res = prep.preprocess(source, filename)
        tokens = Lexer(
            preproc_res.analysis_source,
            filename,
            preproc_result=preproc_res,
            diag_sink=silent_sink,
        ).tokenize()
        parser = Parser(
            tokens,
            source,
            filename,
            enable_repair=False,
            preproc_result=preproc_res,
            diag_sink=silent_sink,
        )
        ast = parser.parse()
        if silent_sink.error_count > 0 or getattr(parser, "errors_count", 0) > 0:
            raise ValueError("Cannot format code containing syntax errors.")
        formatted_body = self.format(ast)

        if directives:
            return "\n".join(directives) + "\n\n" + formatted_body.lstrip()
        return formatted_body

    def _indent(self) -> str:
        return " " * (self.indent_level * self.indent_size)

    def format_template_def(self, node: TemplateDef):
        params_str = ", ".join(f"typename {p}" for p in node.template_params)
        self.lines.append(f"{self._indent()}template <{params_str}>")
        if isinstance(node.decl, FunctionDef):
            self.format_function_def(node.decl)
        elif isinstance(node.decl, ClassDef):
            self.format_class_def(node.decl)

    def format_struct_def(self, node: StructDef):
        self.lines.append(f"{self._indent()}struct {node.name} {{")
        self.indent_level += 1
        for m in node.members:
            self.lines.append(f"{self._indent()}{m.param_type} {m.name};")
        self.indent_level -= 1
        self.lines.append(f"{self._indent()}}};")

    def format_class_def(self, node: ClassDef):
        base_clause = f" : {node.base_access} {node.base_class}" if getattr(node, "base_class", None) else ""
        self.lines.append(f"{self._indent()}class {node.name}{base_clause} {{")
        current_access = None
        for m in node.members:
            if m.access != current_access:
                current_access = m.access
                self.lines.append(f"{self._indent()}{current_access}:")
            self.indent_level += 1
            if isinstance(m.decl, ConstructorDef):
                self.format_constructor_def(m.decl)
            elif isinstance(m.decl, DestructorDef):
                self.format_destructor_def(m.decl)
            elif isinstance(m.decl, FunctionDef):
                self.format_function_def(m.decl)
            elif isinstance(m.decl, Statement):
                self.lines.append(self._indent() + self.format_statement(m.decl))
            self.indent_level -= 1
        self.lines.append(f"{self._indent()}}};")

    def format_constructor_def(self, node: ConstructorDef):
        params_str = ", ".join(self._format_param(p) for p in node.params)
        if node.body is None:
            self.lines.append(f"{self._indent()}{node.class_name}({params_str});")
            return
        self.lines.append(f"{self._indent()}{node.class_name}({params_str}) {{")
        self.indent_level += 1
        for stmt in node.body.statements:
            self.format_statement_line(stmt)
        self.indent_level -= 1
        self.lines.append(f"{self._indent()}}}")

    def format_destructor_def(self, node: DestructorDef):
        if node.body is None:
            self.lines.append(f"{self._indent()}~{node.class_name}();")
            return
        self.lines.append(f"{self._indent()}~{node.class_name}() {{")
        self.indent_level += 1
        for stmt in node.body.statements:
            self.format_statement_line(stmt)
        self.indent_level -= 1
        self.lines.append(f"{self._indent()}}}")

    def format_namespace_def(self, node: NamespaceDef):
        self.lines.append(f"{self._indent()}namespace {node.name} {{")
        self.indent_level += 1
        for decl in node.declarations:
            if isinstance(decl, FunctionDef):
                self.format_function_def(decl)
            elif isinstance(decl, ClassDef):
                self.format_class_def(decl)
            elif isinstance(decl, Statement):
                self.lines.append(self._indent() + self.format_statement(decl))
        self.indent_level -= 1
        self.lines.append(f"{self._indent()}}}")

    def format_enum_def(self, node: EnumDef):
        self.lines.append(f"{self._indent()}enum {node.name} {{")
        self.indent_level += 1
        for i, (e_name, e_val) in enumerate(node.enumerators):
            comma = "," if i < len(node.enumerators) - 1 else ""
            self.lines.append(f"{self._indent()}{e_name} = {e_val}{comma}")
        self.indent_level -= 1
        self.lines.append(f"{self._indent()}}};")

    def _format_param(self, p: Parameter) -> str:
        const_str = "const " if p.is_const else ""
        ref_str = "&" if p.is_reference else ""
        return f"{const_str}{p.param_type}{ref_str} {p.name}"

    def format_function_def(self, node: FunctionDef):
        constexpr_str = "constexpr " if getattr(node, "is_constexpr", False) else ""
        virt_str = "virtual " if getattr(node, "is_virtual", False) else ""
        pure_str = " = 0" if getattr(node, "is_pure_virtual", False) else ""
        override_str = " override" if getattr(node, "is_override", False) else ""
        params_str = ", ".join(self._format_param(p) for p in node.params)
        if node.body is None or getattr(node, "is_pure_virtual", False):
            self.lines.append(f"{self._indent()}{constexpr_str}{virt_str}{node.return_type} {node.name}({params_str}){pure_str};")
            return

        self.lines.append(f"{self._indent()}{constexpr_str}{virt_str}{node.return_type} {node.name}({params_str}){override_str} {{")
        self.indent_level += 1
        for stmt in node.body.statements:
            self.format_statement_line(stmt)
        self.indent_level -= 1
        self.lines.append(f"{self._indent()}}}")

    def format_statement_line(self, node: Statement):
        if isinstance(node, IfStatement):
            self.lines.append(f"{self._indent()}if ({self.format_expression(node.condition)}) {{")
            self.indent_level += 1
            if isinstance(node.then_branch, Block):
                for s in node.then_branch.statements:
                    self.format_statement_line(s)
            else:
                self.format_statement_line(node.then_branch)
            self.indent_level -= 1
            if node.else_branch:
                if isinstance(node.else_branch, IfStatement):
                    self.lines.append(f"{self._indent()}}} else if ({self.format_expression(node.else_branch.condition)}) {{")
                    self.indent_level += 1
                    if isinstance(node.else_branch.then_branch, Block):
                        for s in node.else_branch.then_branch.statements:
                            self.format_statement_line(s)
                    else:
                        self.format_statement_line(node.else_branch.then_branch)
                    self.indent_level -= 1
                else:
                    self.lines.append(f"{self._indent()}}} else {{")
                    self.indent_level += 1
                    if isinstance(node.else_branch, Block):
                        for s in node.else_branch.statements:
                            self.format_statement_line(s)
                    else:
                        self.format_statement_line(node.else_branch)
                    self.indent_level -= 1
            self.lines.append(f"{self._indent()}}}")
        elif isinstance(node, WhileStatement):
            self.lines.append(f"{self._indent()}while ({self.format_expression(node.condition)}) {{")
            self.indent_level += 1
            if isinstance(node.body, Block):
                for s in node.body.statements:
                    self.format_statement_line(s)
            else:
                self.format_statement_line(node.body)
            self.indent_level -= 1
            self.lines.append(f"{self._indent()}}}")
        elif isinstance(node, DoWhileStatement):
            self.lines.append(f"{self._indent()}do {{")
            self.indent_level += 1
            if isinstance(node.body, Block):
                for s in node.body.statements:
                    self.format_statement_line(s)
            else:
                self.format_statement_line(node.body)
            self.indent_level -= 1
            self.lines.append(f"{self._indent()}}} while ({self.format_expression(node.condition)});")
        elif isinstance(node, ForStatement):
            init_str = self.format_statement(node.init).rstrip(";") if node.init else ""
            cond_str = self.format_expression(node.condition) if node.condition else ""
            upd_str = self.format_expression(node.update) if node.update else ""
            self.lines.append(f"{self._indent()}for ({init_str}; {cond_str}; {upd_str}) {{")
            self.indent_level += 1
            if isinstance(node.body, Block):
                for s in node.body.statements:
                    self.format_statement_line(s)
            else:
                self.format_statement_line(node.body)
            self.indent_level -= 1
            self.lines.append(f"{self._indent()}}}")
        elif isinstance(node, RangeForStatement):
            self.lines.append(f"{self._indent()}for ({node.var_type} {node.var_name} : {self.format_expression(node.iterable)}) {{")
            self.indent_level += 1
            if isinstance(node.body, Block):
                for s in node.body.statements:
                    self.format_statement_line(s)
            else:
                self.format_statement_line(node.body)
            self.indent_level -= 1
            self.lines.append(f"{self._indent()}}}")
        elif isinstance(node, TryCatchStatement):
            self.lines.append(f"{self._indent()}try {{")
            self.indent_level += 1
            for s in node.try_block.statements:
                self.format_statement_line(s)
            self.indent_level -= 1
            self.lines.append(f"{self._indent()}}}")
            for catch in node.catch_clauses:
                p_str = f"{catch.param_type} {catch.param_name}" if catch.param_name else catch.param_type
                self.lines.append(f"{self._indent()}catch ({p_str}) {{")
                self.indent_level += 1
                for s in catch.body.statements:
                    self.format_statement_line(s)
                self.indent_level -= 1
                self.lines.append(f"{self._indent()}}}")
        elif isinstance(node, SwitchStatement):
            self.lines.append(f"{self._indent()}switch ({self.format_expression(node.expr)}) {{")
            self.indent_level += 1
            for case in node.cases:
                if case.value:
                    self.lines.append(f"{self._indent()}case {self.format_expression(case.value)}:")
                else:
                    self.lines.append(f"{self._indent()}default:")
                self.indent_level += 1
                for s in case.statements:
                    self.format_statement_line(s)
                self.indent_level -= 1
            self.indent_level -= 1
            self.lines.append(f"{self._indent()}}}")
        elif isinstance(node, Block):
            self.lines.append(f"{self._indent()}{{")
            self.indent_level += 1
            for s in node.statements:
                self.format_statement_line(s)
            self.indent_level -= 1
            self.lines.append(f"{self._indent()}}}")
        else:
            self.lines.append(self._indent() + self.format_statement(node))

    def format_statement(self, node: Statement) -> str:
        if isinstance(node, MultiVarDeclaration):
            if not node.declarations:
                return ";"
            first = node.declarations[0]
            prefix = "constexpr " if getattr(first, "is_constexpr", False) else ("const " if first.is_const else "")
            ref_str = "&" if first.is_reference else ""
            declarators = []
            for declaration in node.declarations:
                text = declaration.name
                if declaration.initializer:
                    text += f" = {self.format_expression(declaration.initializer)}"
                declarators.append(text)
            return f"{prefix}{first.var_type}{ref_str} {', '.join(declarators)};"
        if isinstance(node, VarDeclaration):
            prefix = "constexpr " if getattr(node, "is_constexpr", False) else ("const " if node.is_const else "")
            ref_str = "&" if node.is_reference else ""
            if node.initializer:
                return f"{prefix}{node.var_type}{ref_str} {node.name} = {self.format_expression(node.initializer)};"
            return f"{prefix}{node.var_type}{ref_str} {node.name};"
        elif isinstance(node, ClassInstanceDeclaration):
            args_str = ", ".join(self.format_expression(a) for a in node.args)
            if args_str:
                return f"{node.class_name} {node.name}({args_str});"
            return f"{node.class_name} {node.name};"
        elif isinstance(node, DeleteStatement):
            return f"delete {self.format_expression(node.expr)};"
        elif isinstance(node, UsingNamespace):
            return f"using namespace {node.name};"
        elif isinstance(node, UsingDeclaration):
            return f"using {node.namespace}::{node.member};"
        elif isinstance(node, ArrayDeclaration):
            if getattr(node, "dimensions", None) and len(node.dimensions) > 1:
                dims_str = "".join(f"[{d if d is not None else ''}]" for d in node.dimensions)
            else:
                size_str = str(node.size) if node.size is not None else ""
                dims_str = f"[{size_str}]"
            if node.elements:
                elems = ", ".join(self.format_expression(e) for e in node.elements)
                return f"{node.var_type} {node.name}{dims_str} = {{{elems}}};"
            return f"{node.var_type} {node.name}{dims_str};"
        elif isinstance(node, StructDeclaration):
            if node.elements:
                elems = ", ".join(self.format_expression(e) for e in node.elements)
                return f"struct {node.struct_name} {node.name} = {{{elems}}};"
            return f"struct {node.struct_name} {node.name};"
        elif isinstance(node, ExpressionStatement):
            return f"{self.format_expression(node.expr)};"
        elif isinstance(node, ReturnStatement):
            if node.expr:
                return f"return {self.format_expression(node.expr)};"
            return "return;"
        elif isinstance(node, BreakStatement):
            return "break;"
        elif isinstance(node, ContinueStatement):
            return "continue;"
        elif isinstance(node, ThrowStatement):
            return f"throw {self.format_expression(node.expr)};"
        return ""

    def format_expression(self, node: Expression) -> str:
        if isinstance(node, IntLiteral):
            return str(node.value)
        elif isinstance(node, FloatLiteral):
            return str(node.value)
        elif isinstance(node, BoolLiteral):
            return "true" if node.value else "false"
        elif isinstance(node, StringLiteral):
            return f'"{node.value}"'
        elif isinstance(node, Identifier):
            return node.name
        elif isinstance(node, ThisExpr):
            return "this"
        elif isinstance(node, ScopeResolution):
            return f"{node.namespace}::{node.member}"
        elif isinstance(node, NewExpr):
            args_str = f"({', '.join(self.format_expression(a) for a in node.args)})" if node.args else ""
            return f"new {node.type_name}{args_str}"
        elif isinstance(node, MethodCall):
            args_str = ", ".join(self.format_expression(a) for a in node.args)
            op = "->" if node.is_arrow else "."
            return f"{self.format_expression(node.object_expr)}{op}{node.method_name}({args_str})"
        elif isinstance(node, ArrowAccess):
            return f"{self.format_expression(node.object_expr)}->{node.member}"
        elif isinstance(node, ArrowAssignment):
            return f"{self.format_expression(node.object_expr)}->{node.member} = {self.format_expression(node.expr)}"
        elif isinstance(node, BinaryOp):
            return f"{self.format_expression(node.left)} {node.op} {self.format_expression(node.right)}"
        elif isinstance(node, UnaryOp):
            return f"{node.op}{self.format_expression(node.expr)}"
        elif isinstance(node, AddressOf):
            return f"&{self.format_expression(node.expr)}"
        elif isinstance(node, Deref):
            return f"*{self.format_expression(node.expr)}"
        elif isinstance(node, PreIncrement):
            return f"++{self.format_expression(node.target)}"
        elif isinstance(node, PreDecrement):
            return f"--{self.format_expression(node.target)}"
        elif isinstance(node, PostIncrement):
            return f"{self.format_expression(node.target)}++"
        elif isinstance(node, PostDecrement):
            return f"{self.format_expression(node.target)}--"
        elif isinstance(node, Assignment):
            return f"{node.target} = {self.format_expression(node.expr)}"
        elif isinstance(node, DerefAssignment):
            return f"*{self.format_expression(node.target)} = {self.format_expression(node.expr)}"
        elif isinstance(node, ArrayAccess):
            if getattr(node, "indices", None) and len(node.indices) > 1:
                return f"{node.name}" + "".join(f"[{self.format_expression(i)}]" for i in node.indices)
            return f"{node.name}[{self.format_expression(node.index)}]"
        elif isinstance(node, ArrayAssignment):
            if getattr(node, "indices", None) and len(node.indices) > 1:
                return f"{node.name}" + "".join(f"[{self.format_expression(i)}]" for i in node.indices) + f" = {self.format_expression(node.expr)}"
            return f"{node.name}[{self.format_expression(node.index)}] = {self.format_expression(node.expr)}"
        elif isinstance(node, MemberAccess):
            return f"{self.format_expression(node.object_expr)}.{node.member}"
        elif isinstance(node, MemberAssignment):
            return f"{self.format_expression(node.object_expr)}.{node.member} = {self.format_expression(node.expr)}"
        elif isinstance(node, CastExpression):
            return f"({node.target_type}){self.format_expression(node.expr)}"
        elif isinstance(node, TernaryOp):
            return f"{self.format_expression(node.condition)} ? {self.format_expression(node.true_expr)} : {self.format_expression(node.false_expr)}"
        elif isinstance(node, FunctionCall):
            args_str = ", ".join(self.format_expression(a) for a in node.args)
            return f"{node.name}({args_str})"
        elif isinstance(node, LambdaExpr):
            caps_str = ", ".join(node.captures)
            params_str = ", ".join(self._format_param(p) for p in node.params)
            ret_str = f" -> {node.return_type}" if node.return_type else ""
            body_stmts = " ".join(self.format_statement(s) for s in node.body.statements)
            return f"[{caps_str}]({params_str}){ret_str} {{ {body_stmts} }}"
        return ""
