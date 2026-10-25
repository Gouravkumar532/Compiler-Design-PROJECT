"""
Automated Unit Tests for C++ Compiler Workbench Presets Catalog
==============================================================================
Validates that all presets in `src/presets.py` are well-formed, complete analysis
without unhandled exceptions, and that error presets repair cleanly to 0 errors.
==============================================================================
"""

import unittest
from src.presets import PRESETS
from src.analyzer import analyze_translation_unit
from src.ui_server import execute_cli_command, extract_structured_diagnostics


class TestWorkbenchPresetsCatalog(unittest.TestCase):
    def test_preset_count_at_least_50_more(self):
        # We started with 7 presets; requirement is at least 50 more (>= 57 total).
        self.assertGreaterEqual(len(PRESETS), 57, f"Expected at least 57 presets, found {len(PRESETS)}")

    def test_all_presets_have_required_metadata(self):
        for key, preset in PRESETS.items():
            with self.subTest(preset=key):
                self.assertIn("title", preset, f"Preset '{key}' missing 'title'")
                self.assertIn("description", preset, f"Preset '{key}' missing 'description'")
                self.assertIn("category", preset, f"Preset '{key}' missing 'category'")
                self.assertIn("code", preset, f"Preset '{key}' missing 'code'")
                self.assertTrue(preset["title"].strip(), f"Preset '{key}' title is empty")
                self.assertTrue(preset["description"].strip(), f"Preset '{key}' description is empty")
                self.assertTrue(preset["category"].strip(), f"Preset '{key}' category is empty")
                self.assertTrue(preset["code"].strip(), f"Preset '{key}' code is empty")

    def test_all_presets_analysis_completes(self):
        for key, preset in PRESETS.items():
            with self.subTest(preset=key):
                res = analyze_translation_unit(f"preset_{key}.cpp", preset["code"], enable_suggestions=True)
                self.assertTrue(res.complete, f"Analysis failed or crashed for preset '{key}'")
                self.assertEqual(len(res.internal_failures), 0, f"Internal failures in preset '{key}': {res.internal_failures}")

    def test_all_presets_diagnostics_extraction(self):
        for key, preset in PRESETS.items():
            with self.subTest(preset=key):
                diag_data = extract_structured_diagnostics(preset["code"], f"preset_{key}.cpp")
                self.assertTrue(diag_data["complete"], f"Structured diagnostics incomplete for '{key}'")
                self.assertIsInstance(diag_data["errors"], list)
                self.assertIsInstance(diag_data["warnings"], list)

    def test_all_presets_check_and_suggest_commands(self):
        for key, preset in PRESETS.items():
            with self.subTest(preset=key):
                check_res = execute_cli_command("check", preset["code"], f"preset_{key}.cpp")
                self.assertFalse(check_res["is_interactive"])
                self.assertIsInstance(check_res["output"], str)

                suggest_res = execute_cli_command("suggest", preset["code"], f"preset_{key}.cpp")
                self.assertFalse(suggest_res["is_interactive"])
                self.assertIsInstance(suggest_res["output"], str)

    def test_all_clean_presets_have_zero_errors(self):
        clean_keys = [k for k in PRESETS if k.startswith("clean_")]
        self.assertGreaterEqual(len(clean_keys), 5)
        for key in clean_keys:
            with self.subTest(preset=key):
                res = analyze_translation_unit(f"preset_{key}.cpp", PRESETS[key]["code"], enable_suggestions=True)
                self.assertEqual(res.error_count, 0, f"Clean preset '{key}' has errors: {[d.message for d in res.diagnostics if d.severity == 'error']}")
                fix_res = execute_cli_command("fix", PRESETS[key]["code"], f"preset_{key}.cpp")
                self.assertEqual(fix_res["repair_status"], "unchanged")

    def test_all_error_presets_repair_completely(self):
        error_keys = [k for k in PRESETS if not k.startswith("clean_")]
        self.assertGreaterEqual(len(error_keys), 50)
        for key in error_keys:
            with self.subTest(preset=key):
                fix_res = execute_cli_command("fix", PRESETS[key]["code"], f"preset_{key}.cpp")
                self.assertEqual(
                    fix_res["repair_status"],
                    "complete",
                    f"Preset '{key}' did not repair completely. Status: {fix_res.get('repair_status')}, Output:\n{fix_res.get('output')}"
                )
                self.assertIsNotNone(fix_res["updated_code"])
                final = analyze_translation_unit(f"preset_{key}.cpp", fix_res["updated_code"], enable_suggestions=True)
                self.assertTrue(final.complete)
                self.assertEqual(final.error_count, 0, f"Repaired preset '{key}' still has {final.error_count} errors: {[d.message for d in final.diagnostics if d.severity == 'error']}")


if __name__ == "__main__":
    unittest.main()
