"""Shared, bounded orchestration for verified source repair transactions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence, Set

from src.analysis_result import AnalysisResult, Diagnostic
from src.analyzer import analyze_translation_unit
from src.patch_model import CodePatch, apply_patches_to_source
from src.paths import same_file
from src.repair_verifier import RepairVerifier


@dataclass
class RepairRound:
    number: int
    diagnostics_before: int
    diagnostics_after: int
    patches_applied: List[CodePatch] = field(default_factory=list)


@dataclass
class RepairResult:
    status: str
    message: str
    original_source: str
    updated_source: str
    initial_analysis: AnalysisResult
    final_analysis: AnalysisResult
    applied_patches: List[CodePatch] = field(default_factory=list)
    remaining_patches: List[CodePatch] = field(default_factory=list)
    rounds: List[RepairRound] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.updated_source != self.original_source

    @property
    def success(self) -> bool:
        return self.status in {"complete", "partial", "unchanged"}


def _allowed_confidences(policy: str | Sequence[str]) -> Set[str]:
    if isinstance(policy, str):
        if policy == "all":
            return {"safe", "review", "heuristic"}
        if policy == "safe":
            return {"safe"}
        return {policy}
    return set(policy)


def _eligible_patches(
    result: AnalysisResult,
    confidences: Set[str],
    excluded_codes: Set[str],
) -> List[CodePatch]:
    return [
        patch
        for patch in result.candidate_patches
        if patch.confidence in confidences
        and patch.error_code not in excluded_codes
        and same_file(patch.file_path, result.entry_file)
    ]


def _entry_patches(result: AnalysisResult) -> List[CodePatch]:
    return [
        patch for patch in result.candidate_patches
        if same_file(patch.file_path, result.entry_file)
    ]


def repair_source(
    file_path: str,
    source: str,
    *,
    confidence_policy: str | Sequence[str] = "safe",
    max_rounds: int = 5,
    warn_as_error: bool = False,
    excluded_codes: Sequence[str] = (),
) -> RepairResult:
    """Repair ``source`` entirely in memory and verify the final transaction.

    Per-patch ``verified`` flags are deliberately not used as an input filter:
    individually invalid-looking patches can form a valid dependent repair group.
    No caller should write ``updated_source`` unless ``success`` is true.
    """
    if max_rounds < 1:
        raise ValueError("max_rounds must be at least 1")

    confidences = _allowed_confidences(confidence_policy)
    excluded = set(excluded_codes)
    initial = analyze_translation_unit(
        file_path,
        source,
        enable_suggestions=True,
        warn_as_error=warn_as_error,
    )
    if not initial.safe_to_write:
        return RepairResult(
            "failed",
            "analysis did not complete cleanly",
            source,
            source,
            initial,
            initial,
            remaining_patches=list(initial.candidate_patches),
        )

    current_source = source
    current = initial
    seen_sources = {source}
    all_applied: List[CodePatch] = []
    rounds: List[RepairRound] = []

    for round_number in range(1, max_rounds + 1):
        candidates = _eligible_patches(current, confidences, excluded)
        if not candidates:
            break

        # A producer may provide one atomic whole-source repair alongside the
        # lower-level parser recovery patches that made analysis possible.
        # Prefer the atomic patch; applying overlapping recovery patches would
        # otherwise discard it as a conflict.
        whole_source = [
            patch for patch in candidates
            if patch.start_offset == 0 and patch.end_offset == len(current_source)
        ]
        if whole_source:
            candidates = whole_source

        patched_source, applied = apply_patches_to_source(
            current_source,
            candidates,
            target_file=current.entry_file,
        )
        if not applied or patched_source == current_source:
            break
        if patched_source in seen_sources:
            break

        next_result = analyze_translation_unit(
            file_path,
            patched_source,
            enable_suggestions=True,
            warn_as_error=warn_as_error,
        )
        if not next_result.safe_to_write:
            return RepairResult(
                "rejected",
                "a repair round produced an incomplete analysis",
                source,
                source,
                initial,
                current,
                applied_patches=all_applied,
                remaining_patches=list(current.candidate_patches),
                rounds=rounds,
            )

        rounds.append(
            RepairRound(
                round_number,
                len(current.diagnostics),
                len(next_result.diagnostics),
                list(applied),
            )
        )
        all_applied.extend(applied)
        current_source = patched_source
        current = next_result
        seen_sources.add(current_source)

    if current_source == source:
        remaining = _entry_patches(current)
        return RepairResult(
            "unchanged",
            "no applicable repairs were available",
            source,
            source,
            initial,
            current,
            remaining_patches=remaining,
            rounds=rounds,
        )

    verification = RepairVerifier().verify_final_source(
        initial,
        source,
        current_source,
        all_applied,
        final_result=current,
    )
    if not verification.accepted:
        return RepairResult(
            "rejected",
            verification.message,
            source,
            source,
            initial,
            current,
            applied_patches=all_applied,
            remaining_patches=list(current.candidate_patches),
            rounds=rounds,
        )

    remaining = _entry_patches(current)
    fully_repaired = current.error_count == 0 and not remaining
    status = "complete" if fully_repaired else "partial"
    if fully_repaired:
        message = f"applied {len(all_applied)} verified repair(s)"
    else:
        message = (
            f"applied {len(all_applied)} verified repair(s); "
            f"{current.error_count} error(s) and {len(remaining)} eligible repair(s) remain"
        )
    return RepairResult(
        status,
        message,
        source,
        current_source,
        initial,
        current,
        applied_patches=all_applied,
        remaining_patches=remaining,
        rounds=rounds,
    )
