"""Canonical single-pass translation unit analysis coordinator.

Frontends (CLI, LSP, workbench, patch collection) call
:func:`analyze_translation_unit` to obtain a complete, structured
:class:`AnalysisResult` without side effects (no prompts, no file writes,
no ``sys.exit()``, and no direct terminal printing during analysis).
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from src.analysis_result import (
    AnalysisFailure,
    AnalysisResult,
    Diagnostic,
    SourceLocation,
    dedupe_diagnostics,
)
from src.diagnostics import DiagnosticSink, failure_to_diagnostic
from src.lexer import Lexer
from src.parser import ParseError, Parser
from src.paths import canonical_path
from src.preprocessor import PreprocessResult, Preprocessor
from src.semantic import SemanticAnalyzer
from src.tokens import Token


def analyze_translation_unit(
    file_path: str,
    source: Optional[str] = None,
    *,
    enable_suggestions: bool = True,
    warn_as_error: bool = False,
) -> AnalysisResult:
    """Analyze a C++ translation unit in non-interactive, non-writing mode.

    Never prompts on stdin, never writes to disk, and never calls ``sys.exit()``.
    Unexpected ``Exception`` instances in any stage are captured as
    :class:`AnalysisFailure` objects while preserving all diagnostics collected
    up to that point. ``SystemExit``, ``KeyboardInterrupt``, and
    ``GeneratorExit`` are never caught.
    """
    entry_file = canonical_path(file_path)
    original_sources: Dict[str, str] = {}
    display_names: Dict[str, str] = {entry_file: file_path}
    timings: Dict[str, Tuple[float, str]] = {}
    internal_failures: List[AnalysisFailure] = []
    candidate_patches = []

    sink = DiagnosticSink(emit=False, display_names=display_names)

    preprocess_result: Optional[PreprocessResult] = None
    tokens: List[Token] = []
    ast = None
    symbol_count = 0
    missing_headers: List[str] = []

    preprocess_completed = False
    lexer_completed = False
    parser_completed = False
    semantic_completed = False

    # 0. Load source if not provided
    if source is None:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception as exc:
            failure = AnalysisFailure(
                stage="preprocess",
                message=str(exc),
                exception_type=type(exc).__name__,
                location=SourceLocation(entry_file, 1, 1, 1, 2),
            )
            internal_failures.append(failure)
            sink.add(failure_to_diagnostic(failure, entry_file))
            return AnalysisResult(
                entry_file=entry_file,
                original_sources=original_sources,
                preprocess_result=None,
                tokens=[],
                ast=None,
                diagnostics=dedupe_diagnostics(sink.diagnostics),
                candidate_patches=[],
                parser_completed=False,
                semantic_completed=False,
                internal_failures=internal_failures,
                timings=timings,
                lexer_completed=False,
                preprocess_completed=False,
                display_names=display_names,
                symbol_count=0,
            )

    original_sources[entry_file] = source

    # 1. Preprocessor Stage
    t0 = time.perf_counter()
    try:
        preproc = Preprocessor()
        preprocess_result = preproc.preprocess(source, file_path)
        original_sources = dict(preprocess_result.file_sources)
        display_names.update(preprocess_result.display_names)
        sink.display_names = display_names
        preprocess_completed = True
        timings["Preprocess"] = (
            (time.perf_counter() - t0) * 1000.0,
            f"{len(preprocess_result.included_headers)} headers",
        )
    except Exception as exc:
        timings["Preprocess"] = ((time.perf_counter() - t0) * 1000.0, "failed")
        failure = AnalysisFailure(
            stage="preprocess",
            message=str(exc),
            exception_type=type(exc).__name__,
            location=SourceLocation(entry_file, 1, 1, 1, 2),
        )
        internal_failures.append(failure)
        sink.add(failure_to_diagnostic(failure, entry_file))

    # 2. Lexer Stage
    if preprocess_completed and preprocess_result is not None:
        t0 = time.perf_counter()
        lexer_instance: Optional[Lexer] = None
        try:
            lexer_instance = Lexer(
                preprocess_result.analysis_source,
                file_path,
                preproc_result=preprocess_result,
                diag_sink=sink,
            )
            tokens = lexer_instance.tokenize()
            lexer_completed = True
            timings["Lexical Analysis"] = (
                (time.perf_counter() - t0) * 1000.0,
                f"{len(tokens)} tokens",
            )
        except Exception as exc:
            if lexer_instance is not None and getattr(lexer_instance, "tokens", None):
                tokens = list(lexer_instance.tokens)
            timings["Lexical Analysis"] = ((time.perf_counter() - t0) * 1000.0, "failed")
            failure = AnalysisFailure(
                stage="lexer",
                message=str(exc),
                exception_type=type(exc).__name__,
                location=SourceLocation(entry_file, 1, 1, 1, 2),
            )
            internal_failures.append(failure)
            sink.add(failure_to_diagnostic(failure, entry_file))

    # 3. Parser Stage
    if lexer_completed and preprocess_result is not None:
        t0 = time.perf_counter()
        entry_source = original_sources.get(entry_file, source)
        parser_instance: Optional[Parser] = None
        try:
            parser_instance = Parser(
                tokens,
                entry_source,
                file_path,
                enable_repair=enable_suggestions,
                patch_recorder=candidate_patches if enable_suggestions else None,
                preproc_result=preprocess_result,
                diag_sink=sink,
            )
            ast = parser_instance.parse()
            parser_completed = True
            decl_count = len(ast.declarations) if ast and hasattr(ast, "declarations") else 0
            timings["Syntax Parsing"] = (
                (time.perf_counter() - t0) * 1000.0,
                f"{decl_count} declarations",
            )
        except ParseError as parse_err:
            if parser_instance is not None:
                parser_instance.record_parse_error(parse_err)
            parser_completed = True
            timings["Syntax Parsing"] = ((time.perf_counter() - t0) * 1000.0, "syntax error")
        except Exception as exc:
            timings["Syntax Parsing"] = ((time.perf_counter() - t0) * 1000.0, "failed")
            failure = AnalysisFailure(
                stage="parser",
                message=str(exc),
                exception_type=type(exc).__name__,
                location=SourceLocation(entry_file, 1, 1, 1, 2),
            )
            internal_failures.append(failure)
            sink.add(failure_to_diagnostic(failure, entry_file))

    # 4. Semantic Analysis Stage
    if parser_completed:
        if ast is not None and preprocess_result is not None:
            t0 = time.perf_counter()
            entry_source = original_sources.get(entry_file, source)
            try:
                sem = SemanticAnalyzer(
                    entry_source,
                    file_path,
                    warn_as_error=warn_as_error,
                    included_headers=preprocess_result.included_headers,
                    auto_include=enable_suggestions,
                    exit_on_error=False,
                    patch_recorder=candidate_patches if enable_suggestions else None,
                    preproc_result=preprocess_result,
                    diag_sink=sink,
                )
                sem.analyze(ast)
                symbol_count = (
                    len(sem.global_scope.symbols)
                    + len(sem.global_scope.functions)
                    + len(sem.global_scope.classes)
                    + len(sem.global_scope.structs)
                )
                missing_headers = list(getattr(sem, "missing_headers", []))
                semantic_completed = True
                timings["Semantic Analysis"] = (
                    (time.perf_counter() - t0) * 1000.0,
                    f"{symbol_count} symbols",
                )
            except Exception as exc:
                timings["Semantic Analysis"] = ((time.perf_counter() - t0) * 1000.0, "failed")
                failure = AnalysisFailure(
                    stage="semantic",
                    message=str(exc),
                    exception_type=type(exc).__name__,
                    location=SourceLocation(entry_file, 1, 1, 1, 2),
                )
                internal_failures.append(failure)
                sink.add(failure_to_diagnostic(failure, entry_file))
        else:
            # Parser finished with a syntax error and no usable AST (e.g. enable_suggestions=False)
            semantic_completed = True

    is_complete = (
        preprocess_completed
        and lexer_completed
        and parser_completed
        and semantic_completed
        and not internal_failures
    )
    safe_patches = list(candidate_patches) if is_complete else []

    result = AnalysisResult(
        entry_file=entry_file,
        original_sources=original_sources,
        preprocess_result=preprocess_result,
        tokens=tokens,
        ast=ast,
        diagnostics=dedupe_diagnostics(sink.diagnostics),
        candidate_patches=safe_patches,
        parser_completed=parser_completed,
        semantic_completed=semantic_completed,
        internal_failures=internal_failures,
        timings=timings,
        lexer_completed=lexer_completed,
        preprocess_completed=preprocess_completed,
        display_names=display_names,
        symbol_count=symbol_count,
        missing_headers=missing_headers,
    )
    return result
