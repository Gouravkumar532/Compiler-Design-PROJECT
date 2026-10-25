"""
Unit Test Suite for Logical vs. Assignment Operator & Operator Confusion Detection (Idea 6)
"""

import os
import subprocess
import tempfile
import unittest

from src.lexer import Lexer
from src.parser import Parser
from src.semantic import SemanticAnalyzer
from src.preprocessor import Preprocessor
from src.operator_misuse import OperatorMisuseEngine, OperatorDiagnostic
from src.repair_coordinator import repair_source
from src.error_catalogue import ERROR_CATALOGUE


def repair_all(code: str) -> str:
    """Exercise operator fixes through the canonical repair transaction."""
    result = repair_source("<test>", code, confidence_policy="all", max_rounds=5)
    if not result.success:
        raise AssertionError(result.message)
    return result.updated_source


class TestAssignmentInCondition(unittest.TestCase):
    """Tests for W002: Accidental assignment in conditional headers."""

    def test_if_assignment_unparenthesized_warns(self):
        code = """int main() {
    int status = 0;
    if (status = 0) {
        return 1;
    }
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w002_diags = [d for d in sem.operator_diagnostics if d.code == "W002"]
        self.assertEqual(len(w002_diags), 1)
        self.assertEqual(w002_diags[0].original_snippet, "status = 0")
        self.assertEqual(w002_diags[0].repaired_snippet, "status == 0")

    def test_if_assignment_parenthesized_bypasses(self):
        # GCC/Clang convention: ((x = func())) denotes intentional assignment
        code = """int get_val() { return 1; }

int main() {
    int x = 0;
    if ((x = get_val())) {
        return x;
    }
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w002_diags = [d for d in sem.operator_diagnostics if d.code == "W002"]
        self.assertEqual(len(w002_diags), 0)

    def test_while_assignment_unparenthesized_warns(self):
        code = """int main() {
    int p = 10;
    while (p = 0) {
        p--;
    }
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w002_diags = [d for d in sem.operator_diagnostics if d.code == "W002"]
        self.assertEqual(len(w002_diags), 1)

    def test_while_assignment_parenthesized_bypasses(self):
        code = """int next() { return 0; }

int main() {
    int p = 1;
    while ((p = next())) {
        p = 0;
    }
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w002_diags = [d for d in sem.operator_diagnostics if d.code == "W002"]
        self.assertEqual(len(w002_diags), 0)

    def test_do_while_assignment_unparenthesized_warns(self):
        code = """int main() {
    int x = 1;
    do {
        x--;
    } while (x = 0);
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w002_diags = [d for d in sem.operator_diagnostics if d.code == "W002"]
        self.assertEqual(len(w002_diags), 1)

    def test_for_condition_assignment_unparenthesized_warns(self):
        code = """int main() {
    for (int i = 0; i = 10; i++) {
        break;
    }
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w002_diags = [d for d in sem.operator_diagnostics if d.code == "W002"]
        self.assertEqual(len(w002_diags), 1)

    def test_member_and_arrow_assignment_in_condition(self):
        code = """struct State {
    int active;
};

int main() {
    State s;
    if (s.active = 1) {
        return 1;
    }
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w002_diags = [d for d in sem.operator_diagnostics if d.code == "W002"]
        self.assertEqual(len(w002_diags), 1)
        self.assertEqual(w002_diags[0].repaired_snippet, "s.active == 1")

    def test_autofix_assignment_preserves_earlier_assignments_on_line(self):
        code = """int main() {
    int a = 10; if (a = 5) return 1;
    return 0;
}
"""
        # 'int a = 10' must NOT be corrupted to 'int a == 10'!
        repaired = repair_all(code)
        self.assertIn("int a = 10;", repaired)
        self.assertIn("if (a == 5)", repaired)

    def test_autofix_assignment_compact_no_spaces(self):
        code = """int main() {
    int status = 0;
    if (status=0) {
        return 1;
    }
    return 0;
}
"""
        self.assertIn("status == 0", repair_all(code))


class TestExponentiationVsXor(unittest.TestCase):
    """Tests for W003: Bitwise XOR used where exponentiation was intended."""

    def test_base_2_power_literal(self):
        code = """int main() {
    int x = 2 ^ 8;
    return x;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w003_diags = [d for d in sem.operator_diagnostics if d.code == "W003"]
        self.assertEqual(len(w003_diags), 1)
        self.assertEqual(w003_diags[0].repaired_snippet, "1 << 8")

    def test_square_exponent_literal_2(self):
        code = """int main() {
    int r = 5;
    int square = r ^ 2;
    return square;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w003_diags = [d for d in sem.operator_diagnostics if d.code == "W003"]
        self.assertEqual(len(w003_diags), 1)
        self.assertEqual(w003_diags[0].repaired_snippet, "r * r")

    def test_base_10_power_literal(self):
        code = """int main() {
    int k = 10 ^ 3;
    return k;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w003_diags = [d for d in sem.operator_diagnostics if d.code == "W003"]
        self.assertEqual(len(w003_diags), 1)
        self.assertEqual(w003_diags[0].repaired_snippet, "pow(10, 3)")

    def test_variable_name_power_hint(self):
        code = """int main() {
    int base = 3;
    int exp = 4;
    int power = base ^ exp;
    return power;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w003_diags = [d for d in sem.operator_diagnostics if d.code == "W003"]
        self.assertEqual(len(w003_diags), 1)
        self.assertEqual(w003_diags[0].repaired_snippet, "pow(base, exp)")

    def test_bitwise_mask_ignored(self):
        code = """int main() {
    int flags = 240;
    int mask = flags ^ 255;
    return mask;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w003_diags = [d for d in sem.operator_diagnostics if d.code == "W003"]
        self.assertEqual(len(w003_diags), 0)

    def test_autofix_power_of_two(self):
        code = """int main() {
    int val = 2 ^ 8;
    return val;
}
"""
        self.assertIn("1 << 8", repair_all(code))

    def test_autofix_square_compact_syntax(self):
        code = """int main() {
    int x = 5;
    int sq = x^2;
    return sq;
}
"""
        self.assertIn("x * x", repair_all(code))


class TestChainedComparisons(unittest.TestCase):
    """Tests for W004: Misleading chained relational comparisons."""

    def test_chained_less_than_or_equal(self):
        code = """int main() {
    int score = 50;
    if (10 <= score <= 100) {
        return 1;
    }
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w004_diags = [d for d in sem.operator_diagnostics if d.code == "W004"]
        self.assertEqual(len(w004_diags), 1)
        self.assertEqual(w004_diags[0].repaired_snippet, "10 <= score && score <= 100")

    def test_chained_strictly_less_than(self):
        code = """int main() {
    int x = 5;
    if (0 < x < 10) {
        return 1;
    }
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w004_diags = [d for d in sem.operator_diagnostics if d.code == "W004"]
        self.assertEqual(len(w004_diags), 1)
        self.assertEqual(w004_diags[0].repaired_snippet, "0 < x && x < 10")

    def test_chained_mixed_relational(self):
        code = """int main() {
    int x = 5;
    if (1 <= x < 10) {
        return 1;
    }
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w004_diags = [d for d in sem.operator_diagnostics if d.code == "W004"]
        self.assertEqual(len(w004_diags), 1)
        self.assertEqual(w004_diags[0].repaired_snippet, "1 <= x && x < 10")

    def test_normal_conjunction_not_flagged(self):
        code = """int main() {
    int x = 5;
    if (0 < x && x < 10) {
        return 1;
    }
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w004_diags = [d for d in sem.operator_diagnostics if d.code == "W004"]
        self.assertEqual(len(w004_diags), 0)

    def test_autofix_chained_comparison(self):
        code = """int main() {
    int score = 75;
    if (10 <= score <= 100) {
        return 1;
    }
    return 0;
}
"""
        self.assertIn("10 <= score && score <= 100", repair_all(code))

    def test_autofix_chained_compact_no_spaces(self):
        code = """int main() {
    int score = 75;
    if (10<=score<=100) {
        return 1;
    }
    return 0;
}
"""
        self.assertIn("10 <= score && score <= 100", repair_all(code))


class TestBitwiseInBooleanContext(unittest.TestCase):
    """Tests for W005: Bitwise & or | on boolean expressions."""

    def test_bitwise_and_on_bool_variables(self):
        code = """int main() {
    bool hasPermission = true;
    bool isActive = true;
    if (hasPermission & isActive) {
        return 1;
    }
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w005_diags = [d for d in sem.operator_diagnostics if d.code == "W005"]
        self.assertEqual(len(w005_diags), 1)
        self.assertEqual(w005_diags[0].repaired_snippet, "hasPermission && isActive")

    def test_bitwise_or_on_relational_comparisons(self):
        code = """int main() {
    int x = 5;
    int y = 20;
    if ((x > 0) | (y < 10)) {
        return 1;
    }
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w005_diags = [d for d in sem.operator_diagnostics if d.code == "W005"]
        self.assertEqual(len(w005_diags), 1)
        self.assertEqual(w005_diags[0].repaired_snippet, "x > 0 || y < 10")

    def test_integer_bitmask_not_flagged(self):
        code = """int main() {
    int a = 15;
    int b = 240;
    int c = a & b;
    return c;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        w005_diags = [d for d in sem.operator_diagnostics if d.code == "W005"]
        self.assertEqual(len(w005_diags), 0)

    def test_autofix_bitwise_to_logical(self):
        code = """int main() {
    bool hasPermission = true;
    bool isActive = true;
    if (hasPermission & isActive) {
        return 1;
    }
    return 0;
}
"""
        self.assertIn("hasPermission && isActive", repair_all(code))


class TestCentralizedVerification(unittest.TestCase):
    """Repairs are validated by the shared transaction coordinator."""

    def test_centralized_verification_accepts_operator_repair(self):
        code = "int main() { int x = 0; if (x = 0) return 1; return 0; }"
        result = repair_source("<test>", code, confidence_policy="all")
        self.assertTrue(result.success)
        self.assertIn("if (x == 0)", result.updated_source)

    def test_centralized_verification_preserves_unrepairable_source(self):
        code = "int main() { if ( == 0 ) return 1; }"
        result = repair_source("<test>", code, confidence_policy="all")
        self.assertEqual(result.updated_source, code)
        self.assertGreater(result.final_analysis.error_count, 0)


class TestErrorCatalogueW002ToW005(unittest.TestCase):
    """Tests error catalogue registration for warning codes W002-W005."""

    def test_codes_registered(self):
        for code in ["W002", "W003", "W004", "W005"]:
            self.assertIn(code, ERROR_CATALOGUE)
            entry = ERROR_CATALOGUE[code]
            self.assertTrue(len(entry["title"]) > 0)
            self.assertTrue(len(entry["description"]) > 0)
            self.assertTrue(len(entry["cause"]) > 0)
            self.assertTrue(len(entry["example_bad"]) > 0)
            self.assertTrue(len(entry["example_good"]) > 0)


class TestOperatorMisuseCLIE2E(unittest.TestCase):
    """End-to-end CLI tests for check, warn-as-error, explain, and fix."""

    def test_cli_check_displays_warning(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as f:
            f.write("int main() {\n    int x = 2 ^ 8;\n    return x;\n}\n")
            temp_path = f.name

        try:
            res = subprocess.run(
                ["python", "main.py", "check", temp_path],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)
            self.assertIn("warning[W003]", res.stdout)
            self.assertIn("1 << 8", res.stdout)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_cli_warn_as_error_fails(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as f:
            f.write("int main() {\n    int status = 0;\n    if (status = 0) return 1;\n    return 0;\n}\n")
            temp_path = f.name

        try:
            res = subprocess.run(
                ["python", "main.py", "check", "-Werror", temp_path],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("W002", res.stdout)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_cli_explain_all_codes(self):
        for code in ["W002", "W003", "W004", "W005"]:
            res = subprocess.run(
                ["python", "main.py", "explain", code],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)
            self.assertIn(code, res.stdout)

    def test_cli_fix_in_place(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as f:
            f.write("int main() {\n    int score = 50;\n    if (10 <= score <= 100) return 1;\n    return 0;\n}\n")
            temp_path = f.name

        try:
            res = subprocess.run(
                ["python", "main.py", "fix", "-w", temp_path],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)

            with open(temp_path, "r", encoding="utf-8") as f:
                fixed_content = f.read()

            self.assertIn("10 <= score && score <= 100", fixed_content)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
