"""
Unit tests for Idea 9: Interactive Terminal TUI (Patch Reviewer & Fix Wizard).
"""

import unittest
import tempfile
import os
import shutil
from unittest.mock import patch

from src.patch_model import (
    CodePatch,
    UnifiedDiffRenderer,
    sort_patches_bottom_up,
    apply_patch_to_source,
    apply_patches_to_source,
    collect_candidate_patches,
)
from src.atomic_writer import atomic_write, create_backup, restore_backup
from src.tui_wizard import PatchReviewWizard, read_keystroke


class TestPatchModel(unittest.TestCase):
    """Tests for CodePatch data structure and Diff rendering."""

    def test_code_patch_creation(self):
        patch = CodePatch(
            file_path="test.cpp",
            line_start=4,
            line_end=4,
            col_start=15,
            col_end=22,
            original_text="a + + b",
            replacement_text="a + b",
            error_code="P002",
            summary="Deduplicated consecutive '+' operators",
            explanations=["Deduplicated consecutive '+' operators into single infix '+' operator."],
        )
        self.assertEqual(patch.file_path, "test.cpp")
        self.assertEqual(patch.line_start, 4)
        self.assertEqual(patch.error_code, "P002")
        self.assertEqual(patch.title, "Malformed Expression")
        self.assertFalse(patch.applied)

    def test_summary_card_rendering(self):
        source = (
            "int main() {\n"
            "    int a = 1, b = 2;\n"
            "    int res = a + + b;\n"
            "    return res;\n"
            "}\n"
        )
        patch = CodePatch(
            file_path="test.cpp",
            line_start=3,
            line_end=3,
            col_start=15,
            col_end=22,
            original_text="a + + b",
            replacement_text="a + b",
            error_code="P002",
            summary="Deduplicated consecutive '+' operators",
            explanations=["Deduplicated consecutive '+' operators into single infix '+' operator."],
        )
        card = UnifiedDiffRenderer.render_summary_card(
            patch=patch,
            patch_idx=1,
            total_patches=1,
            source=source,
            context_lines=2,
            color=False,
        )
        self.assertIn("[Patch 1/1] test.cpp:3:15", card)
        self.assertIn("Original:", card)
        self.assertIn("Proposed Fix:", card)
        self.assertIn("Explanation:", card)
        self.assertIn("Deduplicated consecutive '+' operators", card)

    def test_expanded_unified_diff(self):
        source = (
            "int main() {\n"
            "    int a = 1, b = 2;\n"
            "    int res = a + + b;\n"
            "    return res;\n"
            "}\n"
        )
        patch = CodePatch(
            file_path="test.cpp",
            line_start=3,
            line_end=3,
            col_start=15,
            col_end=22,
            original_text="a + + b",
            replacement_text="a + b",
            error_code="P002",
            summary="Fix malformed expression",
            explanations=[],
        )
        diff = UnifiedDiffRenderer.render_unified_diff(
            patch=patch,
            source=source,
            context_lines=3,
            color=False,
        )
        self.assertIn("--- a/test.cpp", diff)
        self.assertIn("+++ b/test.cpp", diff)
        self.assertIn("-    int res = a + + b;", diff)
        self.assertIn("+    int res = a + b;", diff)


class TestPatchSequencing(unittest.TestCase):
    """Tests for conflict-free bottom-to-top patch application."""

    def test_sort_patches_bottom_up(self):
        p1 = CodePatch("t.cpp", 2, 2, 5, 10, "x", "y", "W001", "s1")
        p2 = CodePatch("t.cpp", 10, 10, 2, 4, "a", "b", "W002", "s2")
        p3 = CodePatch("t.cpp", 5, 5, 1, 3, "c", "d", "W003", "s3")
        sorted_p = sort_patches_bottom_up([p1, p2, p3])
        self.assertEqual([p.line_start for p in sorted_p], [10, 5, 2])

    def test_apply_patches_to_source_sequential(self):
        source = (
            "int main() {\n"
            "    int x = 10\n"
            "    if (x = 10) {\n"
            "        int res = 2 ^ 8;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        # Patch at line 4 (W003)
        p1 = CodePatch("t.cpp", 4, 4, 19, 24, "2 ^ 8", "1 << 8", "W003", "Fix XOR")
        # Patch at line 3 (W002)
        p2 = CodePatch("t.cpp", 3, 3, 9, 15, "x = 10", "x == 10", "W002", "Fix assignment")
        # Patch at line 2 (P003 missing semicolon)
        p3 = CodePatch("t.cpp", 2, 2, 15, 15, "", ";", "P003", "Insert semicolon")

        new_source, applied = apply_patches_to_source(source, [p1, p2, p3])
        self.assertEqual(len(applied), 3)
        self.assertIn("int x = 10;", new_source)
        self.assertIn("if (x == 10)", new_source)
        self.assertIn("int res = 1 << 8;", new_source)


class TestAtomicWriter(unittest.TestCase):
    """Tests for atomic file writes and backup creation."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.file_path = os.path.join(self.test_dir, "sample.cpp")
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write("int x = 1;\n")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_atomic_write_without_backup(self):
        new_content = "int x = 42;\n"
        success = atomic_write(self.file_path, new_content, backup=False)
        self.assertTrue(success)
        with open(self.file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), new_content)
        self.assertFalse(os.path.exists(self.file_path + ".bak"))

    def test_atomic_write_with_backup(self):
        new_content = "int x = 99;\n"
        success = atomic_write(self.file_path, new_content, backup=True)
        self.assertTrue(success)
        with open(self.file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), new_content)
        # Check that backup exists with original content
        backup_path = self.file_path + ".bak"
        self.assertTrue(os.path.exists(backup_path))
        with open(backup_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "int x = 1;\n")

    def test_restore_backup(self):
        create_backup(self.file_path)
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write("corrupted data")
        self.assertTrue(restore_backup(self.file_path))
        with open(self.file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "int x = 1;\n")

    def test_atomic_write_preserves_file_permissions(self):
        recorded_modes = []
        orig_chmod = os.chmod
        def mock_chmod(path, mode):
            recorded_modes.append(mode)
            try:
                orig_chmod(path, mode)
            except OSError:
                pass

        fake_stat = os.stat_result((0o100644, 0, 0, 0, 0, 0, 10, 0, 0, 0))
        with patch("os.stat", return_value=fake_stat):
            with patch("os.chmod", side_effect=mock_chmod):
                success = atomic_write(self.file_path, "int x = 500;\n")
                self.assertTrue(success)
                self.assertIn(fake_stat.st_mode, recorded_modes)


class TestTUIWizardInteractive(unittest.TestCase):
    """Tests for PatchReviewWizard terminal interaction with mocked input streams."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.file_path = os.path.join(self.test_dir, "test.cpp")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_wizard_accept_all_patches_individually(self):
        # File with operator misuse W002 and W003
        content = (
            "int main() {\n"
            "    int x = 0;\n"
            "    if (x = 5) {\n"
            "        int y = 2 ^ 8;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(content)

        inputs = ["y", "y", "y"]
        outputs = []

        def mock_input(prompt):
            return inputs.pop(0)

        wizard = PatchReviewWizard(
            files=[self.file_path],
            backup=False,
            color=False,
            input_fn=mock_input,
            output_fn=outputs.append,
        )
        success = wizard.run()
        self.assertTrue(success)

        with open(self.file_path, "r", encoding="utf-8") as f:
            repaired = f.read()

        self.assertIn("x == 5", repaired)
        self.assertIn("1 << 8", repaired)
        full_output = "".join(outputs)
        self.assertIn("[Patch 1 Accepted]", full_output)
        self.assertIn("[Patch 2 Accepted]", full_output)
        self.assertIn("Transaction committed: 2 patch(es)", full_output)

    def test_wizard_skip_patches(self):
        content = (
            "int main() {\n"
            "    int x = 0;\n"
            "    if (x = 5) {\n"
            "        int y = 2 ^ 8;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Skip first patch, accept second patch
        inputs = ["n", "y", "y"]
        outputs = []

        wizard = PatchReviewWizard(
            files=[self.file_path],
            backup=False,
            color=False,
            input_fn=lambda prompt: inputs.pop(0),
            output_fn=outputs.append,
        )
        success = wizard.run()
        self.assertTrue(success)

        with open(self.file_path, "r", encoding="utf-8") as f:
            repaired = f.read()

        # First was skipped (remains x = 5), second was accepted (1 << 8)
        self.assertIn("x = 5", repaired)
        self.assertIn("1 << 8", repaired)

    def test_wizard_apply_all_remaining(self):
        content = (
            "int main() {\n"
            "    int x = 0;\n"
            "    if (x = 5) {\n"
            "        int y = 2 ^ 8;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Hit 'a' on first patch to apply all remaining
        inputs = ["a", "y"]
        outputs = []

        wizard = PatchReviewWizard(
            files=[self.file_path],
            backup=False,
            color=False,
            input_fn=lambda prompt: inputs.pop(0),
            output_fn=outputs.append,
        )
        success = wizard.run()
        self.assertTrue(success)

        with open(self.file_path, "r", encoding="utf-8") as f:
            repaired = f.read()

        self.assertIn("x == 5", repaired)
        self.assertIn("1 << 8", repaired)
        full_output = "".join(outputs)
        self.assertIn("Applying all remaining", full_output)

    def test_wizard_quit_discards_changes(self):
        content = (
            "int main() {\n"
            "    int x = 0;\n"
            "    if (x = 5) {\n"
            "        int y = 2 ^ 8;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(content)

        # First accept, then quit
        inputs = ["y", "q"]
        outputs = []

        wizard = PatchReviewWizard(
            files=[self.file_path],
            backup=False,
            color=False,
            input_fn=lambda prompt: inputs.pop(0),
            output_fn=outputs.append,
        )
        success = wizard.run()
        self.assertFalse(success)

        # File MUST remain completely unchanged!
        with open(self.file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), content)

        full_output = "".join(outputs)
        self.assertIn("Aborted. No changes written", full_output)

    def test_wizard_explain_and_diff_commands(self):
        content = (
            "int main() {\n"
            "    int x = 0;\n"
            "    if (x = 5) {\n"
            "        return 1;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(content)

        # First ask for 'e' (explain), then 'd' (diff), then 'y' (apply)
        inputs = ["e", "d", "y", "y"]
        outputs = []

        wizard = PatchReviewWizard(
            files=[self.file_path],
            backup=False,
            color=False,
            input_fn=lambda prompt: inputs.pop(0),
            output_fn=outputs.append,
        )
        success = wizard.run()
        self.assertTrue(success)

        full_output = "".join(outputs)
        # Verify explain output was printed
        self.assertIn("Assignment in Conditional Statement", full_output)
        # Verify detailed diff was printed
        self.assertIn("Detailed 10-line Unified Diff", full_output)
        # Verify patch was ultimately accepted
        self.assertIn("[Patch 1 Accepted]", full_output)

        with open(self.file_path, "r", encoding="utf-8") as f:
            self.assertIn("x == 5", f.read())

    def test_wizard_with_backup_flag(self):
        content = (
            "int main() {\n"
            "    int x = 0;\n"
            "    if (x = 5) {\n"
            "        return 1;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(content)

        wizard = PatchReviewWizard(
            files=[self.file_path],
            backup=True,
            color=False,
            input_fn=lambda prompt: "y",
            output_fn=lambda text: None,
        )
        success = wizard.run()
        self.assertTrue(success)

        # Verify backup was created
        backup_path = self.file_path + ".bak"
        self.assertTrue(os.path.exists(backup_path))
        with open(backup_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), content)

    def test_wizard_keyboard_interrupt_save_partial(self):
        content = (
            "int main() {\n"
            "    int x = 0;\n"
            "    if (x = 5) {\n"
            "        int y = 2 ^ 8;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Patch 1: accept, interrupt patch 2, choose verify, then confirm transaction.
        calls = [0]
        def mock_input(prompt):
            calls[0] += 1
            if calls[0] == 1:
                return "y"
            elif calls[0] == 2:
                raise KeyboardInterrupt
            elif calls[0] == 3:
                return "v"
            elif calls[0] == 4:
                return "y"
            return "n"

        wizard = PatchReviewWizard(
            files=[self.file_path],
            backup=False,
            color=False,
            input_fn=mock_input,
            output_fn=lambda text: None,
        )
        wizard.run()

        with open(self.file_path, "r", encoding="utf-8") as f:
            repaired = f.read()

        # Patch 1 was saved
        self.assertIn("x == 5", repaired)
        # Patch 2 was not applied
        self.assertIn("2 ^ 8", repaired)

    def test_wizard_keyboard_interrupt_discard_all(self):
        content = (
            "int main() {\n"
            "    int x = 0;\n"
            "    if (x = 5) {\n"
            "        int y = 2 ^ 8;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Patch 1: 'y', Patch 2: raise KeyboardInterrupt, Prompt to save: 'n'
        calls = [0]
        def mock_input(prompt):
            calls[0] += 1
            if calls[0] == 1:
                return "y"
            elif calls[0] == 2:
                raise KeyboardInterrupt
            elif calls[0] == 3:
                return "n"
            return "n"

        wizard = PatchReviewWizard(
            files=[self.file_path],
            backup=False,
            color=False,
            input_fn=mock_input,
            output_fn=lambda text: None,
        )
        wizard.run()

        # File must be untouched
        with open(self.file_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), content)

    def test_clean_file_returns_no_patches(self):
        clean_code = "int main() {\n    return 0;\n}\n"
        with open(self.file_path, "w", encoding="utf-8") as f:
            f.write(clean_code)

        patches = collect_candidate_patches(self.file_path)
        self.assertEqual(len(patches), 0)

    def test_wizard_completes_safe_followup_repairs_in_same_transaction(self):
        source = "int main(){ cout << 1 << endl; vector<int> v; return 0; }\n"
        with open(self.file_path, "w", encoding="utf-8") as source_file:
            source_file.write(source)

        answers = iter(["a", "y"])
        wizard = PatchReviewWizard(
            files=[self.file_path],
            backup=False,
            color=False,
            input_fn=lambda prompt: next(answers),
            output_fn=lambda text: None,
        )
        self.assertTrue(wizard.run())

        with open(self.file_path, "r", encoding="utf-8") as source_file:
            repaired = source_file.read()
        self.assertIn("#include <iostream>", repaired)
        self.assertIn("#include <vector>", repaired)
        self.assertIn("std::cout", repaired)
        self.assertIn("std::vector", repaired)


if __name__ == "__main__":
    unittest.main()
