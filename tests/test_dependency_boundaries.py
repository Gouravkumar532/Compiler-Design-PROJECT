"""Architecture guards for active-versus-archived code boundaries."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ACTIVE_PYTHON_FILES = [REPOSITORY_ROOT / "main.py"] + sorted(
    path
    for root_name in ("src", "tests")
    for path in (REPOSITORY_ROOT / root_name).rglob("*.py")
    if "__pycache__" not in path.parts
)
PRODUCTION_PYTHON_FILES = [REPOSITORY_ROOT / "main.py"] + sorted(
    (REPOSITORY_ROOT / "src").rglob("*.py")
)


class TestDependencyBoundaries(unittest.TestCase):
    def test_active_python_never_imports_archive(self):
        violations = []
        for path in ACTIVE_PYTHON_FILES:
            if path == Path(__file__).resolve():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                else:
                    continue
                for module in modules:
                    if module == "archive" or module.startswith("archive."):
                        violations.append(f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno} -> {module}")
        self.assertEqual(violations, [], "active code imports archived code: " + ", ".join(violations))

    def test_active_python_never_loads_archive_by_path(self):
        violations = []
        for path in ACTIVE_PYTHON_FILES:
            if path == Path(__file__).resolve():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                normalized = node.value.replace("\\", "/").lower()
                if normalized.startswith("archive/") or "/archive/" in normalized:
                    violations.append(f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}")
        self.assertEqual(violations, [], "active code loads archived paths: " + ", ".join(violations))

    def test_semantic_analysis_does_not_apply_repairs(self):
        semantic_path = REPOSITORY_ROOT / "src" / "semantic.py"
        tree = ast.parse(semantic_path.read_text(encoding="utf-8"), filename=str(semantic_path))
        calls = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "apply_repairs"
        ]
        self.assertEqual(calls, [], "semantic analysis must only generate repair candidates")

    def test_main_has_no_parallel_low_level_fix_pipeline(self):
        main_path = REPOSITORY_ROOT / "main.py"
        tree = ast.parse(main_path.read_text(encoding="utf-8"), filename=str(main_path))
        forbidden = {"src.lexer", "src.parser", "src.preprocessor", "src.semantic"}
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        self.assertFalse(
            imports & forbidden,
            "main.py must use the canonical analyzer/coordinator instead of rebuilding the pipeline",
        )

    def test_removed_legacy_repair_apis_do_not_return(self):
        forbidden_functions = {
            "analyze_source",
            "apply_repairs",
            "confirm_suggestion",
            "insert_line_before",
            "insert_text_at",
            "speculative_verify",
        }
        violations = []
        for path in PRODUCTION_PYTHON_FILES:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in forbidden_functions:
                    violations.append(
                        f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno} -> {node.name}"
                    )
        self.assertEqual(violations, [], "legacy repair APIs returned: " + ", ".join(violations))

    def test_parser_constructor_has_no_mutation_controls(self):
        parser_path = REPOSITORY_ROOT / "src" / "parser.py"
        tree = ast.parse(parser_path.read_text(encoding="utf-8"), filename=str(parser_path))
        parser_class = next(
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Parser"
        )
        constructor = next(
            node for node in parser_class.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        argument_names = {arg.arg for arg in constructor.args.args + constructor.args.kwonlyargs}
        self.assertFalse(
            argument_names & {"auto_fix", "interactive", "write_in_place", "allowed_write_files"},
            "Parser must recover in memory; mutation controls belong to the repair coordinator/TUI",
        )


if __name__ == "__main__":
    unittest.main()
