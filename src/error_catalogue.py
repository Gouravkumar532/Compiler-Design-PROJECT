"""Catalogue of compiler error and warning codes with detailed explanations."""

ERROR_CATALOGUE = {
    "E001": {
        "title": "Undeclared Identifier",
        "description": "An identifier (variable or function) was used before being declared in the current scope.",
        "cause": "Typo in the identifier name, or missing variable declaration, or forgotten #include header.",
        "example_bad": """int main() {
    count = 10; // Error: 'count' is not declared
    return 0;
}""",
        "example_good": """int main() {
    int count = 10; // OK: declared before use
    return count;
}"""
    },
    "E002": {
        "title": "Type Mismatch",
        "description": "An operation or assignment was attempted between incompatible types without an explicit cast.",
        "cause": "Assigning incompatible pointer types or invalid operands to an operator.",
        "example_bad": """int main() {
    int* ptr = 42; // Error: cannot assign integer to pointer directly
    return 0;
}""",
        "example_good": """int main() {
    int x = 42;
    int* ptr = &x; // OK: address-of produces a pointer
    return *ptr;
}"""
    },
    "E003": {
        "title": "Syntax Error / Unexpected Token",
        "description": "The parser encountered a token that does not conform to the language grammar.",
        "cause": "Missing semicolon, mismatched parentheses or braces, or misplaced keyword.",
        "example_bad": """int main() {
    int x = 10 // Error: missing ';'
    return x;
}""",
        "example_good": """int main() {
    int x = 10; // OK: properly terminated statement
    return x;
}"""
    },
    "E004": {
        "title": "Unterminated Literal",
        "description": "A string or character literal was opened with quotes but was not closed before line ending or EOF.",
        "cause": "Missing closing quote ' or \".",
        "example_bad": """int main() {
    char* str = "hello world; // Error: missing closing quote
    return 0;
}""",
        "example_good": """int main() {
    char* str = "hello world"; // OK: closed string literal
    return 0;
}"""
    },
    "E005": {
        "title": "Duplicate Declaration",
        "description": "A variable, struct, or function with this name has already been declared in this scope.",
        "cause": "Re-declaring a variable within the same block scope.",
        "example_bad": """int main() {
    int a = 5;
    int a = 10; // Error: 'a' is already declared in this scope
    return a;
}""",
        "example_good": """int main() {
    int a = 5;
    a = 10; // OK: reassigning instead of redeclaring
    return a;
}"""
    },
    "E006": {
        "title": "Invalid Assignment Target (Not an LValue)",
        "description": "The left-hand side of an assignment must refer to a modifiable memory location (LValue).",
        "cause": "Assigning to a literal value, a function call result, or a non-assignable expression.",
        "example_bad": """int main() {
    10 = x; // Error: literal 10 cannot be assigned to
    return 0;
}""",
        "example_good": """int main() {
    x = 10; // OK: variable x is an assignable lvalue
    return x;
}"""
    },
    "E007": {
        "title": "Invalid Jump Statement",
        "description": "A 'break' or 'continue' statement was used outside of a loop or switch block.",
        "cause": "Using 'break' or 'continue' in top-level function code outside of while/for/switch.",
        "example_bad": """int main() {
    break; // Error: break not within loop or switch
    return 0;
}""",
        "example_good": """int main() {
    while (1) {
        break; // OK: inside loop
    }
    return 0;
}"""
    },
    "E008": {
        "title": "Missing Return Value",
        "description": "A non-void function reached a return statement without providing an expression value.",
        "cause": "Writing 'return;' in a function returning int, double, etc.",
        "example_bad": """int calculate() {
    return; // Error: function returns 'int', value expected
}""",
        "example_good": """int calculate() {
    return 42; // OK: provides integer return value
}"""
    },
    "E009": {
        "title": "Access Specifier Violation",
        "description": "Attempted to access a private or protected class member from outside the class.",
        "cause": "Calling a private method or reading/writing a private field from outside class scope.",
        "example_bad": """class Counter {
private:
    int count;
};
int main() {
    Counter c;
    c.count = 5; // Error: member 'count' is private
    return 0;
}""",
        "example_good": """class Counter {
public:
    int count;
};
int main() {
    Counter c;
    c.count = 5; // OK: public member
    return c.count;
}"""
    },
    "E010": {
        "title": "Const Assignment Violation",
        "description": "Cannot assign a new value to a variable or field qualified as const.",
        "cause": "Attempting to modify a constant after its initialization.",
        "example_bad": """int main() {
    const int max_val = 100;
    max_val = 200; // Error: cannot assign to const variable
    return max_val;
}""",
        "example_good": """int main() {
    const int max_val = 100;
    int curr_val = max_val;
    curr_val = 200; // OK: curr_val is not const
    return curr_val;
}"""
    },
    "E011": {
        "title": "Uninitialized Reference",
        "description": "A reference variable was declared without an initializer target.",
        "cause": "References in C++ must always be bound to an existing variable upon declaration.",
        "example_bad": """int main() {
    int& ref; // Error: reference variable must be initialized
    return 0;
}""",
        "example_good": """int main() {
    int x = 10;
    int& ref = x; // OK: bound to x
    return ref;
}"""
    },
    "E012": {
        "title": "Invalid 'this' Usage",
        "description": "'this' pointer was used outside of a class member function, constructor, or destructor.",
        "cause": "Referencing 'this' in a free/global function or static context.",
        "example_bad": """int global_func() {
    return this->x; // Error: 'this' can only be used inside a class member function
}""",
        "example_good": """class Point {
public:
    int x;
    int getX() {
        return this->x; // OK: inside class member function
    }
};"""
    },
    "E013": {
        "title": "Cannot Instantiate Abstract Class",
        "description": "Attempted to instantiate a class that contains unimplemented pure virtual methods.",
        "cause": "Class declares or inherits a pure virtual method ('= 0;') without providing an implementation.",
        "example_bad": """class Shape {
public:
    virtual int area() = 0;
};
int main() {
    Shape s; // Error: cannot instantiate abstract class 'Shape'
    return 0;
}""",
        "example_good": """class Shape {
public:
    virtual int area() = 0;
};
class Circle : public Shape {
public:
    int area() override { return 10; }
};
int main() {
    Circle c; // OK: Circle implements all pure virtual methods
    return c.area();
}"""
    },
    "E014": {
        "title": "Invalid Constexpr Expression",
        "description": "Expression in a constexpr declaration is not a compile-time constant or is missing an initializer.",
        "cause": "Attempted to initialize a constexpr variable with a non-constant runtime expression or missing initializer.",
        "example_bad": """int get_val() { return 10; }
int main() {
    constexpr int x = get_val(); // Error: 'get_val()' is not a compile-time constant
    return 0;
}""",
        "example_good": """constexpr int add(int a, int b) { return a + b; }
int main() {
    constexpr int x = add(10, 20); // OK: evaluated at compile time to 30
    return x;
}"""
    },
    "E015": {
        "title": "Missing Standard Library Header",
        "description": "A standard library identifier, type, or function was used without including the required header file.",
        "cause": "Using standard library symbols such as 'cout', 'cin', 'string', 'vector', 'sqrt', 'printf', 'malloc', or 'sort' without the corresponding '#include <header>' directive.",
        "example_bad": """int main() {
    std::cout << "Hello World" << std::endl; // Error: <iostream> not included
    return 0;
}""",
        "example_good": """#include <iostream>

int main() {
    std::cout << "Hello World" << std::endl; // OK: <iostream> included
    return 0;
}"""
    },
    "E016": {
        "title": "Unqualified Namespace Symbol",
        "description": "A symbol, function, or type was used without its required namespace qualifier or using directive.",
        "cause": "Referencing standard library elements (e.g., 'cout', 'endl', 'string', 'vector') or user-defined namespace members without 'std::' / '<namespace>::' or 'using namespace <name>;'.",
        "example_bad": """#include <iostream>

int main() {
    cout << "Hello" << endl; // Error: 'cout' and 'endl' are in namespace 'std'
    return 0;
}""",
        "example_good": """#include <iostream>

// Option A: Explicit qualification
int main() {
    std::cout << "Hello" << std::endl;
    return 0;
}

// Option B: Using directive
// using namespace std;"""
    },
    "W001": {
        "title": "Unused Variable",
        "description": "A variable was declared and initialized, but its value was never read.",
        "cause": "Leftover debug code or typo in variable name elsewhere.",
        "example_bad": """int main() {
    int unused_var = 100; // Warning: variable 'unused_var' never read
    return 0;
}""",
        "example_good": """int main() {
    int _unused = 100; // Hint: prefix with underscore to silence warning
    return 0;
}"""
    },
    "W002": {
        "title": "Assignment in Conditional Statement",
        "description": "An assignment '=' was used within an 'if', 'while', or 'for' condition instead of equality '=='. In C++, assignment yields the assigned value, which easily introduces silent logic errors.",
        "cause": "Accidental single '=' instead of double '==' for comparison.",
        "example_bad": """int main() {
    int status = 0;
    if (status = 0) { // Warning: assignment in condition always evaluates to false
        return 1;
    }
    return 0;
}""",
        "example_good": """int main() {
    int status = 0;
    if (status == 0) { // Correct: equality comparison
        return 1;
    }
    return 0;
}"""
    },
    "W003": {
        "title": "Bitwise XOR Used as Exponentiation",
        "description": "The '^' operator represents bitwise XOR in C++, not mathematical exponentiation.",
        "cause": "Confusion with Python, BASIC, or mathematical notation where '^' denotes power.",
        "example_bad": """int main() {
    int x = 2 ^ 8; // Warning: evaluates to 10 (2 XOR 8), not 256
    int square = 5 ^ 2; // Warning: evaluates to 7 (5 XOR 2), not 25
    return 0;
}""",
        "example_good": """#include <cmath>

int main() {
    int x = 1 << 8; // Bit shift for 2^8 = 256 (or pow(2, 8))
    int square = 5 * 5; // Multiplication for 5^2 = 25 (or pow(5, 2))
    return 0;
}"""
    },
    "W004": {
        "title": "Misleading Chained Comparison",
        "description": "Chained relational comparisons like 'a < b < c' evaluate left-to-right as '(a < b) < c'. The boolean result (0 or 1) is then compared to c, which does not reflect mathematical chained inequality.",
        "cause": "Attempting mathematical range checks like '10 <= score <= 100' or Python chained comparisons.",
        "example_bad": """int main() {
    int score = 150;
    if (10 <= score <= 100) { // Warning: (10 <= 150) is 1; 1 <= 100 is always true!
        return 1;
    }
    return 0;
}""",
        "example_good": """int main() {
    int score = 150;
    if (10 <= score && score <= 100) { // Correct: conjunction of comparisons
        return 1;
    }
    return 0;
}"""
    },
    "W005": {
        "title": "Bitwise Operator in Boolean Context",
        "description": "Bitwise AND '&' or OR '|' used with boolean operands instead of logical '&&' or '||'. Bitwise operators do not short-circuit and evaluate all operands eagerly.",
        "cause": "Typo using single '&' or '|' where logical short-circuiting operator was intended.",
        "example_bad": """int main() {
    bool hasPermission = true;
    bool isActive = true;
    if (hasPermission & isActive) { // Warning: bitwise '&' does not short-circuit
        return 1;
    }
    return 0;
}""",
        "example_good": """int main() {
    bool hasPermission = true;
    bool isActive = true;
    if (hasPermission && isActive) { // Correct: logical AND with short-circuiting
        return 1;
    }
    return 0;
}"""
    },
    "W006": {
        "title": "Constant Array Index Out of Bounds",
        "description": "An array was accessed with a constant literal index that is negative or greater than or equal to the declared array size.",
        "cause": "Typo in constant index, 0-based vs 1-based indexing confusion, or carrying over Python negative indexing (e.g., arr[-1] to access the last element).",
        "example_bad": """int main() {
    int buffer[5];
    buffer[5] = 42; // Warning: valid indices are 0..4; index 5 is out of bounds
    int last = buffer[-1]; // Warning: C++ does not support negative indices
    return 0;
}""",
        "example_good": """int main() {
    int buffer[5];
    buffer[4] = 42; // Correct: maximum valid index is 4 (size - 1)
    int last = buffer[4]; // Correct: access last element
    return 0;
}"""
    },
    "W007": {
        "title": "Off-By-One Array Boundary Condition",
        "description": "A loop boundary condition allows the loop induction variable to reach or exceed the array size, causing an out-of-bounds access on the final iteration.",
        "cause": "Using '<=' instead of '<' in loop condition (e.g., 'for (int i = 0; i <= size; i++)') or 1-based indexing on a 0-based array.",
        "example_bad": """int main() {
    int scores[10];
    for (int i = 0; i <= 10; i++) { // Warning: index reaches 10; scores[10] is out of bounds
        scores[i] = 0;
    }
    return 0;
}""",
        "example_good": """int main() {
    int scores[10];
    for (int i = 0; i < 10; i++) { // Correct: indices 0..9 are within bounds
        scores[i] = 0;
    }
    return 0;
}"""
    },
    "P001": {
        "title": "Parser Syntax Error",
        "description": "The parser encountered an unexpected token or invalid syntax structure that does not conform to C++ grammar.",
        "cause": "Typo, missing semicolon, unmatched bracket, or invalid keyword placement.",
        "example_bad": """int main() {
    int x = ; // Error: missing expression
    return 0;
}""",
        "example_good": """int main() {
    int x = 42; // OK: valid expression
    return 0;
}"""
    },
    "P002": {
        "title": "Malformed Expression",
        "description": "An expression contains malformed syntax, such as concatenated identifiers, misplaced or dangling operators, missing infix operators, or unbalanced delimiters.",
        "cause": "Accidental postfix notation, typo combining variable names without an operator, or missing multiplication operator.",
        "example_bad": """int main() {
    int a = 1, b = 2;
    int res = ab+; // Error: 'ab' is undeclared and '+' is misplaced
    return res;
}""",
        "example_good": """int main() {
    int a = 1, b = 2;
    int res = a + b; // OK: decomposed identifiers with infix operator
    return res;
}"""
    },
    "P003": {
        "title": "Missing Semicolon",
        "description": "A statement, declaration, struct, or class definition is missing a terminating semicolon ';'.",
        "cause": "Omitting ';' at the end of a statement, after a variable declaration, after a return statement, or after a class/struct closing brace.",
        "example_bad": """class Student {
    int id;
}
int main() {
    int a = 10
    int b = 20;
    return a + b;
}""",
        "example_good": """class Student {
    int id;
};
int main() {
    int a = 10;
    int b = 20;
    return a + b;
}"""
    },
    "P004": {
        "title": "Unbalanced Delimiter",
        "description": "An opening delimiter ('{', '(', or '[') was not properly closed, or an unexpected closing delimiter was encountered.",
        "cause": "Missing closing parenthesis in control statement condition headers, missing closing brace in a block, or indentation mismatch in nested blocks.",
        "example_bad": """int calculate() {
    if (x > 10 {
        return 1;
    return 0;
}""",
        "example_good": """int calculate() {
    if (x > 10) {
        return 1;
    }
    return 0;
}"""
    },
    "P005": {
        "title": "Cross-Language Syntax Confusion",
        "description": "Foreign language keywords, primitives, or grammar (from Python, Java, or JavaScript) were detected in C++ source.",
        "cause": "Carrying over habits from other languages, such as 'def', 'elif', 'boolean', 'String', 'True', 'False', 'None', 'null', 'for..in range', or 'print'.",
        "example_bad": """def add(int a, int b):
    return a + b

int main() {
    boolean flag = True;
    if (flag):
        print("Hello");
    elif (!flag):
        print("World");
    return 0;
}""",
        "example_good": """int add(int a, int b) {
    return a + b;
}

int main() {
    bool flag = true;
    if (flag) {
        std::cout << "Hello" << std::endl;
    } else if (!flag) {
        std::cout << "World" << std::endl;
    }
    return 0;
}"""
    },
    "L001": {
        "title": "Invalid Lexical Character",
        "description": "The lexer encountered an unexpected character or symbol that does not form part of any valid C++ token.",
        "cause": "Typographical errors, non-ASCII symbols, or stray punctuation (e.g. '@', '$', '`').",
        "example_bad": """int main() {
    int @x = 10; // Error: '@' is an invalid character in C++
    return 0;
}""",
        "example_good": """int main() {
    int x = 10; // OK: valid identifier
    return 0;
}"""
    },
    "L002": {
        "title": "Unterminated String Literal",
        "description": "A string literal opened with double quotes was not closed before line ending or EOF.",
        "cause": "Missing closing double quote '\"'.",
        "example_bad": """int main() {
    const char* msg = "hello; // Error: missing closing quote
    return 0;
}""",
        "example_good": """int main() {
    const char* msg = "hello"; // OK: closed string literal
    return 0;
}"""
    },
    "L003": {
        "title": "Unterminated Character Literal",
        "description": "A character literal opened with single quote was not closed before line ending or EOF.",
        "cause": "Missing closing single quote '\\''.",
        "example_bad": """int main() {
    char c = 'a; // Error: missing closing single quote
    return 0;
}""",
        "example_good": """int main() {
    char c = 'a'; // OK: closed character literal
    return 0;
}"""
    }
}
