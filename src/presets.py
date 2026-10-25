"""
Showcase and Educational Presets for C++ Compiler Workbench
==============================================================================
Curated collection of 70 interactive C++ code snippets demonstrating compiler
diagnostics, error detection, syntax repair, and idiomatic standard patterns.
==============================================================================
"""

from typing import Dict, Any

PRESETS: Dict[str, Dict[str, Any]] = {
    # ==========================================================================
    # 1. CROSS-LANGUAGE SYNTAX (P005)
    # ==========================================================================
    "cross_language": {
        "title": "Cross-Language Syntax (Python def, elif, print)",
        "description": "Translates Python habits (def ... -> int:, elif, print, boolean, None) into standard C++.",
        "category": "1. Cross-Language Syntax (P005)",
        "code": """#include <iostream>

def calculate_bonus(int base, int score) -> int:
    if (score > 100) {
        return base * 2;
    } elif (score > 50):
        return base + 100;
    else:
        return base;

int main() {
    int bonus = calculate_bonus(500, 75);
    print("Calculated bonus: %d", bonus);
    boolean active = True;
    int* ptr = None;
    return 0;
}
""",
    },
    "cross_py_def_with_return": {
        "title": "Python Function with Return Arrow (def foo() -> int:)",
        "description": "Detects Python function declaration syntax and converts it to C++ int return type.",
        "category": "1. Cross-Language Syntax (P005)",
        "code": """#include <iostream>

def add_numbers(int a, int b) -> int:
    return a + b;

int main() {
    std::cout << add_numbers(10, 20) << std::endl;
    return 0;
}
""",
    },
    "cross_py_def_void": {
        "title": "Python Def Void Function (def greet():)",
        "description": "Converts Python def functions without return type annotations to void functions.",
        "category": "1. Cross-Language Syntax (P005)",
        "code": """#include <iostream>

def greet():
    std::cout << "Hello from C++" << std::endl;

int main() {
    greet();
    return 0;
}
""",
    },
    "cross_py_elif_chain": {
        "title": "Python Elif Chain (elif / else:)",
        "description": "Translates Python elif: and else: block statements to C++ else if (...) { ... }.",
        "category": "1. Cross-Language Syntax (P005)",
        "code": """#include <iostream>

int check_sign(int x) {
    if (x > 0) {
        return 1;
    } elif (x < 0):
        return -1;
    else:
        return 0;
}

int main() {
    return check_sign(5);
}
""",
    },
    "cross_py_print_func": {
        "title": "Python Print Function Call (print(...))",
        "description": "Replaces Python print(...) statements with std::cout stream statements.",
        "category": "1. Cross-Language Syntax (P005)",
        "code": """#include <iostream>

int main() {
    int score = 95;
    print("Your score is %d", score);
    return 0;
}
""",
    },
    "cross_py_bool_literals": {
        "title": "Python Boolean Literals (True / False / boolean)",
        "description": "Translates capitalized True / False and Java boolean to C++ bool, true, and false.",
        "category": "1. Cross-Language Syntax (P005)",
        "code": """#include <iostream>

int main() {
    boolean isReady = True;
    boolean isFinished = False;
    if (isReady) {
        std::cout << "Ready!" << std::endl;
    }
    return 0;
}
""",
    },
    "cross_py_none_keyword": {
        "title": "Python None Pointer (ptr = None)",
        "description": "Replaces Python None assignment on pointer types with modern C++ nullptr.",
        "category": "1. Cross-Language Syntax (P005)",
        "code": """#include <iostream>

int main() {
    int* data = None;
    if (data == None) {
        std::cout << "Pointer is null" << std::endl;
    }
    return 0;
}
""",
    },
    "cross_js_null_keyword": {
        "title": "Java/JS Null Pointer (ptr = null)",
        "description": "Translates lowercase null keyword to C++ nullptr.",
        "category": "1. Cross-Language Syntax (P005)",
        "code": """#include <iostream>

int main() {
    int* ptr = null;
    if (ptr == null) {
        std::cout << "Null pointer verified" << std::endl;
    }
    return 0;
}
""",
    },
    "cross_java_system_out": {
        "title": "Java System.out.println Syntax",
        "description": "Translates Java System.out.println to standard C++ std::cout stream.",
        "category": "1. Cross-Language Syntax (P005)",
        "code": """#include <iostream>

int main() {
    System.out.println("Hello from Java style");
    return 0;
}
""",
    },
    "cross_py_range_for": {
        "title": "Python Range For Loop (for i in range(10):)",
        "description": "Converts Python range-based for loops to idiomatic C++ for (int i = 0; i < n; i++).",
        "category": "1. Cross-Language Syntax (P005)",
        "code": """#include <iostream>

int main() {
    for i in range(5):
        std::cout << i << std::endl;
    return 0;
}
""",
    },

    # ==========================================================================
    # 2. SEMICOLONS & DELIMITERS (P003, P004)
    # ==========================================================================
    "missing_delimiters": {
        "title": "Missing Semicolons & Unclosed Braces",
        "description": "Detects omitted semicolons at statement ends and balances unclosed braces.",
        "category": "2. Semicolons & Delimiters (P003, P004)",
        "code": """#include <iostream>

struct Vector2D {
    double x
    double y;
}

int main() {
    int count = 10
    int total = 0;
    if (count > 0) {
        std::cout << "Count is positive" << std::endl;
    return 0;
}
""",
    },
    "semi_var_decl_simple": {
        "title": "Missing Semicolon: Variable Declaration",
        "description": "Inserts omitted semicolon after a variable declaration followed by another statement.",
        "category": "2. Semicolons & Delimiters (P003, P004)",
        "code": """#include <iostream>

int main() {
    int width = 100
    int height = 200;
    std::cout << width * height << std::endl;
    return 0;
}
""",
    },
    "semi_return_stmt": {
        "title": "Missing Semicolon: Return Statement",
        "description": "Inserts missing semicolon on return statement immediately before closing brace.",
        "category": "2. Semicolons & Delimiters (P003, P004)",
        "code": """#include <iostream>

int compute() {
    int a = 15;
    int b = 25;
    return a + b
}

int main() {
    return compute();
}
""",
    },
    "semi_expr_stmt": {
        "title": "Missing Semicolon: Expression Statement",
        "description": "Detects omitted semicolon on increment or assignment statements.",
        "category": "2. Semicolons & Delimiters (P003, P004)",
        "code": """#include <iostream>

int main() {
    int count = 0;
    count++
    return count;
}
""",
    },
    "semi_struct_def": {
        "title": "Missing Semicolon: Struct Definition",
        "description": "Appends required semicolon after struct definition closing brace.",
        "category": "2. Semicolons & Delimiters (P003, P004)",
        "code": """#include <iostream>

struct Point {
    int x;
    int y;
}

int main() {
    Point p;
    p.x = 10;
    p.y = 20;
    return p.x + p.y;
}
""",
    },
    "semi_class_def": {
        "title": "Missing Semicolon: Class Definition",
        "description": "Appends required semicolon after class definition closing brace.",
        "category": "2. Semicolons & Delimiters (P003, P004)",
        "code": """#include <iostream>

class Student {
    int id;
}

int main() {
    Student s;
    return 0;
}
""",
    },
    "semi_enum_def": {
        "title": "Missing Semicolon: Enum Definition",
        "description": "Appends required semicolon after enum definition closing brace.",
        "category": "2. Semicolons & Delimiters (P003, P004)",
        "code": """#include <iostream>

enum Direction {
    NORTH,
    SOUTH,
    EAST,
    WEST
}

int main() {
    int dir = NORTH;
    return dir;
}
""",
    },
    "semi_for_loop_header": {
        "title": "Missing Semicolon: For Loop Header",
        "description": "Repairs omitted semicolon inside for loop initialization/condition headers.",
        "category": "2. Semicolons & Delimiters (P003, P004)",
        "code": """#include <iostream>

int main() {
    int total = 0;
    for (int i = 0 i < 10; i++) {
        total += i;
    }
    return total;
}
""",
    },
    "delim_unclosed_if_brace": {
        "title": "Unclosed Delimiter: Missing Block Closing Brace",
        "description": "Detects unclosed if block brace based on indentation level and closes scope.",
        "category": "2. Semicolons & Delimiters (P003, P004)",
        "code": """#include <iostream>

int main() {
    int x = 10;
    if (x > 5) {
        std::cout << "x is greater than 5" << std::endl;
    return 0;
}
""",
    },
    "delim_missing_paren_if": {
        "title": "Unclosed Delimiter: Missing Closing Parenthesis in If",
        "description": "Inserts missing closing parenthesis before opening block brace in condition.",
        "category": "2. Semicolons & Delimiters (P003, P004)",
        "code": """#include <iostream>

int main() {
    int threshold = 50;
    if (threshold > 25 {
        std::cout << "Above threshold" << std::endl;
    }
    return 0;
}
""",
    },
    "delim_missing_bracket_arr": {
        "title": "Unclosed Delimiter: Missing Closing Bracket in Array",
        "description": "Inserts missing closing bracket in array declaration or index expression.",
        "category": "2. Semicolons & Delimiters (P003, P004)",
        "code": """#include <iostream>

int main() {
    int arr[10;
    arr[0] = 42;
    return arr[0];
}
""",
    },

    # ==========================================================================
    # 3. EXPRESSION REPAIRS (P002)
    # ==========================================================================
    "expression_repair": {
        "title": "Malformed Expressions (ab+, dangling operators)",
        "description": "Auto-corrects concatenated variables (ab -> a, b) and dangling postfix operators.",
        "category": "3. Expression Repairs (P002)",
        "code": """#include <iostream>

int main() {
    int a = 5;
    int b = 10;
    int c = 2;
    int res1 = ab+;
    int res2 = (a+bc*);
    int res3 = a + + b;
    std::cout << "Result: " << res1 + res2 + res3 << std::endl;
    return 0;
}
""",
    },
    "expr_split_two_vars": {
        "title": "Expression Repair: Concatenated Undeclared Variables (ab+)",
        "description": "Splits undeclared variable ab into declared identifiers a and b with infix +.",
        "category": "3. Expression Repairs (P002)",
        "code": """#include <iostream>

int main() {
    int a = 12;
    int b = 8;
    int sum = ab+;
    return sum;
}
""",
    },
    "expr_missing_operator_vars": {
        "title": "Expression Repair: Missing Operator between Variables (a b)",
        "description": "Inserts missing multiplication operator between juxtaposed variables.",
        "category": "3. Expression Repairs (P002)",
        "code": """#include <iostream>

int main() {
    int a = 10;
    int b = 20;
    int res = a b;
    return res;
}
""",
    },
    "expr_postfix_rpn_add": {
        "title": "Expression Repair: Postfix Addition (x y +)",
        "description": "Relocates postfix addition operator between two in-scope operands.",
        "category": "3. Expression Repairs (P002)",
        "code": """#include <iostream>

int main() {
    int x = 14;
    int y = 6;
    int res = x y +;
    return res;
}
""",
    },
    "expr_postfix_rpn_sub": {
        "title": "Expression Repair: Postfix Subtraction (a b -)",
        "description": "Relocates postfix subtraction operator between identifiers.",
        "category": "3. Expression Repairs (P002)",
        "code": """#include <iostream>

int main() {
    int a = 50;
    int b = 20;
    int diff = a b -;
    return diff;
}
""",
    },
    "expr_postfix_rpn_mul": {
        "title": "Expression Repair: Postfix Multiplication (m n *)",
        "description": "Relocates dangling multiplication operator to infix position.",
        "category": "3. Expression Repairs (P002)",
        "code": """#include <iostream>

int main() {
    int m = 6;
    int n = 7;
    int prod = m n *;
    return prod;
}
""",
    },
    "expr_dangling_mult_paren": {
        "title": "Expression Repair: Dangling Multiply in Parens ((a+bc*))",
        "description": "Splits bc and relocates trailing * to infix between b and c.",
        "category": "3. Expression Repairs (P002)",
        "code": """#include <iostream>

int main() {
    int a = 4;
    int b = 5;
    int c = 6;
    int val = (a+bc*);
    return val;
}
""",
    },
    "expr_implicit_mult_literal": {
        "title": "Expression Repair: Implicit Multiplication (2(a + b))",
        "description": "Inserts missing * operator between numeric constant and opening parenthesis.",
        "category": "3. Expression Repairs (P002)",
        "code": """#include <iostream>

int main() {
    int a = 10;
    int b = 20;
    int perimeter = 2(a + b);
    return perimeter;
}
""",
    },
    "expr_dedup_consecutive_plus": {
        "title": "Expression Repair: Consecutive Plus Operators (a + + b)",
        "description": "Deduplicates redundant consecutive binary operators.",
        "category": "3. Expression Repairs (P002)",
        "code": """#include <iostream>

int main() {
    int a = 15;
    int b = 25;
    int res = a + + b;
    return res;
}
""",
    },

    # ==========================================================================
    # 4. MISSING HEADERS & AUTO-INCLUDE (E015)
    # ==========================================================================
    "auto_include": {
        "title": "Missing Headers & Namespaces (cout, vector)",
        "description": "Auto-detects undeclared standard library symbols and injects missing headers.",
        "category": "4. Missing Headers & Includes (E015)",
        "code": """int main() {
    cout << "Welcome to modern C++!" << endl;
    vector<int> numbers;
    double root = sqrt(64.0);
    return 0;
}
""",
    },
    "include_iostream_cout": {
        "title": "Missing Header: std::cout and std::endl (<iostream>)",
        "description": "Auto-detects std::cout / std::endl and injects #include <iostream>.",
        "category": "4. Missing Headers & Includes (E015)",
        "code": """int main() {
    std::cout << "Hello Antigravity!" << std::endl;
    return 0;
}
""",
    },
    "include_vector_container": {
        "title": "Missing Header: std::vector (<vector>)",
        "description": "Auto-detects std::vector usage and injects #include <vector>.",
        "category": "4. Missing Headers & Includes (E015)",
        "code": """int main() {
    std::vector<int> numbers;
    numbers.push_back(10);
    return 0;
}
""",
    },
    "include_string_type": {
        "title": "Missing Header: std::string (<string>)",
        "description": "Auto-detects std::string usage and injects #include <string>.",
        "category": "4. Missing Headers & Includes (E015)",
        "code": """int main() {
    std::string message = "Compiler Design 2026";
    return 0;
}
""",
    },
    "include_cmath_sqrt": {
        "title": "Missing Header: sqrt Math Function (<cmath>)",
        "description": "Detects sqrt function call and automatically injects #include <cmath>.",
        "category": "4. Missing Headers & Includes (E015)",
        "code": """int main() {
    double val = sqrt(144.0);
    return 0;
}
""",
    },
    "include_cmath_pow": {
        "title": "Missing Header: pow Math Function (<cmath>)",
        "description": "Detects pow function call and injects #include <cmath>.",
        "category": "4. Missing Headers & Includes (E015)",
        "code": """int main() {
    double p = pow(2.0, 10.0);
    return 0;
}
""",
    },
    "include_cstdio_printf": {
        "title": "Missing Header: printf Standard I/O (<cstdio>)",
        "description": "Detects C-style printf call and injects #include <cstdio>.",
        "category": "Missing Headers & Includes",
        "code": """int main() {
    printf("Computing value: %d\\n", 42);
    return 0;
}
""",
    },
    "include_cstdlib_abs": {
        "title": "Missing Header: abs / rand Utility (<cstdlib>)",
        "description": "Detects abs function call and injects #include <cstdlib>.",
        "category": "4. Missing Headers & Includes (E015)",
        "code": """int main() {
    int magnitude = abs(-99);
    return magnitude;
}
""",
    },
    "include_algorithm_sort": {
        "title": "Missing Header: std::sort Algorithm (<algorithm>)",
        "description": "Detects std::sort algorithm call and injects #include <algorithm>.",
        "category": "4. Missing Headers & Includes (E015)",
        "code": """#include <vector>

int main() {
    std::vector<int> nums;
    std::sort(nums.begin(), nums.end());
    return 0;
}
""",
    },

    # ==========================================================================
    # 5. NAMESPACE RESOLUTION (E016)
    # ==========================================================================
    "namespace_unqualified_cout": {
        "title": "Namespace Resolution: Unqualified cout Stream",
        "description": "Suggests std::cout qualification or using namespace std; for naked cout.",
        "category": "5. Namespace Resolution (E016)",
        "code": """#include <iostream>

int main() {
    cout << "Unqualified stream identifier" << std::endl;
    return 0;
}
""",
    },
    "namespace_unqualified_cin": {
        "title": "Namespace Resolution: Unqualified cin Input Stream",
        "description": "Suggests std::cin qualification for unadorned cin identifier.",
        "category": "5. Namespace Resolution (E016)",
        "code": """#include <iostream>

int main() {
    int x;
    cin >> x;
    return 0;
}
""",
    },
    "namespace_unqualified_vector": {
        "title": "Namespace Resolution: Unqualified vector Container",
        "description": "Suggests std::vector qualification when <vector> is included.",
        "category": "5. Namespace Resolution (E016)",
        "code": """#include <vector>

int main() {
    vector<int> items;
    return 0;
}
""",
    },
    "namespace_unqualified_string": {
        "title": "Namespace Resolution: Unqualified string Type",
        "description": "Suggests std::string qualification when <string> is included.",
        "category": "5. Namespace Resolution (E016)",
        "code": """#include <string>

int main() {
    string greeting = "Hello Antigravity";
    return 0;
}
""",
    },
    "namespace_unqualified_endl": {
        "title": "Namespace Resolution: Unqualified endl Manipulator",
        "description": "Suggests std::endl qualification for stream manipulator.",
        "category": "5. Namespace Resolution (E016)",
        "code": """#include <iostream>

int main() {
    std::cout << "Testing" << endl;
    return 0;
}
""",
    },
    "namespace_user_function": {
        "title": "Namespace Resolution: User Namespace Function (Math::square)",
        "description": "Suggests qualifying unqualified user namespace functions.",
        "category": "5. Namespace Resolution (E016)",
        "code": """namespace Math {
    int square(int x) {
        return x * x;
    }
}

int main() {
    int res = square(5);
    return res;
}
""",
    },

    # ==========================================================================
    # 6. OPERATOR MISUSE HAZARDS (W002-W005)
    # ==========================================================================
    "operator_misuse": {
        "title": "Operator Hazards (if x = 5, 2 ^ 8, chained <)",
        "description": "Detects assignment in conditional (W002), XOR vs power (W003), and chained comparisons (W004).",
        "category": "6. Operator Misuse Hazards (W002-W005)",
        "code": """#include <iostream>

int main() {
    int status = 0;
    if (status = 1) {
        std::cout << "Accidental assignment in condition!" << std::endl;
    }

    int power = 2 ^ 8;
    int x = 5;
    if (1 < x < 10) {
        std::cout << "Chained comparison hazard!" << std::endl;
    }

    bool hasRole = true, isReady = false;
    if (hasRole & isReady) {
        std::cout << "Bitwise & in boolean context" << std::endl;
    }
    return 0;
}
""",
    },
    "op_assign_in_if_cond": {
        "title": "Operator Misuse: Assignment in If Condition (if (x = 5))",
        "description": "Warns when assignment '=' is mistakenly used instead of equality '==' in if check.",
        "category": "6. Operator Misuse Hazards (W002-W005)",
        "code": """#include <iostream>

int main() {
    int flag = 0;
    if (flag = 1) {
        std::cout << "Always true because of assignment!" << std::endl;
    }
    return 0;
}
""",
    },
    "op_assign_in_while_cond": {
        "title": "Operator Misuse: Assignment in While Loop (while (p = 0))",
        "description": "Warns about accidental assignment '=' inside while loop condition.",
        "category": "6. Operator Misuse Hazards (W002-W005)",
        "code": """#include <iostream>

int main() {
    int p = 5;
    while (p = 0) {
        std::cout << "Loop never runs" << std::endl;
    }
    return 0;
}
""",
    },
    "op_xor_power_literal": {
        "title": "Operator Misuse: Bitwise XOR as Power (2 ^ 8)",
        "description": "Warns that ^ is bitwise XOR rather than mathematical exponentiation.",
        "category": "6. Operator Misuse Hazards (W002-W005)",
        "code": """#include <iostream>

int main() {
    int result = 2 ^ 8;
    std::cout << "Expected 256 but got XOR: " << result << std::endl;
    return 0;
}
""",
    },
    "op_xor_power_variable": {
        "title": "Operator Misuse: Bitwise XOR on Variables (base ^ 2)",
        "description": "Detects base ^ 2 pattern and advises multiplying or using pow().",
        "category": "6. Operator Misuse Hazards (W002-W005)",
        "code": """#include <iostream>

int main() {
    int radius = 5;
    int area = 3 * (radius ^ 2);
    return area;
}
""",
    },
    "op_chained_less_than": {
        "title": "Operator Misuse: Chained Less-Than (0 < x < 10)",
        "description": "Warns that chained comparisons do not evaluate mathematically in C++.",
        "category": "6. Operator Misuse Hazards (W002-W005)",
        "code": """#include <iostream>

int main() {
    int x = 15;
    if (0 < x < 10) {
        std::cout << "Surprise! (0 < 15) is 1, and (1 < 10) is true!" << std::endl;
    }
    return 0;
}
""",
    },
    "op_chained_less_equal": {
        "title": "Operator Misuse: Chained Range (10 <= score <= 100)",
        "description": "Warns about <= chaining and provides split logical AND replacement.",
        "category": "6. Operator Misuse Hazards (W002-W005)",
        "code": """#include <iostream>

int main() {
    int score = 150;
    if (10 <= score <= 100) {
        std::cout << "Invalid range evaluation" << std::endl;
    }
    return 0;
}
""",
    },
    "op_bitwise_and_bool": {
        "title": "Operator Misuse: Bitwise & with Boolean Operands",
        "description": "Flags non-short-circuiting bitwise & on boolean variables.",
        "category": "6. Operator Misuse Hazards (W002-W005)",
        "code": """#include <iostream>

int main() {
    bool hasAuth = true;
    bool isValid = false;
    if (hasAuth & isValid) {
        std::cout << "Should use logical &&" << std::endl;
    }
    return 0;
}
""",
    },
    "op_bitwise_or_bool": {
        "title": "Operator Misuse: Bitwise | with Boolean Operands",
        "description": "Flags non-short-circuiting bitwise | on boolean expressions.",
        "category": "6. Operator Misuse Hazards (W002-W005)",
        "code": """#include <iostream>

int main() {
    bool hasAuth = true;
    bool isValid = false;
    if (hasAuth | isValid) {
        std::cout << "Should use logical ||" << std::endl;
    }
    return 0;
}
""",
    },

    # ==========================================================================
    # 7. ARRAY BOUNDS & OFF-BY-ONE (W006, W007)
    # ==========================================================================
    "array_bounds": {
        "title": "Static Array Bounds & Off-by-One Loop",
        "description": "Statically detects literal out-of-bounds indexing (W006) and loop boundary hazards (W007).",
        "category": "7. Array Bounds & Off-by-One (W006, W007)",
        "code": """#include <iostream>

int main() {
    int arr[5] = {10, 20, 30, 40, 50};
    arr[5] = 99; // Out-of-bounds: valid indices are 0..4

    for (int i = 0; i <= 5; i++) { // Hazard: i reaches 5, exceeding size 5
        std::cout << arr[i] << std::endl;
    }
    return 0;
}
""",
    },
    "bounds_literal_max_index": {
        "title": "Array Bounds: Literal Index Equal to Array Size (arr[5])",
        "description": "Warns when constant index equals array length (valid indices 0..size-1).",
        "category": "7. Array Bounds & Off-by-One (W006, W007)",
        "code": """#include <iostream>

int main() {
    int buffer[5];
    buffer[5] = 42;
    return 0;
}
""",
    },
    "bounds_literal_exceeded": {
        "title": "Array Bounds: Index Exceeding Size by Margin (arr[15] of 10)",
        "description": "Warns when constant index is significantly larger than declared capacity.",
        "category": "7. Array Bounds & Off-by-One (W006, W007)",
        "code": """#include <iostream>

int main() {
    int table[10];
    int val = table[15];
    return val;
}
""",
    },
    "bounds_negative_index_last": {
        "title": "Array Bounds: Negative Index Literal (arr[-1])",
        "description": "Explains that C++ does not support Python negative indexing for end of array.",
        "category": "7. Array Bounds & Off-by-One (W006, W007)",
        "code": """#include <iostream>

int main() {
    int values[5] = {1, 2, 3, 4, 5};
    int last = values[-1];
    return last;
}
""",
    },
    "bounds_negative_index_offset": {
        "title": "Array Bounds: Negative Index Offset (arr[-2])",
        "description": "Warns on negative index and calculates equivalent positive index.",
        "category": "7. Array Bounds & Off-by-One (W006, W007)",
        "code": """#include <iostream>

int main() {
    int values[5] = {1, 2, 3, 4, 5};
    int second_last = values[-2];
    return second_last;
}
""",
    },
    "bounds_loop_off_by_one_le": {
        "title": "Off-by-One Hazard: For Loop with <= Size",
        "description": "Detects classic loop condition i <= size and recommends changing to i < size.",
        "category": "7. Array Bounds & Off-by-One (W006, W007)",
        "code": """#include <iostream>

int main() {
    int arr[10];
    for (int i = 0; i <= 10; i++) {
        arr[i] = i * 2;
    }
    return 0;
}
""",
    },
    "bounds_loop_one_based_index": {
        "title": "Off-by-One Hazard: 1-Based For Loop on 0-Based Array",
        "description": "Identifies 1-based loop indexing into 0-based array exceeding maximum index.",
        "category": "7. Array Bounds & Off-by-One (W006, W007)",
        "code": """#include <iostream>

int main() {
    int data[10];
    for (int i = 1; i <= 10; i++) {
        data[i] = i;
    }
    return 0;
}
""",
    },
    "bounds_while_off_by_one": {
        "title": "Off-by-One Hazard: While Loop with <= Bound",
        "description": "Flags while loop condition i <= size when indexing into array.",
        "category": "7. Array Bounds & Off-by-One (W006, W007)",
        "code": """#include <iostream>

int main() {
    int list[10];
    int i = 0;
    while (i <= 10) {
        list[i] = 100;
        i++;
    }
    return 0;
}
""",
    },

    # ==========================================================================
    # 8. CLEAN C++ SHOWCASE PROGRAMS
    # ==========================================================================
    "clean_hello": {
        "title": "Clean C++ Hello World",
        "description": "Error-free standard C++ source code that passes all compiler checks.",
        "category": "8. Clean C++ Showcase Programs",
        "code": """#include <iostream>

int main() {
    std::cout << "Hello, World from Modern C++!" << std::endl;
    int x = 42;
    std::cout << "Computed value: " << x << std::endl;
    return 0;
}
""",
    },
    "clean_math_calculator": {
        "title": "Clean C++: Arithmetic & Math Calculator",
        "description": "Valid C++ program performing arithmetic calculations with clean control flow.",
        "category": "8. Clean C++ Showcase Programs",
        "code": """#include <iostream>

int add(int a, int b) {
    return a + b;
}

int multiply(int a, int b) {
    return a * b;
}

int main() {
    int x = 15;
    int y = 25;
    int sum = add(x, y);
    int prod = multiply(x, y);
    std::cout << "Sum: " << sum << ", Product: " << prod << std::endl;
    return 0;
}
""",
    },
    "clean_fibonacci_iterative": {
        "title": "Clean C++: Iterative Fibonacci Sequence",
        "description": "Computes first N Fibonacci numbers using an array and loop.",
        "category": "8. Clean C++ Showcase Programs",
        "code": """#include <iostream>

int main() {
    int fib[10];
    fib[0] = 0;
    fib[1] = 1;
    for (int i = 2; i < 10; i++) {
        fib[i] = fib[i - 1] + fib[i - 2];
    }
    std::cout << "Fib[9] = " << fib[9] << std::endl;
    return 0;
}
""",
    },
    "clean_binary_search": {
        "title": "Clean C++: Binary Search Algorithm",
        "description": "Classic binary search algorithm on a sorted integer array.",
        "category": "8. Clean C++ Showcase Programs",
        "code": """#include <iostream>

int do_binary_search(int* arr, int size, int target) {
    int left = 0;
    int right = size - 1;
    while (left <= right) {
        int mid = left + (right - left) / 2;
        if (arr[mid] == target) {
            return mid;
        } else if (arr[mid] < target) {
            left = mid + 1;
        } else {
            right = mid - 1;
        }
    }
    return -1;
}

int main() {
    int data[5] = {2, 4, 6, 8, 10};
    int idx = do_binary_search(data, 5, 6);
    std::cout << "Found target at index: " << idx << std::endl;
    return 0;
}
""",
    },
    "clean_bubble_sort": {
        "title": "Clean C++: In-Place Bubble Sort",
        "description": "Sorts an array in ascending order with early termination check.",
        "category": "8. Clean C++ Showcase Programs",
        "code": """#include <iostream>

int main() {
    int arr[5] = {64, 34, 25, 12, 22};
    int n = 5;
    for (int i = 0; i < n - 1; i++) {
        for (int j = 0; j < n - i - 1; j++) {
            if (arr[j] > arr[j + 1]) {
                int temp = arr[j];
                arr[j] = arr[j + 1];
                arr[j + 1] = temp;
            }
        }
    }
    std::cout << "Sorted element 0: " << arr[0] << std::endl;
    return 0;
}
""",
    },
    "clean_point_struct": {
        "title": "Clean C++: 2D Point Struct with Functions",
        "description": "Demonstrates struct declaration, members, and geometric distance function.",
        "category": "8. Clean C++ Showcase Programs",
        "code": """#include <iostream>

struct Point {
    int x;
    int y;
};

int manhattan_dist(Point p) {
    return p.x + p.y;
}

int main() {
    Point pt;
    pt.x = 7;
    pt.y = 13;
    std::cout << "Distance: " << manhattan_dist(pt) << std::endl;
    return 0;
}
""",
    },
    "clean_counter_class": {
        "title": "Clean C++: Encapsulated Counter Class",
        "description": "C++ class with private members, public constructor, and methods.",
        "category": "8. Clean C++ Showcase Programs",
        "code": """#include <iostream>

class Counter {
private:
    int val;
public:
    Counter(int start) {
        val = start;
    }

    void increment() {
        val++;
    }

    int get_value() {
        return val;
    }
};

int main() {
    Counter c(10);
    c.increment();
    std::cout << "Counter value: " << c.get_value() << std::endl;
    return 0;
}
""",
    },
    "clean_template_max": {
        "title": "Clean C++: Generic Function Template",
        "description": "Demonstrates template function monomorphization with integer arguments.",
        "category": "8. Clean C++ Showcase Programs",
        "code": """#include <iostream>

template<typename T>
T find_max(T a, T b) {
    if (a > b) {
        return a;
    }
    return b;
}

int main() {
    int result = find_max(42, 99);
    std::cout << "Maximum: " << result << std::endl;
    return 0;
}
""",
    },
}
