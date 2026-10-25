"""
Auto-Include & Missing Header Recommendation Engine (Idea 4)

Intercepts unresolved standard library identifiers and types, queries the
StdlibRegistry, and generates optimal automated '#include <header>' insertion
patches. Provides Rust-like diagnostic cards (E015) and automated repair capabilities.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
import re

from src.stdlib_registry import registry, StdlibRegistry
from src.errors import report_missing_header


@dataclass
class MissingHeaderDiagnostic:
    """Represents a detected missing header error with placement and suggestion information."""
    symbol: str
    header: str
    line: int
    col: int
    length: int
    insertion_line: int
    suggested_include: str
    file: Optional[str] = None
    macro_generated: bool = False

    @property
    def action_text(self) -> str:
        return f"add '{self.suggested_include}' at line {self.insertion_line}"


def restore_preprocessor_includes(source: str) -> str:
    """
    Restores preprocessor runtime comments back into standard '#include <header>' directives.
    Useful when saving repaired preprocessed code back to disk.
    """
    return re.sub(
        r'//\s*Standard header\s*<([^>]+)>\s*provided by compiler runtime',
        r'#include <\1>',
        source,
    )


class AutoIncludeEngine:
    """
    Analyzes source code for missing standard library headers,
    computes safe and clean insertion positions, and applies repairs.
    """

    def __init__(
        self,
        source: str,
        filename: str = "<stdin>",
        enable_repair: bool = True,
        stdlib_reg: Optional[StdlibRegistry] = None,
    ):
        self.source = source
        self.filename = filename
        self.enable_repair = enable_repair
        self.registry = stdlib_reg or registry
        self.diagnostics: List[MissingHeaderDiagnostic] = []
        self._reported_keys: Set[Tuple[str, str, str, int, int]] = set()

    @staticmethod
    def scan_included_headers(source: str) -> Set[str]:
        """
        Scans source code for all included header filenames, supporting:
          - Angle bracket includes: #include <header>
          - Quoted includes: #include "header"
          - Preprocessor runtime comments: // Standard header <header> provided by compiler runtime
        """
        headers: Set[str] = set()
        for line in source.splitlines():
            line_str = line.strip()
            # Standard angle bracket
            m = re.match(r'#include\s*<([^>]+)>', line_str)
            if m:
                headers.add(m.group(1).strip())
                continue
            # Quoted
            m = re.match(r'#include\s*["\']([^"\']+)["\']', line_str)
            if m:
                headers.add(m.group(1).strip())
                continue
            # Compiler runtime comment produced by Preprocessor
            m = re.match(r'//\s*Standard header\s*<([^>]+)>\s*provided by compiler runtime', line_str)
            if m:
                headers.add(m.group(1).strip())
                continue
        return headers

    @staticmethod
    def find_insertion_point(source: str) -> int:
        """
        Determines the optimal 1-based line number to insert new '#include' directives.
        Priority:
          1. Immediately after the last existing '#include' directive.
          2. After include guard definitions (#ifndef FOO ... #define FOO).
          3. After '#pragma once'.
          4. After leading comment block (if present).
          5. Line 1.
        """
        lines = source.splitlines()
        if not lines:
            return 1

        last_include_line = -1
        pragma_once_line = -1
        guard_define_line = -1
        saw_guard_ifndef = False

        for idx, line in enumerate(lines):
            stripped = line.strip()

            # Check for #include or preprocessor comment for header
            if stripped.startswith("#include") or stripped.startswith("// Standard header <"):
                last_include_line = idx + 1
                continue

            # Check for #pragma once
            if stripped.startswith("#pragma") and "once" in stripped:
                pragma_once_line = idx + 1
                continue

            # Check for include guards
            if not saw_guard_ifndef and re.match(r'#ifndef\s+[A-Za-z0-9_]+', stripped):
                saw_guard_ifndef = True
                continue
            if saw_guard_ifndef and guard_define_line == -1 and re.match(r'#define\s+[A-Za-z0-9_]+', stripped):
                guard_define_line = idx + 1
                continue

        # 1. After last #include
        if last_include_line != -1:
            return last_include_line + 1

        # 2. After include guard define
        if guard_define_line != -1:
            return guard_define_line + 1

        # 3. After #pragma once
        if pragma_once_line != -1:
            return pragma_once_line + 1

        # 4. After top comment block (e.g. license, file comments)
        idx = 0
        in_multiline_comment = False
        saw_comment = False

        while idx < len(lines):
            stripped = lines[idx].strip()
            if in_multiline_comment:
                saw_comment = True
                if "*/" in stripped:
                    in_multiline_comment = False
                idx += 1
                continue

            if stripped.startswith("/*"):
                saw_comment = True
                if "*/" not in stripped:
                    in_multiline_comment = True
                idx += 1
                continue

            if stripped.startswith("//"):
                saw_comment = True
                idx += 1
                continue

            if not stripped and saw_comment:
                # Blank lines inside or right after header comment
                idx += 1
                continue

            # First non-comment, non-blank line reached
            break

        if saw_comment and idx > 0:
            return idx + 1

        # 5. Default: line 1
        return 1

    def create_diagnostic(
        self,
        symbol: str,
        header: str,
        line: int,
        col: int,
        length: Optional[int] = None,
        file: Optional[str] = None,
        source_override: Optional[str] = None,
        macro_generated: bool = False,
    ) -> MissingHeaderDiagnostic:
        """Constructs a MissingHeaderDiagnostic with accurate placement."""
        target_source = source_override if source_override is not None else self.source
        insertion_line = self.find_insertion_point(target_source)
        suggested_include = f"#include <{header}>"
        return MissingHeaderDiagnostic(
            symbol=symbol,
            header=header,
            line=line,
            col=col,
            length=length or len(symbol),
            insertion_line=insertion_line,
            suggested_include=suggested_include,
            file=file or self.filename,
            macro_generated=macro_generated,
        )

    def report_diagnostic(
        self,
        diag: MissingHeaderDiagnostic,
        exit_immediately: bool = False,
        emit: bool = True,
        filename_override: Optional[str] = None,
        source_override: Optional[str] = None,
    ) -> bool:
        """Records and optionally emits the Rust-like diagnostic card for E015."""
        target_file = filename_override or diag.file or self.filename
        key = (target_file, diag.symbol, diag.header, diag.line, diag.col)
        if key in self._reported_keys:
            return False
        self._reported_keys.add(key)
        self.diagnostics.append(diag)

        if emit:
            report_missing_header(
                filename=target_file,
                source=source_override if source_override is not None else self.source,
                line=diag.line,
                col=diag.col,
                symbol=diag.symbol,
                header=diag.header,
                insertion_line=diag.insertion_line,
                code="E015",
                length=diag.length,
                exit_immediately=exit_immediately,
            )
        return True

    def generate_patch(self, source: str, missing_headers: List[str]) -> str:
        """
        Inserts '#include <header>' directives for all missing_headers into source.
        Ensures idempotency (never duplicates already-included headers) and clean formatting.
        """
        if not missing_headers:
            return source

        current_includes = self.scan_included_headers(source)
        # Deduplicate missing headers while preserving discovery order
        headers_to_add: List[str] = []
        for h in missing_headers:
            clean_h = h.strip().strip("<>\"'")
            if not self.registry.is_header_included(clean_h, current_includes):
                if clean_h not in headers_to_add:
                    headers_to_add.append(clean_h)

        if not headers_to_add:
            return source

        insertion_line = self.find_insertion_point(source)
        lines = source.splitlines()

        # Build insertion text
        include_lines = [f"#include <{h}>" for h in headers_to_add]

        # Determine if we should add blank lines for separation
        insert_idx = min(max(0, insertion_line - 1), len(lines))

        # Check surroundings
        prev_is_include = False
        if insert_idx > 0 and 0 <= insert_idx - 1 < len(lines):
            prev_line = lines[insert_idx - 1].strip()
            if prev_line.startswith("#include") or prev_line.startswith("// Standard header <"):
                prev_is_include = True

        next_has_content = False
        if insert_idx < len(lines):
            next_line = lines[insert_idx].strip()
            if next_line and not next_line.startswith("#include"):
                next_has_content = True

        # Assemble new lines
        new_lines = list(lines[:insert_idx])

        # If inserting after comments or pragma and no blank line, we can just insert
        new_lines.extend(include_lines)

        if next_has_content:
            new_lines.append("")

        new_lines.extend(lines[insert_idx:])

        # Preserve trailing newline if original had one
        res = "\n".join(new_lines)
        if source.endswith("\n") and not res.endswith("\n"):
            res += "\n"
        return res
