import unittest

from src.lexer import Lexer
from src.parser import Parser, ParseError
from src.semantic import SemanticAnalyzer
from src.repair_coordinator import repair_source
from src.delimiter_repair import (
    compute_line_indents,
)


class TestDelimiterRepairUtilities(unittest.TestCase):
    def test_compute_line_indents(self):
        code = "int main() {\n    int a = 10;\n        return a;\n}"
        indents = compute_line_indents(code)
        self.assertEqual(indents[1], 0)
        self.assertEqual(indents[2], 4)
        self.assertEqual(indents[3], 8)
        self.assertEqual(indents[4], 0)

class RepairIntegrationTestCase(unittest.TestCase):
    def repaired_source(self, source):
        result = repair_source("<test>", source, confidence_policy="all")
        self.assertTrue(result.success)
        return result.updated_source


class TestMissingSemicolonRepair(RepairIntegrationTestCase):
    def test_missing_semicolon_var_decl_consecutive_lines(self):
        src = """int a = 10
int b = 20;"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 2)
        self.assertIn("int a = 10;", self.repaired_source(src))

    def test_missing_semicolon_same_line_statements(self):
        src = "int a = 10 int b = 20;"
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 2)
        self.assertIn("int a = 10;", self.repaired_source(src))

    def test_missing_semicolon_after_return(self):
        src = """int main() {
    return 42
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        self.assertIn("return 42;", self.repaired_source(src))

    def test_missing_semicolon_after_class_definition(self):
        src = """class Student {
    int id;
}
int main() {
    return 0;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 2)
        self.assertIn("};", self.repaired_source(src))

    def test_missing_semicolon_after_struct_definition(self):
        src = """struct Point {
    int x;
    int y;
}
int main() {
    return 0;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 2)
        self.assertIn("};", self.repaired_source(src))

    def test_missing_semicolon_after_enum_definition(self):
        src = """enum Color {
    RED,
    GREEN,
    BLUE
}
int main() {
    return 0;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 2)
        self.assertIn("};", self.repaired_source(src))

    def test_missing_semicolon_in_for_loop_header(self):
        src = """int main() {
    int count = 0;
    for (int i = 0 i < 10; i++) {
        count++;
    }
    return count;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        self.assertIn("for (int i = 0; i < 10; i++)", self.repaired_source(src))

    def test_missing_semicolon_expression_statement(self):
        src = """int main() {
    int count = 0;
    count++
    return count;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        self.assertIn("count++;", self.repaired_source(src))

    def test_multiple_missing_semicolons_in_file(self):
        src = """int a = 10
int b = 20
int c = 30;
int main() {
    int x = 1
    int y = 2;
    return x + y
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 4)
        repaired = self.repaired_source(src)
        self.assertIn("int a = 10;", repaired)
        self.assertIn("int b = 20;", repaired)
        self.assertIn("int x = 1;", repaired)
        self.assertIn("return x + y;", repaired)


class TestUnbalancedDelimiterRepair(RepairIntegrationTestCase):
    def test_missing_rparen_if_header(self):
        src = """int main() {
    int x = 15;
    int count = 0;
    if (x > 10 {
        count++;
    }
    return count;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        self.assertIn("if (x > 10 ) {", self.repaired_source(src))

    def test_missing_rparen_while_header(self):
        src = """int main() {
    int x = 5;
    while (x > 0 {
        x--;
    }
    return x;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        self.assertIn("while (x > 0 ) {", self.repaired_source(src))

    def test_missing_rparen_for_header(self):
        src = """int main() {
    int count = 0;
    for (int i = 0; i < 10; i++ {
        count++;
    }
    return count;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        self.assertIn("i++ ) {", self.repaired_source(src))

    def test_missing_closing_brace_indentation_pattern4(self):
        src = """int calculate() {
    int valid = 1;
    if (valid) {
        return 1;
    return 0;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        
        # Verify block was repaired with matching brace before 'return 0;'
        expected_line = "    }\n    return 0;"
        repaired = self.repaired_source(src)
        self.assertIn(expected_line, repaired)

        # Full pipeline test: Semantic Analysis
        sem = SemanticAnalyzer(repaired, "<test>")
        sem.analyze(ast)
        self.assertEqual(sem.errors_count, 0)

    def test_missing_closing_brace_at_eof(self):
        src = """int main() {
    return 0;
"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        self.assertIn("}", self.repaired_source(src))

    def test_missing_rparen_in_function_call(self):
        src = """int add(int a, int b) { return a + b; }
int main() {
    int res = add(1, 2;
    return res;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 2)
        self.assertIn("add(1, 2)", self.repaired_source(src))

    def test_missing_rparen_in_parameter_list(self):
        src = """int compute(int x, int y {
    return x + y;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        self.assertIn("compute(int x, int y )", self.repaired_source(src))

    def test_missing_rbracket_in_array_decl(self):
        src = """int main() {
    int arr[10;
    return 0;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        self.assertIn("arr[10]", self.repaired_source(src))

    def test_delimiter_stack_tracking(self):
        src = """int main() {
    int x = (10 + 20);
    return x;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)
        # Delimiter stack should be cleanly balanced and empty at end
        self.assertEqual(len(parser.delimiter_stack), 0)


class TestModesAndFlags(unittest.TestCase):
    def test_no_repair_flag_raises_parse_error(self):
        src = """int a = 10
int b = 20;"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=False)
        with self.assertRaises(ParseError):
            parser.parse_var_decl()

    def test_recovery_never_mutates_source(self):
        src = """int a = 10
int b = 20;"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 2)
        self.assertEqual(parser.source, src)

    def test_coordinator_applies_repair_without_parser_side_effects(self):
        src = """int a = 10
int b = 20;"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        parser.parse()
        self.assertEqual(parser.source, src)
        self.assertIn("int a = 10;", repair_source("<test>", src, confidence_policy="all").updated_source)

    def test_non_interactive_without_fix_exits(self):
        src = """int a = 10
int b = 20;"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True)
        ast = parser.parse()
        self.assertGreater(parser.errors_count, 0)
        self.assertEqual(parser.source, src)


if __name__ == "__main__":
    unittest.main()
