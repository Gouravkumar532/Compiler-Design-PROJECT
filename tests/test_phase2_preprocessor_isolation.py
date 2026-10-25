import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from main import main as cli_main
from src.analyzer import analyze_translation_unit
from src.repair_coordinator import repair_source
from src.lexer import Lexer
from src.lsp import LanguageServer
from src.paths import same_file
from src.preprocessor import Preprocessor
from src.tokens import TokenType
from src.tui_wizard import PatchReviewWizard
from src.ui_server import extract_structured_diagnostics


class TestPhase2PreprocessorIsolation(unittest.TestCase):
    """Comprehensive tests verifying Phase 2 preprocessor isolation, provenance, and write guards."""

    def test_single_preprocessor_instance_call_isolation(self):
        """Reusing one Preprocessor instance across multiple files must not leak macros, headers, or include sets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            header = os.path.join(tmpdir, "shared.h")
            with open(header, "w", encoding="utf-8") as f:
                f.write("int shared_fn() { return 7; }\n")

            file_a = os.path.join(tmpdir, "a.cpp")
            file_b = os.path.join(tmpdir, "b.cpp")
            src_a = '#include <vector>\n#include "shared.h"\n#define ONLY_IN_A 999\nint a = ONLY_IN_A;\n'
            src_b = '#include "shared.h"\nint b = ONLY_IN_A;\nint main() { std::vector<int> v; return shared_fn(); }\n'

            prep = Preprocessor()
            res_a = prep.preprocess(src_a, file_a)
            res_b = prep.preprocess(src_b, file_b)

            self.assertIn("ONLY_IN_A", res_a.macros)
            self.assertNotIn("ONLY_IN_A", res_b.macros)
            self.assertIn("vector", res_a.included_headers)
            self.assertNotIn("vector", res_b.included_headers)

            # shared.h must be expanded in both res_a and res_b
            self.assertIn("shared_fn", res_a.analysis_source)
            self.assertIn("shared_fn", res_b.analysis_source)

    def test_macros_do_not_leak_between_translation_units(self):
        """Macros defined in file A must not exist when file B is analyzed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_a = os.path.join(tmpdir, "a.cpp")
            file_b = os.path.join(tmpdir, "b.cpp")

            with open(file_a, "w", encoding="utf-8") as f:
                f.write("#define LEAKED_MACRO 12345\nint a = LEAKED_MACRO;\n")

            with open(file_b, "w", encoding="utf-8") as f:
                f.write("int b = LEAKED_MACRO;\n")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                analyze_translation_unit(file_a)
                result_b = analyze_translation_unit(file_b)

            b_lexemes = [t.lexeme for t in result_b.tokens]
            self.assertIn("LEAKED_MACRO", b_lexemes)
            self.assertNotIn("12345", b_lexemes)

    def test_included_headers_do_not_suppress_needed_includes_between_files(self):
        """Included headers in file A must not suppress needed includes in file B."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_a = os.path.join(tmpdir, "a.cpp")
            file_b = os.path.join(tmpdir, "b.cpp")

            with open(file_a, "w", encoding="utf-8") as f:
                f.write("#include <vector>\nint main() { std::vector<int> v; return 0; }\n")

            with open(file_b, "w", encoding="utf-8") as f:
                f.write("int main() { std::vector<int> v; return 0; }\n")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                analyze_translation_unit(file_a)
                result_b = analyze_translation_unit(file_b)

            missing = result_b.missing_headers
            self.assertIn("vector", missing)

    def test_local_include_deduplication_does_not_leak_between_files(self):
        """Local include deduplication state must not leak between files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            header = os.path.join(tmpdir, "shared.h")
            with open(header, "w", encoding="utf-8") as f:
                f.write("int shared_func() { return 42; }\n")

            file_a = os.path.join(tmpdir, "a.cpp")
            file_b = os.path.join(tmpdir, "b.cpp")

            with open(file_a, "w", encoding="utf-8") as f:
                f.write('#include "shared.h"\nint main() { return shared_func(); }\n')

            with open(file_b, "w", encoding="utf-8") as f:
                f.write('#include "shared.h"\nint main() { return shared_func(); }\n')

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                analyze_translation_unit(file_a)
                result_b = analyze_translation_unit(file_b)

            b_lexemes = [t.lexeme for t in result_b.tokens]
            self.assertIn("shared_func", b_lexemes)
            self.assertEqual(result_b.error_count, 0)

    def test_monotonic_analysis_lines_and_indentation_across_header_and_parent(self):
        """Token analysis lines remain monotonic across a long header and short parent, and indentation uses analysis lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            header = os.path.join(tmpdir, "long_header.h")
            # Header has 15 lines; line 2 has indent 8
            header_lines = ["struct H {"] + ["        int m" + str(i) + ";" for i in range(13)] + ["};"]
            with open(header, "w", encoding="utf-8") as f:
                f.write("\n".join(header_lines) + "\n")

            parent = os.path.join(tmpdir, "parent.cpp")
            # Parent line 2 has indent 4
            parent_src = '#include "long_header.h"\nint main() {\n    return 0;\n}\n'
            with open(parent, "w", encoding="utf-8") as f:
                f.write(parent_src)

            prep = Preprocessor()
            pres = prep.preprocess(parent_src, parent)
            tokens = Lexer(pres.analysis_source, parent, preproc_result=pres).tokenize()
            non_eof = [t for t in tokens if t.type != TokenType.EOF]

            # Analysis lines must be non-decreasing across the entire stream
            for prev_t, curr_t in zip(non_eof, non_eof[1:]):
                self.assertLessEqual(prev_t.line, curr_t.line)

            # Find 'return' in parent.cpp (physical line 3, indent 4)
            ret_tok = [t for t in non_eof if t.lexeme == "return"][0]
            self.assertTrue(same_file(ret_tok.file, parent))
            self.assertEqual(ret_tok.source_line, 3)
            self.assertGreater(ret_tok.line, 15)  # analysis line comes after 15-line header
            self.assertEqual(ret_tok.indent, 4)

    def test_longer_and_shorter_macro_expansion_physical_columns(self):
        """Tokens after longer and shorter macro expansions on the same line retain exact physical columns."""
        code = (
            "#define SHORT_M (100000 + 200000)\n"
            "#define VERY_LONG_MACRO_IDENTIFIER 1\n"
            "int main() {\n"
            "    int x = SHORT_M + 42;\n"
            "    int y = VERY_LONG_MACRO_IDENTIFIER + 99;\n"
            "    return x + y;\n"
            "}\n"
        )
        prep = Preprocessor()
        pres = prep.preprocess(code, "macro_cols.cpp")
        tokens = Lexer(pres.analysis_source, "macro_cols.cpp", preproc_result=pres).tokenize()

        # Line 4: "    int x = SHORT_M + 42;" -> '42' starts at col 23
        tok_42 = [t for t in tokens if t.lexeme == "42"][0]
        self.assertEqual(tok_42.source_line, 4)
        self.assertEqual(tok_42.source_col, 23)
        self.assertFalse(tok_42.macro_generated)

        # Line 5: "    int y = VERY_LONG_MACRO_IDENTIFIER + 99;" -> '99' starts at col 42
        tok_99 = [t for t in tokens if t.lexeme == "99"][0]
        self.assertEqual(tok_99.source_line, 5)
        self.assertEqual(tok_99.source_col, 42)
        self.assertFalse(tok_99.macro_generated)

        # Expanded tokens from SHORT_M must have macro_generated == True
        tok_100000 = [t for t in tokens if t.lexeme == "100000"][0]
        self.assertTrue(tok_100000.macro_generated)
        self.assertEqual(tok_100000.source_line, 4)
        self.assertEqual(tok_100000.source_col, 13)

    def test_no_patch_generated_inside_macro_expansion(self):
        """No automatic CodePatch may be produced inside macro-generated tokens."""
        code = (
            "#define BAD_EXPR ab+\n"
            "int main() {\n"
            "    int a = 1;\n"
            "    int b = 2;\n"
            "    int r = BAD_EXPR;\n"
            "    return r;\n"
            "}\n"
        )
        res = analyze_translation_unit("macro_patch.cpp", code, enable_suggestions=True)
        # Diagnostics should still be reported and marked macro_generated=True
        p002_diags = [d for d in res.diagnostics if d.code == "P002"]
        self.assertGreaterEqual(len(p002_diags), 1)
        self.assertTrue(p002_diags[0].macro_generated)
        # Candidate patches must NOT contain a patch for the macro expansion
        p002_patches = [p for p in res.candidate_patches if p.error_code == "P002"]
        self.assertEqual(len(p002_patches), 0)

    def test_lexical_semantic_p002_p005_and_brace_errors_in_included_header(self):
        """Lexical, P002, P004, P005, and semantic diagnostics inside an included header point to that header."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Lexical error L001 + P002 + P005 + semantic E001 in header
            header = os.path.join(tmpdir, "bad_header.h")
            header_src = (
                "int hdr_calc() {\n"
                "    int a = 1;\n"
                "    int b = 2;\n"
                "    int bad_expr = ab+;\n"
                "    boolean flag = True;\n"
                "    int undef_v = mystery_symbol;\n"
                "    int lex_err = 10 @ 20;\n"
                "    return a + b;\n"
                "}\n"
            )
            with open(header, "w", encoding="utf-8") as f:
                f.write(header_src)

            parent = os.path.join(tmpdir, "main.cpp")
            parent_src = '#include "bad_header.h"\nint main() {\n    return hdr_calc();\n}\n'
            with open(parent, "w", encoding="utf-8") as f:
                f.write(parent_src)

            res = analyze_translation_unit(parent, parent_src, enable_suggestions=True)
            by_code = {d.code: d for d in res.diagnostics}

            for expected_code, expected_line in [
                ("P002", 4),
                ("P005", 5),
                ("E001", 6),
                ("L001", 7),
            ]:
                self.assertIn(expected_code, by_code, f"Missing {expected_code}")
                diag = by_code[expected_code]
                self.assertTrue(same_file(diag.file_path, header), f"{expected_code} pointed to {diag.file_path}")
                self.assertEqual(diag.line, expected_line)

            # 2. Missing closing brace P004 opened inside header targets header
            brace_header = os.path.join(tmpdir, "unclosed.h")
            with open(brace_header, "w", encoding="utf-8") as f:
                f.write("int unclosed_fn() {\n    int x = 1;\n    return x;\n")

            brace_parent = os.path.join(tmpdir, "brace_main.cpp")
            brace_parent_src = '#include "unclosed.h"\nint main() {\n    return 0;\n}\n'
            with open(brace_parent, "w", encoding="utf-8") as f:
                f.write(brace_parent_src)

            brace_res = analyze_translation_unit(brace_parent, brace_parent_src, enable_suggestions=True)
            p004_diags = [d for d in brace_res.diagnostics if d.code == "P004"]
            self.assertGreaterEqual(len(p004_diags), 1)
            self.assertTrue(same_file(p004_diags[0].file_path, brace_header))
            for patch_obj in brace_res.candidate_patches:
                if patch_obj.error_code == "P004":
                    self.assertTrue(same_file(patch_obj.file_path, brace_header))

    def test_fix_only_parent_when_repair_belongs_to_header_leaves_both_files_unchanged(self):
        """Fixing only parent.cpp when the only repair belongs to local.h must not modify either file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            header = os.path.join(tmpdir, "local.h")
            header_src = "int helper() {\n    int bad = 42\n    return bad;\n}\n"
            with open(header, "wb") as f:
                f.write(header_src.encode("utf-8"))

            parent = os.path.join(tmpdir, "main.cpp")
            parent_src = '#include "local.h"\nint main() {\n    return helper();\n}\n'
            with open(parent, "wb") as f:
                f.write(parent_src.encode("utf-8"))

            with open(header, "rb") as f:
                orig_header_bytes = f.read()
            with open(parent, "rb") as f:
                orig_parent_bytes = f.read()

            # 1. Test CLI `fix main.cpp -w`
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), patch.object(sys, "argv", ["main.py", "fix", parent, "-w"]):
                try:
                    cli_main()
                except SystemExit as exc:
                    self.assertEqual(exc.code, 0)

            with open(header, "rb") as f:
                self.assertEqual(orig_header_bytes, f.read())
            with open(parent, "rb") as f:
                self.assertEqual(orig_parent_bytes, f.read())

            # 2. Test TUI PatchReviewWizard on parent only
            wizard = PatchReviewWizard(
                files=[parent],
                input_fn=lambda _: "a",
                output_fn=lambda _: None,
            )
            self.assertTrue(wizard.run())
            with open(header, "rb") as f:
                self.assertEqual(orig_header_bytes, f.read())
            with open(parent, "rb") as f:
                self.assertEqual(orig_parent_bytes, f.read())

    def test_fix_preserves_local_include_and_does_not_inline_content(self):
        """Target file containing #include "local.h" retains directive and does not inline content on fix."""
        with tempfile.TemporaryDirectory() as tmpdir:
            header = os.path.join(tmpdir, "local.h")
            with open(header, "w", encoding="utf-8") as f:
                f.write("int calculate() {\n    return 100;\n}\n")

            target = os.path.join(tmpdir, "main.cpp")
            with open(target, "w", encoding="utf-8") as f:
                f.write('#include "local.h"\nint main() {\n    int res = calculate()\n    return res;\n}\n')

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                with open(target, "r", encoding="utf-8") as source_file:
                    target_source = source_file.read()
                repaired = repair_source(
                    target,
                    target_source,
                    confidence_policy="all",
                    excluded_codes=("W002", "W003", "W006"),
                ).updated_source

            self.assertIn('#include "local.h"', repaired)
            self.assertNotIn("int calculate() {", repaired)
            self.assertNotIn("return 100;", repaired)
            self.assertIn("int res = calculate();", repaired)

    def test_lsp_and_workbench_physical_locations_after_quoted_includes(self):
        """LSP and workbench report physical file paths and physical line numbers after quoted includes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            header = os.path.join(tmpdir, "local.h")
            with open(header, "w", encoding="utf-8") as f:
                # 10 lines in header, with an error on line 2 of header
                f.write("int h_fn() {\n    int h_err = 10\n    return h_err;\n}\n" + ("// pad\n" * 6))

            target = os.path.join(tmpdir, "main.cpp")
            code = '#include "local.h"\nint main() {\n    int m_err = 20\n    return m_err + h_fn();\n}\n'
            with open(target, "w", encoding="utf-8") as f:
                f.write(code)

            # Workbench structured diagnostics
            wb = extract_structured_diagnostics(code, target)
            p003_errors = [e for e in wb["errors"] if e["code"] == "P003"]
            self.assertEqual(len(p003_errors), 2)

            hdr_diag = [e for e in p003_errors if same_file(e["file"], header)][0]
            main_diag = [e for e in p003_errors if same_file(e["file"], target)][0]
            self.assertEqual(hdr_diag["line"], 2)
            self.assertEqual(main_diag["line"], 3)

            # LSP diagnostics
            server = LanguageServer()
            uri = f"file:///{target.replace(os.sep, '/')}"
            published = []
            with patch.object(server, "_send_message", side_effect=lambda msg: published.append(msg)):
                server._validate_document(uri, code)

            lsp_diags = published[0]["params"]["diagnostics"]
            lsp_p003 = [d for d in lsp_diags if d["code"] == "P003"]
            self.assertEqual(len(lsp_p003), 2)
            lsp_hdr = [d for d in lsp_p003 if same_file(d["file"], header)][0]
            lsp_main = [d for d in lsp_p003 if same_file(d["file"], target)][0]
            self.assertEqual(lsp_hdr["range"]["start"]["line"], 1)   # 0-based for line 2
            self.assertEqual(lsp_main["range"]["start"]["line"], 2)  # 0-based for line 3


if __name__ == "__main__":
    unittest.main()
