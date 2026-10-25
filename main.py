import argparse
import sys
import time
from typing import Tuple, Dict

from src.formatter import Formatter
from src.errors import explain_error, list_error_codes, Colors
from src.lsp import LanguageServer
from src.ast_viewer import format_ast
from src.analyzer import analyze_translation_unit
from src.diagnostics import render_diagnostics
from src.paths import canonical_path, same_file


def print_phase_timings(file_path: str, timings: Dict[str, Tuple[float, str]], total_time: float):
    print(f"\n{Colors.BOLD}{Colors.CYAN}[diagnostics]{Colors.RESET} Analysis Breakdown for {Colors.BOLD}{file_path}{Colors.RESET}:")
    print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}")
    print(f"{'Phase':<22} {'Time (s)':<12} {'Details'}")
    print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}")
    for idx, (phase, (duration, details)) in enumerate(timings.items(), 1):
        print(f"{idx}. {phase:<19} {duration:.4f}s      {Colors.DIM}{details}{Colors.RESET}")
    print(f"{Colors.DIM}{'-' * 60}{Colors.RESET}")
    print(f"{Colors.BOLD}{'Total Analysis Time:':<22} {total_time:.4f}s{Colors.RESET}\n")


def main():
    parser = argparse.ArgumentParser(
        prog="c++",
        description="Intelligent C++ Error Correction, Diagnostics & Recommendation Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Check command
    check_parser = subparsers.add_parser("check", help="Analyze source files for syntax and semantic errors")
    check_parser.add_argument("files", nargs="+", help="Input .cpp source file(s)")
    check_parser.add_argument("-v", "--verbose", action="store_true", help="Display phase analysis timings")
    check_parser.add_argument("-Werror", "--warn-as-error", action="store_true", help="Treat compiler warnings as errors")
    check_parser.add_argument("--no-suggest", action="store_true", help="Disable expression repair suggestions")

    # 2. Fix command
    fix_parser = subparsers.add_parser("fix", help="Automatically repair detected syntax, expression, and delimiter errors")
    fix_parser.add_argument("files", nargs="+", help="Input .cpp source file(s) to repair")
    fix_parser.add_argument("-w", "--write", "--in-place", action="store_true", dest="in_place", help="Write repaired code back to files on disk")
    fix_parser.add_argument("-i", "--interactive", action="store_true", default=False, help="Prompt before applying each individual fix")
    fix_parser.add_argument("--backup", action="store_true", help="Create .bak backup before modifying files on disk")
    fix_parser.add_argument("-v", "--verbose", action="store_true", help="Display detailed repair timings")

    # 3. Suggest / Recommend command
    suggest_parser = subparsers.add_parser("suggest", help="Show proposed code repairs, diagnostics, and explanations without altering files")
    suggest_parser.add_argument("files", nargs="+", help="Input .cpp source file(s)")
    suggest_parser.add_argument("-v", "--verbose", action="store_true", help="Display analysis timings")

    # 4. Explain command (c++ explain)
    explain_parser = subparsers.add_parser("explain", help="Display pedagogical explanation and code examples for an error code")
    explain_parser.add_argument("code", nargs="?", default=None, help="Error code (e.g., P002, E001, W001). Omit to list all.")

    # 5. Formatter command (c++ fmt)
    fmt_parser = subparsers.add_parser("fmt", help="Format source code according to standard styling")
    fmt_parser.add_argument("files", nargs="+", help="Input .cpp file(s) to format")
    fmt_parser.add_argument("-w", "--write", action="store_true", help="Write result back to file in-place instead of stdout")

    # 6. Tokens inspection
    tokens_parser = subparsers.add_parser("tokens", help="Inspect token stream produced by lexer")
    tokens_parser.add_argument("files", nargs="+", help="Input .cpp source file(s)")

    # 7. AST inspection
    ast_parser = subparsers.add_parser("ast", help="Display visual Abstract Syntax Tree (AST) hierarchy")
    ast_parser.add_argument("files", nargs="+", help="Input .cpp source file(s)")

    # 8. Test command (c++ test)
    test_parser = subparsers.add_parser("test", help="Run automated test suite for error repair and diagnostics")
    test_parser.add_argument("-v", "--verbose", action="store_true", help="Show verbose unit test output")

    # 9. LSP command (c++ lsp)
    subparsers.add_parser("lsp", help="Start Language Server Protocol (LSP) server for live IDE diagnostics & fixes")

    # 10. Workbench command (c++ workbench)
    wb_parser = subparsers.add_parser("workbench", help="Launch interactive C++ Compiler Workbench in your web browser")
    wb_parser.add_argument("file", nargs="?", default=None, help="Optional .cpp source file to load into the workbench")
    wb_parser.add_argument("-p", "--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    wb_parser.add_argument("--enable-native-run", action="store_true", help="Explicitly allow local native C++ compilation and execution")
    wb_parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")

    args = parser.parse_args()

    # Commands with no file arguments
    if args.command == "workbench":
        from src.ui_server import start_workbench
        start_workbench(
            port=args.port,
            open_browser=not args.no_browser,
            initial_file=args.file,
            enable_native_run=args.enable_native_run,
        )
        sys.exit(0)

    if args.command == "lsp":
        LanguageServer().run()
        sys.exit(0)

    if args.command == "explain":
        if args.code:
            explain_error(args.code)
        else:
            list_error_codes()
        sys.exit(0)

    if args.command == "test":
        import unittest
        loader = unittest.TestLoader()
        suite = loader.discover("tests", pattern="test_*.py")
        runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1)
        result = runner.run(suite)
        sys.exit(0 if result.wasSuccessful() else 1)

    # File processing commands
    start_time = time.time()
    verbose = getattr(args, "verbose", False)
    warn_as_error = getattr(args, "warn_as_error", False)

    if args.command == "tokens":
        had_errors = False
        for file_path in args.files:
            result = analyze_translation_unit(file_path, enable_suggestions=False)
            if not result.complete:
                render_diagnostics(result.diagnostics, result.display_names)
                had_errors = True
                continue
            tokens = result.tokens
            print(f"\n{Colors.BOLD}{Colors.CYAN}--- Token Stream for {file_path} ({len(tokens)} tokens) ---{Colors.RESET}")
            for t in tokens:
                print(f"  Line {t.line:3d}, Col {t.col:2d}: {t.type.name:<18} {repr(t.lexeme)}")
        sys.exit(1 if had_errors else 0)

    if args.command == "ast":
        had_errors = False
        for file_path in args.files:
            result = analyze_translation_unit(file_path, enable_suggestions=False)
            render_diagnostics(result.diagnostics, result.display_names)
            if verbose:
                total_sec = sum(d for d, _ in result.timings.values()) / 1000.0
                sec_timings = {k: (v[0] / 1000.0, v[1]) for k, v in result.timings.items()}
                print_phase_timings(file_path, sec_timings, total_sec)
            if not result.complete or result.ast is None:
                had_errors = True
                continue
            print(f"\n{Colors.BOLD}{Colors.CYAN}--- Abstract Syntax Tree for {file_path} ---{Colors.RESET}")
            print(format_ast(result.ast, use_color=True))
        sys.exit(1 if had_errors else 0)

    if args.command == "fmt":
        formatter = Formatter()
        for file_path in args.files:
            with open(file_path, "r", encoding="utf-8") as f:
                src = f.read()
            formatted = formatter.format_source(src, file_path)
            if args.write:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(formatted)
                print(f"{Colors.GREEN}Formatted and updated {file_path}{Colors.RESET}")
            else:
                print(formatted)
        sys.exit(0)

    if args.command == "check":
        no_suggest = getattr(args, "no_suggest", False)
        had_errors = False
        for file_path in args.files:
            result = analyze_translation_unit(
                file_path,
                enable_suggestions=not no_suggest,
                warn_as_error=warn_as_error,
            )
            render_diagnostics(result.diagnostics, result.display_names)
            if verbose:
                total_sec = sum(d for d, _ in result.timings.values()) / 1000.0
                sec_timings = {k: (v[0] / 1000.0, v[1]) for k, v in result.timings.items()}
                print_phase_timings(file_path, sec_timings, total_sec)
            if result.has_errors or not result.complete:
                had_errors = True
        if had_errors:
            sys.exit(1)
        print(f"{Colors.GREEN}Check passed without errors for {len(args.files)} file(s).{Colors.RESET} ({time.time() - start_time:.3f}s)")
        sys.exit(0)

    if args.command == "suggest":
        from src.patch_model import UnifiedDiffRenderer
        had_errors = False
        total_patches_count = 0
        for file_path in args.files:
            result = analyze_translation_unit(
                file_path,
                enable_suggestions=True,
                warn_as_error=warn_as_error,
            )
            src_content = result.original_sources.get(result.entry_file, "")
            file_patches = [
                p for p in result.candidate_patches
                if same_file(p.file_path, file_path)
            ]
            if file_patches:
                total_patches_count += len(file_patches)
                print(f"\n{Colors.BOLD}{Colors.CYAN}Found {len(file_patches)} proposed repair(s) for {file_path}:{Colors.RESET}\n")
                for idx, p in enumerate(file_patches, 1):
                    print(UnifiedDiffRenderer.render_summary_card(p, idx, len(file_patches), src_content, color=True))

            render_diagnostics(result.diagnostics, result.display_names)
            if verbose:
                total_sec = sum(d for d, _ in result.timings.values()) / 1000.0
                sec_timings = {k: (v[0] / 1000.0, v[1]) for k, v in result.timings.items()}
                print_phase_timings(file_path, sec_timings, total_sec)

            if result.has_errors or not result.complete:
                had_errors = True
        if had_errors:
            sys.exit(1)
        if total_patches_count == 0:
            print(f"{Colors.CYAN}No unhandled errors or suggestions for {len(args.files)} file(s).{Colors.RESET}")
        sys.exit(0)

    if args.command == "fix":
        in_place = getattr(args, "in_place", False)
        interactive = getattr(args, "interactive", None)
        backup = getattr(args, "backup", False)

        if interactive:
            from src.tui_wizard import PatchReviewWizard
            wizard = PatchReviewWizard(
                files=args.files,
                backup=backup,
                verbose=verbose,
                allowed_write_files={canonical_path(f) for f in args.files},
            )
            success = wizard.run()
            sys.exit(0 if success else 1)

        from src.atomic_writer import atomic_write
        from src.repair_coordinator import repair_source
        had_failure = False
        for file_path in args.files:
            try:
                with open(file_path, "r", encoding="utf-8") as source_file:
                    original_source = source_file.read()
            except OSError as exc:
                print(f"{Colors.RED}[fix] Cannot read {file_path}: {exc}.{Colors.RESET}")
                had_failure = True
                continue

            repair = repair_source(
                file_path,
                original_source,
                confidence_policy="all",
                max_rounds=5,
                warn_as_error=warn_as_error,
                excluded_codes=("W002", "W003", "W006"),
            )
            repaired_source = repair.updated_source
            if not repair.success:
                render_diagnostics(repair.initial_analysis.diagnostics, repair.initial_analysis.display_names)
                print(f"{Colors.RED}[fix] Repair failed for {file_path}: {repair.message}. Refusing to write.{Colors.RESET}")
                had_failure = True
                continue

            if in_place:
                if repaired_source != original_source:
                    atomic_write(file_path, repaired_source, backup=backup)
                    backup_msg = f" (backup created at {file_path}.bak)" if backup else ""
                    print(f"{Colors.GREEN}Successfully applied repairs to {file_path}{backup_msg}.{Colors.RESET}")
                else:
                    print(f"{Colors.CYAN}[fix] No applicable repairs for {file_path}. File left untouched.{Colors.RESET}")
            else:
                print(repaired_source)
            if repair.status == "partial":
                print(f"{Colors.YELLOW}[fix] Partial repair: {repair.message}.{Colors.RESET}")
        sys.exit(1 if had_failure else 0)


if __name__ == "__main__":
    main()
