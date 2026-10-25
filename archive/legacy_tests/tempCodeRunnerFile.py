import unittest
from typing import Set

from src.tokens import Token, TokenType
from src.lexer import Lexer
from src.parser import Parser, ParseError
from src.expression_repair import (
    ExpressionRepairEngine,
    find_symbol_partition,
    tokens_to_code,
)
from src.semantic import SemanticAnalyzer
from src.codegen import CodeGenerator


class TestIdentifierDecomposition(unittest.TestCase):
    def test_partition_single_letters(self):
        symbols = {"a", "b", "c"}
        self.assertEqual(find_symbol_partition("ab", symbols), ["a", "b"])
        self.assertEqual(find_symbol_partition("bc", symbols), ["b", "c"])
        self.assertEqual(find_symbol_partition("abc", symbols), ["a", "b", "c"])

    def test_partition_multichar_identifiers(self):
        symbols = {"width", "height", "depth"}
        self.assertEqual(
            find_symbol_partition("widthheight", symbols), ["width", "height"]
        )

    def test_partition_unknown_returns_none(self):
        symbols = {"x", "y"}
        self.assertIsNone(find_symbol_partition("xyz", symbols))
        self.assertIsNone(find_symbol_partition("x", symbols))

    def test_engine_decompose_tokens(self):
        engine = ExpressionRepairEngine({"a", "b", "c"})
        tokens = Lexer("ab + bc", "<test>").tokenize()[:-1]
        decomposed, expls = engine.decompose_identifiers(tokens)
        lexemes = [t.lexeme for t in decomposed]
        self.assertEqual(lexemes, ["a", "b", "+", "b", "c"])
        self.assertEqual(len(expls), 2)
        self.assertIn("split undeclared identifier 'ab'", expls[0])
        self.assertIn("split undeclared identifier 'bc'", expls[1])


class TestPatternHeuristics(unittest.TestCase):
    def test_pattern_1_postfix_relocation_ab_plus(self):
        tokens = Lexer("ab+", "<test>").tokenize()[:-1]
        engine = ExpressionRepairEngine({"a", "b"})
        suggestions = engine.repair(tokens)
        self.assertGreater(len(suggestions), 0)
        self.assertEqual(suggestions[0].repaired_code, "a + b")
        self.assertTrue(
            any("relocated operator '+'" in exp for exp in suggestions[0].explanation)
        )

    def test_pattern_1_postfix_relocation_xy_plus(self):
        tokens = Lexer("x y +", "<test>").tokenize()[:-1]
        engine = ExpressionRepairEngine({"x", "y"})
        suggestions = engine.repair(tokens)
        self.assertGreater(len(suggestions), 0)
        self.assertEqual(suggestions[0].repaired_code, "x + y")

    def test_pattern_2_dangling_operator_inside_parentheses(self):
        tokens = Lexer("(a+bc*)", "<test>").tokenize()[:-1]
        engine = ExpressionRepairEngine({"a", "b", "c"})
        suggestions = engine.repair(tokens)
        self.assertGreater(len(suggestions), 0)
        self.assertEqual(suggestions[0].repaired_code, "(a + b * c)")
        self.assertTrue(
            any("split undeclared identifier 'bc'" in exp for exp in suggestions[0].explanation)
        )
        self.assertTrue(
            any("relocated operator '*'" in exp for exp in suggestions[0].explanation)
        )

    def test_pattern_3_trailing_operator_mixed(self):
        tokens = Lexer("a * b + c d *", "<test>").tokenize()[:-1]
        engine = ExpressionRepairEngine({"a", "b", "c", "d"})
        suggestions = engine.repair(tokens)
        self.assertGreater(len(suggestions), 0)
        self.assertEqual(suggestions[0].repaired_code, "a * b + c * d")

    def test_pattern_3_missing_multiplication_juxtaposition(self):
        tokens = Lexer("2(a + b)", "<test>").tokenize()[:-1]
        engine = ExpressionRepairEngine({"a", "b"})
        suggestions = engine.repair(tokens)
        self.assertGreater(len(suggestions), 0)
        self.assertEqual(suggestions[0].repaired_code, "2 * (a + b)")
        self.assertTrue(
            any("inserted missing '*'" in exp for exp in suggestions[0].explanation)
        )

    def test_pattern_3_missing_operator_between_variables(self):
        tokens = Lexer("x y", "<test>").tokenize()[:-1]
        engine = ExpressionRepairEngine({"x", "y"})
        suggestions = engine.repair(tokens)
        self.assertGreater(len(suggestions), 0)
        self.assertEqual(suggestions[0].repaired_code, "x * y")

    def test_pattern_4_unclosed_parenthesis(self):
        tokens = Lexer("(x + y", "<test>").tokenize()[:-1]
        engine = ExpressionRepairEngine({"x", "y"})
        suggestions = engine.repair(tokens)
        self.assertGreater(len(suggestions), 0)
        self.assertEqual(suggestions[0].repaired_code, "(x + y)")
        self.assertTrue(
            any("closed unclosed '('" in exp for exp in suggestions[0].explanation)
        )

    def test_pattern_5_consecutive_operator_deduplication(self):
        tokens = Lexer("a + + b", "<test>").tokenize()[:-1]
        engine = ExpressionRepairEngine({"a", "b"})
        suggestions = engine.repair(tokens)
        self.assertGreater(len(suggestions), 0)
        self.assertEqual(suggestions[0].repaired_code, "a + b")
        self.assertTrue(
            any("deduplicated consecutive '+'" in exp for exp in suggestions[0].explanation)
        )


class TestParserEndToEndIntegration(unittest.TestCase):
    def test_parser_autofix_postfix(self):
        src = """int main() {
    int a = 10;
    int b = 20;
    int res = ab+;
    return res;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True, auto_fix=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)

    def test_parser_autofix_parenthesized_dangling(self):
        src = """int main() {
    int a = 1;
    int b = 2;
    int c = 3;
    int res = (a+bc*);
    return res;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True, auto_fix=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)

        # Full pipeline test: Semantic Analysis & Codegen
        sem = SemanticAnalyzer(src, "<test>")
        sem.analyze(ast)
        ir = CodeGenerator().generate(ast)
        self.assertIn("define i32 @main()", ir)

    def test_parser_autofix_function_parameters_in_scope(self):
        src = """int compute(int x, int y) {
    return x y +;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True, auto_fix=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)

    def test_parser_autofix_multiplication_juxtaposition(self):
        src = """int main() {
    int a = 5;
    int b = 3;
    int res = 2(a + b);
    return res;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True, auto_fix=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)

    def test_parser_autofix_unclosed_paren(self):
        src = """int main() {
    int x = 4;
    int y = 5;
    int res = (x + y;
    return res;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True, auto_fix=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)

    def test_parser_autofix_consecutive_operators(self):
        src = """int main() {
    int a = 10;
    int b = 20;
    int res = a + + b;
    return res;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True, auto_fix=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)

    def test_parser_valid_code_untouched(self):
        src = """int main() {
    int a = 1;
    int b = 2;
    int c = 3;
    int res = a + b * c;
    return res;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True, auto_fix=True)
        ast = parser.parse()
        self.assertEqual(len(ast.declarations), 1)

    def test_parser_no_suggest_flag_raises(self):
        src = """int main() {
    int a = 1;
    int b = 2;
    int res = ab+;
    return res;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=False)
        with self.assertRaises(ParseError):
            # When error is called without parse wrapper, it raises ParseError
            parser.pos = 0
            while not parser.is_at_end():
                if parser._is_function_decl():
                    parser.parse_function()
                else:
                    parser.parse_var_decl()


    def test_parser_interactive_confirmation_yes(self):
        from unittest.mock import patch
        src = """int main() {
    int a = 1;
    int b = 2;
    int res = ab+;
    return res;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True, auto_fix=False, interactive=True)
        with patch("src.parser.confirm_suggestion", return_value=True):
            ast = parser.parse()
            self.assertEqual(len(ast.declarations), 1)

    def test_parser_interactive_confirmation_no(self):
        from unittest.mock import patch
        src = """int main() {
    int a = 1;
    int b = 2;
    int res = ab+;
    return res;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True, auto_fix=False, interactive=True)
        with patch("src.parser.confirm_suggestion", return_value=False):
            with self.assertRaises(SystemExit) as ctx:
                parser.parse()
            self.assertEqual(ctx.exception.code, 1)

    def test_parser_non_interactive_without_fix_exits(self):
        src = """int main() {
    int a = 1;
    int b = 2;
    int res = ab+;
    return res;
}"""
        tokens = Lexer(src, "<test>").tokenize()
        parser = Parser(tokens, src, "<test>", enable_repair=True, auto_fix=False, interactive=False)
        with self.assertRaises(SystemExit) as ctx:
            parser.parse()
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
