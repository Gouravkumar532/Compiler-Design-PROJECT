"""
Comprehensive Standard Library Symbol Registry (Idea 4)

Maps standard C/C++ library identifiers, types, functions, and objects to
their required headers. Provides lookup mechanisms for both qualified (e.g.
'std::cout') and unqualified (e.g. 'cout') forms, and resolves equivalent
C and C++ header names (e.g. <cmath> and <math.h>).
"""

from typing import Dict, List, Optional, Set, Tuple


# Primary mapping of standard library headers to the symbols they define.
STDLIB_HEADER_SYMBOLS: Dict[str, List[str]] = {
    "iostream": [
        "cout", "cin", "cerr", "clog", "endl",
        "istream", "ostream", "iostream",
        "wcout", "wcin", "wcerr", "wclog",
        "wistream", "wostream", "wiostream",
        "ws",
    ],
    "string": [
        "string", "wstring", "u16string", "u32string",
        "to_string", "to_wstring",
        "stoi", "stol", "stoll", "stoul", "stoull",
        "stof", "stod", "stold",
        "getline",
    ],
    "vector": [
        "vector",
    ],
    "cmath": [
        "sqrt", "pow", "abs", "fabs", "sin", "cos", "tan",
        "asin", "acos", "atan", "atan2",
        "sinh", "cosh", "tanh",
        "floor", "ceil", "round", "trunc",
        "log", "log10", "log2", "exp", "exp2",
        "hypot", "fmod", "remainder", "cbrt",
        "isinf", "isnan", "isfinite",
    ],
    "cstdio": [
        "printf", "scanf", "sprintf", "snprintf", "fprintf", "fscanf",
        "fopen", "fclose", "fread", "fwrite", "fseek", "ftell", "rewind",
        "FILE", "fputs", "fgets", "puts", "gets", "getchar", "putchar",
        "perror", "fflush", "sscanf", "stdout", "stdin", "stderr",
        "EOF", "remove", "rename", "tmpfile",
    ],
    "cstdlib": [
        "malloc", "free", "calloc", "realloc",
        "exit", "abort", "atexit", "quick_exit",
        "rand", "srand", "RAND_MAX",
        "atoi", "atol", "atoll", "atof", "strtol", "strtod",
        "system", "getenv", "qsort", "bsearch",
        "div", "ldiv", "lldiv",
    ],
    "algorithm": [
        "sort", "stable_sort", "reverse", "max", "min", "minmax",
        "min_element", "max_element", "minmax_element",
        "find", "find_if", "find_if_not", "count", "count_if",
        "fill", "copy", "copy_if", "transform", "replace", "replace_if",
        "binary_search", "lower_bound", "upper_bound", "equal_range",
        "unique", "all_of", "any_of", "none_of",
        "for_each", "generate", "remove", "remove_if",
        "rotate", "shuffle", "clamp",
    ],
    "numeric": [
        "accumulate", "iota", "inner_product", "adjacent_difference",
        "partial_sum", "reduce", "midpoint", "gcd", "lcm",
    ],
    "map": [
        "map", "multimap",
    ],
    "unordered_map": [
        "unordered_map", "unordered_multimap",
    ],
    "set": [
        "set", "multiset",
    ],
    "unordered_set": [
        "unordered_set", "unordered_multiset",
    ],
    "memory": [
        "unique_ptr", "shared_ptr", "weak_ptr",
        "make_unique", "make_shared",
        "allocator", "addressof",
    ],
    "fstream": [
        "ifstream", "ofstream", "fstream",
        "wifstream", "wofstream", "wfstream",
    ],
    "sstream": [
        "stringstream", "istringstream", "ostringstream",
        "wstringstream", "wistringstream", "wostringstream",
    ],
    "iomanip": [
        "setw", "setprecision", "setfill",
        "fixed", "scientific", "showpoint", "noshowpoint",
        "left", "right", "internal",
        "hex", "dec", "oct", "quoted",
    ],
    "utility": [
        "pair", "make_pair", "move", "forward", "swap", "declval",
    ],
    "queue": [
        "queue", "priority_queue",
    ],
    "stack": [
        "stack",
    ],
    "deque": [
        "deque",
    ],
    "list": [
        "list", "forward_list",
    ],
    "cassert": [
        "assert",
    ],
    "cstring": [
        "strlen", "strcpy", "strncpy", "strcmp", "strncmp",
        "strcat", "strncat", "memcpy", "memset", "memmove", "memcmp",
        "strchr", "strrchr", "strstr", "strtok", "strerror",
    ],
    "cctype": [
        "isalpha", "isdigit", "isalnum", "isspace", "isprint",
        "ispunct", "islower", "isupper", "tolower", "toupper",
    ],
    "climits": [
        "INT_MAX", "INT_MIN", "CHAR_BIT", "CHAR_MAX", "CHAR_MIN",
        "SHRT_MAX", "SHRT_MIN", "LONG_MAX", "LONG_MIN",
        "LLONG_MAX", "LLONG_MIN", "UCHAR_MAX", "UINT_MAX",
    ],
    "cstdint": [
        "int8_t", "int16_t", "int32_t", "int64_t",
        "uint8_t", "uint16_t", "uint32_t", "uint64_t",
        "size_t", "intptr_t", "uintptr_t",
    ],
    "chrono": [
        "chrono",
    ],
    "functional": [
        "function", "bind", "reference_wrapper", "ref", "cref",
        "plus", "minus", "multiplies", "divides", "modulus",
        "equal_to", "not_equal_to", "greater", "less",
    ],
    "thread": [
        "thread",
    ],
}

# Equivalent C vs C++ header sets. If any of the equivalent headers is included,
# the requirement is considered satisfied.
EQUIVALENT_HEADERS: Dict[str, Set[str]] = {
    "cmath": {"cmath", "math.h"},
    "math.h": {"cmath", "math.h"},
    "cstdio": {"cstdio", "stdio.h"},
    "stdio.h": {"cstdio", "stdio.h"},
    "cstdlib": {"cstdlib", "stdlib.h"},
    "stdlib.h": {"cstdlib", "stdlib.h"},
    "cstring": {"cstring", "string.h"},
    "string.h": {"cstring", "string.h"},
    "cctype": {"cctype", "ctype.h"},
    "ctype.h": {"cctype", "ctype.h"},
    "cassert": {"cassert", "assert.h"},
    "assert.h": {"cassert", "assert.h"},
    "cstdint": {"cstdint", "stdint.h"},
    "stdint.h": {"cstdint", "stdint.h"},
    "climits": {"climits", "limits.h"},
    "limits.h": {"climits", "limits.h"},
    "cfloat": {"cfloat", "float.h"},
    "float.h": {"cfloat", "float.h"},
    "ctime": {"ctime", "time.h"},
    "time.h": {"ctime", "time.h"},
}

# Build reverse index without discarding legitimate alternative headers.
_SYMBOL_TO_HEADERS: Dict[str, List[str]] = {}
for header, symbols in STDLIB_HEADER_SYMBOLS.items():
    for sym in symbols:
        candidates = _SYMBOL_TO_HEADERS.setdefault(sym, [])
        if header not in candidates:
            candidates.append(header)


class StdlibRegistry:
    """Registry providing fast lookup from identifiers to standard headers."""

    def __init__(self):
        self.symbol_to_headers: Dict[str, List[str]] = {
            symbol: list(headers) for symbol, headers in _SYMBOL_TO_HEADERS.items()
        }
        self.symbol_to_header: Dict[str, str] = {
            symbol: headers[0] for symbol, headers in self.symbol_to_headers.items()
        }
        self.equivalent_headers: Dict[str, Set[str]] = dict(EQUIVALENT_HEADERS)

    def lookup(self, symbol: str) -> Optional[str]:
        """
        Looks up a symbol and returns its standard header name (e.g. 'iostream').
        Handles:
          - Qualified forms: 'std::cout' -> 'iostream'
          - Leading scope: '::std::cout' or '::cout'
          - Template instantiations: 'std::vector<int>' -> 'vector'
          - Unqualified forms: 'cout' -> 'iostream'
        """
        if not symbol:
            return None

        clean = symbol.strip()
        # Strip leading scope
        if clean.startswith("::"):
            clean = clean[2:]

        # Strip template arguments if present: 'vector<int>' -> 'vector'
        if "<" in clean:
            clean = clean.split("<")[0].strip()

        # Handle std:: prefix
        if clean.startswith("std::"):
            clean = clean[5:]

        # Check direct lookup
        if clean in self.symbol_to_header:
            return self.symbol_to_header[clean]

        return None

    def lookup_candidates(self, symbol: str) -> List[str]:
        """Return every registered header candidate for a normalized symbol."""
        if not symbol:
            return []
        clean = symbol.strip()
        if clean.startswith("::"):
            clean = clean[2:]
        if "<" in clean:
            clean = clean.split("<", 1)[0].strip()
        if clean.startswith("std::"):
            clean = clean[5:]
        return list(self.symbol_to_headers.get(clean, []))

    def get_equivalent_headers(self, header: str) -> Set[str]:
        """Returns all equivalent header names for a given header (e.g. cmath <-> math.h)."""
        clean = header.strip().strip("<>\"'")
        return self.equivalent_headers.get(clean, {clean})

    def is_header_included(self, header: str, included_headers: Set[str]) -> bool:
        """
        Determines if the given header or any of its C equivalents is present
        in the set of already-included headers.
        """
        clean = header.strip().strip("<>\"'")
        equivs = self.get_equivalent_headers(clean)
        clean_included = {h.strip().strip("<>\"'") for h in included_headers}
        return bool(equivs.intersection(clean_included))

    def all_symbols(self) -> List[str]:
        """Returns all registered standard library symbols."""
        return list(self.symbol_to_header.keys())


# Singleton instance for convenience across compiler modules
registry = StdlibRegistry()
