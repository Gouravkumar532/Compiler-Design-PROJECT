import unittest

from src.patch_model import (
    CodePatch,
    apply_patch_exact,
    apply_patches_to_source,
    prepare_patch,
)


class TestExactPatchSafety(unittest.TestCase):
    def patch(self, source, line, col, old, new, code="P003"):
        patch = CodePatch("sample.cpp", line, line, col, col + len(old), old, new, code, "test")
        return prepare_patch(patch, source)

    def test_repeated_text_changes_only_anchored_occurrence(self):
        source = "int x = x + x;\n"
        patch = self.patch(source, 1, 13, "x", "value")
        result = apply_patch_exact(source, patch)
        self.assertTrue(result.applied)
        self.assertEqual(result.source, "int x = x + value;\n")

    def test_stale_patch_is_rejected(self):
        source = "int x = 1;\n"
        patch = self.patch(source, 1, 9, "1", "2")
        result = apply_patch_exact("int x = 3;\n", patch)
        self.assertFalse(result.applied)
        self.assertEqual(result.status, "stale")

    def test_overlapping_ranges_are_not_written(self):
        source = "abcdef\n"
        first = self.patch(source, 1, 2, "bcd", "X")
        second = self.patch(source, 1, 3, "cde", "Y")
        updated, applied = apply_patches_to_source(source, [first, second])
        self.assertEqual(updated, source)
        self.assertEqual(applied, [])
        self.assertIn("overlapping", first.verification_message)

    def test_same_offset_insertions_have_deterministic_priority(self):
        source = "int main() {}\n"
        include = self.patch(source, 1, 1, "", "#include <vector>\n", "E015")
        using = self.patch(source, 1, 1, "", "using std::vector;\n", "E016")
        semi = self.patch(source, 1, 1, "", ";", "P003")
        updated, applied = apply_patches_to_source(source, [semi, using, include])
        self.assertEqual(len(applied), 3)
        self.assertTrue(updated.startswith("#include <vector>\nusing std::vector;\n;"))

    def test_crlf_and_missing_trailing_newline_are_preserved(self):
        source = "int x = 1;\r\nint y = 2;"
        patch = self.patch(source, 2, 9, "2", "3")
        result = apply_patch_exact(source, patch)
        self.assertEqual(result.source, "int x = 1;\r\nint y = 3;")
        self.assertFalse(result.source.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
