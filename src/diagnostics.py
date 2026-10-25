"""Diagnostic collection and rendering.

Deep compiler stages *record* structured diagnostics in a :class:`DiagnosticSink`.
Rendering to the terminal is a separate concern: by default a sink prints each
new diagnostic immediately (legacy direct-use behaviour); the canonical analyzer
creates a silent sink and renders the finished result afterwards with
:func:`render_diagnostics`.
"""

from typing import Any, Dict, Iterable, List, Optional

from src.analysis_result import AnalysisFailure, Diagnostic, SourceLocation
from src.errors import Colors


def make_diagnostic(
    code: str,
    severity: str,
    message: str,
    file: Optional[str] = None,
    line: int = 1,
    col: int = 1,
    end_line: Optional[int] = None,
    end_col: Optional[int] = None,
    *,
    file_path: Optional[str] = None,
    source_text: Optional[str] = None,
    source: Optional[str] = None,
    help_text: Optional[str] = "",
    notes: Optional[List[str]] = None,
    stage: str = "",
    length: Optional[int] = None,
    style: str = "",
    suggestion: Optional[str] = None,
    explanations: Optional[List[str]] = None,
    fixability: str = "none",
    patch: Optional[Any] = None,
    macro_generated: bool = False,
    extra: Optional[Dict[str, Any]] = None,
) -> Diagnostic:
    """Build a canonical diagnostic located in physical file ``file`` / ``file_path``."""
    target_file = file_path if file_path is not None else (file if file is not None else "<stdin>")
    if end_line is None:
        end_line = line
    if end_col is None:
        end_col = col + (length if length is not None else 1)

    src = source_text if source_text is not None else source
    source_line = ""
    data: Dict[str, Any] = dict(extra or {})
    if src is not None:
        lines = src.splitlines()
        if 0 <= line - 1 < len(lines):
            source_line = lines[line - 1]
            data["has_snippet"] = True

    if not style:
        if code == "P002":
            style = "malformed_expression"
        elif code == "P003":
            style = "missing_semicolon"
        elif code == "P004":
            style = "delimiter"
        elif code == "P005":
            style = "cross_language"
        elif code == "E015":
            style = "missing_header"
        elif code == "E016":
            style = "namespace"
    if style:
        data["style"] = style
    if suggestion is not None and "suggestion" not in data:
        data["suggestion"] = suggestion

    exp_list = list(explanations or [])
    note_list = list(notes) if notes is not None else list(exp_list)
    effective_help = help_text or (suggestion if style == "delimiter" and suggestion else "")

    return Diagnostic(
        code=code,
        severity=severity,
        message=message,
        location=SourceLocation(target_file, line, col, end_line, max(end_col, col)),
        help_text=effective_help or "",
        notes=note_list,
        source_stage=stage,
        source_line=source_line,
        suggestion=suggestion,
        explanations=exp_list,
        fixability=fixability,
        patch=patch,
        macro_generated=bool(macro_generated),
        extra=data,
    )


class DiagnosticSink:
    """Ordered, de-duplicated collection of diagnostics shared by all stages."""

    def __init__(self, emit: bool = True, display_names: Optional[Dict[str, str]] = None):
        self.emit = emit
        self.display_names: Dict[str, str] = dict(display_names or {})
        self.diagnostics: List[Diagnostic] = []
        self._keys = set()

    def add(self, diag: Diagnostic) -> bool:
        """Record ``diag``. Returns False (and records nothing) for a duplicate."""
        key = diag.key()
        if key in self._keys:
            return False
        self._keys.add(key)
        self.diagnostics.append(diag)
        if self.emit:
            render_diagnostic(diag, self.display_names)
        return True

    @property
    def error_count(self) -> int:
        return sum(1 for d in self.diagnostics if d.severity in ("error", "internal"))

    @property
    def warning_count(self) -> int:
        return sum(1 for d in self.diagnostics if d.severity == "warning")


def failure_to_diagnostic(failure: AnalysisFailure, default_file: str = "<stdin>") -> Diagnostic:
    """Convert an internal stage failure into a canonical internal Diagnostic."""
    loc = failure.location or SourceLocation(default_file, 1, 1, 1, 2)
    return Diagnostic(
        code="INTERNAL",
        severity="internal",
        message=f"Internal {failure.stage} failure ({failure.exception_type}): {failure.message}",
        location=loc,
        help_text="Analysis did not complete cleanly; file modifications are disabled.",
        source_stage=failure.stage,
    )


def _display(diag: Diagnostic, display_names: Optional[Dict[str, str]]) -> str:
    file = diag.location.file_path
    if display_names and file in display_names:
        return display_names[file]
    return file


def render_diagnostic(
    diag: Diagnostic, display_names: Optional[Dict[str, str]] = None
) -> None:
    """Print one diagnostic as a Rust-style card."""
    C = Colors
    style = diag.extra.get("style", "")
    is_error = diag.severity in ("error", "internal")
    sev_color = C.RED if is_error else C.YELLOW
    sev_name = "error" if diag.severity == "error" else ("internal" if diag.severity == "internal" else "warning")
    loc = diag.location

    print(f"\n{C.BOLD}{sev_color}{sev_name}[{diag.code}]{C.RESET}: {C.BOLD}{diag.message}{C.RESET}")
    print(f"  {C.CYAN}-->{C.RESET} {_display(diag, display_names)}:{loc.line}:{loc.col}")

    if diag.source_line or diag.extra.get("has_snippet"):
        line_text = diag.source_line
        num = str(loc.line)
        margin = " " * len(num)
        print(f" {C.CYAN}{margin} |{C.RESET}")
        print(f" {C.CYAN}{num} |{C.RESET} {line_text}")
        indent = " " * max(0, loc.col - 1)
        if style == "missing_semicolon":
            print(f" {C.CYAN}{margin} |{C.RESET} {indent}{C.BOLD}{C.GREEN}+{C.RESET}{C.BOLD}{C.RED}^{C.RESET}")
        else:
            length = loc.end_col - loc.col if loc.end_line == loc.line else 1
            underline = "^" * max(1, length)
            print(f" {C.CYAN}{margin} |{C.RESET} {indent}{C.BOLD}{sev_color}{underline}{C.RESET}")
        print(f" {C.CYAN}{margin} |{C.RESET}")

    if style in ("malformed_expression", "cross_language"):
        suggestion = diag.extra.get("suggestion") or diag.suggestion or ""
        if suggestion:
            print(f"  {C.BOLD}{C.GREEN}help:{C.RESET} did you mean '{C.BOLD}{C.GREEN}{suggestion}{C.RESET}'?")
        for exp in (diag.explanations or diag.notes):
            print(f"        - {exp}")
        print()
    elif style == "missing_semicolon":
        print(f"  {C.BOLD}{C.GREEN}help:{C.RESET} insert ';' here\n")
    elif style == "delimiter":
        help_msg = diag.help_text or diag.suggestion or ""
        if help_msg:
            print(f"  {C.BOLD}{C.GREEN}help:{C.RESET} {help_msg}\n")
        else:
            print()
    elif style == "missing_header":
        if diag.help_text:
            print(f"  {C.BOLD}{C.GREEN}help:{C.RESET} {diag.help_text}")
        action = diag.extra.get("action", "")
        if action:
            print(f"  {C.BOLD}{C.CYAN}action:{C.RESET} {action}\n")
        else:
            print()
    elif style == "namespace":
        for note in diag.notes:
            print(f"  {C.BOLD}{C.CYAN}note:{C.RESET} {note}")
        print(f"  {C.BOLD}{C.GREEN}help:{C.RESET} fix this error by choosing one of the following:")
        print(f"        [Option 1] Qualify symbol directly:")
        print(f"                   {C.BOLD}{C.GREEN}{diag.extra.get('option1', '')}{C.RESET}")
        print(f"        [Option 2] Add directive at line {diag.extra.get('directive_line', 1)}:")
        print(f"                   {C.BOLD}{C.GREEN}{diag.extra.get('option2', '')}{C.RESET}\n")
    else:
        for note in diag.notes:
            print(f"  {C.BOLD}{C.CYAN}note:{C.RESET} {note}")
        if diag.help_text:
            help_color = C.GREEN if is_error else C.CYAN
            print(f"  {C.BOLD}{help_color}help:{C.RESET} {diag.help_text}")
        print()


def render_diagnostics(
    diagnostics: Iterable[Diagnostic], display_names: Optional[Dict[str, str]] = None
) -> None:
    """Render a finished diagnostic collection to the terminal."""
    for diag in diagnostics:
        render_diagnostic(diag, display_names)


emit_diagnostic = render_diagnostic
emit_diagnostics = render_diagnostics


def diagnostic_to_dict(diag: Diagnostic) -> Dict[str, Any]:
    """JSON-serialisable view shared by the workbench and tests."""
    loc = diag.location
    caret_len = max(1, (loc.end_col - loc.col) if loc.end_line == loc.line else 1)
    caret = " " * max(0, loc.col - 1) + ("^" * caret_len)
    formatted_snippet = (
        f"{loc.line:3d} | {diag.source_line}\n    | {caret}"
        if diag.source_line
        else ""
    )
    return {
        "code": diag.code,
        "severity": diag.severity,
        "message": diag.message,
        "file": loc.file_path,
        "line": loc.line,
        "col": loc.col,
        "end_line": loc.end_line,
        "end_col": loc.end_col,
        "help": diag.help_text,
        "notes": list(diag.notes),
        "stage": diag.source_stage,
        "snippet": formatted_snippet,
        "source_line": diag.source_line,
        "fixability": diag.fixability,
        "macro_generated": diag.macro_generated,
    }


def diagnostic_to_lsp(diag: Diagnostic) -> Dict[str, Any]:
    """LSP Diagnostic using original-document (0-based) coordinates."""
    loc = diag.location
    return {
        "range": {
            "start": {"line": max(0, loc.line - 1), "character": max(0, loc.col - 1)},
            "end": {
                "line": max(0, loc.end_line - 1),
                "character": max(0, loc.end_col - 1) if loc.end_line != loc.line or loc.end_col > loc.col else max(0, loc.col - 1) + 1,
            },
        },
        "severity": 1 if diag.severity in ("error", "internal") else 2,
        "code": diag.code,
        "source": "c++",
        "message": diag.message,
        "file": loc.file_path,
        "data": {
            "file": loc.file_path,
            "line": loc.line,
            "col": loc.col,
            "end_line": loc.end_line,
            "end_col": loc.end_col,
        },
    }
