from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional

class TokenType(Enum):
    # Keywords
    INT = auto()
    FLOAT = auto()
    DOUBLE = auto()
    VOID = auto()
    IF = auto()
    ELSE = auto()
    WHILE = auto()
    FOR = auto()
    RETURN = auto()
    CHAR = auto()
    SIZEOF = auto()
    DO = auto()
    BREAK = auto()
    CONTINUE = auto()
    SWITCH = auto()
    CASE = auto()
    DEFAULT = auto()
    STRUCT = auto()
    ENUM = auto()
    CLASS = auto()
    PUBLIC = auto()
    PRIVATE = auto()
    PROTECTED = auto()
    THIS = auto()
    NEW = auto()
    DELETE = auto()
    BOOL = auto()
    TRUE = auto()
    FALSE = auto()
    CONST = auto()
    OPERATOR = auto()
    NAMESPACE = auto()
    USING = auto()
    VIRTUAL = auto()
    OVERRIDE = auto()
    TEMPLATE = auto()
    TYPENAME = auto()
    TRY = auto()
    CATCH = auto()
    THROW = auto()
    AUTO = auto()
    CONSTEXPR = auto()

    # Alien / Cross-Language Keywords (Idea 3)
    DEF = auto()              # Python 'def'
    ELIF = auto()             # Python 'elif'
    PASS = auto()             # Python 'pass'
    NONE = auto()             # Python 'None'
    NULL_LIT = auto()         # Java/JS 'null'
    TRUE_LIT = auto()         # Python 'True'
    FALSE_LIT = auto()        # Python 'False'
    IN = auto()               # Python 'in'
    RANGE = auto()            # Python 'range'
    IS = auto()               # Python 'is'
    BOOLEAN_TYPE = auto()     # Java/JS 'boolean'
    STRING_JAVA_TYPE = auto() # Java 'String'
    AND_KEYWORD = auto()      # Python 'and'
    OR_KEYWORD = auto()       # Python 'or'
    NOT_KEYWORD = auto()      # Python 'not'
    PRINT_STMT = auto()       # Python 'print'
    SYSTEM_OUT = auto()       # Java 'System.out'

    # Identifiers and Literals
    IDENTIFIER = auto()
    INT_LIT = auto()
    FLOAT_LIT = auto()
    STRING_LIT = auto()
    CHAR_LIT = auto()

    # Operators
    PLUS = auto()      # +
    MINUS = auto()     # -
    STAR = auto()      # *
    SLASH = auto()     # /
    MOD = auto()       # %
    INCREMENT = auto() # ++
    DECREMENT = auto() # --
    SHL = auto()       # <<
    SHR = auto()       # >>
    TILDE = auto()     # ~

    ASSIGN = auto()    # =
    PLUS_ASSIGN = auto() # +=
    MINUS_ASSIGN = auto()# -=
    STAR_ASSIGN = auto() # *=
    SLASH_ASSIGN = auto()# /=
    MOD_ASSIGN = auto()  # %=

    EQ = auto()        # ==
    NEQ = auto()       # !=
    LT = auto()        # <
    GT = auto()        # >
    LE = auto()        # <=
    GE = auto()        # >=

    AND = auto()       # &&
    OR = auto()        # ||
    NOT = auto()       # !
    QUESTION = auto()  # ?
    AMP = auto()       # &
    PIPE = auto()      # |
    CARET = auto()     # ^
    ARROW = auto()     # ->

    # Separators
    LPAREN = auto()    # (
    RPAREN = auto()    # )
    LBRACE = auto()    # {
    RBRACE = auto()    # }
    SEMICOLON = auto() # ;
    COMMA = auto()     # ,
    LBRACKET = auto()  # [
    RBRACKET = auto()  # ]
    COLON = auto()     # :
    DOT = auto()       # .
    SCOPE = auto()     # ::

    EOF = auto()

@dataclass
class Token:
    """Represents a lexical token with its value and dual coordinates.

    ``line``/``col``/``indent`` are *analysis* coordinates (the text the parser
    actually reads, after include/macro expansion).  Parser ordering, newline,
    indentation and delimiter logic use them exclusively.  ``file`` plus the
    ``source_*`` fields are the *physical* origin used by diagnostics/patches.
    """
    type: TokenType
    lexeme: str
    line: int                 # analysis/generated line for parser logic
    col: int                  # analysis/generated column
    indent: int = 0           # analysis-source indentation
    file: Optional[str] = None
    source_line: Optional[int] = None
    source_col: Optional[int] = None
    source_end_line: Optional[int] = None
    source_end_col: Optional[int] = None
    synthetic: bool = False
    macro_generated: bool = False

KEYWORDS = {
    "int": TokenType.INT,
    "float": TokenType.FLOAT,
    "double": TokenType.DOUBLE,
    "void": TokenType.VOID,
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "for": TokenType.FOR,
    "return": TokenType.RETURN,
    "char": TokenType.CHAR,
    "sizeof": TokenType.SIZEOF,
    "do": TokenType.DO,
    "break": TokenType.BREAK,
    "continue": TokenType.CONTINUE,
    "switch": TokenType.SWITCH,
    "case": TokenType.CASE,
    "default": TokenType.DEFAULT,
    "struct": TokenType.STRUCT,
    "enum": TokenType.ENUM,
    "class": TokenType.CLASS,
    "public": TokenType.PUBLIC,
    "private": TokenType.PRIVATE,
    "protected": TokenType.PROTECTED,
    "this": TokenType.THIS,
    "new": TokenType.NEW,
    "delete": TokenType.DELETE,
    "bool": TokenType.BOOL,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "const": TokenType.CONST,
    "operator": TokenType.OPERATOR,
    "namespace": TokenType.NAMESPACE,
    "using": TokenType.USING,
    "virtual": TokenType.VIRTUAL,
    "override": TokenType.OVERRIDE,
    "template": TokenType.TEMPLATE,
    "typename": TokenType.TYPENAME,
    "try": TokenType.TRY,
    "catch": TokenType.CATCH,
    "throw": TokenType.THROW,
    "auto": TokenType.AUTO,
    "constexpr": TokenType.CONSTEXPR,
    # Alien keywords
    "def": TokenType.DEF,
    "elif": TokenType.ELIF,
    "pass": TokenType.PASS,
    "None": TokenType.NONE,
    "null": TokenType.NULL_LIT,
    "True": TokenType.TRUE_LIT,
    "False": TokenType.FALSE_LIT,
    "in": TokenType.IN,
    "range": TokenType.RANGE,
    "is": TokenType.IS,
    "boolean": TokenType.BOOLEAN_TYPE,
    "String": TokenType.STRING_JAVA_TYPE,
    "and": TokenType.AND_KEYWORD,
    "or": TokenType.OR_KEYWORD,
    "not": TokenType.NOT_KEYWORD,
}

ALIEN_KEYWORDS = {
    "def": {
        "token": TokenType.DEF,
        "language": "Python",
        "description": "Python function definition keyword",
        "replacement": "<return_type> <func_name>(<params>)",
        "explanation": "In C++, functions specify their return type before the function name instead of using 'def'.",
    },
    "elif": {
        "token": TokenType.ELIF,
        "language": "Python",
        "description": "Python else-if conditional keyword",
        "replacement": "else if",
        "explanation": "In C++, multi-branch conditions use 'else if' rather than Python's 'elif'.",
    },
    "pass": {
        "token": TokenType.PASS,
        "language": "Python",
        "description": "Python no-op statement",
        "replacement": ";",
        "explanation": "In C++, an empty statement is represented by a single semicolon ';' or an empty block '{}'.",
    },
    "None": {
        "token": TokenType.NONE,
        "language": "Python",
        "description": "Python null object reference",
        "replacement": "nullptr",
        "explanation": "In C++, the null pointer literal is 'nullptr' rather than Python's 'None'.",
    },
    "null": {
        "token": TokenType.NULL_LIT,
        "language": "Java/JavaScript",
        "description": "Java/JavaScript null literal",
        "replacement": "nullptr",
        "explanation": "In C++, the null pointer literal is 'nullptr' rather than 'null'.",
    },
    "True": {
        "token": TokenType.TRUE_LIT,
        "language": "Python",
        "description": "Python capitalized boolean True literal",
        "replacement": "true",
        "explanation": "In C++, boolean literals are lowercase ('true' and 'false').",
    },
    "False": {
        "token": TokenType.FALSE_LIT,
        "language": "Python",
        "description": "Python capitalized boolean False literal",
        "replacement": "false",
        "explanation": "In C++, boolean literals are lowercase ('true' and 'false').",
    },
    "in": {
        "token": TokenType.IN,
        "language": "Python",
        "description": "Python membership/iteration operator",
        "replacement": ":",
        "explanation": "In C++, range-based for loops use a colon ':' (e.g., 'for (auto x : container)').",
    },
    "range": {
        "token": TokenType.RANGE,
        "language": "Python",
        "description": "Python range generator",
        "replacement": "for (int i = 0; i < N; i++)",
        "explanation": "In C++, standard counted iteration uses 'for (int i = 0; i < N; i++)' rather than 'range()'.",
    },
    "is": {
        "token": TokenType.IS,
        "language": "Python",
        "description": "Python object identity comparison",
        "replacement": "==",
        "explanation": "In C++, equality comparison uses '==' rather than Python's 'is'.",
    },
    "boolean": {
        "token": TokenType.BOOLEAN_TYPE,
        "language": "Java/JavaScript",
        "description": "Java/JavaScript boolean primitive type",
        "replacement": "bool",
        "explanation": "In C++, the boolean primitive type is 'bool' rather than 'boolean'.",
    },
    "String": {
        "token": TokenType.STRING_JAVA_TYPE,
        "language": "Java",
        "description": "Java capitalized String class",
        "replacement": "std::string",
        "explanation": "In C++, string types are provided by 'std::string' from the <string> library.",
    },
    "and": {
        "token": TokenType.AND_KEYWORD,
        "language": "Python",
        "description": "Python logical AND keyword",
        "replacement": "&&",
        "explanation": "In idiomatic C++, logical conjunction is written as '&&'.",
    },
    "or": {
        "token": TokenType.OR_KEYWORD,
        "language": "Python",
        "description": "Python logical OR keyword",
        "replacement": "||",
        "explanation": "In idiomatic C++, logical disjunction is written as '||'.",
    },
    "not": {
        "token": TokenType.NOT_KEYWORD,
        "language": "Python",
        "description": "Python logical NOT keyword",
        "replacement": "!",
        "explanation": "In idiomatic C++, logical negation is written as '!'.",
    },
    "print": {
        "token": TokenType.PRINT_STMT,
        "language": "Python",
        "description": "Python print output function",
        "replacement": "std::cout << ... << std::endl;",
        "explanation": "In C++, console output is performed via 'std::cout << ... << std::endl;' rather than 'print()'.",
    },
    "System.out": {
        "token": TokenType.SYSTEM_OUT,
        "language": "Java",
        "description": "Java standard output stream",
        "replacement": "std::cout",
        "explanation": "In C++, console output uses 'std::cout' (from <iostream>) rather than Java's 'System.out'.",
    },
    "System.out.println": {
        "token": TokenType.SYSTEM_OUT,
        "language": "Java",
        "description": "Java print line statement",
        "replacement": "std::cout << ... << std::endl;",
        "explanation": "In C++, console line output uses 'std::cout << ... << std::endl;' rather than Java's 'System.out.println()'.",
    },
}

