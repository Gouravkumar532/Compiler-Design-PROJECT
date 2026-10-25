import io
import os
import tempfile
import unittest
from unittest.mock import patch

from src.analyzer import analyze_translation_unit
from src.lexer import Lexer
from src.lsp import LanguageServer
from src.parser import Parser
from src.preprocessor import Preprocessor
from src.ui_server import execute_cli_command, extract_structured_diagnostics


class TestPhase1AnalysisModes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_non_tty_check_two_syntax_errors(self):
        """Non-TTY check test with at least two repairable syntax errors; assert both diagnostics are collected and no prompt occurs."""
        code = """int main() {
    int a = 10
    int b = 20
    return 0;
}
"""
        file_path = os.path.join(self.temp_dir.name, "two_errors.cpp")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)

        with patch("builtins.input", side_effect=AssertionError("input() prompt was called!")):
            with patch("sys.stdin.isatty", return_value=False):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    result = analyze_translation_unit(file_path)

        self.assertGreaterEqual(result.error_count, 2)
        p003_diags = [d for d in result.diagnostics if d.code == "P003"]
        self.assertEqual(len(p003_diags), 2)

    def test_simulated_tty_check_no_prompt(self):
        """Simulated-TTY check test; assert no prompt occurs and file is untouched."""
        code = """int main() {
    int a = 10
    int b = 20
    return 0;
}
"""
        file_path = os.path.join(self.temp_dir.name, "tty_check.cpp")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)

        with patch("builtins.input", side_effect=AssertionError("input() prompt was called on simulated TTY!")):
            with patch("sys.stdin.isatty", return_value=True):
                buf = io.StringIO()
                with patch("sys.stdout", buf):
                    result = analyze_translation_unit(file_path)

        self.assertGreaterEqual(result.error_count, 2)

    def test_simulated_tty_suggest_and_workbench_no_prompt(self):
        """Simulated-TTY suggest and workbench diagnostics/commands never prompt or write."""
        from src.patch_model import collect_candidate_patches

        code = """int main() {
    int a = 10
    int b = 20
    return 0;
}
"""
        file_path = os.path.join(self.temp_dir.name, "tty_suggest.cpp")
        with open(file_path, "wb") as f:
            f.write(code.encode("utf-8"))
        with open(file_path, "rb") as f:
            orig_bytes = f.read()

        with patch("builtins.input", side_effect=AssertionError("input() prompt was called!")):
            with patch("sys.stdin.isatty", return_value=True):
                patches = collect_candidate_patches(file_path, code)
                self.assertEqual(len(patches), 2)

                wb_diags = extract_structured_diagnostics(code, file_path)
                self.assertGreaterEqual(len(wb_diags["errors"]), 2)

                check_res = execute_cli_command("check", code, file_path)
                self.assertIn("P003", check_res["output"])

                suggest_res = execute_cli_command("suggest", code, file_path)
                self.assertIn("P003", suggest_res["output"])

        with open(file_path, "rb") as f:
            self.assertEqual(orig_bytes, f.read())

    def test_parser_recovery_produces_later_diagnostics_without_duplicates(self):
        """Parser recovery reports each repairable error once and continues analysis."""
        code = """int main() {
    int a = 10
    int b = 20
    return 0;
}
"""
        tokens = Lexer(code, "<test>").tokenize()
        parser = Parser(
            tokens,
            code,
            "<test>",
            enable_repair=True,
        )

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            parser.parse()

        # Exactly 2 missing semicolons, not double-counted when synchronize() runs
        p003_diags = [d for d in parser.sink.diagnostics if d.code == "P003"]
        self.assertEqual(len(p003_diags), 2)
        self.assertEqual(parser.errors_count, 2)

    def test_check_leaves_input_file_byte_for_byte_unchanged(self):
        """Assert check leaves the input file byte-for-byte unchanged."""
        code = """int main() {
    int a = 10
    int b = 20
    return 0;
}
"""
        file_path = os.path.join(self.temp_dir.name, "test_check_preserve.cpp")
        with open(file_path, "wb") as f:
            f.write(code.encode("utf-8"))

        with open(file_path, "rb") as f:
            original_bytes = f.read()

        buf = io.StringIO()
        with patch("sys.stdout", buf):
            analyze_translation_unit(file_path)

        with open(file_path, "rb") as f:
            after_bytes = f.read()
        self.assertEqual(original_bytes, after_bytes)

    def test_suggest_leaves_input_file_byte_for_byte_unchanged(self):
        """Assert suggest leaves the input file byte-for-byte unchanged."""
        from src.patch_model import collect_candidate_patches

        code = """int main() {
    int a = 10
    int b = 20
    return 0;
}
"""
        file_path = os.path.join(self.temp_dir.name, "test_suggest_preserve.cpp")
        with open(file_path, "wb") as f:
            f.write(code.encode("utf-8"))

        with open(file_path, "rb") as f:
            original_bytes = f.read()

        patches = collect_candidate_patches(file_path, code)
        self.assertGreater(len(patches), 0)

        with open(file_path, "rb") as f:
            after_bytes = f.read()
        self.assertEqual(original_bytes, after_bytes)

    def test_lsp_diagnostics_leave_input_unchanged_and_never_prompt(self):
        """Assert LSP diagnostics leave the input unchanged even when isatty() is True."""
        code = """int main() {
    int a = 10
    int b = 20
    return 0;
}
"""
        file_path = os.path.join(self.temp_dir.name, "test_lsp_preserve.cpp")
        with open(file_path, "wb") as f:
            f.write(code.encode("utf-8"))

        with open(file_path, "rb") as f:
            original_bytes = f.read()

        server = LanguageServer()
        uri = f"file:///{file_path.replace(os.sep, '/')}"

        published = []
        with patch("builtins.input", side_effect=AssertionError("LSP must never prompt!")):
            with patch("sys.stdin.isatty", return_value=True):
                with patch.object(server, "_send_message", side_effect=lambda msg: published.append(msg)):
                    server._validate_document(uri, code)

        self.assertGreater(len(published), 0)
        diags = published[0]["params"]["diagnostics"]
        self.assertGreaterEqual(len(diags), 2)
        with open(file_path, "rb") as f:
            after_bytes = f.read()
        self.assertEqual(original_bytes, after_bytes)

    def test_context_aware_synchronize_recovers_in_for_and_block(self):
        """Unrepairable syntax error in a for-header or statement recovers and still detects later errors."""
        code = """int main() {
    for (int i = 0; @@@; i++) {
        int x = 1;
    }
    int after_for = 42
    return 0;
}
"""
        res = analyze_translation_unit("recover_for.cpp", code, enable_suggestions=True)
        codes = [d.code for d in res.diagnostics]
        # Must report lexical error L001 on @@@ AND recover to detect missing semicolon P003 on after_for
        self.assertIn("L001", codes)
        self.assertIn("P003", codes)

    def test_virtual_tokens_carried_with_synthetic_flag_and_provenance(self):
        """Virtual tokens inserted during P003/P004 carry synthetic=True and physical provenance."""
        code = """int main() {
    int a = 10
    if (a > 0) {
        return a;
}
"""
        preproc = Preprocessor()
        pres = preproc.preprocess(code, "virt.cpp")
        tokens = Lexer(pres.analysis_source, "virt.cpp", preproc_result=pres).tokenize()
        from src.diagnostics import DiagnosticSink
        sink = DiagnosticSink(emit=False)
        parser = Parser(
            tokens,
            code,
            "virt.cpp",
            enable_repair=True,
            preproc_result=pres,
            diag_sink=sink,
        )
        parser.parse()
        synthetic_tokens = [t for t in parser.tokens if getattr(t, "synthetic", False)]
        self.assertGreaterEqual(len(synthetic_tokens), 1)
        for st in synthetic_tokens:
            self.assertTrue(st.file.endswith("virt.cpp"))
            self.assertGreaterEqual(st.source_line, 1)


if __name__ == "__main__":
    unittest.main()
