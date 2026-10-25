"""
Patch Model & Diff Generation Engine (Idea 9: Interactive Terminal TUI)

Provides structured code patch representation (CodePatch), bottom-up sequencing,
colorized unified diff rendering, and patch application engine.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
import difflib
import hashlib
import os
import re

from src.errors import Colors, ERROR_CATALOGUE
from src.paths import canonical_path, same_file


@dataclass
class CodePatch:
    """Represents a structured code transformation patch."""
    file_path: str
    line_start: int
    line_end: int
    col_start: int
    col_end: int
    original_text: str
    replacement_text: str
    error_code: str
    summary: str
    explanations: List[str] = field(default_factory=list)
    applied: bool = False
    title: str = ""
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    expected_text: Optional[str] = None
    context_hash: str = ""
    confidence: str = "review"
    verified: bool = False
    verification_message: str = ""

    def __post_init__(self):
        if self.expected_text is None:
            self.expected_text = self.original_text
        if self.confidence not in {"safe", "review", "heuristic"}:
            raise ValueError(f"invalid patch confidence: {self.confidence}")
        if not self.title:
            if self.error_code in ERROR_CATALOGUE:
                self.title = ERROR_CATALOGUE[self.error_code].get("title", self.summary)
            else:
                self.title = self.summary


@dataclass(frozen=True)
class PatchApplicationResult:
    source: str
    applied: bool
    status: str
    message: str = ""


def _line_col_offset(source: str, line: int, col: int) -> int:
    """Translate one-based display coordinates without normalising newlines."""
    if line < 1 or col < 1:
        raise ValueError("line and column must be one-based positive integers")
    lines = source.splitlines(keepends=True)
    if not lines:
        if line == 1 and col == 1:
            return 0
        raise ValueError("location is outside the source")
    if line == len(lines) + 1 and col == 1:
        return len(source)
    if line > len(lines):
        raise ValueError("line is outside the source")
    prefix = sum(len(item) for item in lines[: line - 1])
    raw_line = lines[line - 1]
    content_length = len(raw_line.rstrip("\r\n"))
    if col - 1 > content_length:
        raise ValueError("column is outside the source line")
    return prefix + col - 1


def locate_snippet_span(source: str, line: int, anchor_col: int, snippet: str) -> Tuple[int, int, int]:
    """Resolve a producer's snippet at creation time using its diagnostic anchor.

    Repeated text is disambiguated by requiring the anchored column to fall inside
    the occurrence.  If no occurrence contains it, the location is not exact and
    patch creation must fail instead of guessing.
    """
    lines = source.splitlines(keepends=True)
    if line < 1 or line > len(lines):
        raise ValueError("patch line is outside the source")
    content = lines[line - 1].rstrip("\r\n")
    anchor = anchor_col - 1
    matches = []
    start = content.find(snippet)
    while start >= 0:
        end = start + len(snippet)
        if start <= anchor <= max(start, end - 1):
            matches.append((start, end))
        start = content.find(snippet, start + 1)
    if len(matches) != 1:
        raise ValueError("diagnostic anchor does not identify exactly one source occurrence")
    start, end = matches[0]
    absolute = sum(len(item) for item in lines[: line - 1])
    return start + 1, absolute + start, absolute + end


def locate_whitespace_flexible_span(
    source: str,
    line: int,
    anchor_col: int,
    snippet: str,
) -> Tuple[int, int, int, str]:
    """Locate a generated snippet while tolerating source whitespace differences.

    Semantic diagnostics render expressions with normalized spaces, while the
    user's source may be compact (for example ``x^2``).  The returned expected
    text is always the exact source slice, preserving stale-patch protection.
    """
    try:
        col, start, end = locate_snippet_span(source, line, anchor_col, snippet)
        return col, start, end, snippet
    except ValueError:
        pass

    lines = source.splitlines(keepends=True)
    if line < 1 or line > len(lines):
        raise ValueError("patch line is outside the source")
    content = lines[line - 1].rstrip("\r\n")
    anchor = anchor_col - 1
    parts = re.split(r"\s+", snippet.strip())
    pattern = r"\s*".join(re.escape(part) for part in parts if part)
    matches = [
        match
        for match in re.finditer(pattern, content)
        if match.start() <= anchor <= max(match.start(), match.end() - 1)
    ]
    if len(matches) != 1:
        raise ValueError("diagnostic anchor does not identify exactly one source occurrence")
    match = matches[0]
    absolute = sum(len(item) for item in lines[: line - 1])
    return (
        match.start() + 1,
        absolute + match.start(),
        absolute + match.end(),
        match.group(0),
    )


def _patch_context_hash(source: str, start: int, end: int, radius: int = 32) -> str:
    before = source[max(0, start - radius):start]
    after = source[end:min(len(source), end + radius)]
    return hashlib.sha256((before + "\0" + after).encode("utf-8")).hexdigest()[:20]


def prepare_patch(patch: CodePatch, source: str) -> CodePatch:
    """Populate deterministic offsets/context from coordinates when a producer did not."""
    if patch.start_offset is None:
        patch.start_offset = _line_col_offset(source, patch.line_start, patch.col_start)
    if patch.end_offset is None:
        if patch.expected_text:
            patch.end_offset = patch.start_offset + len(patch.expected_text)
        else:
            patch.end_offset = patch.start_offset
    if not patch.context_hash:
        patch.context_hash = _patch_context_hash(source, patch.start_offset, patch.end_offset)
    return patch


def apply_patch_exact(source: str, patch: CodePatch) -> PatchApplicationResult:
    try:
        prepare_patch(patch, source)
    except ValueError as exc:
        return PatchApplicationResult(source, False, "invalid-range", str(exc))
    start = patch.start_offset
    end = patch.end_offset
    if start is None or end is None or start < 0 or end < start or end > len(source):
        return PatchApplicationResult(source, False, "invalid-range", "patch offsets are outside the source")
    expected = patch.expected_text or ""
    if source[start:end] != expected:
        return PatchApplicationResult(source, False, "stale", "source slice no longer matches expected_text")
    if patch.context_hash != _patch_context_hash(source, start, end):
        return PatchApplicationResult(source, False, "stale", "surrounding source context changed")
    updated = source[:start] + patch.replacement_text + source[end:]
    if updated == source:
        return PatchApplicationResult(source, False, "no-op", "replacement does not change the source")
    return PatchApplicationResult(updated, True, "applied")


class UnifiedDiffRenderer:
    """Renders colorized unified diffs and interactive patch summary cards."""

    @staticmethod
    def render_summary_card(
        patch: CodePatch,
        patch_idx: int,
        total_patches: int,
        source: str,
        context_lines: int = 2,
        color: bool = True,
    ) -> str:
        """
        Renders the target user experience summary card for an individual patch.
        Shows header, original snippet, proposed fix, and explanations.
        """
        lines = source.splitlines()
        border_char = "=" * 80
        divider_char = "-" * 80

        c_bold = Colors.BOLD if color else ""
        c_cyan = Colors.CYAN if color else ""
        c_yellow = Colors.YELLOW if color else ""
        c_red = Colors.RED if color else ""
        c_green = Colors.GREEN if color else ""
        c_dim = Colors.DIM if color else ""
        c_reset = Colors.RESET if color else ""

        # Title / header line
        header = f"{c_bold}{border_char}{c_reset}\n"
        header += (
            f"  {c_bold}{c_cyan}[Patch {patch_idx}/{total_patches}]{c_reset} "
            f"{patch.file_path}:{patch.line_start}:{patch.col_start} - "
            f"{c_bold}{patch.title}{c_reset} ({c_yellow}{patch.error_code}{c_reset})\n"
        )
        header += f"{c_bold}{border_char}{c_reset}\n"

        # Surrounding context for original
        start_line = max(1, patch.line_start - context_lines)
        end_line = min(len(lines), max(patch.line_end, patch.line_start) + context_lines)

        original_section = f"{c_bold}Original:{c_reset}\n"
        max_num_len = len(str(end_line))

        for l_num in range(start_line, end_line + 1):
            line_str = lines[l_num - 1] if 0 <= l_num - 1 < len(lines) else ""
            num_padding = " " * (max_num_len - len(str(l_num)))
            original_section += f"   {num_padding}{c_dim}{l_num} |{c_reset} {line_str}\n"

        # Proposed fix section
        fix_section = f"\n{c_bold}Proposed Fix:{c_reset}\n"
        
        # Build modified lines for this patch snippet
        patch_source = apply_patch_to_source(source, patch)
        patch_lines = patch_source.splitlines()

        # Compute diff on the affected line window
        window_orig = lines[start_line - 1 : end_line]
        # Estimate affected window in patch_lines
        diff_orig = [l + "\n" for l in window_orig]
        diff_new_window = patch_lines[start_line - 1 : min(len(patch_lines), end_line + (len(patch_lines) - len(lines)))]
        diff_new = [l + "\n" for l in diff_new_window]

        diff_gen = list(difflib.unified_diff(diff_orig, diff_new, n=0, lineterm=""))
        
        # Fallback if unified diff was empty or identical
        diff_found = False
        for line in diff_gen:
            if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
                continue
            diff_found = True
            line_str = line[1:].rstrip("\r\n")
            if line.startswith("-"):
                fix_section += f"{c_red}{c_bold}- {line_str}{c_reset}\n"
            elif line.startswith("+"):
                fix_section += f"{c_green}{c_bold}+ {line_str}{c_reset}\n"

        if not diff_found:
            # Direct line display
            line_num = patch.line_start
            orig_line = lines[line_num - 1] if 0 <= line_num - 1 < len(lines) else patch.original_text
            fix_section += f"{c_red}{c_bold}-  {line_num} | {orig_line}{c_reset}\n"
            
            # Show replacement
            if patch.original_text:
                replaced = orig_line.replace(patch.original_text, patch.replacement_text, 1)
            else:
                replaced = orig_line + patch.replacement_text
            fix_section += f"{c_green}{c_bold}+  {line_num} | {replaced}{c_reset}\n"

        # Explanation section
        explanation_section = f"\n{c_bold}Explanation:{c_reset}\n"
        if patch.explanations:
            for exp in patch.explanations:
                explanation_section += f"  {c_cyan}*{c_reset} {exp}\n"
        else:
            explanation_section += f"  {c_cyan}*{c_reset} {patch.summary}\n"

        footer = f"\n{divider_char}\n"

        return header + original_section + fix_section + explanation_section + footer

    @staticmethod
    def render_unified_diff(
        patch: CodePatch,
        source: str,
        context_lines: int = 10,
        color: bool = True,
    ) -> str:
        """Renders an expanded unified diff with colored additions and deletions."""
        patched_source = apply_patch_to_source(source, patch)
        
        orig_lines = [l + "\n" for l in source.splitlines()]
        patch_lines = [l + "\n" for l in patched_source.splitlines()]

        diff = list(
            difflib.unified_diff(
                orig_lines,
                patch_lines,
                fromfile=f"a/{os.path.basename(patch.file_path)}",
                tofile=f"b/{os.path.basename(patch.file_path)}",
                n=context_lines,
            )
        )

        c_red = Colors.RED if color else ""
        c_green = Colors.GREEN if color else ""
        c_cyan = Colors.CYAN if color else ""
        c_bold = Colors.BOLD if color else ""
        c_reset = Colors.RESET if color else ""

        result = []
        for line in diff:
            stripped = line.rstrip("\n")
            if stripped.startswith("---") or stripped.startswith("+++"):
                result.append(f"{c_bold}{stripped}{c_reset}")
            elif stripped.startswith("@@"):
                result.append(f"{c_cyan}{stripped}{c_reset}")
            elif stripped.startswith("-"):
                result.append(f"{c_red}{stripped}{c_reset}")
            elif stripped.startswith("+"):
                result.append(f"{c_green}{stripped}{c_reset}")
            else:
                result.append(stripped)

        return "\n".join(result)


def sort_patches_bottom_up(patches: List[CodePatch]) -> List[CodePatch]:
    """
    Sorts patches in descending order by start line and column.
    Applying edits bottom-to-top guarantees earlier line/col coordinates
    in the source file remain valid and uncorrupted.
    """
    return sorted(
        patches,
        key=lambda p: (
            canonical_path(p.file_path),
            p.start_offset if p.start_offset is not None else -1,
            p.line_start,
            p.col_start,
        ),
        reverse=True,
    )


def apply_patch_to_source(source: str, patch: CodePatch) -> str:
    """
    Applies a single CodePatch to a source string safely.
    Handles exact line/column offsets, insertions, and multiline replacements.
    """
    return apply_patch_exact(source, patch).source


def apply_patches_to_source(
    source: str,
    patches: List[CodePatch],
    target_file: Optional[str] = None,
) -> Tuple[str, List[CodePatch]]:
    """
    Sequences and applies multiple patches using bottom-up ordering.
    If target_file is given, only patches targeting that physical file are applied.
    Returns the updated source string and list of successfully applied patches.
    """
    if target_file is not None:
        patches = [p for p in patches if same_file(p.file_path, target_file)]

    prepared = []
    seen = set()
    for patch in patches:
        try:
            prepare_patch(patch, source)
        except ValueError:
            continue
        if patch.context_hash != _patch_context_hash(source, patch.start_offset, patch.end_offset):
            patch.verification_message = "surrounding source context changed"
            continue
        if source[patch.start_offset:patch.end_offset] != (patch.expected_text or ""):
            patch.verification_message = "source slice no longer matches expected_text"
            continue
        identity = (canonical_path(patch.file_path), patch.start_offset, patch.end_offset,
                    patch.expected_text, patch.replacement_text)
        if identity not in seen:
            seen.add(identity)
            prepared.append(patch)

    # Reject all replacement overlaps. Compatible insertions share a point and
    # are ordered deterministically by category.
    ranged = sorted((p for p in prepared if p.start_offset != p.end_offset), key=lambda p: p.start_offset or 0)
    conflicted = set()
    for left, right in zip(ranged, ranged[1:]):
        if (right.start_offset or 0) < (left.end_offset or 0):
            conflicted.update((id(left), id(right)))

    insertion_priority = lambda p: (
        0 if p.replacement_text.lstrip().startswith("#include") else
        1 if p.replacement_text.lstrip().startswith("using ") else 2
    )
    prepared.sort(key=lambda p: (
        p.start_offset if p.start_offset is not None else -1,
        insertion_priority(p) if p.start_offset == p.end_offset else 0,
    ), reverse=True)
    sorted_patches = prepared
    applied_patches = []
    current_source = source

    for patch in sorted_patches:
        if id(patch) in conflicted:
            patch.verification_message = "overlapping patch conflict"
            continue
        # All stale checks were performed against the same original snapshot.
        # Rebase only the context fingerprint after safe bottom-up edits.
        original_context_hash = patch.context_hash
        patch.context_hash = _patch_context_hash(current_source, patch.start_offset, patch.end_offset)
        result = apply_patch_exact(current_source, patch)
        patch.context_hash = original_context_hash
        if result.applied:
            current_source = result.source
            patch.applied = True
            applied_patches.append(patch)
        else:
            patch.verification_message = result.message

    return current_source, applied_patches


def collect_candidate_patches_with_result(file_path: str, source: Optional[str] = None):
    """
    Runs the full analysis pipeline via analyze_translation_unit() and returns
    (candidate_patches, analysis_result). Returns empty patch list if not safe_to_write.
    """
    from src.analyzer import analyze_translation_unit

    result = analyze_translation_unit(file_path, source, enable_suggestions=True)
    if not result.safe_to_write:
        return [], result
    return list(result.candidate_patches), result


def collect_candidate_patches(file_path: str, source: Optional[str] = None) -> List[CodePatch]:
    """
    Runs the full syntax and semantic diagnostic pipeline on a source file in-memory
    and collects all candidate CodePatch objects without modifying the file on disk.
    """
    patches, _ = collect_candidate_patches_with_result(file_path, source)
    return patches

