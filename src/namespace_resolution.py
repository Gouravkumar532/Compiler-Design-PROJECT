"""
Intelligent Namespace Resolution & Scope Qualification Engine (Idea 5)

Intercepts unresolved identifiers, functions, and types that exist within inactive
namespaces (such as 'std' or user-defined namespaces). Provides Rust-like diagnostic
cards (E016) and dual automated repair options:
  - Option A: Explicit qualification (e.g., 'std::cout', 'Geometry::area')
  - Option B: Using directive/declaration (e.g., 'using namespace std;', 'using Geometry::area;')
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple
import re

from src.stdlib_registry import registry, StdlibRegistry
from src.auto_include import AutoIncludeEngine
from src.errors import report_unqualified_namespace


@dataclass
class UnqualifiedNamespaceDiagnostic:
    """Represents a detected unqualified namespace symbol error."""
    symbol: str
    namespace: str
    line: int
    col: int
    length: int
    kind: str = "identifier"  # "identifier", "function", "type"
    fix_option_a: str = ""
    fix_option_b: str = ""
    insertion_line: int = 1
    file: Optional[str] = None
    macro_generated: bool = False

    def __post_init__(self):
        if not self.fix_option_a:
            self.fix_option_a = f"{self.namespace}::{self.symbol}"
        if not self.fix_option_b:
            if self.namespace == "std":
                self.fix_option_b = "using namespace std;"
            else:
                self.fix_option_b = f"using {self.namespace}::{self.symbol};"


class NamespaceResolutionEngine:
    """
    Maintains an index of symbols grouped by their enclosing namespaces,
    detects unqualified symbols during semantic analysis, and generates
    dual qualification or directive patches.
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

        # Maps namespace name -> set of symbols declared in that namespace
        self.namespace_symbol_index: Dict[str, Set[str]] = {}
        # User defined namespaces in order of appearance
        self.user_namespaces: List[str] = []
        # Diagnostics collected during analysis
        self.diagnostics: List[UnqualifiedNamespaceDiagnostic] = []
        self._reported_keys: Set[Tuple[str, str, str, int, int]] = set()

        # Initialize std namespace from registry
        self._init_std_namespace()

    def _init_std_namespace(self):
        """Indexes all standard library symbols under the 'std' namespace."""
        self.namespace_symbol_index["std"] = set(self.registry.all_symbols())

    def register_user_namespace(self, name: str):
        """Registers a user-defined namespace."""
        if name not in self.namespace_symbol_index:
            self.namespace_symbol_index[name] = set()
            self.user_namespaces.append(name)

    def register_symbol(self, namespace: str, symbol: str):
        """Registers a symbol under the given namespace."""
        if namespace not in self.namespace_symbol_index:
            self.register_user_namespace(namespace)
        self.namespace_symbol_index[namespace].add(symbol)

    def find_candidate_namespaces(
        self,
        symbol: str,
        active_namespaces: Set[str],
        included_headers: Set[str],
    ) -> List[str]:
        """
        Finds inactive namespaces that declare the given symbol.
        Filters out already-active namespaces.
        Rank candidates:
          - If defined in a local user namespace defined earlier in translation unit -> prioritize local user namespace.
          - If defined in 'std' and its required header is included -> prioritized for standard elements.
        """
        clean_sym = symbol.strip()
        if "<" in clean_sym:
            clean_sym = clean_sym.split("<")[0].strip()

        candidates: List[str] = []

        # 1. Check user-defined namespaces first (local scope prioritization)
        for ns in self.user_namespaces:
            if ns in active_namespaces:
                continue
            if clean_sym in self.namespace_symbol_index.get(ns, set()):
                candidates.append(ns)

        # 2. Check std namespace
        if "std" not in active_namespaces:
            if clean_sym in self.namespace_symbol_index.get("std", set()):
                header = self.registry.lookup(clean_sym)
                # Only offer 'std' if the header is included (missing header is handled by E015)
                if header and self.registry.is_header_included(header, included_headers):
                    if "std" not in candidates:
                        candidates.append("std")

        return candidates

    def find_using_insertion_point(self, source: str, namespace: str) -> int:
        """
        Determines the optimal 1-based line number to insert 'using namespace <ns>;'.
        For 'std': after #include directives (using AutoIncludeEngine logic).
        For user namespaces: immediately after the namespace definition block ends,
        or after includes if namespace was defined in an included file.
        """
        lines = source.splitlines()
        if not lines:
            return 1

        if namespace == "std":
            return AutoIncludeEngine.find_insertion_point(source)

        # Search for the closing brace of 'namespace <name> { ... }'
        in_target_ns = False
        brace_depth = 0
        ns_end_line = -1

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not in_target_ns:
                # Check for namespace declaration
                match = re.match(r'namespace\s+' + re.escape(namespace) + r'\b', stripped)
                if match:
                    in_target_ns = True
                    brace_depth += line.count('{') - line.count('}')
                    if brace_depth == 0 and '{' in line and '}' in line:
                        ns_end_line = idx + 1
                        break
            else:
                brace_depth += line.count('{') - line.count('}')
                if brace_depth <= 0:
                    ns_end_line = idx + 1
                    break

        if ns_end_line != -1:
            # Place after closing brace of namespace definition
            return ns_end_line + 1

        # Fallback: after #include or at line 1
        return AutoIncludeEngine.find_insertion_point(source)

    def create_diagnostic(
        self,
        symbol: str,
        namespace: str,
        line: int,
        col: int,
        length: Optional[int] = None,
        kind: str = "identifier",
        file: Optional[str] = None,
        source_override: Optional[str] = None,
        macro_generated: bool = False,
    ) -> UnqualifiedNamespaceDiagnostic:
        """Constructs an UnqualifiedNamespaceDiagnostic with dual fix proposals."""
        target_source = source_override if source_override is not None else self.source
        insertion_line = self.find_using_insertion_point(target_source, namespace)
        fix_a = f"{namespace}::{symbol}"
        if namespace == "std":
            fix_b = "using namespace std;"
        else:
            fix_b = f"using {namespace}::{symbol};"

        return UnqualifiedNamespaceDiagnostic(
            symbol=symbol,
            namespace=namespace,
            line=line,
            col=col,
            length=length or len(symbol),
            kind=kind,
            fix_option_a=fix_a,
            fix_option_b=fix_b,
            insertion_line=insertion_line,
            file=file or self.filename,
            macro_generated=macro_generated,
        )

    def report_diagnostic(
        self,
        diag: UnqualifiedNamespaceDiagnostic,
        exit_immediately: bool = False,
        other_namespaces: Optional[List[str]] = None,
        emit: bool = True,
        filename_override: Optional[str] = None,
        source_override: Optional[str] = None,
    ) -> bool:
        """Records and optionally emits the Rust-like diagnostic card for E016."""
        target_file = filename_override or diag.file or self.filename
        key = (target_file, diag.symbol, diag.namespace, diag.line, diag.col)
        if key in self._reported_keys:
            return False
        self._reported_keys.add(key)
        self.diagnostics.append(diag)

        if emit:
            report_unqualified_namespace(
                filename=target_file,
                source=source_override if source_override is not None else self.source,
                line=diag.line,
                col=diag.col,
                symbol=diag.symbol,
                namespace=diag.namespace,
                code="E016",
                length=diag.length,
                exit_immediately=exit_immediately,
                directive_line=diag.insertion_line,
                directive_text=diag.fix_option_b,
                other_namespaces=other_namespaces,
            )
        return True

    def generate_qualification_patch(
        self,
        source: str,
        diagnostics: List[UnqualifiedNamespaceDiagnostic],
    ) -> str:
        """
        Option A: In-place scope qualification ('namespace::symbol').
        Applies replacements in reverse order (bottom-to-top, right-to-left)
        to prevent column offset shifts.
        """
        if not diagnostics:
            return source

        lines = source.splitlines()
        # Sort descending by line, then descending by column
        sorted_diags = sorted(diagnostics, key=lambda d: (d.line, d.col), reverse=True)

        for diag in sorted_diags:
            line_idx = diag.line - 1
            if 0 <= line_idx < len(lines):
                line_str = lines[line_idx]
                col_idx = diag.col - 1

                # Verify exact token match at col_idx
                if 0 <= col_idx < len(line_str) and line_str[col_idx : col_idx + len(diag.symbol)] == diag.symbol:
                    # Replace in-place
                    lines[line_idx] = (
                        line_str[:col_idx]
                        + f"{diag.namespace}::{diag.symbol}"
                        + line_str[col_idx + len(diag.symbol):]
                    )
                else:
                    # If col is slightly off (e.g. after macro or format), find whole-word occurrence
                    pattern = r'\b' + re.escape(diag.symbol) + r'\b'
                    matches = list(re.finditer(pattern, line_str))
                    if matches:
                        # Find match closest to col_idx
                        closest_m = min(matches, key=lambda m: abs(m.start() - col_idx))
                        lines[line_idx] = (
                            line_str[:closest_m.start()]
                            + f"{diag.namespace}::{diag.symbol}"
                            + line_str[closest_m.end():]
                        )

        result = "\n".join(lines)
        if source.endswith("\n") and not result.endswith("\n"):
            result += "\n"
        return result

    def generate_using_patch(
        self,
        source: str,
        diagnostics: List[UnqualifiedNamespaceDiagnostic],
    ) -> str:
        """
        Option B: Using directive/declaration insertion.
        For 'std': 'using namespace std;'
        For custom symbols: 'using <namespace>::<symbol>;' (or 'using namespace <ns>;')
        """
        if not diagnostics:
            return source

        directives_to_add: List[Tuple[str, str, int]] = []
        seen_directives = set()

        for diag in diagnostics:
            directive = diag.fix_option_b
            if directive not in seen_directives and directive not in source:
                seen_directives.add(directive)
                directives_to_add.append((directive, diag.namespace, diag.insertion_line))

        current_source = source
        for directive, ns, insertion_line in directives_to_add:
            if directive in current_source:
                continue

            insert_line = self.find_using_insertion_point(current_source, ns)
            lines = current_source.splitlines()
            insert_idx = min(max(0, insert_line - 1), len(lines))

            # Check surrounding lines for clean spacing
            next_has_content = False
            if insert_idx < len(lines):
                next_line = lines[insert_idx].strip()
                if next_line and not next_line.startswith("using"):
                    next_has_content = True

            new_lines = list(lines[:insert_idx])
            new_lines.append(directive)
            if next_has_content:
                new_lines.append("")
            new_lines.extend(lines[insert_idx:])

            current_source = "\n".join(new_lines)
            if source.endswith("\n") and not current_source.endswith("\n"):
                current_source += "\n"

        return current_source
