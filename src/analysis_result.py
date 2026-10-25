"""Canonical analysis data model.

Every compiler stage reports structured :class:`Diagnostic` objects; frontends
(CLI, LSP, workbench, patch collection) consume the single
:class:`AnalysisResult` instead of parsing terminal text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from src.preprocessor import PreprocessResult
    from src.tokens import Token
    from src.ast_nodes import Program
    from src.patch_model import CodePatch


@dataclass(frozen=True)
class SourceLocation:
    """A physical source span (1-based, end exclusive) in one canonical file."""
    file_path: str
    line: int
    col: int
    end_line: int
    end_col: int


@dataclass
class Diagnostic:
    code: str
    severity: str  # "error" | "warning" | "internal"
    message: str
    location: SourceLocation
    help_text: str = ""
    notes: List[str] = field(default_factory=list)
    source_stage: str = ""
    # Rendering and repair metadata (never used for deduplication):
    source_line: str = ""
    suggestion: Optional[str] = None
    explanations: List[str] = field(default_factory=list)
    fixability: str = "none"  # "none" | "auto" | "manual"
    patch: Optional[CodePatch] = None
    macro_generated: bool = False
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def file_path(self) -> str:
        return self.location.file_path

    @property
    def line(self) -> int:
        return self.location.line

    @property
    def col(self) -> int:
        return self.location.col

    @property
    def end_line(self) -> int:
        return self.location.end_line

    @property
    def end_col(self) -> int:
        return self.location.end_col

    def key(self) -> Tuple[Any, ...]:
        loc = self.location
        return (
            loc.file_path,
            loc.line,
            loc.col,
            loc.end_line,
            loc.end_col,
            self.code,
            self.severity,
            self.message,
        )


@dataclass
class AnalysisFailure:
    stage: str
    message: str
    exception_type: str
    location: Optional[SourceLocation] = None


def dedupe_diagnostics(diagnostics: List[Diagnostic]) -> List[Diagnostic]:
    """Remove true duplicates while preserving discovery order."""
    seen = set()
    result: List[Diagnostic] = []
    for diag in diagnostics:
        k = diag.key()
        if k in seen:
            continue
        seen.add(k)
        result.append(diag)
    return result


@dataclass
class AnalysisResult:
    entry_file: str
    original_sources: Dict[str, str]
    preprocess_result: Optional[PreprocessResult]
    tokens: List[Token]
    ast: Optional[Program]
    diagnostics: List[Diagnostic]
    candidate_patches: List[CodePatch]
    parser_completed: bool
    semantic_completed: bool
    internal_failures: List[AnalysisFailure]
    timings: Dict[str, Tuple[float, str]]
    lexer_completed: bool = True
    preprocess_completed: bool = True
    display_names: Dict[str, str] = field(default_factory=dict)
    symbol_count: int = 0
    missing_headers: List[str] = field(default_factory=list)
    repaired_source: Optional[str] = None  # entry source after in-memory fixes (fix mode only)

    @property
    def failures(self) -> List[AnalysisFailure]:
        return self.internal_failures

    @property
    def complete(self) -> bool:
        """True only when every stage ran to completion without internal failure."""
        return (
            self.preprocess_completed
            and self.lexer_completed
            and self.parser_completed
            and self.semantic_completed
            and not self.internal_failures
        )

    @property
    def errors(self) -> List[Diagnostic]:
        return [d for d in self.diagnostics if d.severity in ("error", "internal")]

    @property
    def warnings(self) -> List[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    @property
    def has_errors(self) -> bool:
        return any(d.severity in ("error", "internal") for d in self.diagnostics) or bool(self.internal_failures)

    @property
    def safe_to_write(self) -> bool:
        """Incomplete analysis must never be written back to disk."""
        return self.complete

    def diagnostics_for(self, file_path: str) -> List[Diagnostic]:
        return [d for d in self.diagnostics if d.location.file_path == file_path]
