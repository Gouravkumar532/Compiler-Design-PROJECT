"""
Unit Test Suite for Auto-Include & Missing Header Recommendation Engine (Idea 4)
"""

import os
import subprocess
import tempfile
import unittest

from src.lexer import Lexer
from src.parser import Parser
from src.semantic import SemanticAnalyzer
from src.preprocessor import Preprocessor
from src.stdlib_registry import StdlibRegistry, registry
from src.auto_include import AutoIncludeEngine, restore_preprocessor_includes
from src.error_catalogue import ERROR_CATALOGUE
from src.errors import explain_error


class TestStdlibRegistry(unittest.TestCase):
    """Tests for the standard library symbol registry and lookup mechanisms."""

    def setUp(self):
        self.reg = StdlibRegistry()

    def test_unqualified_lookup(self):
        self.assertEqual(self.reg.lookup("cout"), "iostream")
        self.assertEqual(self.reg.lookup("cin"), "iostream")
        self.assertEqual(self.reg.lookup("endl"), "iostream")
        self.assertEqual(self.reg.lookup("string"), "string")
        self.assertEqual(self.reg.lookup("vector"), "vector")
        self.assertEqual(self.reg.lookup("sqrt"), "cmath")
        self.assertEqual(self.reg.lookup("printf"), "cstdio")
        self.assertEqual(self.reg.lookup("malloc"), "cstdlib")
        self.assertEqual(self.reg.lookup("sort"), "algorithm")
        self.assertEqual(self.reg.lookup("map"), "map")
        self.assertEqual(self.reg.lookup("set"), "set")
        self.assertEqual(self.reg.lookup("unique_ptr"), "memory")

    def test_qualified_lookup(self):
        self.assertEqual(self.reg.lookup("std::cout"), "iostream")
        self.assertEqual(self.reg.lookup("std::vector"), "vector")
        self.assertEqual(self.reg.lookup("std::string"), "string")
        self.assertEqual(self.reg.lookup("std::sqrt"), "cmath")
        self.assertEqual(self.reg.lookup("std::sort"), "algorithm")
        self.assertEqual(self.reg.lookup("::std::endl"), "iostream")

    def test_templated_type_lookup(self):
        self.assertEqual(self.reg.lookup("std::vector<int>"), "vector")
        self.assertEqual(self.reg.lookup("vector<std::string>"), "vector")
        self.assertEqual(self.reg.lookup("std::map<int, double>"), "map")
        self.assertEqual(self.reg.lookup("unique_ptr<int>"), "memory")

    def test_unknown_symbol_returns_none(self):
        self.assertIsNone(self.reg.lookup("foobar_custom_func"))
        self.assertIsNone(self.reg.lookup("MyCustomClass"))
        self.assertIsNone(self.reg.lookup(""))

    def test_equivalent_c_and_cpp_headers(self):
        self.assertTrue(self.reg.is_header_included("cmath", {"math.h"}))
        self.assertTrue(self.reg.is_header_included("math.h", {"cmath"}))
        self.assertTrue(self.reg.is_header_included("cstdio", {"stdio.h"}))
        self.assertTrue(self.reg.is_header_included("cstdlib", {"stdlib.h"}))
        self.assertTrue(self.reg.is_header_included("cstring", {"string.h"}))
        self.assertFalse(self.reg.is_header_included("iostream", {"vector", "cmath"}))


class TestAutoIncludePlacement(unittest.TestCase):
    """Tests for optimal header insertion placement."""

    def test_empty_or_code_only_inserts_at_line_1(self):
        src = "int main() {\n    return 0;\n}\n"
        line = AutoIncludeEngine.find_insertion_point(src)
        self.assertEqual(line, 1)

    def test_inserts_after_existing_includes(self):
        src = "#include <vector>\n#include <string>\n\nint main() {}\n"
        line = AutoIncludeEngine.find_insertion_point(src)
        self.assertEqual(line, 3)

    def test_inserts_after_pragma_once(self):
        src = "#pragma once\n\nint main() {}\n"
        line = AutoIncludeEngine.find_insertion_point(src)
        self.assertEqual(line, 2)

    def test_inserts_after_include_guards(self):
        src = "#ifndef HEADER_H\n#define HEADER_H\n\nint main() {}\n#endif\n"
        line = AutoIncludeEngine.find_insertion_point(src)
        self.assertEqual(line, 3)

    def test_inserts_after_leading_comments(self):
        src = "// Copyright 2026\n// Example file\n\nint main() {}\n"
        line = AutoIncludeEngine.find_insertion_point(src)
        self.assertEqual(line, 4)


class TestAutoIncludePatchGeneration(unittest.TestCase):
    """Tests patch generation and idempotency."""

    def setUp(self):
        self.engine = AutoIncludeEngine("")

    def test_patch_single_include(self):
        src = "int main() {\n    cout << 10;\n}\n"
        patched = self.engine.generate_patch(src, ["iostream"])
        self.assertTrue(patched.startswith("#include <iostream>\n\nint main()"))

    def test_patch_multiple_includes_preserves_order(self):
        src = "int main() {}\n"
        patched = self.engine.generate_patch(src, ["vector", "string", "cmath"])
        self.assertIn("#include <vector>\n#include <string>\n#include <cmath>", patched)

    def test_patch_idempotency_does_not_duplicate(self):
        src = "#include <iostream>\n\nint main() {\n    cout << 10;\n}\n"
        patched = self.engine.generate_patch(src, ["iostream"])
        self.assertEqual(patched, src)
        # Count occurrences of iostream
        self.assertEqual(patched.count("<iostream>"), 1)

    def test_restore_preprocessor_includes(self):
        src = "// Standard header <vector> provided by compiler runtime\nint main() {}"
        restored = restore_preprocessor_includes(src)
        self.assertEqual(restored, "#include <vector>\nint main() {}")


class TestSemanticMissingHeaderDetection(unittest.TestCase):
    """Tests semantic analyzer missing header interception and diagnostics."""

    def test_pattern_1_missing_iostream(self):
        code = "int main() {\n    std::cout << \"Hello\" << std::endl;\n}\n"
        tokens = Lexer(code, "<test>").tokenize()
        ast = Parser(tokens, code, "<test>").parse()
        sem = SemanticAnalyzer(code, "<test>", exit_on_error=False)
        sem.analyze(ast)

        self.assertIn("iostream", sem.missing_headers)
        self.assertGreaterEqual(sem.errors_count, 1)
        self.assertTrue(any(d.header == "iostream" for d in sem.missing_header_diagnostics))

    def test_pattern_2_missing_vector_and_string(self):
        code = "int main() {\n    std::vector<std::string> names;\n}\n"
        tokens = Lexer(code, "<test>").tokenize()
        ast = Parser(tokens, code, "<test>").parse()
        sem = SemanticAnalyzer(code, "<test>", exit_on_error=False)
        sem.analyze(ast)

        self.assertIn("vector", sem.missing_headers)
        self.assertIn("string", sem.missing_headers)
        self.assertGreaterEqual(sem.errors_count, 2)

    def test_pattern_3_missing_cmath_and_cstdlib(self):
        code = "int main() {\n    double root = sqrt(16.0);\n    int* p = (int*)malloc(sizeof(int));\n}\n"
        tokens = Lexer(code, "<test>").tokenize()
        ast = Parser(tokens, code, "<test>").parse()
        sem = SemanticAnalyzer(code, "<test>", exit_on_error=False)
        sem.analyze(ast)

        self.assertIn("cmath", sem.missing_headers)
        self.assertIn("cstdlib", sem.missing_headers)
        self.assertGreaterEqual(sem.errors_count, 2)

    def test_multiple_symbols_same_header_deduplicated(self):
        code = "int main() {\n    cout << 1;\n    cin >> x;\n    cerr << 2;\n    clog << 3;\n}\n"
        tokens = Lexer(code, "<test>").tokenize()
        ast = Parser(tokens, code, "<test>").parse()
        sem = SemanticAnalyzer(code, "<test>", exit_on_error=False)
        sem.analyze(ast)

        # Ensure missing_headers list only has one instance of iostream
        self.assertEqual(sem.missing_headers.count("iostream"), 1)

    def test_c_standard_io_printf_and_file(self):
        code = "int main() {\n    FILE* fp = (FILE*)0;\n    printf(\"Value\\n\");\n}\n"
        tokens = Lexer(code, "<test>").tokenize()
        ast = Parser(tokens, code, "<test>").parse()
        sem = SemanticAnalyzer(code, "<test>", exit_on_error=False)
        sem.analyze(ast)

        self.assertIn("cstdio", sem.missing_headers)

    def test_header_included_causes_no_errors(self):
        code = "#include <iostream>\nint main() {\n    std::cout << 42;\n    return 0;\n}\n"
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", included_headers=prep.included_headers, exit_on_error=False)
        sem.analyze(ast)

        self.assertEqual(len(sem.missing_headers), 0)
        self.assertEqual(sem.errors_count, 0)

    def test_header_included_but_missing_namespace_suggestion(self):
        code = "#include <iostream>\nint main() {\n    cout << 42;\n    return 0;\n}\n"
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", included_headers=prep.included_headers, exit_on_error=False)
        sem.analyze(ast)

        # <iostream> is already included, so it shouldn't suggest adding <iostream> again
        self.assertNotIn("iostream", sem.missing_headers)
        # Should be an undeclared identifier error with namespace suggestion
        self.assertGreater(sem.errors_count, 0)

    def test_templated_function_call_missing_header(self):
        code = "int main() {\n    std::make_unique<int>(42);\n}\n"
        tokens = Lexer(code, "<test>").tokenize()
        ast = Parser(tokens, code, "<test>").parse()
        sem = SemanticAnalyzer(code, "<test>", exit_on_error=False)
        sem.analyze(ast)

        self.assertIn("memory", sem.missing_headers)

    def test_error_catalogue_e015_registered(self):
        self.assertIn("E015", ERROR_CATALOGUE)
        info = ERROR_CATALOGUE["E015"]
        self.assertEqual(info["title"], "Missing Standard Library Header")
        self.assertIn("cout", info["cause"])


class TestAutoIncludeCLIE2E(unittest.TestCase):
    """End-to-end command line tests for check, suggest, and fix commands."""

    def test_cli_check_fails_on_missing_header(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as f:
            f.write("int main() {\n    std::cout << 100;\n}\n")
            temp_path = f.name

        try:
            res = subprocess.run(
                ["python", "main.py", "check", temp_path],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("error[E015]", res.stdout)
            self.assertIn("<iostream>", res.stdout)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_cli_fix_writes_in_place_and_passes_subsequent_check(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as f:
            f.write("int main() {\n    std::vector<std::string> names;\n}\n")
            temp_path = f.name

        try:
            # 1. Run fix -w
            fix_res = subprocess.run(
                ["python", "main.py", "fix", temp_path, "-w"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(fix_res.returncode, 0)

            with open(temp_path, "r", encoding="utf-8") as f:
                repaired = f.read()

            self.assertIn("#include <vector>", repaired)
            self.assertIn("#include <string>", repaired)

            # 2. Subsequent check passes without error
            check_res = subprocess.run(
                ["python", "main.py", "check", temp_path],
                capture_output=True,
                text=True,
            )
            self.assertEqual(check_res.returncode, 0)
            self.assertIn("Check passed without errors", check_res.stdout)

            # 3. Running fix a second time does not duplicate headers (idempotency)
            fix_res_2 = subprocess.run(
                ["python", "main.py", "fix", temp_path, "-w"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(fix_res_2.returncode, 0)
            with open(temp_path, "r", encoding="utf-8") as f:
                repaired_2 = f.read()
            self.assertEqual(repaired_2.count("<vector>"), 1)
            self.assertEqual(repaired_2.count("<string>"), 1)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_cli_suggest_reports_without_modifying_file(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as f:
            original_code = "int main() {\n    double root = sqrt(4.0);\n}\n"
            f.write(original_code)
            temp_path = f.name

        try:
            suggest_res = subprocess.run(
                ["python", "main.py", "suggest", temp_path],
                capture_output=True,
                text=True,
            )
            # Diagnosed E015 in output
            self.assertIn("error[E015]", suggest_res.stdout)
            self.assertIn("<cmath>", suggest_res.stdout)

            # Ensure file on disk was NOT modified
            with open(temp_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(content, original_code)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_cli_multi_file_fix(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as f1:
            f1.write("int main() {\n    std::cout << 1;\n}\n")
            path1 = f1.name

        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as f2:
            f2.write("int main() {\n    std::vector<int> v;\n}\n")
            path2 = f2.name

        try:
            res = subprocess.run(
                ["python", "main.py", "fix", path1, path2, "-w"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)

            with open(path1, "r", encoding="utf-8") as f:
                c1 = f.read()
            with open(path2, "r", encoding="utf-8") as f:
                c2 = f.read()

            self.assertIn("#include <iostream>", c1)
            self.assertIn("#include <vector>", c2)
        finally:
            for p in [path1, path2]:
                if os.path.exists(p):
                    os.remove(p)


if __name__ == "__main__":
    unittest.main()
