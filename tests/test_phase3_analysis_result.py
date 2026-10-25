import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import main as cli_module
from src.analysis_result import Diagnostic, SourceLocation, dedupe_diagnostics
from src.analyzer import analyze_translation_unit
from src.lsp import LanguageServer
from src.patch_model import collect_candidate_patches, collect_candidate_patches_with_result
from src.paths import canonical_path, same_file
from src.tui_wizard import PatchReviewWizard
from src.ui_server import execute_cli_command, extract_structured_diagnostics


class TestPhase3AnalysisResult(unittest.TestCase):
    """Comprehensive tests for Phase 3 canonical AnalysisResult, stage failure handling, and frontend unity."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_clean_source_returns_complete_result(self):
        """Clean C++ source returns a complete AnalysisResult with zero diagnostics and safe_to_write=True."""
        code = "#include <iostream>\nint main() {\n    int x = 42;\n    std::cout << x << std::endl;\n    return 0;\n}\n"
        file_path = os.path.join(self.temp_dir.name, "clean.cpp")
        res = analyze_translation_unit(file_path, code)

        self.assertTrue(res.preprocess_completed)
        self.assertTrue(res.lexer_completed)
        self.assertTrue(res.parser_completed)
        self.assertTrue(res.semantic_completed)
        self.assertTrue(res.complete)
        self.assertTrue(res.safe_to_write)
        self.assertFalse(res.has_errors)
        self.assertEqual(len(res.diagnostics), 0)
        self.assertEqual(len(res.internal_failures), 0)
        self.assertEqual(len(res.candidate_patches), 0)

    def test_02_broken_source_returns_structured_diagnostics_without_stdout(self):
        """Broken source returns structured Diagnostics and CodePatches without writing anything to stdout."""
        code = "int main() {\n    int x = 10\n    if (x = 5) {\n        return x;\n    }\n    return 0;\n}\n"
        file_path = os.path.join(self.temp_dir.name, "broken.cpp")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            res = analyze_translation_unit(file_path, code)

        # Canonical analyzer must be completely silent on stdout/stderr
        self.assertEqual(buf.getvalue(), "")
        self.assertTrue(res.complete)
        self.assertTrue(res.safe_to_write)
        self.assertTrue(res.has_errors)

        codes = [d.code for d in res.diagnostics]
        self.assertIn("P003", codes)
        self.assertIn("W002", codes)

        p003 = [d for d in res.diagnostics if d.code == "P003"][0]
        self.assertTrue(same_file(p003.file_path, file_path))
        self.assertEqual(p003.line, 2)
        self.assertGreaterEqual(len(res.candidate_patches), 1)

    def test_03_independent_stage_failures_recorded_explicitly(self):
        """Injecting RuntimeError in preprocess, lexer, parser, and semantic stages produces explicit AnalysisFailures."""
        code = "int main() { int x = 1; return x; }\n"
        file_path = os.path.join(self.temp_dir.name, "stage_fail.cpp")

        # 1. Preprocessor failure
        with patch("src.analyzer.Preprocessor.preprocess", side_effect=RuntimeError("preproc boom")):
            res = analyze_translation_unit(file_path, code)
        self.assertFalse(res.preprocess_completed)
        self.assertFalse(res.complete)
        self.assertFalse(res.safe_to_write)
        self.assertEqual(len(res.internal_failures), 1)
        self.assertEqual(res.internal_failures[0].stage, "preprocess")
        self.assertEqual(res.candidate_patches, [])

        # 2. Lexer failure
        with patch("src.analyzer.Lexer.tokenize", side_effect=RuntimeError("lexer boom")):
            res = analyze_translation_unit(file_path, code)
        self.assertTrue(res.preprocess_completed)
        self.assertFalse(res.lexer_completed)
        self.assertFalse(res.complete)
        self.assertFalse(res.safe_to_write)
        self.assertEqual(len(res.internal_failures), 1)
        self.assertEqual(res.internal_failures[0].stage, "lexer")

        # 3. Parser failure
        with patch("src.analyzer.Parser.parse", side_effect=RuntimeError("parser boom")):
            res = analyze_translation_unit(file_path, code)
        self.assertTrue(res.preprocess_completed)
        self.assertTrue(res.lexer_completed)
        self.assertFalse(res.parser_completed)
        self.assertFalse(res.complete)
        self.assertFalse(res.safe_to_write)
        self.assertEqual(len(res.internal_failures), 1)
        self.assertEqual(res.internal_failures[0].stage, "parser")

        # 4. Semantic failure
        with patch("src.analyzer.SemanticAnalyzer.analyze", side_effect=RuntimeError("semantic boom")):
            res = analyze_translation_unit(file_path, code)
        self.assertTrue(res.preprocess_completed)
        self.assertTrue(res.lexer_completed)
        self.assertTrue(res.parser_completed)
        self.assertFalse(res.semantic_completed)
        self.assertFalse(res.complete)
        self.assertFalse(res.safe_to_write)
        self.assertEqual(len(res.internal_failures), 1)
        self.assertEqual(res.internal_failures[0].stage, "semantic")

    def test_04_earlier_diagnostics_survive_later_stage_failure(self):
        """Real diagnostics from earlier stages are preserved when a later stage fails."""
        code = "int main() {\n    int x = 10 @ 20\n    return x;\n}\n"
        file_path = os.path.join(self.temp_dir.name, "survive.cpp")

        # Lexer emits L001, Parser emits P003, then SemanticAnalyzer crashes
        with patch("src.analyzer.SemanticAnalyzer.analyze", side_effect=RuntimeError("semantic crash")):
            res = analyze_translation_unit(file_path, code)

        self.assertFalse(res.complete)
        self.assertFalse(res.safe_to_write)
        self.assertEqual(res.candidate_patches, [])
        codes = [d.code for d in res.diagnostics]
        self.assertIn("L001", codes)
        self.assertIn("P003", codes)
        self.assertIn("INTERNAL", codes)

        # Workbench also preserves L001 and P003 alongside INTERNAL instead of replacing with E000
        with patch("src.analyzer.SemanticAnalyzer.analyze", side_effect=RuntimeError("semantic crash")):
            wb = extract_structured_diagnostics(code, file_path)
        wb_codes = [e["code"] for e in wb["errors"]]
        self.assertIn("L001", wb_codes)
        self.assertIn("P003", wb_codes)
        self.assertIn("INTERNAL", wb_codes)
        self.assertNotIn("E000", wb_codes)

    def test_05_incomplete_results_cannot_be_written_by_cli_tui_or_workbench(self):
        """Incomplete analysis must never write to disk or return updated_code in CLI, TUI, or workbench."""
        code = "int main() {\n    int x = 10\n    return x;\n}\n"
        file_path = os.path.join(self.temp_dir.name, "no_write.cpp")
        with open(file_path, "wb") as f:
            f.write(code.encode("utf-8"))
        with open(file_path, "rb") as f:
            orig_bytes = f.read()

        with patch("src.analyzer.SemanticAnalyzer.analyze", side_effect=RuntimeError("semantic crash")):
            # 1. Candidate patch collection returns empty list
            patches, res = collect_candidate_patches_with_result(file_path, code)
            self.assertFalse(res.safe_to_write)
            self.assertEqual(patches, [])
            self.assertEqual(collect_candidate_patches(file_path, code), [])

            # 2. CLI `fix -w` exits non-zero and leaves file untouched
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), patch.object(sys, "argv", ["main.py", "fix", file_path, "-w"]):
                with self.assertRaises(SystemExit) as cm:
                    cli_module.main()
                self.assertNotEqual(cm.exception.code, 0)

            with open(file_path, "rb") as f:
                self.assertEqual(orig_bytes, f.read())

            # 3. TUI PatchReviewWizard returns False and leaves file untouched
            wizard = PatchReviewWizard(
                files=[file_path],
                input_fn=lambda _: "y",
                output_fn=lambda _: None,
            )
            self.assertFalse(wizard.run())
            with open(file_path, "rb") as f:
                self.assertEqual(orig_bytes, f.read())

            # 4. Workbench `fix` refuses to return updated_code
            wb_res = execute_cli_command("fix", code, file_path)
            self.assertIsNone(wb_res["updated_code"])

    def test_06_suggest_calls_analyzer_exactly_once_per_file(self):
        """CLI `suggest` must call analyze_translation_unit() exactly once per file."""
        code = "int main() {\n    int x = 10\n    return x;\n}\n"
        file_path = os.path.join(self.temp_dir.name, "suggest_once.cpp")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)

        call_count = 0
        real_analyze = analyze_translation_unit

        def counting_analyze(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return real_analyze(*args, **kwargs)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with patch("main.analyze_translation_unit", side_effect=counting_analyze):
                with patch.object(sys, "argv", ["main.py", "suggest", file_path]):
                    with self.assertRaises(SystemExit) as cm:
                        cli_module.main()
                    self.assertEqual(cm.exception.code, 1)

        self.assertEqual(call_count, 1)

    def test_07_cli_lsp_and_workbench_expose_same_code_location_and_message(self):
        """CLI/canonical analyzer, LSP, and workbench expose identical diagnostic code, location, and message."""
        code = "int main() {\n    int x = 10\n    return z;\n}\n"
        file_path = os.path.join(self.temp_dir.name, "parity.cpp")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)

        res = analyze_translation_unit(file_path, code)
        wb = extract_structured_diagnostics(code, file_path)

        server = LanguageServer()
        uri = f"file:///{file_path.replace(os.sep, '/')}"
        published = []
        with patch.object(server, "_send_message", side_effect=lambda msg: published.append(msg)):
            server._validate_document(uri, code)
        lsp_diags = published[0]["params"]["diagnostics"]

        wb_all = wb["errors"] + wb["warnings"]
        self.assertEqual(len(res.diagnostics), len(wb_all))
        self.assertEqual(len(res.diagnostics), len(lsp_diags))

        for canon_d, wb_d, lsp_d in zip(res.diagnostics, wb_all, lsp_diags):
            self.assertEqual(canon_d.code, wb_d["code"])
            self.assertEqual(canon_d.code, lsp_d["code"])
            self.assertEqual(canon_d.message, wb_d["message"])
            self.assertEqual(canon_d.message, lsp_d["message"])
            self.assertEqual(canon_d.line, wb_d["line"])
            self.assertEqual(canon_d.col, wb_d["col"])
            self.assertEqual(canon_d.line - 1, lsp_d["range"]["start"]["line"])
            self.assertEqual(canon_d.col - 1, lsp_d["range"]["start"]["character"])
            self.assertTrue(same_file(canon_d.file_path, wb_d["file"]))
            self.assertTrue(same_file(canon_d.file_path, lsp_d["file"]))

    def test_08_deduplication_removes_true_duplicates_and_preserves_distinct_locations(self):
        """dedupe_diagnostics removes identical diagnostics while keeping distinct locations."""
        loc1 = SourceLocation("a.cpp", 2, 5, 2, 6)
        loc2 = SourceLocation("a.cpp", 3, 5, 3, 6)
        d1 = Diagnostic(code="P003", severity="error", message="missing ';'", location=loc1)
        d1_dup = Diagnostic(code="P003", severity="error", message="missing ';'", location=loc1, help_text="different help")
        d2 = Diagnostic(code="P003", severity="error", message="missing ';'", location=loc2)

        deduped = dedupe_diagnostics([d1, d1_dup, d2])
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0].location, loc1)
        self.assertEqual(deduped[1].location, loc2)

    def test_09_system_exit_keyboard_interrupt_and_generator_exit_not_swallowed(self):
        """SystemExit, KeyboardInterrupt, and GeneratorExit must propagate out of analyze_translation_unit."""
        code = "int main() { return 0; }\n"
        file_path = os.path.join(self.temp_dir.name, "non_standard_exc.cpp")

        for exc_cls in (SystemExit, KeyboardInterrupt, GeneratorExit):
            with self.subTest(exc_cls=exc_cls):
                with patch("src.analyzer.Lexer.tokenize", side_effect=exc_cls("must propagate")):
                    with self.assertRaises(exc_cls):
                        analyze_translation_unit(file_path, code)


if __name__ == "__main__":
    unittest.main()
