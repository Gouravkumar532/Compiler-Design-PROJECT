import unittest

from src.analyzer import analyze_translation_unit
from src.patch_model import CodePatch, prepare_patch
from src.repair_verifier import RepairVerifier


class TestRepairVerifier(unittest.TestCase):
    def test_verified_candidate_removes_target_without_regression(self):
        source = "int main() {\n    int x = 0;\n    if (x = 5) return 1;\n    return 0;\n}\n"
        result = analyze_translation_unit("verify.cpp", source, enable_suggestions=True)
        patch = next(p for p in result.candidate_patches if p.error_code == "W002")
        outcome = RepairVerifier().verify(result, source, [patch])
        self.assertTrue(outcome.accepted)
        self.assertTrue(patch.verified)
        self.assertIn("x == 5", outcome.patched_source)

    def test_no_improvement_is_rejected(self):
        source = "int main() { return 0; }\n"
        result = analyze_translation_unit("verify.cpp", source, enable_suggestions=False)
        patch = CodePatch("verify.cpp", 1, 1, 1, 1, "", " ", "P003", "no target", confidence="safe")
        prepare_patch(patch, source)
        outcome = RepairVerifier().verify(result, source, [patch])
        self.assertFalse(outcome.accepted)
        self.assertIn("target diagnostic", outcome.message)

    def test_patch_that_introduces_diagnostic_is_rejected(self):
        source = "int main() { return 0; }\n"
        result = analyze_translation_unit("verify.cpp", source, enable_suggestions=False)
        start = source.index("0")
        patch = CodePatch(
            "verify.cpp", 1, 1, start + 1, start + 2, "0", "unknown_name",
            "P003", "introduce error", start_offset=start, end_offset=start + 1,
            confidence="safe",
        )
        prepare_patch(patch, source)
        outcome = RepairVerifier().verify(result, source, [patch])
        self.assertFalse(outcome.accepted)


if __name__ == "__main__":
    unittest.main()
