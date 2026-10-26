import json
import os

corpus_dir = os.path.join(os.path.dirname(__file__), "corpus")
os.makedirs(corpus_dir, exist_ok=True)

# 1. Syntax & Delimiters (25 cases)
syn_cases = [
    {
        "id": f"SYN_{i+1:03d}",
        "category": "Syntax_Delimiters",
        "difficulty": "Easy" if i < 15 else "Medium",
        "description": desc,
        "buggy_code": buggy,
        "expected_fix": expected,
        "expected_error_code": err
    }
    for i, (desc, buggy, expected, err) in enumerate([
        ("Missing semicolon after variable declaration", "int main() {\n    int a = 10\n    return a;\n}", "int main() {\n    int a = 10;\n    return a;\n}", "P003"),
        ("Missing semicolon after return statement", "int main() {\n    int a = 10;\n    return a\n}", "int main() {\n    int a = 10;\n    return a;\n}", "P003"),
        ("Missing semicolon after assignment", "int main() {\n    int x = 5;\n    x = 20\n    return x;\n}", "int main() {\n    int x = 5;\n    x = 20;\n    return x;\n}", "P003"),
        ("Missing semicolon after struct declaration", "struct Point {\n    int x;\n    int y;\n}\nint main() { return 0; }", "struct Point {\n    int x;\n    int y;\n};\nint main() { return 0; }", "P003"),
        ("Missing semicolon after class declaration", "class Box {\n    int width;\n}\nint main() { return 0; }", "class Box {\n    int width;\n};\nint main() { return 0; }", "P003"),
        ("Missing semicolon after multiple variables", "int main() {\n    int a = 1, b = 2\n    return a + b;\n}", "int main() {\n    int a = 1, b = 2;\n    return a + b;\n}", "P003"),
        ("Missing semicolon after function call", "void foo() {}\nint main() {\n    foo()\n    return 0;\n}", "void foo() {}\nint main() {\n    foo();\n    return 0;\n}", "P003"),
        ("Missing semicolon before closing brace", "int main() {\n    int res = 42\n}", "int main() {\n    int res = 42;\n}", "P003"),
        ("Missing semicolon after float declaration", "int main() {\n    float pi = 3.14\n    return 0;\n}", "int main() {\n    float pi = 3.14;\n    return 0;\n}", "P003"),
        ("Missing semicolon after char declaration", "int main() {\n    char c = 'a'\n    return 0;\n}", "int main() {\n    char c = 'a';\n    return 0;\n}", "P003"),
        ("Missing semicolon after bool declaration", "int main() {\n    bool ok = true\n    return 0;\n}", "int main() {\n    bool ok = true;\n    return 0;\n}", "P003"),
        ("Missing semicolon after break", "int main() {\n    while (1) {\n        break\n    }\n    return 0;\n}", "int main() {\n    while (1) {\n        break;\n    }\n    return 0;\n}", "P003"),
        ("Missing semicolon after continue", "int main() {\n    for (int i = 0; i < 5; i++) {\n        continue\n    }\n    return 0;\n}", "int main() {\n    for (int i = 0; i < 5; i++) {\n        continue;\n    }\n    return 0;\n}", "P003"),
        ("Missing semicolon after pointer declaration", "int main() {\n    int* p = nullptr\n    return 0;\n}", "int main() {\n    int* p = nullptr;\n    return 0;\n}", "P003"),
        ("Missing semicolon after array declaration", "int main() {\n    int arr[5] = {1, 2, 3, 4, 5}\n    return 0;\n}", "int main() {\n    int arr[5] = {1, 2, 3, 4, 5};\n    return 0;\n}", "P003"),
        ("Missing closing parenthesis in if statement", "int main() {\n    int x = 5;\n    if (x > 0 {\n        return 1;\n    }\n    return 0;\n}", "int main() {\n    int x = 5;\n    if (x > 0) {\n        return 1;\n    }\n    return 0;\n}", "P006"),
        ("Missing closing parenthesis in while loop", "int main() {\n    int i = 0;\n    while (i < 5 {\n        i++;\n    }\n    return 0;\n}", "int main() {\n    int i = 0;\n    while (i < 5) {\n        i++;\n    }\n    return 0;\n}", "P006"),
        ("Missing closing parenthesis in for loop", "int main() {\n    for (int i = 0; i < 5; i++ {\n        int x = i;\n    }\n    return 0;\n}", "int main() {\n    for (int i = 0; i < 5; i++) {\n        int x = i;\n    }\n    return 0;\n}", "P006"),
        ("Missing closing bracket in array indexing", "int main() {\n    int arr[5];\n    int val = arr[2;\n    return val;\n}", "int main() {\n    int arr[5];\n    int val = arr[2];\n    return val;\n}", "P004"),
        ("Missing closing bracket in array declaration", "int main() {\n    int arr[5;\n    return 0;\n}", "int main() {\n    int arr[5];\n    return 0;\n}", "P004"),
        ("Missing closing brace based on indentation", "int main() {\n    if (1) {\n        return 1;\n    return 0;\n}", "int main() {\n    if (1) {\n        return 1;\n    }\n    return 0;\n}", "P004"),
        ("Unclosed parenthesis in expression", "int main() {\n    int a = 1, b = 2;\n    int res = (a + b;\n    return res;\n}", "int main() {\n    int a = 1, b = 2;\n    int res = (a + b);\n    return res;\n}", "P004"),
        ("Missing semicolon after enum declaration", "enum Color { RED, GREEN, BLUE }\nint main() { return 0; }", "enum Color { RED, GREEN, BLUE };\nint main() { return 0; }", "P003"),
        ("Missing semicolon between consecutive statements", "int main() {\n    int x = 1\n    int y = 2;\n    return x + y;\n}", "int main() {\n    int x = 1;\n    int y = 2;\n    return x + y;\n}", "P003"),
        ("Missing semicolon in do-while", "int main() {\n    int i = 0;\n    do { i++; } while (i < 5)\n    return 0;\n}", "int main() {\n    int i = 0;\n    do { i++; } while (i < 5);\n    return 0;\n}", "P003")
    ])
]

with open(os.path.join(corpus_dir, "01_syntax_delimiters.json"), "w", encoding="utf-8") as f:
    json.dump(syn_cases, f, indent=2)

# 2. Expression Repairs (25 cases)
exp_cases = [
    {
        "id": f"EXP_{i+1:03d}",
        "category": "Expression_Repairs",
        "difficulty": "Medium",
        "description": desc,
        "buggy_code": buggy,
        "expected_fix": expected,
        "expected_error_code": "P002"
    }
    for i, (desc, buggy, expected) in enumerate([
        ("Concatenated identifiers with plus", "int main() {\n    int a = 1, b = 2;\n    int res = ab+;\n    return res;\n}", "int main() {\n    int a = 1, b = 2;\n    int res = a + b;\n    return res;\n}"),
        ("Concatenated identifiers with multiply", "int main() {\n    int c = 3, d = 4;\n    int res = cd*;\n    return res;\n}", "int main() {\n    int c = 3, d = 4;\n    int res = c * d;\n    return res;\n}"),
        ("Concatenated identifiers with minus", "int main() {\n    int x = 5, y = 2;\n    int res = xy-;\n    return res;\n}", "int main() {\n    int x = 5, y = 2;\n    int res = x - y;\n    return res;\n}"),
        ("Concatenated identifiers with divide", "int main() {\n    int j = 10, k = 2;\n    int res = jk/;\n    return res;\n}", "int main() {\n    int j = 10, k = 2;\n    int res = j / k;\n    return res;\n}"),
        ("Parenthesized concatenated with plus", "int main() {\n    int a = 1, b = 2;\n    int res = (ab+);\n    return res;\n}", "int main() {\n    int a = 1, b = 2;\n    int res = (a + b);\n    return res;\n}"),
        ("Concatenated compound expression", "int main() {\n    int a = 1, b = 2, c = 3;\n    int res = (a+bc*);\n    return res;\n}", "int main() {\n    int a = 1, b = 2, c = 3;\n    int res = (a + b * c);\n    return res;\n}"),
        ("Concatenated in assignment", "int main() {\n    int a = 2, b = 3, res = 0;\n    res = ab+;\n    return res;\n}", "int main() {\n    int a = 2, b = 3, res = 0;\n    res = a + b;\n    return res;\n}"),
        ("Concatenated in multiplication assignment", "int main() {\n    int x = 4, y = 5, val = 0;\n    val = xy*;\n    return val;\n}", "int main() {\n    int x = 4, y = 5, val = 0;\n    val = x * y;\n    return val;\n}"),
        ("Concatenated named variables", "int main() {\n    int num1 = 10, num2 = 20;\n    int sum = num1num2+;\n    return sum;\n}", "int main() {\n    int num1 = 10, num2 = 20;\n    int sum = num1 + num2;\n    return sum;\n}"),
        ("Implicit multiplication before parenthesis", "int main() {\n    int a = 1, b = 2;\n    int res = 2(a + b);\n    return res;\n}", "int main() {\n    int a = 1, b = 2;\n    int res = 2 * (a + b);\n    return res;\n}"),
        ("Implicit multiplication on identifier x", "int main() {\n    int x = 5;\n    int res = 3x;\n    return res;\n}", "int main() {\n    int x = 5;\n    int res = 3 * x;\n    return res;\n}"),
        ("Implicit multiplication on identifier y", "int main() {\n    int y = 7;\n    int res = 5y;\n    return res;\n}", "int main() {\n    int y = 7;\n    int res = 5 * y;\n    return res;\n}"),
        ("Duplicate plus operators in binary expression", "int main() {\n    int a = 1, b = 2;\n    int res = a + + b;\n    return res;\n}", "int main() {\n    int a = 1, b = 2;\n    int res = a + b;\n    return res;\n}"),
        ("Duplicate minus operators in binary expression", "int main() {\n    int x = 5, y = 3;\n    int res = x - - y;\n    return res;\n}", "int main() {\n    int x = 5, y = 3;\n    int res = x - y;\n    return res;\n}"),
        ("Adjacent plus and multiply operators", "int main() {\n    int a = 2, b = 3;\n    int res = a + * b;\n    return res;\n}", "int main() {\n    int a = 2, b = 3;\n    int res = a + b;\n    return res;\n}"),
        ("Adjacent minus and divide operators", "int main() {\n    int a = 2, b = 3;\n    int res = a - / b;\n    return res;\n}", "int main() {\n    int a = 2, b = 3;\n    int res = a - b;\n    return res;\n}"),
        ("Adjacent multiply and divide operators", "int main() {\n    int x = 6, y = 2;\n    int res = x * / y;\n    return res;\n}", "int main() {\n    int x = 6, y = 2;\n    int res = x * y;\n    return res;\n}"),
        ("Parenthesized groups implicit multiplication", "int main() {\n    int x = 1, y = 2, z = 3;\n    int res = (x + y)(z);\n    return res;\n}", "int main() {\n    int x = 1, y = 2, z = 3;\n    int res = (x + y) * (z);\n    return res;\n}"),
        ("Single variable parentheses multiplication", "int main() {\n    int a = 4, b = 5;\n    int res = (a)(b);\n    return res;\n}", "int main() {\n    int a = 4, b = 5;\n    int res = (a) * (b);\n    return res;\n}"),
        ("Constant and parenthesized multiplication", "int main() {\n    int k = 3;\n    int res = 10(k);\n    return res;\n}", "int main() {\n    int k = 3;\n    int res = 10 * (k);\n    return res;\n}"),
        ("Concatenated expression in return statement", "int main() {\n    int u = 3, v = 4;\n    return uv+;\n}", "int main() {\n    int u = 3, v = 4;\n    return u + v;\n}"),
        ("Concatenated multiplication in initialization", "int main() {\n    int p = 5, q = 6;\n    int total = pq*;\n    return total;\n}", "int main() {\n    int p = 5, q = 6;\n    int total = p * q;\n    return total;\n}"),
        ("Concatenated subtraction in argument", "int helper(int v) { return v; }\nint main() {\n    int m = 8, n = 3;\n    return helper(mn-);\n}", "int helper(int v) { return v; }\nint main() {\n    int m = 8, n = 3;\n    return helper(m - n);\n}"),
        ("Compound expression in loop update", "int main() {\n    int r = 1, s = 2, t = 3;\n    r = st*;\n    return r;\n}", "int main() {\n    int r = 1, s = 2, t = 3;\n    r = s * t;\n    return r;\n}"),
        ("Concatenated division in variable initialization", "int main() {\n    int num = 20, den = 4;\n    int res = numden/;\n    return res;\n}", "int main() {\n    int num = 20, den = 4;\n    int res = num / den;\n    return res;\n}")
    ])
]

with open(os.path.join(corpus_dir, "02_expression_repairs.json"), "w", encoding="utf-8") as f:
    json.dump(exp_cases, f, indent=2)

# 3. Cross-Language (15 cases)
cro_cases = [
    {
        "id": f"CRO_{i+1:03d}",
        "category": "Cross_Language",
        "difficulty": "Easy" if i < 10 else "Medium",
        "description": desc,
        "buggy_code": buggy,
        "expected_fix": expected,
        "expected_error_code": "P005"
    }
    for i, (desc, buggy, expected) in enumerate([
        ("Python def function header", "def add(int a, int b):\n    return a + b;\n", "int add(int a, int b) {\n    return a + b;\n}\n"),
        ("Python elif statement", "int main() {\n    int x = 5;\n    if (x > 10) {\n        return 1;\n    }\n    elif (x > 0):\n        return 2;\n    return 0;\n}", "int main() {\n    int x = 5;\n    if (x > 10) {\n        return 1;\n    }\n    else if (x > 0) {\n        return 2;\n    }\n    return 0;\n}"),
        ("Python print call", 'int main() {\n    print("Hello world!");\n    return 0;\n}', '#include <iostream>\nint main() {\n    std::cout << "Hello world!" << std::endl;\n    return 0;\n}'),
        ("Python True boolean literal", "int main() {\n    bool flag = True;\n    return 0;\n}", "int main() {\n    bool flag = true;\n    return 0;\n}"),
        ("Python False boolean literal", "int main() {\n    bool flag = False;\n    return 0;\n}", "int main() {\n    bool flag = false;\n    return 0;\n}"),
        ("Python None pointer literal", "int main() {\n    int* ptr = None;\n    return 0;\n}", "int main() {\n    int* ptr = nullptr;\n    return 0;\n}"),
        ("Java boolean keyword", "int main() {\n    boolean active = true;\n    return 0;\n}", "int main() {\n    bool active = true;\n    return 0;\n}"),
        ("Java System.out.println call", 'int main() {\n    System.out.println("Java style");\n    return 0;\n}', '#include <iostream>\nint main() {\n    std::cout << "Java style" << std::endl;\n    return 0;\n}'),
        ("JS null pointer literal", "int main() {\n    int* p = null;\n    return 0;\n}", "int main() {\n    int* p = nullptr;\n    return 0;\n}"),
        ("Python and keyword", "int main() {\n    bool a = true, b = true;\n    if (a and b) {\n        return 1;\n    }\n    return 0;\n}", "int main() {\n    bool a = true, b = true;\n    if (a && b) {\n        return 1;\n    }\n    return 0;\n}"),
        ("Python or keyword", "int main() {\n    bool a = false, b = true;\n    if (a or b) {\n        return 1;\n    }\n    return 0;\n}", "int main() {\n    bool a = false, b = true;\n    if (a || b) {\n        return 1;\n    }\n    return 0;\n}"),
        ("Python def main entry", "def main():\n    return 0;\n", "int main() {\n    return 0;\n}\n"),
        ("Python colon on if statement", "int main() {\n    int x = 1;\n    if (x > 0):\n        return 1;\n    return 0;\n}", "int main() {\n    int x = 1;\n    if (x > 0) {\n        return 1;\n    }\n    return 0;\n}"),
        ("Python colon on while statement", "int main() {\n    int i = 0;\n    while (i < 5):\n        i++;\n    return 0;\n}", "int main() {\n    int i = 0;\n    while (i < 5) {\n        i++;\n    }\n    return 0;\n}"),
        ("Python colon on else statement", "int main() {\n    int x = 0;\n    if (x > 0) {\n        return 1;\n    }\n    else:\n        return 0;\n}", "int main() {\n    int x = 0;\n    if (x > 0) {\n        return 1;\n    }\n    else {\n        return 0;\n    }\n}")
    ])
]

with open(os.path.join(corpus_dir, "03_cross_language.json"), "w", encoding="utf-8") as f:
    json.dump(cro_cases, f, indent=2)

# 4. Missing Headers & NS (20 cases)
hdr_cases = [
    {
        "id": f"HDR_{i+1:03d}",
        "category": "Missing_Headers_NS",
        "difficulty": "Easy",
        "description": desc,
        "buggy_code": buggy,
        "expected_fix": expected,
        "expected_error_code": err
    }
    for i, (desc, buggy, expected, err) in enumerate([
        ("std::cout without iostream", 'int main() {\n    std::cout << "test";\n    return 0;\n}', '#include <iostream>\nint main() {\n    std::cout << "test";\n    return 0;\n}', "E015"),
        ("std::cin without iostream", "int main() {\n    int x;\n    std::cin >> x;\n    return 0;\n}", "#include <iostream>\nint main() {\n    int x;\n    std::cin >> x;\n    return 0;\n}", "E015"),
        ("std::vector without vector header", "int main() {\n    std::vector<int> v;\n    return 0;\n}", "#include <vector>\nint main() {\n    std::vector<int> v;\n    return 0;\n}", "E015"),
        ("std::string without string header", 'int main() {\n    std::string s = "hello";\n    return 0;\n}', '#include <string>\nint main() {\n    std::string s = "hello";\n    return 0;\n}', "E015"),
        ("std::map without map header", "int main() {\n    std::map<int, int> m;\n    return 0;\n}", "#include <map>\nint main() {\n    std::map<int, int> m;\n    return 0;\n}", "E015"),
        ("std::set without set header", "int main() {\n    std::set<int> st;\n    return 0;\n}", "#include <set>\nint main() {\n    std::set<int> st;\n    return 0;\n}", "E015"),
        ("std::sqrt without cmath header", "int main() {\n    double r = std::sqrt(16.0);\n    return 0;\n}", "#include <cmath>\nint main() {\n    double r = std::sqrt(16.0);\n    return 0;\n}", "E015"),
        ("std::pow without cmath header", "int main() {\n    double p = std::pow(2.0, 8.0);\n    return 0;\n}", "#include <cmath>\nint main() {\n    double p = std::pow(2.0, 8.0);\n    return 0;\n}", "E015"),
        ("std::sort without algorithm header", "int main() {\n    int arr[3] = {3, 1, 2};\n    std::sort(arr, arr + 3);\n    return 0;\n}", "#include <algorithm>\nint main() {\n    int arr[3] = {3, 1, 2};\n    std::sort(arr, arr + 3);\n    return 0;\n}", "E015"),
        ("std::ifstream without fstream header", 'int main() {\n    std::ifstream file("input.txt");\n    return 0;\n}', '#include <fstream>\nint main() {\n    std::ifstream file("input.txt");\n    return 0;\n}', "E015"),
        ("std::ofstream without fstream header", 'int main() {\n    std::ofstream file("output.txt");\n    return 0;\n}', '#include <fstream>\nint main() {\n    std::ofstream file("output.txt");\n    return 0;\n}', "E015"),
        ("std::stringstream without sstream header", "int main() {\n    std::stringstream ss;\n    return 0;\n}", "#include <sstream>\nint main() {\n    std::stringstream ss;\n    return 0;\n}", "E015"),
        ("std::unique_ptr without memory header", "int main() {\n    std::unique_ptr<int> p;\n    return 0;\n}", "#include <memory>\nint main() {\n    std::unique_ptr<int> p;\n    return 0;\n}", "E015"),
        ("std::shared_ptr without memory header", "int main() {\n    std::shared_ptr<int> p;\n    return 0;\n}", "#include <memory>\nint main() {\n    std::shared_ptr<int> p;\n    return 0;\n}", "E015"),
        ("std::pair without utility header", "int main() {\n    std::pair<int, int> p = {1, 2};\n    return 0;\n}", "#include <utility>\nint main() {\n    std::pair<int, int> p = {1, 2};\n    return 0;\n}", "E015"),
        ("std::tuple without tuple header", "int main() {\n    std::tuple<int, char> t;\n    return 0;\n}", "#include <tuple>\nint main() {\n    std::tuple<int, char> t;\n    return 0;\n}", "E015"),
        ("std::stack without stack header", "int main() {\n    std::stack<int> s;\n    return 0;\n}", "#include <stack>\nint main() {\n    std::stack<int> s;\n    return 0;\n}", "E015"),
        ("std::queue without queue header", "int main() {\n    std::queue<int> q;\n    return 0;\n}", "#include <queue>\nint main() {\n    std::queue<int> q;\n    return 0;\n}", "E015"),
        ("Unqualified cout without std namespace", 'int main() {\n    cout << "hello";\n    return 0;\n}', '#include <iostream>\nint main() {\n    std::cout << "hello";\n    return 0;\n}', "E015"),
        ("Unqualified vector without std namespace", "int main() {\n    vector<int> v;\n    return 0;\n}", "#include <vector>\nint main() {\n    std::vector<int> v;\n    return 0;\n}", "E015")
    ])
]

with open(os.path.join(corpus_dir, "04_missing_headers_ns.json"), "w", encoding="utf-8") as f:
    json.dump(hdr_cases, f, indent=2)

# 5. Operator Misuse (15 cases)
opr_cases = [
    {
        "id": f"OPR_{i+1:03d}",
        "category": "Operator_Misuse",
        "difficulty": "Medium",
        "description": desc,
        "buggy_code": buggy,
        "expected_fix": expected,
        "expected_error_code": err
    }
    for i, (desc, buggy, expected, err) in enumerate([
        ("Assignment in if condition", "int main() {\n    int x = 0;\n    if (x = 5) {\n        return 1;\n    }\n    return 0;\n}", "int main() {\n    int x = 0;\n    if (x == 5) {\n        return 1;\n    }\n    return 0;\n}", "W002"),
        ("Assignment in while condition", "int main() {\n    int p = 1;\n    while (p = 0) {\n        return 1;\n    }\n    return 0;\n}", "int main() {\n    int p = 1;\n    while (p == 0) {\n        return 1;\n    }\n    return 0;\n}", "W002"),
        ("Bitwise XOR instead of exponentiation literal", "int main() {\n    int x = 2 ^ 8;\n    return x;\n}", "int main() {\n    int x = (1 << 8);\n    return x;\n}", "W003"),
        ("Bitwise XOR power of 10", "int main() {\n    int k = 10 ^ 3;\n    return k;\n}", "#include <cmath>\nint main() {\n    int k = std::pow(10, 3);\n    return k;\n}", "W003"),
        ("Bitwise XOR square variable", "int main() {\n    int r = 5;\n    int sq = r ^ 2;\n    return sq;\n}", "int main() {\n    int r = 5;\n    int sq = r * r;\n    return sq;\n}", "W003"),
        ("Chained comparison three terms", "int main() {\n    int x = 5;\n    if (1 < x < 10) {\n        return 1;\n    }\n    return 0;\n}", "int main() {\n    int x = 5;\n    if (1 < x && x < 10) {\n        return 1;\n    }\n    return 0;\n}", "W004"),
        ("Chained comparison score bounds", "int main() {\n    int score = 50;\n    if (10 <= score <= 100) {\n        return 1;\n    }\n    return 0;\n}", "int main() {\n    int score = 50;\n    if (10 <= score && score <= 100) {\n        return 1;\n    }\n    return 0;\n}", "W004"),
        ("Chained comparison lower zero", "int main() {\n    int a = 2;\n    if (0 <= a < 5) {\n        return 1;\n    }\n    return 0;\n}", "int main() {\n    int a = 2;\n    if (0 <= a && a < 5) {\n        return 1;\n    }\n    return 0;\n}", "W004"),
        ("Bitwise AND in boolean context", "int main() {\n    bool a = true, b = false;\n    if (a & b) {\n        return 1;\n    }\n    return 0;\n}", "int main() {\n    bool a = true, b = false;\n    if (a && b) {\n        return 1;\n    }\n    return 0;\n}", "W005"),
        ("Bitwise OR in boolean context", "int main() {\n    int x = 5, y = 20;\n    if ((x > 0) | (y < 10)) {\n        return 1;\n    }\n    return 0;\n}", "int main() {\n    int x = 5, y = 20;\n    if ((x > 0) || (y < 10)) {\n        return 1;\n    }\n    return 0;\n}", "W005"),
        ("Constant array index out of bounds", "int main() {\n    int arr[5];\n    arr[5] = 10;\n    return 0;\n}", "int main() {\n    int arr[5];\n    arr[4] = 10;\n    return 0;\n}", "W006"),
        ("Negative array indexing", "int main() {\n    int arr[5];\n    int last = arr[-1];\n    return last;\n}", "int main() {\n    int arr[5];\n    int last = arr[4];\n    return last;\n}", "W006"),
        ("Off-by-one loop condition <= size", "int main() {\n    int arr[5];\n    for (int i = 0; i <= 5; i++) {\n        arr[i] = i;\n    }\n    return 0;\n}", "int main() {\n    int arr[5];\n    for (int i = 0; i < 5; i++) {\n        arr[i] = i;\n    }\n    return 0;\n}", "W007"),
        ("1-based indexing on 0-based array", "int main() {\n    int arr[5];\n    for (int i = 1; i <= 5; i++) {\n        arr[i] = i;\n    }\n    return 0;\n}", "int main() {\n    int arr[5];\n    for (int i = 0; i < 5; i++) {\n        arr[i] = i;\n    }\n    return 0;\n}", "W007"),
        ("Off-by-one while loop condition", "int main() {\n    int arr[5];\n    int i = 0;\n    while (i <= 5) {\n        arr[i] = 0;\n        i++;\n    }\n    return 0;\n}", "int main() {\n    int arr[5];\n    int i = 0;\n    while (i < 5) {\n        arr[i] = 0;\n        i++;\n    }\n    return 0;\n}", "W007")
    ])
]

with open(os.path.join(corpus_dir, "05_operator_misuse.json"), "w", encoding="utf-8") as f:
    json.dump(opr_cases, f, indent=2)

# 6. Clean Control (20 cases)
cln_cases = [
    {
        "id": f"CLN_{i+1:03d}",
        "category": "Clean_Control",
        "difficulty": "Easy",
        "description": desc,
        "buggy_code": code,
        "expected_fix": code,
        "expected_error_code": ""
    }
    for i, (desc, code) in enumerate([
        ("Minimal clean main", "int main() {\n    return 0;\n}\n"),
        ("Basic arithmetic operations", "int main() {\n    int a = 10, b = 20;\n    int c = a + b * 2;\n    return c;\n}\n"),
        ("Standard while loop", "int main() {\n    int i = 0;\n    while (i < 10) {\n        i++;\n    }\n    return i;\n}\n"),
        ("Standard for loop with array", "int main() {\n    int arr[5];\n    for (int i = 0; i < 5; i++) {\n        arr[i] = i * 2;\n    }\n    return arr[0];\n}\n"),
        ("Function declaration and call", "int add(int a, int b) {\n    return a + b;\n}\nint main() {\n    return add(3, 4);\n}\n"),
        ("Clean struct declaration and usage", "struct Point {\n    int x;\n    int y;\n};\nint main() {\n    Point p;\n    p.x = 1;\n    p.y = 2;\n    return p.x + p.y;\n}\n"),
        ("Clean class declaration", "class Counter {\npublic:\n    int val;\n    void inc() { val++; }\n};\nint main() {\n    Counter c;\n    c.val = 0;\n    c.inc();\n    return c.val;\n}\n"),
        ("Proper iostream include and output", '#include <iostream>\nint main() {\n    std::cout << "Hello clean!" << std::endl;\n    return 0;\n}\n'),
        ("Valid equality comparison in if", "int main() {\n    int x = 5;\n    if (x == 5) {\n        return 1;\n    }\n    return 0;\n}\n"),
        ("Valid logical AND in condition", "int main() {\n    int x = 5;\n    if (x > 0 && x < 10) {\n        return 1;\n    }\n    return 0;\n}\n"),
        ("Genuine bitwise XOR between integers", "int main() {\n    int a = 10;\n    int b = 5;\n    int mask = a ^ b;\n    return mask;\n}\n"),
        ("Genuine bitwise AND masking", "int main() {\n    int flags = 255;\n    int masked = flags & 15;\n    return masked;\n}\n"),
        ("Array indexing with constant in bounds", "int main() {\n    int arr[10];\n    arr[0] = 1;\n    arr[9] = 2;\n    return arr[0] + arr[9];\n}\n"),
        ("Clean switch statement", "int main() {\n    int opt = 2;\n    switch (opt) {\n        case 1: return 10;\n        case 2: return 20;\n        default: return 0;\n    }\n}\n"),
        ("Const variable usage", "int main() {\n    const int MAX = 100;\n    int x = MAX - 10;\n    return x;\n}\n"),
        ("Pointer referencing and dereferencing", "int main() {\n    int val = 42;\n    int* ptr = &val;\n    return *ptr;\n}\n"),
        ("Nested loops with independent induction variables", "int main() {\n    int sum = 0;\n    for (int i = 0; i < 3; i++) {\n        for (int j = 0; j < 3; j++) {\n            sum += i + j;\n        }\n    }\n    return sum;\n}\n"),
        ("Recursive factorial", "int fact(int n) {\n    if (n <= 1) return 1;\n    return n * fact(n - 1);\n}\nint main() {\n    return fact(5);\n}\n"),
        ("Proper if-else if-else chain", "int main() {\n    int x = 5;\n    if (x > 10) {\n        return 1;\n    } else if (x > 0) {\n        return 2;\n    } else {\n        return 0;\n    }\n}\n"),
        ("Valid do-while loop with semicolon", "int main() {\n    int i = 0;\n    do {\n        i++;\n    } while (i < 5);\n    return i;\n}\n")
    ])
]

with open(os.path.join(corpus_dir, "06_clean_control.json"), "w", encoding="utf-8") as f:
    json.dump(cln_cases, f, indent=2)

print("Regenerated all 120 corpus cases successfully.")
