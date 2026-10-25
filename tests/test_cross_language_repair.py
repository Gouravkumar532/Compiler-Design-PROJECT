import unittest

from src.lexer import Lexer
from src.parser import Parser
from src.repair_coordinator import repair_source
from src.cross_language_repair import CrossLanguageRepairEngine


class TestCrossLanguageEngineUnits(unittest.TestCase):
    def test_python_def_with_typed_params(self):
        code = "def add(int a, int b):\n    return a + b\n"
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0].category, "function_def")
        self.assertIn("int add(int a, int b) {", repaired)
        self.assertIn("return a + b;", repaired)
        self.assertTrue(repaired.strip().endswith("}"))

    def test_python_def_with_return_type_annotation(self):
        code = "def multiply(double x, double y) -> double:\n    return x * y\n"
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertEqual(len(diags), 1)
        self.assertIn("double multiply(double x, double y) {", repaired)

    def test_python_def_main(self):
        code = "def main():\n    return 0\n"
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn("int main() {", repaired)

    def test_python_def_untyped_params(self):
        code = "def process(val):\n    return val\n"
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn("auto process(auto val) {", repaired)

    def test_python_elif_and_colons(self):
        code = "if (x > 0):\n    y = 1;\nelif (x < 0):\n    y = -1;\nelse:\n    y = 0;\n"
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertTrue(any(d.category == "control_flow" for d in diags))
        self.assertIn("if (x > 0) {", repaired)
        self.assertIn("else if (x < 0) {", repaired)
        self.assertIn("else {", repaired)

    def test_python_elif_without_parens(self):
        code = "if (x > 0) {\n    y = 1;\n} elif x < 0:\n    y = -1;\n"
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn("else if (x < 0) {", repaired)

    def test_python_for_range_single_arg(self):
        code = "for i in range(10):\n    x = x + i;\n"
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn("for (int i = 0; i < 10; i++) {", repaired)

    def test_python_for_range_two_args(self):
        code = "for idx in range(1, 100):\n    x = x + idx;\n"
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn("for (int idx = 1; idx < 100; idx++) {", repaired)

    def test_python_for_range_three_args_step(self):
        code = "for step_i in range(0, 50, 5):\n    x = x + step_i;\n"
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn("for (int step_i = 0; step_i < 50; step_i += 5) {", repaired)

    def test_python_for_range_negative_step(self):
        code = "for count in range(10, 0, -1):\n    x = x + count;\n"
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn("for (int count = 10; count > 0; count += -1) {", repaired)

    def test_python_pass_statement(self):
        code = "if (flag) {\n    pass;\n}\n"
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn(";", repaired)
        self.assertNotIn("pass", repaired)

    def test_java_boolean_type(self):
        code = "boolean isActive = true;"
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn("bool isActive = true;", repaired)

    def test_java_string_type(self):
        code = 'String message = "Hello";'
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn('std::string message = "Hello";', repaired)

    def test_literals_true_false_none_null(self):
        code = "bool t = True;\nbool f = False;\nint* p1 = None;\nint* p2 = null;\n"
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn("bool t = true;", repaired)
        self.assertIn("bool f = false;", repaired)
        self.assertIn("int* p1 = nullptr;", repaired)
        self.assertIn("int* p2 = nullptr;", repaired)

    def test_python_print_statement(self):
        code = 'print("Score: ", score);'
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn('std::cout << "Score: " << score << std::endl;', repaired)

    def test_java_system_out_println(self):
        code = 'System.out.println("Result: " + res);'
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn('std::cout << "Result: " << res << std::endl;', repaired)

    def test_java_system_out_print(self):
        code = 'System.out.print("Prefix: " + msg);'
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn('std::cout << "Prefix: " << msg;', repaired)

    def test_python_logical_operators(self):
        code = "if (not flag && a and b || c or d) {\n    return 1;\n}\n"
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn("!", repaired)
        self.assertIn("&&", repaired)
        self.assertIn("||", repaired)

    def test_python_is_none_and_is_not_none(self):
        code = "if (ptr is None) { return 0; }\nif (ptr is not None) { return 1; }\n"
        tokens = Lexer(code, "<test>").tokenize()
        engine = CrossLanguageRepairEngine(code, "<test>")
        repaired, diags = engine.translate_entire_source(tokens)
        self.assertIn("ptr == nullptr", repaired)
        self.assertIn("ptr != nullptr", repaired)


class TestCrossLanguageParserIntegration(unittest.TestCase):
    def repaired_source(self, source):
        result = repair_source("<test>", source, confidence_policy="all")
        self.assertTrue(result.success)
        return result.updated_source

    def test_parser_auto_fix_python_function(self):
        src = """def add(int a, int b):
    return a + b
"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        self.assertEqual(ast.declarations[0].name, "add")
        self.assertIn("int add(int a, int b)", self.repaired_source(src))

    def test_parser_auto_fix_java_types_and_literals(self):
        src = """int main() {
    boolean active = True;
    String name = "Test";
    int* ptr = None;
    return 0;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        repaired = self.repaired_source(src)
        self.assertIn("bool active = true;", repaired)
        self.assertIn('std::string name = "Test";', repaired)
        self.assertIn("int* ptr = nullptr;", repaired)

    def test_parser_auto_fix_elif_branching(self):
        src = """int main() {
    int x = 5;
    int y = 0;
    if (x > 0):
        y = 1;
    elif (x < 0):
        y = -1;
    else:
        y = 0;
    return y;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        self.assertIn("else if (x < 0) {", self.repaired_source(src))

    def test_parser_auto_fix_for_range_loop(self):
        src = """int main() {
    int sum = 0;
    for i in range(10):
        sum = sum + i;
    return sum;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        self.assertIn("for (int i = 0; i < 10; i++) {", self.repaired_source(src))

    def test_parser_auto_fix_print_statement(self):
        src = """int main() {
    int x = 42;
    print("Value: ", x);
    return 0;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        self.assertIn('std::cout << "Value: " << x << std::endl;', self.repaired_source(src))

    def test_parser_auto_fix_system_out_println(self):
        src = """int main() {
    int score = 100;
    System.out.println("Score: " + score);
    return 0;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        self.assertIn('std::cout << "Score: " << score << std::endl;', self.repaired_source(src))

    def test_parser_diagnostic_in_check_mode(self):
        src = """int main() {
    boolean flag = True;
    return 0;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertGreater(parser.errors_count, 0)
        self.assertEqual(parser.source, src)

    def test_zero_disruption_to_pure_cpp(self):
        # Code that defines a variable 'range' or user function 'print' must not be disrupted
        src = """int range = 10;
void print(int val) {
    int x = val;
}
int main() {
    print(range);
    return 0;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 3)
        self.assertEqual(ast.declarations[0].name, "range")
        self.assertEqual(ast.declarations[1].name, "print")
        # Ensure 'print' was not rewritten into std::cout
        self.assertNotIn("std::cout", parser.source)

    def test_direct_parser_hooks_def_and_logical_ops(self):
        # Directly tests parse_function, parse_if, parse_logical_and/or, and parse_unary hooks
        src = """def compute(int a, int b) -> int: {
    if (a > 0 and b > 0) {
        return a + b;
    } elif (not a or not b): {
        return 0;
    }
    return -1;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=False)
        func = parser.parse_function()
        self.assertEqual(func.name, "compute")
        self.assertEqual(func.return_type, "int")
        self.assertEqual(len(func.params), 2)

    def test_direct_parser_hooks_for_in_range(self):
        # Directly tests parse_for with (i in range(...))
        src = """for (int i in range(10)): {
    int x = i;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=False)
        parser.advance() # consume 'for'
        for_stmt = parser.parse_for()
        self.assertIsNotNone(for_stmt)


if __name__ == "__main__":
    unittest.main()
