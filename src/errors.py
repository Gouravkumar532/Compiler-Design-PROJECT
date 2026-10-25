import sys
from typing import Iterable, Optional, List
from src.error_catalogue import ERROR_CATALOGUE

class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'

def levenshtein_distance(s1: str, s2: str) -> int:
    """Compute the Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]

def find_closest_match(target: str, candidates: Iterable[str], max_dist: int = 3) -> Optional[str]:
    """Find the candidate string with the smallest edit distance to target."""
    best_candidate = None
    best_dist = max_dist + 1
    for candidate in candidates:
        if candidate == target:
            continue
        dist = levenshtein_distance(target.lower(), candidate.lower())
        if dist < best_dist:
            best_dist = dist
            best_candidate = candidate
    return best_candidate if best_dist <= max_dist else None

def report_error(
    filename: str,
    source: str,
    line: int,
    col: int,
    msg: str,
    code: str = "E001",
    help_text: Optional[str] = None,
    length: int = 1,
    exit_immediately: bool = False
):
    """Prints a beautiful Rust-like error card with line snippet, caret underline, and optional suggestion."""
    print(f"\n{Colors.BOLD}{Colors.RED}error[{code}]{Colors.RESET}: {Colors.BOLD}{msg}{Colors.RESET}")
    print(f"  {Colors.CYAN}-->{Colors.RESET} {filename}:{line}:{col}")
    
    lines = source.splitlines()
    if 0 <= line - 1 < len(lines):
        line_text = lines[line - 1]
        line_num_str = str(line)
        margin = " " * len(line_num_str)
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")
        print(f" {Colors.CYAN}{line_num_str} |{Colors.RESET} {line_text}")
        
        caret_indent = " " * (col - 1)
        underline_len = max(1, length)
        underline = "^" * underline_len
        print(f" {Colors.CYAN}{margin} |{Colors.RESET} {caret_indent}{Colors.BOLD}{Colors.RED}{underline}{Colors.RESET}")
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")

    if help_text:
        print(f"  {Colors.BOLD}{Colors.GREEN}help:{Colors.RESET} {help_text}")
    print()
    if exit_immediately:
        sys.exit(1)

def report_warning(
    filename: str,
    source: str,
    line: int,
    col: int,
    msg: str,
    code: str = "W001",
    help_text: Optional[str] = None,
    length: int = 1
):
    """Prints a formatted warning message with snippet and suggestion."""
    print(f"\n{Colors.BOLD}{Colors.YELLOW}warning[{code}]{Colors.RESET}: {Colors.BOLD}{msg}{Colors.RESET}")
    print(f"  {Colors.CYAN}-->{Colors.RESET} {filename}:{line}:{col}")
    
    lines = source.splitlines()
    if 0 <= line - 1 < len(lines):
        line_text = lines[line - 1]
        line_num_str = str(line)
        margin = " " * len(line_num_str)
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")
        print(f" {Colors.CYAN}{line_num_str} |{Colors.RESET} {line_text}")
        
        caret_indent = " " * (col - 1)
        underline_len = max(1, length)
        underline = "^" * underline_len
        print(f" {Colors.CYAN}{margin} |{Colors.RESET} {caret_indent}{Colors.BOLD}{Colors.YELLOW}{underline}{Colors.RESET}")
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")

    if help_text:
        print(f"  {Colors.BOLD}{Colors.CYAN}help:{Colors.RESET} {help_text}")
    print()

def format_diff(original: str, repaired: str) -> str:
    """Highlight differences between original and repaired expression."""
    import difflib
    matcher = difflib.SequenceMatcher(None, original, repaired)
    parts = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            parts.append(repaired[j1:j2])
        elif tag == 'insert':
            parts.append(f"{Colors.GREEN}{Colors.BOLD}{repaired[j1:j2]}{Colors.RESET}")
        elif tag == 'delete':
            pass
        elif tag == 'replace':
            parts.append(f"{Colors.GREEN}{Colors.BOLD}{repaired[j1:j2]}{Colors.RESET}")
    return "".join(parts)

def report_malformed_expression(
    filename: str,
    source: str,
    line: int,
    col: int,
    original_expr: str,
    suggestion: str,
    explanations: List[str],
    code: str = "P002",
    length: Optional[int] = None,
):
    """Prints a Rust-like diagnostic card for a malformed expression with repair hints."""
    print(f"\n{Colors.BOLD}{Colors.RED}error[{code}]{Colors.RESET}: {Colors.BOLD}malformed expression '{original_expr}'{Colors.RESET}")
    print(f"  {Colors.CYAN}-->{Colors.RESET} {filename}:{line}:{col}")
    
    lines = source.splitlines()
    if 0 <= line - 1 < len(lines):
        line_text = lines[line - 1]
        line_num_str = str(line)
        margin = " " * len(line_num_str)
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")
        print(f" {Colors.CYAN}{line_num_str} |{Colors.RESET} {line_text}")
        
        caret_indent = " " * max(0, col - 1)
        underline_len = length if length is not None else max(1, len(original_expr))
        underline = "^" * underline_len
        print(f" {Colors.CYAN}{margin} |{Colors.RESET} {caret_indent}{Colors.BOLD}{Colors.RED}{underline}{Colors.RESET}")
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")

    print(f"  {Colors.BOLD}{Colors.GREEN}help:{Colors.RESET} did you mean '{Colors.BOLD}{Colors.GREEN}{suggestion}{Colors.RESET}'?")
    for exp in explanations:
        print(f"        - {exp}")
    print()

def report_cross_language_anti_pattern(
    filename: str,
    source: str,
    line: int,
    col: int,
    alien_syntax: str,
    suggestion: str,
    explanations: List[str],
    code: str = "P005",
    length: Optional[int] = None,
):
    """Prints a Rust-like diagnostic card for cross-language syntax / anti-pattern."""
    print(f"\n{Colors.BOLD}{Colors.RED}error[{code}]{Colors.RESET}: {Colors.BOLD}cross-language syntax '{alien_syntax}' is not valid in C++{Colors.RESET}")
    print(f"  {Colors.CYAN}-->{Colors.RESET} {filename}:{line}:{col}")
    
    lines = source.splitlines()
    if 0 <= line - 1 < len(lines):
        line_text = lines[line - 1]
        line_num_str = str(line)
        margin = " " * len(line_num_str)
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")
        print(f" {Colors.CYAN}{line_num_str} |{Colors.RESET} {line_text}")
        
        caret_indent = " " * max(0, col - 1)
        underline_len = length if length is not None else max(1, len(alien_syntax))
        underline = "^" * underline_len
        print(f" {Colors.CYAN}{margin} |{Colors.RESET} {caret_indent}{Colors.BOLD}{Colors.RED}{underline}{Colors.RESET}")
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")

    print(f"  {Colors.BOLD}{Colors.GREEN}help:{Colors.RESET} did you mean '{Colors.BOLD}{Colors.GREEN}{suggestion}{Colors.RESET}'?")
    for exp in explanations:
        print(f"        - {exp}")
    print()


def report_missing_semicolon(
    filename: str,
    source: str,
    line: int,
    col: int,
    context: str = "statement",
    code: str = "P003",
    length: int = 1,
):
    """Prints a Rust-like diagnostic card for a missing semicolon with repair indicator."""
    print(f"\n{Colors.BOLD}{Colors.RED}error[{code}]{Colors.RESET}: {Colors.BOLD}missing semicolon ';' after {context}{Colors.RESET}")
    print(f"  {Colors.CYAN}-->{Colors.RESET} {filename}:{line}:{col}")
    
    lines = source.splitlines()
    if 0 <= line - 1 < len(lines):
        line_text = lines[line - 1]
        line_num_str = str(line)
        margin = " " * len(line_num_str)
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")
        print(f" {Colors.CYAN}{line_num_str} |{Colors.RESET} {line_text}")
        
        caret_indent = " " * max(0, col - 1)
        print(f" {Colors.CYAN}{margin} |{Colors.RESET} {caret_indent}{Colors.BOLD}{Colors.GREEN}+{Colors.RESET}{Colors.BOLD}{Colors.RED}^{Colors.RESET}")
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")

    print(f"  {Colors.BOLD}{Colors.GREEN}help:{Colors.RESET} insert ';' here\n")

def report_unbalanced_delimiter(
    filename: str,
    source: str,
    line: int,
    col: int,
    msg: str,
    suggestion: str,
    code: str = "P004",
    length: int = 1,
):
    """Prints a Rust-like diagnostic card for an unbalanced delimiter."""
    print(f"\n{Colors.BOLD}{Colors.RED}error[{code}]{Colors.RESET}: {Colors.BOLD}{msg}{Colors.RESET}")
    print(f"  {Colors.CYAN}-->{Colors.RESET} {filename}:{line}:{col}")
    
    lines = source.splitlines()
    if 0 <= line - 1 < len(lines):
        line_text = lines[line - 1]
        line_num_str = str(line)
        margin = " " * len(line_num_str)
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")
        print(f" {Colors.CYAN}{line_num_str} |{Colors.RESET} {line_text}")
        
        caret_indent = " " * max(0, col - 1)
        underline = "^" * max(1, length)
        print(f" {Colors.CYAN}{margin} |{Colors.RESET} {caret_indent}{Colors.BOLD}{Colors.RED}{underline}{Colors.RESET}")
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")

    print(f"  {Colors.BOLD}{Colors.GREEN}help:{Colors.RESET} {suggestion}\n")

def report_missing_header(
    filename: str,
    source: str,
    line: int,
    col: int,
    symbol: str,
    header: str,
    insertion_line: int = 1,
    code: str = "E015",
    length: Optional[int] = None,
    exit_immediately: bool = False,
):
    """Prints a Rust-like diagnostic card for a missing standard library header with quick-fix action."""
    print(f"\n{Colors.BOLD}{Colors.RED}error[{code}]{Colors.RESET}: {Colors.BOLD}use of undeclared identifier '{symbol}'{Colors.RESET}")
    print(f"  {Colors.CYAN}-->{Colors.RESET} {filename}:{line}:{col}")

    lines = source.splitlines()
    if 0 <= line - 1 < len(lines):
        line_text = lines[line - 1]
        line_num_str = str(line)
        margin = " " * len(line_num_str)
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")
        print(f" {Colors.CYAN}{line_num_str} |{Colors.RESET} {line_text}")

        caret_indent = " " * max(0, col - 1)
        underline_len = length if length is not None else max(1, len(symbol))
        underline = "^" * underline_len
        print(f" {Colors.CYAN}{margin} |{Colors.RESET} {caret_indent}{Colors.BOLD}{Colors.RED}{underline}{Colors.RESET}")
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")

    print(f"  {Colors.BOLD}{Colors.GREEN}help:{Colors.RESET} '{symbol}' is defined in header '<{header}>'")
    print(f"  {Colors.BOLD}{Colors.CYAN}action:{Colors.RESET} add '#include <{header}>' at line {insertion_line}\n")
    if exit_immediately:
        sys.exit(1)

def report_unqualified_namespace(
    filename: str,
    source: str,
    line: int,
    col: int,
    symbol: str,
    namespace: str,
    code: str = "E016",
    length: Optional[int] = None,
    exit_immediately: bool = False,
    directive_line: int = 1,
    directive_text: Optional[str] = None,
    other_namespaces: Optional[List[str]] = None,
):
    """Prints a Rust-like diagnostic card for an unqualified namespace symbol with dual fix choices."""
    qualified = f"{namespace}::{symbol}"
    print(f"\n{Colors.BOLD}{Colors.RED}error[{code}]{Colors.RESET}: {Colors.BOLD}'{symbol}' was not declared in this scope; did you mean '{qualified}'?{Colors.RESET}")
    print(f"  {Colors.CYAN}-->{Colors.RESET} {filename}:{line}:{col}")

    lines = source.splitlines()
    if 0 <= line - 1 < len(lines):
        line_text = lines[line - 1]
        line_num_str = str(line)
        margin = " " * len(line_num_str)
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")
        print(f" {Colors.CYAN}{line_num_str} |{Colors.RESET} {line_text}")

        caret_indent = " " * max(0, col - 1)
        underline_len = length if length is not None else max(1, len(symbol))
        underline = "^" * underline_len
        print(f" {Colors.CYAN}{margin} |{Colors.RESET} {caret_indent}{Colors.BOLD}{Colors.RED}{underline}{Colors.RESET}")
        print(f" {Colors.CYAN}{margin} |{Colors.RESET}")

    note_text = f"'{symbol}' is defined in namespace '{namespace}'"
    if other_namespaces:
        others_str = ", ".join(f"'{ns}'" for ns in other_namespaces)
        note_text += f" (also found in {others_str})"
    print(f"  {Colors.BOLD}{Colors.CYAN}note:{Colors.RESET} {note_text}")

    fix_b = directive_text or (f"using namespace {namespace};" if namespace == "std" else f"using {namespace}::{symbol};")
    print(f"  {Colors.BOLD}{Colors.GREEN}help:{Colors.RESET} fix this error by choosing one of the following:")
    print(f"        [Option 1] Qualify symbol directly:")
    print(f"                   {Colors.BOLD}{Colors.GREEN}{qualified}{Colors.RESET}")
    print(f"        [Option 2] Add directive at line {directive_line}:")
    print(f"                   {Colors.BOLD}{Colors.GREEN}{fix_b}{Colors.RESET}\n")
    if exit_immediately:
        sys.exit(1)

def explain_error(code: str):
    """Explains a compiler error code with detailed description and examples."""
    code_upper = code.upper()
    if code_upper not in ERROR_CATALOGUE:
        print(f"{Colors.RED}Unknown error code '{code}'.{Colors.RESET}")
        list_error_codes()
        return

    info = ERROR_CATALOGUE[code_upper]
    is_warning = code_upper.startswith("W")
    badge_color = Colors.YELLOW if is_warning else Colors.RED

    print(f"\n{Colors.BOLD}{badge_color}=== {code_upper}: {info['title']} ==={Colors.RESET}\n")
    print(f"{Colors.BOLD}Description:{Colors.RESET}")
    print(f"  {info['description']}\n")
    print(f"{Colors.BOLD}Common Cause:{Colors.RESET}")
    print(f"  {info['cause']}\n")
    
    print(f"{Colors.BOLD}{Colors.RED}Erroneous Code Example:{Colors.RESET}")
    for line in info['example_bad'].splitlines():
        print(f"  {Colors.DIM}|{Colors.RESET} {line}")
    print()

    print(f"{Colors.BOLD}{Colors.GREEN}Recommended Fix:{Colors.RESET}")
    for line in info['example_good'].splitlines():
        print(f"  {Colors.DIM}|{Colors.RESET} {line}")
    print()

def list_error_codes():
    """Lists all available error codes and their titles."""
    print(f"\n{Colors.BOLD}Available Compiler Error & Warning Codes:{Colors.RESET}")
    print("--------------------------------------------------")
    for code, info in sorted(ERROR_CATALOGUE.items()):
        color = Colors.YELLOW if code.startswith("W") else Colors.RED
        print(f"  {color}{code:<6}{Colors.RESET} {info['title']}")
    print("--------------------------------------------------")
    print(f"Run {Colors.CYAN}python main.py explain <code>{Colors.RESET} for full details on any code.\n")
