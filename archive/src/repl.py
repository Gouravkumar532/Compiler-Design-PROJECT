"""Interactive REPL (Read-Eval-Print Loop) for C++."""

import sys
from typing import Dict, Any
from src.tokens import TokenType
from src.lexer import Lexer
from src.parser import Parser
from src.ast_nodes import *
try:
    from archive.src.codegen import CodeGenerator
except ImportError:
    from src.codegen import CodeGenerator
from src.errors import Colors

class REPL:
    def __init__(self):
        self.variables: Dict[str, Any] = {}
        self.var_types: Dict[str, str] = {}
        self.pointers: Dict[str, str] = {} # var_name -> target_var_name
        self.session_statements: List[str] = []

    def run(self):
        print(f"{Colors.BOLD}{Colors.CYAN}C++ Interactive REPL v0.2.0{Colors.RESET}")
        print(f"Type expressions or statements. Commands: {Colors.YELLOW}:help{Colors.RESET}, {Colors.YELLOW}:ir{Colors.RESET}, {Colors.YELLOW}:vars{Colors.RESET}, {Colors.YELLOW}:clear{Colors.RESET}, {Colors.YELLOW}:exit{Colors.RESET}\n")

        while True:
            try:
                line = input(f"{Colors.GREEN}c++>{Colors.RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{Colors.CYAN}Bye!{Colors.RESET}")
                break

            if not line:
                continue

            # Special REPL commands
            if line.startswith(":"):
                cmd = line[1:].strip().lower()
                if cmd in ["exit", "quit", "q"]:
                    print(f"{Colors.CYAN}Bye!{Colors.RESET}")
                    break
                elif cmd == "help":
                    self.show_help()
                elif cmd == "vars":
                    self.show_vars()
                elif cmd == "ir":
                    self.show_ir()
                elif cmd == "clear":
                    self.variables.clear()
                    self.var_types.clear()
                    self.pointers.clear()
                    self.session_statements.clear()
                    print(f"{Colors.GREEN}Session cleared.{Colors.RESET}")
                else:
                    print(f"{Colors.RED}Unknown command ':{cmd}'. Type :help for commands.{Colors.RESET}")
                continue

            self.eval_line(line)

    def show_help(self):
        print(f"\n{Colors.BOLD}REPL Commands:{Colors.RESET}")
        print(f"  {Colors.YELLOW}:vars{Colors.RESET}   List declared variables and their values")
        print(f"  {Colors.YELLOW}:ir{Colors.RESET}     Show generated LLVM IR for the current session")
        print(f"  {Colors.YELLOW}:clear{Colors.RESET}  Clear the current environment session")
        print(f"  {Colors.YELLOW}:help{Colors.RESET}   Show this help screen")
        print(f"  {Colors.YELLOW}:exit{Colors.RESET}   Exit the REPL\n")

    def show_vars(self):
        if not self.variables:
            print(f"{Colors.DIM}(No variables declared yet){Colors.RESET}")
            return
        print(f"\n{Colors.BOLD}Session Variables:{Colors.RESET}")
        for name, val in self.variables.items():
            t = self.var_types.get(name, "int")
            print(f"  {Colors.CYAN}{t}{Colors.RESET} {name} = {Colors.YELLOW}{val}{Colors.RESET}")
        print()

    def show_ir(self):
        if not self.session_statements:
            print(f"{Colors.DIM}(No statements in session yet){Colors.RESET}")
            return
        
        full_source = "int main() {\n" + "\n".join(f"    {s};" for s in self.session_statements) + "\n    return 0;\n}"
        try:
            lexer = Lexer(full_source, "<repl>")
            tokens = lexer.tokenize()
            parser = Parser(tokens, full_source, "<repl>")
            ast = parser.parse()
            codegen = CodeGenerator()
            ir = codegen.generate(ast)
            print(f"\n{Colors.BOLD}--- Generated LLVM IR ---{Colors.RESET}")
            print(ir)
            print(f"{Colors.BOLD}-------------------------{Colors.RESET}\n")
        except Exception as e:
            print(f"{Colors.RED}Could not generate IR: {e}{Colors.RESET}")

    def eval_line(self, line: str):
        # Auto-append semicolon if missing
        clean = line.rstrip(";")

        # Try to parse as statement or expression
        wrapped = f"int main() {{ {clean}; }}"
        try:
            lexer = Lexer(wrapped, "<repl>")
            tokens = lexer.tokenize()
            parser = Parser(tokens, wrapped, "<repl>")
            ast = parser.parse()
            
            stmt = ast.functions[0].body.statements[0]
            self.execute_statement(stmt, clean)
            self.session_statements.append(clean)
        except SystemExit:
            # Error was reported by parser/lexer
            pass
        except Exception as e:
            print(f"{Colors.RED}Evaluation error:{Colors.RESET} {e}")

    def execute_statement(self, stmt: Statement, raw_text: str):
        if isinstance(stmt, VarDeclaration):
            val = 0
            if stmt.initializer:
                val = self.eval_expr(stmt.initializer)
            self.variables[stmt.name] = val
            self.var_types[stmt.name] = stmt.var_type
            if "*" in stmt.var_type and isinstance(stmt.initializer, AddressOf) and isinstance(stmt.initializer.expr, Identifier):
                self.pointers[stmt.name] = stmt.initializer.expr.name
            print(f"{Colors.DIM}{stmt.var_type} {stmt.name} = {val}{Colors.RESET}")
        elif isinstance(stmt, ExpressionStatement):
            expr = stmt.expr
            if isinstance(expr, Assignment):
                val = self.eval_expr(expr.expr)
                self.variables[expr.target] = val
                print(f"{Colors.DIM}{expr.target} = {val}{Colors.RESET}")
            elif isinstance(expr, DerefAssignment):
                val = self.eval_expr(expr.expr)
                if isinstance(expr.target, Identifier) and expr.target.name in self.pointers:
                    target_var = self.pointers[expr.target.name]
                    self.variables[target_var] = val
                print(f"{Colors.DIM}*{self.eval_repr(expr.target)} = {val}{Colors.RESET}")
            elif isinstance(expr, FunctionCall) and expr.name == "printf":
                self.handle_printf(expr)
            else:
                res = self.eval_expr(expr)
                if res is not None:
                    print(f"{Colors.BOLD}{Colors.YELLOW}=> {res}{Colors.RESET}")

    def handle_printf(self, call: FunctionCall):
        if not call.args:
            return
        fmt = self.eval_expr(call.args[0])
        if not isinstance(fmt, str):
            return
        args = [self.eval_expr(a) for a in call.args[1:]]
        # Replace %d, %f, %s with %s formatting in Python
        fmt_py = fmt.replace("%d", "{}").replace("%f", "{}").replace("%s", "{}").replace("%c", "{}")
        formatted = fmt_py.format(*args)
        # Handle escape characters
        formatted = formatted.replace("\\n", "\n").replace("\\t", "\t")
        sys.stdout.write(formatted)
        sys.stdout.flush()

    def eval_expr(self, expr: Expression) -> Any:
        if isinstance(expr, IntLiteral):
            return expr.value
        elif isinstance(expr, FloatLiteral):
            return expr.value
        elif isinstance(expr, StringLiteral):
            return expr.value
        elif isinstance(expr, Identifier):
            if expr.name in self.variables:
                return self.variables[expr.name]
            print(f"{Colors.RED}Undeclared identifier '{expr.name}'{Colors.RESET}")
            return 0
        elif isinstance(expr, AddressOf):
            if isinstance(expr.expr, Identifier):
                return f"&{expr.expr.name}"
            return 0
        elif isinstance(expr, Deref):
            if isinstance(expr.expr, Identifier) and expr.expr.name in self.pointers:
                target_var = self.pointers[expr.expr.name]
                return self.variables.get(target_var, 0)
            return 0
        elif isinstance(expr, BinaryOp):
            l = self.eval_expr(expr.left)
            r = self.eval_expr(expr.right)
            ops = {
                '+': lambda a, b: a + b,
                '-': lambda a, b: a - b,
                '*': lambda a, b: a * b,
                '/': lambda a, b: a // b if isinstance(a, int) and isinstance(b, int) else a / b,
                '%': lambda a, b: a % b,
                '==': lambda a, b: 1 if a == b else 0,
                '!=': lambda a, b: 1 if a != b else 0,
                '<': lambda a, b: 1 if a < b else 0,
                '<=': lambda a, b: 1 if a <= b else 0,
                '>': lambda a, b: 1 if a > b else 0,
                '>=': lambda a, b: 1 if a >= b else 0,
                '&&': lambda a, b: 1 if (a and b) else 0,
                '||': lambda a, b: 1 if (a or b) else 0,
            }
            if expr.op in ops:
                return ops[expr.op](l, r)
            return 0
        elif isinstance(expr, UnaryOp):
            val = self.eval_expr(expr.expr)
            if expr.op == '-': return -val
            if expr.op == '!': return 0 if val else 1
            return val
        elif isinstance(expr, TernaryOp):
            cond = self.eval_expr(expr.condition)
            return self.eval_expr(expr.true_expr) if cond else self.eval_expr(expr.false_expr)
        elif isinstance(expr, CastExpression):
            val = self.eval_expr(expr.expr)
            if expr.target_type == "int": return int(val)
            if expr.target_type in ["float", "double"]: return float(val)
            if expr.target_type == "char": return int(val) & 0xFF
            return val
        return 0

    def eval_repr(self, expr: Expression) -> str:
        if isinstance(expr, Identifier):
            return expr.name
        return "expr"
