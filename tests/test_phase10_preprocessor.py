import os
import tempfile
import unittest

from src.analyzer import analyze_translation_unit
from src.preprocessor import Preprocessor


class TestPhase10Preprocessor(unittest.TestCase):
    """Exhaustive tests for Phase 10 preprocessor enhancements:
    - Literal and comment macro protection
    - Nested conditional compilation (#ifdef, #ifndef, #else, #endif)
    - Line count stability and origin mapping
    - Diagnostic production on malformed directives
    """

    def setUp(self):
        self.preprocessor = Preprocessor()

    def test_macro_inside_string_literal_unchanged(self):
        src = '#define FOO 42\nconst char* s = "FOO is not expanded";\n'
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn('"FOO is not expanded"', res.analysis_source)

    def test_macro_inside_char_literal_unchanged(self):
        src = "#define X 99\nchar c = 'X';\n"
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn("'X'", res.analysis_source)

    def test_macro_inside_line_comment_unchanged(self):
        src = "#define VALUE 100\n// VALUE should not be expanded\nint v = VALUE;\n"
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn("// VALUE should not be expanded", res.analysis_source)
        self.assertIn("int v = 100;", res.analysis_source)

    def test_macro_inside_single_line_block_comment_unchanged(self):
        src = "#define BUFFER_SIZE 1024\n/* BUFFER_SIZE comment */\nint b = BUFFER_SIZE;\n"
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn("/* BUFFER_SIZE comment */", res.analysis_source)
        self.assertIn("int b = 1024;", res.analysis_source)

    def test_macro_inside_multiline_block_comment_unchanged(self):
        src = (
            "#define TOTAL 50\n"
            "/*\n"
            " * TOTAL inside multiline comment\n"
            " */\n"
            "int t = TOTAL;\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn("TOTAL inside multiline comment", res.analysis_source)
        self.assertIn("int t = 50;", res.analysis_source)

    def test_macro_partial_identifier_not_expanded(self):
        src = "#define CAT 1\nint CAT_DOG = 2;\nint CAT = 3;\n"
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn("int CAT_DOG = 2;", res.analysis_source)
        self.assertIn("int 1 = 3;", res.analysis_source)

    def test_macro_with_url_comment_preserved(self):
        src = '#define URL "http://example.com/api" // server endpoint\n'
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertEqual(res.macros["URL"], '"http://example.com/api"')

    def test_ifdef_active_branch(self):
        src = (
            "#define FEATURE_ENABLED\n"
            "#ifdef FEATURE_ENABLED\n"
            "int active = 1;\n"
            "#endif\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn("int active = 1;", res.analysis_source)
        # Verify line count preserved
        self.assertEqual(len(src.splitlines()), len(res.analysis_source.splitlines()))

    def test_ifdef_inactive_branch(self):
        src = (
            "#ifdef UNDEFINED_FEATURE\n"
            "int inactive = 1;\n"
            "#endif\n"
            "int active = 2;\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertNotIn("inactive", res.analysis_source)
        self.assertIn("int active = 2;", res.analysis_source)
        self.assertEqual(len(src.splitlines()), len(res.analysis_source.splitlines()))

    def test_ifndef_active_branch(self):
        src = (
            "#ifndef MISSING_FEATURE\n"
            "int present = 1;\n"
            "#endif\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn("int present = 1;", res.analysis_source)

    def test_ifndef_inactive_branch(self):
        src = (
            "#define EXISTING_FEATURE\n"
            "#ifndef EXISTING_FEATURE\n"
            "int suppressed = 1;\n"
            "#endif\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertNotIn("suppressed", res.analysis_source)

    def test_else_branch_switching(self):
        src = (
            "#define USE_FAST\n"
            "#ifdef USE_FAST\n"
            "int mode = 1;\n"
            "#else\n"
            "int mode = 2;\n"
            "#endif\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        lines = res.analysis_source.splitlines()
        self.assertIn("int mode = 1;", lines[2])
        self.assertEqual(lines[4].strip(), "")

        # Without definition:
        src_no_def = (
            "#ifdef USE_FAST\n"
            "int mode = 1;\n"
            "#else\n"
            "int mode = 2;\n"
            "#endif\n"
        )
        res_no_def = self.preprocessor.preprocess(src_no_def, "test.cpp")
        lines_no_def = res_no_def.analysis_source.splitlines()
        self.assertEqual(lines_no_def[1].strip(), "")
        self.assertIn("int mode = 2;", lines_no_def[3])

    def test_nested_conditionals(self):
        src = (
            "#define OUTER\n"
            "#undef INNER\n"
            "#ifdef OUTER\n"
            "    #ifdef INNER\n"
            "    int a = 1;\n"
            "    #else\n"
            "    int b = 2;\n"
            "    #endif\n"
            "#else\n"
            "    int c = 3;\n"
            "#endif\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertNotIn("int a = 1;", res.analysis_source)
        self.assertIn("int b = 2;", res.analysis_source)
        self.assertNotIn("int c = 3;", res.analysis_source)

    def test_inactive_include_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_cpp = os.path.join(tmpdir, "main.cpp")
            src = (
                "#ifdef NEVER_DEFINED\n"
                '#include "non_existent_file_12345.h"\n'
                "#endif\n"
                "int main() { return 0; }\n"
            )
            res = self.preprocessor.preprocess(src, file_cpp)
            self.assertNotIn("non_existent_file_12345.h", res.included_headers)
            self.assertEqual(len(res.diagnostics), 0)

    def test_inactive_define_and_undef_do_not_leak(self):
        src = (
            "#ifdef NEVER_DEFINED\n"
            "#define LEAKED_VAL 999\n"
            "#endif\n"
            "int val = LEAKED_VAL;\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertNotIn("LEAKED_VAL", res.macros)
        self.assertIn("int val = LEAKED_VAL;", res.analysis_source)

    def test_unmatched_else_diagnostic(self):
        src = "int x = 1;\n#else\nint y = 2;\n"
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertTrue(any("unmatched #else" in d.message for d in res.diagnostics))

    def test_unmatched_endif_diagnostic(self):
        src = "int x = 1;\n#endif\n"
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertTrue(any("unmatched #endif" in d.message for d in res.diagnostics))

    def test_duplicate_else_diagnostic(self):
        src = (
            "#ifdef FOO\n"
            "int a = 1;\n"
            "#else\n"
            "int b = 2;\n"
            "#else\n"
            "int c = 3;\n"
            "#endif\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertTrue(any("duplicate #else" in d.message for d in res.diagnostics))

    def test_unterminated_conditional_diagnostic(self):
        src = "int a = 1;\n#ifdef MISSING_ENDIF\nint b = 2;\n"
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertTrue(any("unterminated #ifdef" in d.message for d in res.diagnostics))

    def test_include_without_whitespace(self):
        src = "#include<string>\n#include<iostream>\nint main() { return 0; }\n"
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn("string", res.included_headers)
        self.assertIn("iostream", res.included_headers)
        self.assertIn("// Standard header <string>", res.analysis_source)

    def test_if_defined_active_branch(self):
        src = (
            "#define DEBUG\n"
            "#if defined(DEBUG)\n"
            "int x = 1;\n"
            "#else\n"
            "int x = 2;\n"
            "#endif\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn("int x = 1;", res.analysis_source)
        self.assertNotIn("int x = 2;", res.analysis_source)
        self.assertEqual(len(src.splitlines()), len(res.analysis_source.splitlines()))

    def test_if_defined_inactive_branch(self):
        src = (
            "#if defined(DEBUG)\n"
            "int x = 1;\n"
            "#else\n"
            "int x = 2;\n"
            "#endif\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertNotIn("int x = 1;", res.analysis_source)
        self.assertIn("int x = 2;", res.analysis_source)

    def test_if_expr_comparison_and_logic(self):
        src = (
            "#define VERSION 3\n"
            "#if VERSION >= 2 && VERSION < 5\n"
            "int supported = 1;\n"
            "#else\n"
            "int supported = 0;\n"
            "#endif\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn("int supported = 1;", res.analysis_source)
        self.assertNotIn("int supported = 0;", res.analysis_source)

    def test_if_elif_else_ladder(self):
        src = (
            "#define LEVEL 2\n"
            "#if LEVEL == 1\n"
            "int l = 10;\n"
            "#elif LEVEL == 2\n"
            "int l = 20;\n"
            "#elif LEVEL == 3\n"
            "int l = 30;\n"
            "#else\n"
            "int l = 40;\n"
            "#endif\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertNotIn("int l = 10;", res.analysis_source)
        self.assertIn("int l = 20;", res.analysis_source)
        self.assertNotIn("int l = 30;", res.analysis_source)
        self.assertNotIn("int l = 40;", res.analysis_source)

    def test_function_like_macro_expansion(self):
        src = (
            "#define SQUARE(x) ((x) * (x))\n"
            "int y = SQUARE(3);\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn("int y = ((3) * (3));", res.analysis_source)
        self.assertIn("SQUARE", res.macros)

    def test_function_like_macro_nested_call(self):
        src = (
            "#define ADD(a, b) ((a) + (b))\n"
            "#define MULT(a, b) ((a) * (b))\n"
            "int z = MULT(ADD(1, 2), 3);\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn("int z = ((((1) + (2))) * (3));", res.analysis_source)

    def test_function_like_macro_not_expanded_without_parens(self):
        src = (
            "#define FOO(x) ((x) + 1)\n"
            "int FOO = 42;\n"
            "int val = FOO(5);\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn("int FOO = 42;", res.analysis_source)
        self.assertIn("int val = ((5) + 1);", res.analysis_source)

    def test_comment_marker_in_string_literal_does_not_corrupt_preprocessor(self):
        src = (
            'const char* s = "/*";\n'
            "#define FOO 42\n"
            "int x = FOO;\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn('const char* s = "/*";', res.analysis_source)
        self.assertIn("int x = 42;", res.analysis_source)

    def test_comment_marker_in_char_literal_does_not_corrupt_preprocessor(self):
        src = (
            "char c = '/*';\n"
            "#define BAR 100\n"
            "int y = BAR;\n"
        )
        res = self.preprocessor.preprocess(src, "test.cpp")
        self.assertIn("int y = 100;", res.analysis_source)

    def test_integration_with_analyzer(self):
        with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False, encoding="utf-8") as f:
            f.write("#ifdef UNSET_MACRO\nint bad syntax;\n#endif\nint main() { return 0; }\n")
            f_path = f.name
        try:
            result = analyze_translation_unit(f_path)
            self.assertTrue(result.preprocess_completed)
            self.assertTrue(result.parser_completed)
            # The bad syntax was in inactive conditional branch, so no syntax errors should be reported!
            syntax_errors = [d for d in result.diagnostics if d.code.startswith("P")]
            self.assertEqual(len(syntax_errors), 0)
        finally:
            if os.path.exists(f_path):
                os.remove(f_path)


if __name__ == "__main__":
    unittest.main()
