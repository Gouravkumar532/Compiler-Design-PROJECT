"""
Unit and Integration Test Suite for Static Array Bounds & Off-By-One Diagnostics (Idea 8)
"""

import os
import subprocess
import tempfile
import unittest

from src.lexer import Lexer
from src.parser import Parser
from src.semantic import SemanticAnalyzer
from src.preprocessor import Preprocessor
from src.array_bounds import ArrayBoundsEngine, ArrayBoundsDiagnostic
from src.error_catalogue import ERROR_CATALOGUE


def analyze_test_code(code: str) -> SemanticAnalyzer:
    prep = Preprocessor()
    processed = prep.process(code, "<test>")
    tokens = Lexer(processed, "<test>").tokenize()
    ast = Parser(tokens, processed, "<test>").parse()
    sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
    sem.analyze(ast)
    return sem


class TestLiteralArrayBounds(unittest.TestCase):
    """Tests for W006: Constant Literal Array Index Out of Bounds."""

    def test_literal_index_equal_size_warns(self):
        code = """int main() {
    int buffer[5];
    buffer[5] = 42;
    return 0;
}
"""
        sem = analyze_test_code(code)
        w006_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W006"]
        self.assertEqual(len(w006_diags), 1)
        self.assertEqual(w006_diags[0].array_name, "buffer")
        self.assertEqual(w006_diags[0].array_size, 5)
        self.assertEqual(w006_diags[0].accessed_index, 5)
        self.assertEqual(w006_diags[0].repaired_snippet, "buffer[4]")

    def test_literal_index_greater_than_size_warns(self):
        code = """int main() {
    int arr[10];
    int x = arr[15];
    return x;
}
"""
        sem = analyze_test_code(code)
        w006_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W006"]
        self.assertEqual(len(w006_diags), 1)
        self.assertEqual(w006_diags[0].accessed_index, 15)
        self.assertEqual(w006_diags[0].repaired_snippet, "arr[9]")

    def test_literal_index_negative_warns(self):
        code = """int main() {
    int arr[5];
    int last = arr[-1];
    return last;
}
"""
        sem = analyze_test_code(code)
        w006_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W006"]
        self.assertEqual(len(w006_diags), 1)
        self.assertEqual(w006_diags[0].accessed_index, -1)
        self.assertIn("negative", w006_diags[0].message)
        self.assertEqual(w006_diags[0].repaired_snippet, "arr[4]")

    def test_literal_index_negative_two_warns(self):
        code = """int main() {
    int arr[5];
    int second_last = arr[-2];
    return second_last;
}
"""
        sem = analyze_test_code(code)
        w006_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W006"]
        self.assertEqual(len(w006_diags), 1)
        self.assertEqual(w006_diags[0].accessed_index, -2)
        self.assertEqual(w006_diags[0].repaired_snippet, "arr[3]")

    def test_literal_index_within_bounds_no_warning(self):
        code = """int main() {
    int buffer[5];
    buffer[0] = 1;
    buffer[4] = 2;
    int a = buffer[0];
    int b = buffer[4];
    return a + b;
}
"""
        sem = analyze_test_code(code)
        w006_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W006"]
        self.assertEqual(len(w006_diags), 0)

    def test_deduced_array_size_literal_bounds(self):
        code = """int main() {
    int arr[] = {10, 20, 30};
    arr[3] = 40;
    return 0;
}
"""
        sem = analyze_test_code(code)
        w006_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W006"]
        self.assertEqual(len(w006_diags), 1)
        self.assertEqual(w006_diags[0].array_size, 3)
        self.assertEqual(w006_diags[0].accessed_index, 3)
        self.assertEqual(w006_diags[0].repaired_snippet, "arr[2]")

    def test_deduced_array_size_valid_no_warning(self):
        code = """int main() {
    int arr[] = {10, 20, 30};
    int x = arr[2];
    return x;
}
"""
        sem = analyze_test_code(code)
        w006_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W006"]
        self.assertEqual(len(w006_diags), 0)

    def test_const_variable_array_size(self):
        code = """int main() {
    const int N = 5;
    int arr[N];
    arr[5] = 10;
    return 0;
}
"""
        sem = analyze_test_code(code)
        w006_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W006"]
        self.assertEqual(len(w006_diags), 1)
        self.assertEqual(w006_diags[0].accessed_index, 5)

    def test_constexpr_variable_array_size(self):
        code = """int main() {
    constexpr int SIZE = 8;
    int arr[SIZE];
    arr[8] = 0;
    return 0;
}
"""
        sem = analyze_test_code(code)
        w006_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W006"]
        self.assertEqual(len(w006_diags), 1)
        self.assertEqual(w006_diags[0].accessed_index, 8)

    def test_multidimensional_array_first_dim_bounds(self):
        code = """int main() {
    int grid[3][3];
    grid[3][0] = 1;
    return 0;
}
"""
        sem = analyze_test_code(code)
        w006_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W006"]
        self.assertEqual(len(w006_diags), 1)
        self.assertEqual(w006_diags[0].accessed_index, 3)

    def test_multidimensional_array_second_dim_bounds(self):
        code = """int main() {
    int grid[3][3];
    grid[0][3] = 1;
    return 0;
}
"""
        sem = analyze_test_code(code)
        w006_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W006"]
        self.assertEqual(len(w006_diags), 1)
        self.assertEqual(w006_diags[0].accessed_index, 3)

    def test_multidimensional_array_valid_no_warning(self):
        code = """int main() {
    int grid[3][3];
    grid[0][0] = 1;
    grid[2][2] = 2;
    return 0;
}
"""
        sem = analyze_test_code(code)
        w006_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W006"]
        self.assertEqual(len(w006_diags), 0)

    def test_pointer_subscripting_no_warning(self):
        code = """int main() {
    int* ptr = (int*)0;
    ptr[10] = 1;
    return 0;
}
"""
        sem = analyze_test_code(code)
        w006_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W006"]
        self.assertEqual(len(w006_diags), 0)


class TestLoopBoundsOffByOne(unittest.TestCase):
    """Tests for W007: Loop Boundary Off-by-One Array Hazards."""

    def test_for_loop_less_or_equal_warns(self):
        code = """int main() {
    int scores[10];
    for (int i = 0; i <= 10; i++) {
        scores[i] = 0;
    }
    return 0;
}
"""
        sem = analyze_test_code(code)
        w007_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W007"]
        self.assertEqual(len(w007_diags), 1)
        self.assertEqual(w007_diags[0].array_name, "scores")
        self.assertEqual(w007_diags[0].array_size, 10)
        self.assertEqual(w007_diags[0].accessed_index, 10)
        self.assertEqual(w007_diags[0].repaired_snippet, "i < 10")

    def test_for_loop_strictly_less_no_warning(self):
        code = """int main() {
    int scores[10];
    for (int i = 0; i < 10; i++) {
        scores[i] = 0;
    }
    return 0;
}
"""
        sem = analyze_test_code(code)
        w007_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W007"]
        self.assertEqual(len(w007_diags), 0)

    def test_for_loop_less_or_equal_size_minus_one_no_warning(self):
        code = """int main() {
    int scores[10];
    for (int i = 0; i <= 9; i++) {
        scores[i] = 0;
    }
    return 0;
}
"""
        sem = analyze_test_code(code)
        w007_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W007"]
        self.assertEqual(len(w007_diags), 0)

    def test_for_loop_1_based_indexing_confusion(self):
        code = """int main() {
    int data[10];
    for (int i = 1; i <= 10; i++) {
        data[i] = i * 2;
    }
    return 0;
}
"""
        sem = analyze_test_code(code)
        w007_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W007"]
        self.assertEqual(len(w007_diags), 1)
        self.assertIn("1-based", w007_diags[0].message)

    def test_for_loop_1_based_indexing_adjusted_index_no_warning(self):
        code = """int main() {
    int data[10];
    for (int i = 1; i <= 10; i++) {
        data[i - 1] = i * 2;
    }
    return 0;
}
"""
        sem = analyze_test_code(code)
        w007_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W007"]
        self.assertEqual(len(w007_diags), 0)

    def test_for_loop_with_const_bound_var(self):
        code = """int main() {
    const int N = 10;
    int scores[N];
    for (int i = 0; i <= N; i++) {
        scores[i] = 0;
    }
    return 0;
}
"""
        sem = analyze_test_code(code)
        w007_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W007"]
        self.assertEqual(len(w007_diags), 1)
        self.assertEqual(w007_diags[0].repaired_snippet, "i < N")

    def test_for_loop_exceeding_smaller_array(self):
        code = """int main() {
    int arr[5];
    for (int i = 0; i < 10; i++) {
        arr[i] = 0;
    }
    return 0;
}
"""
        sem = analyze_test_code(code)
        w007_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W007"]
        self.assertEqual(len(w007_diags), 1)

    def test_for_loop_offset_exceeds_bounds(self):
        code = """int main() {
    int arr[10];
    for (int i = 0; i < 10; i++) {
        arr[i + 1] = 0;
    }
    return 0;
}
"""
        sem = analyze_test_code(code)
        w007_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W007"]
        self.assertEqual(len(w007_diags), 1)

    def test_for_loop_reverse_out_of_bounds(self):
        code = """int main() {
    int arr[10];
    for (int i = 10; i >= 0; i--) {
        arr[i] = 0;
    }
    return 0;
}
"""
        sem = analyze_test_code(code)
        w007_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W007"]
        self.assertEqual(len(w007_diags), 1)
        self.assertIn("reverse", w007_diags[0].message)

    def test_while_loop_off_by_one(self):
        code = """int main() {
    int scores[10];
    int i = 0;
    while (i <= 10) {
        scores[i] = 0;
        i++;
    }
    return 0;
}
"""
        sem = analyze_test_code(code)
        w007_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W007"]
        self.assertEqual(len(w007_diags), 1)
        self.assertEqual(w007_diags[0].repaired_snippet, "i < 10")

    def test_do_while_loop_off_by_one(self):
        code = """int main() {
    int scores[10];
    int i = 0;
    do {
        scores[i] = 0;
        i++;
    } while (i <= 10);
    return 0;
}
"""
        sem = analyze_test_code(code)
        w007_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W007"]
        self.assertEqual(len(w007_diags), 1)
        self.assertEqual(w007_diags[0].repaired_snippet, "i < 10")

    def test_multiple_arrays_in_loop_prioritizes_smaller_capacity(self):
        code = """int main() {
    int big[10];
    int small[5];
    for (int i = 0; i <= 10; i++) {
        big[i] = 1;
        small[i] = 2;
    }
    return 0;
}
"""
        sem = analyze_test_code(code)
        w007_diags = [d for d in sem.array_bounds_diagnostics if d.code == "W007"]
        self.assertEqual(len(w007_diags), 1)
        self.assertEqual(w007_diags[0].array_name, "small")
        self.assertEqual(w007_diags[0].array_size, 5)


class TestArrayBoundsErrorCatalogue(unittest.TestCase):
    """Tests that W006 and W007 are catalogued with explanations and examples."""

    def test_w006_and_w007_catalogue_entries(self):
        for code in ["W006", "W007"]:
            self.assertIn(code, ERROR_CATALOGUE)
            entry = ERROR_CATALOGUE[code]
            self.assertTrue(len(entry["title"]) > 0)
            self.assertTrue(len(entry["description"]) > 0)
            self.assertTrue(len(entry["cause"]) > 0)
            self.assertTrue(len(entry["example_bad"]) > 0)
            self.assertTrue(len(entry["example_good"]) > 0)


class TestArrayBoundsCLIE2E(unittest.TestCase):
    """End-to-end CLI tests for check, warn-as-error, explain, and fix."""

    def test_cli_check_displays_warning(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as f:
            f.write("int main() {\n    int scores[10];\n    for (int i = 0; i <= 10; i++) {\n        scores[i] = 0;\n    }\n    return 0;\n}\n")
            temp_path = f.name

        try:
            res = subprocess.run(
                ["python", "main.py", "check", temp_path],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)
            self.assertIn("warning[W007]", res.stdout)
            self.assertIn("off-by-one", res.stdout)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_cli_warn_as_error_fails(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as f:
            f.write("int main() {\n    int scores[10];\n    for (int i = 0; i <= 10; i++) {\n        scores[i] = 0;\n    }\n    return 0;\n}\n")
            temp_path = f.name

        try:
            res = subprocess.run(
                ["python", "main.py", "check", "-Werror", temp_path],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("W007", res.stdout)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_cli_explain_w006_and_w007(self):
        for code in ["W006", "W007"]:
            res = subprocess.run(
                ["python", "main.py", "explain", code],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)
            self.assertIn(code, res.stdout)

    def test_cli_fix_w007_in_place(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as f:
            f.write("int main() {\n    int scores[10];\n    for (int i = 0; i <= 10; i++) {\n        scores[i] = 0;\n    }\n    return 0;\n}\n")
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

            self.assertIn("i < 10", fixed_content)
            self.assertNotIn("i <= 10", fixed_content)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_cli_fix_w006_is_review_only(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as f:
            f.write("int main() {\n    int buffer[5];\n    buffer[5] = 42;\n    return 0;\n}\n")
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

            self.assertIn("buffer[5] = 42", fixed_content)
            self.assertNotIn("buffer[4] = 42", fixed_content)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_cli_fix_w006_negative_is_review_only(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as f:
            f.write("int main() {\n    int arr[5];\n    int last = arr[-1];\n    return last;\n}\n")
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

            self.assertIn("arr[-1]", fixed_content)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
