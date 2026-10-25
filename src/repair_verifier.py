"""Central, side-effect-free verification for every source repair."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
from typing import List, Optional, Sequence, Tuple

from src.analysis_result import AnalysisResult, Diagnostic
from src.patch_model import CodePatch, apply_patches_to_source
from src.paths import same_file


@dataclass
class VerificationResult:
    accepted: bool
    message: str
    patched_source: str
    patches: List[CodePatch] = field(default_factory=list)
    before_diagnostics: List[Diagnostic] = field(default_factory=list)
    after_diagnostics: List[Diagnostic] = field(default_factory=list)


def _identity(diag: Diagnostic) -> Tuple[str, str, str]:
    # Insertions legitimately relocate unchanged diagnostics.  Compare their
    # semantic identity and multiplicity so line shifts are not false regressions.
    return (diag.code, diag.severity, diag.message)


class RepairVerifier:
    """Apply exact patches in memory and re-run the canonical analyzer once."""

    def verify(
        self,
        original_result: AnalysisResult,
        original_source: str,
        patches: Sequence[CodePatch],
    ) -> VerificationResult:
        candidates = list(patches)
        if not original_result.complete:
            return VerificationResult(False, "original analysis is incomplete", original_source, candidates)
        if not candidates:
            return VerificationResult(False, "no candidate patches", original_source, candidates)
        if any(not same_file(p.file_path, original_result.entry_file) for p in candidates):
            return VerificationResult(False, "patch targets a different physical file", original_source, candidates)

        patched, applied = apply_patches_to_source(
            original_source, candidates, target_file=original_result.entry_file
        )
        if len(applied) != len(candidates):
            return VerificationResult(False, "patch application was stale, conflicting, or a no-op", original_source, candidates)

        from src.analyzer import analyze_translation_unit

        after = analyze_translation_unit(
            original_result.entry_file,
            patched,
            enable_suggestions=False,
        )
        if not after.complete:
            return VerificationResult(
                False, "patched analysis is incomplete", patched, candidates,
                list(original_result.diagnostics), list(after.diagnostics),
            )

        before = list(original_result.diagnostics)
        after_diags = list(after.diagnostics)
        target_codes = {p.error_code for p in candidates}
        removed_target = any(
            sum(1 for d in after_diags if d.code == code)
            < sum(1 for d in before if d.code == code)
            for code in target_codes
        )
        if not removed_target:
            return VerificationResult(False, "target diagnostic was not removed", patched, candidates, before, after_diags)

        before_ids = Counter(_identity(d) for d in before)
        after_ids = Counter(_identity(d) for d in after_diags)
        if any(count > before_ids[identity] for identity, count in after_ids.items()):
            return VerificationResult(False, "repair introduced a new diagnostic", patched, candidates, before, after_diags)

        before_errors = sum(d.severity in {"error", "internal"} for d in before)
        after_errors = sum(d.severity in {"error", "internal"} for d in after_diags)
        if after_errors > before_errors:
            return VerificationResult(False, "repair increased the error count", patched, candidates, before, after_diags)

        for patch in candidates:
            patch.verified = True
            patch.verification_message = "verified by complete re-analysis"
        return VerificationResult(True, "verified", patched, candidates, before, after_diags)

    def verify_final_source(
        self,
        original_result: AnalysisResult,
        original_source: str,
        final_source: str,
        patches: Sequence[CodePatch],
        *,
        final_result: Optional[AnalysisResult] = None,
    ) -> VerificationResult:
        """Verify a completed multi-round transaction.

        Intermediate analysis may legitimately expose a follow-up diagnostic
        (for example E015 missing-header becoming E016 missing-namespace).  This
        method compares the original and final states, never an intermediate
        state, and still requires a strict diagnostic-score improvement.
        """
        candidates = list(patches)
        if not original_result.complete:
            return VerificationResult(False, "original analysis is incomplete", original_source, candidates)
        if not candidates:
            return VerificationResult(False, "no patches were applied", original_source, candidates)
        if final_source == original_source:
            return VerificationResult(False, "repair transaction did not change the source", original_source, candidates)
        if any(not same_file(p.file_path, original_result.entry_file) for p in candidates):
            return VerificationResult(False, "patch targets a different physical file", original_source, candidates)

        if final_result is None:
            from src.analyzer import analyze_translation_unit

            final_result = analyze_translation_unit(
                original_result.entry_file,
                final_source,
                enable_suggestions=True,
            )
        if not final_result.complete:
            return VerificationResult(
                False,
                "final repaired analysis is incomplete",
                final_source,
                candidates,
                list(original_result.diagnostics),
                list(final_result.diagnostics),
            )

        before = list(original_result.diagnostics)
        after = list(final_result.diagnostics)
        before_score = (original_result.error_count, original_result.warning_count)
        after_score = (final_result.error_count, final_result.warning_count)
        if after_score >= before_score:
            return VerificationResult(
                False,
                "final repair did not reduce the diagnostic score",
                final_source,
                candidates,
                before,
                after,
            )

        target_codes = {patch.error_code for patch in candidates}
        if not any(
            sum(diag.code == code for diag in after) < sum(diag.code == code for diag in before)
            for code in target_codes
        ):
            return VerificationResult(
                False,
                "final repair did not remove a target diagnostic",
                final_source,
                candidates,
                before,
                after,
            )

        for patch in candidates:
            patch.verified = True
            patch.verification_message = "verified as part of final repair transaction"
        return VerificationResult(True, "verified final repair transaction", final_source, candidates, before, after)

