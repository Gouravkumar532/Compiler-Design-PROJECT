"""
Unit Test Suite for Intelligent Namespace Resolution & Scope Qualification (Idea 5)
"""

import os
import subprocess
import tempfile
import unittest

from src.lexer import Lexer
from src.parser import Parser
from src.semantic import SemanticAnalyzer
from src.preprocessor import Preprocessor
from src.stdlib_registry import StdlibRegistry, registry
from src.namespace_resolution import NamespaceResolutionEngine, UnqualifiedNamespaceDiagnostic
from src.repair_coordinator import repair_source
from src.error_catalogue import ERROR_CATALOGUE
from src.errors import explain_error


class TestNamespaceIndexing(unittest.TestCase):
    """Tests for namespace symbol table indexing."""

    def setUp(self):
        self.engine = NamespaceResolutionEngine("")

    def test_std_namespace_indexed(self):
        self.assertIn("std", self.engine.namespace_symbol_index)
        std_syms = self.engine.namespace_symbol_index["std"]
        self.assertIn("cout", std_syms)
        self.assertIn("cin", std_syms)
        self.assertIn("endl", std_syms)
        self.assertIn("vector", std_syms)
        self.assertIn("string", std_syms)

    def test_user_namespace_registration(self):
        self.engine.register_user_namespace("Geometry")
        self.engine.register_symbol("Geometry", "area")
        self.engine.register_symbol("Geometry", "perimeter")
        self.engine.register_symbol("Geometry", "PI")

        self.assertIn("Geometry", self.engine.user_namespaces)
        geom_syms = self.engine.namespace_symbol_index["Geometry"]
        self.assertIn("area", geom_syms)
        self.assertIn("perimeter", geom_syms)
        self.assertIn("PI", geom_syms)


class TestUnqualifiedLookupAndDisambiguation(unittest.TestCase):
    """Tests for unqualified lookup and candidate ranking."""

    def setUp(self):
        self.engine = NamespaceResolutionEngine("")
        self.engine.register_user_namespace("Math")
        self.engine.register_symbol("Math", "sqrt")
        self.engine.register_symbol("Math", "factorial")

    def test_std_lookup_requires_header_included(self):
        # When <iostream> is NOT included, "cout" should NOT be returned as a candidate for E016
        candidates_no_header = self.engine.find_candidate_namespaces("cout", set(), set())
        self.assertEqual(candidates_no_header, [])

        # When <iostream> IS included, "cout" should be recognized in "std"
        candidates_with_header = self.engine.find_candidate_namespaces("cout", set(), {"iostream"})
        self.assertEqual(candidates_with_header, ["std"])

    def test_active_namespace_ignored(self):
        # If 'std' is already active, it shouldn't be suggested
        candidates = self.engine.find_candidate_namespaces("cout", {"std"}, {"iostream"})
        self.assertEqual(candidates, [])

    def test_user_namespace_prioritized_over_std(self):
        # Both Math and std have sqrt (when cmath is included)
        # Local user namespace Math should be prioritized
        candidates = self.engine.find_candidate_namespaces("sqrt", set(), {"cmath"})
        self.assertEqual(candidates[0], "Math")

    def test_unknown_symbol_returns_no_candidates(self):
        candidates = self.engine.find_candidate_namespaces("totally_unrelated_var", set(), {"iostream"})
        self.assertEqual(candidates, [])


class TestDualFixGeneration(unittest.TestCase):
    """Tests for Option A (qualification) and Option B (using directive) patch generation."""

    def setUp(self):
        self.engine = NamespaceResolutionEngine("")

    def test_option_a_single_qualification(self):
        source = "int main() {\n    cout << 42;\n}\n"
        diag = UnqualifiedNamespaceDiagnostic(
            symbol="cout",
            namespace="std",
            line=2,
            col=5,
            length=4,
        )
        patched = self.engine.generate_qualification_patch(source, [diag])
        self.assertIn("std::cout << 42;", patched)

    def test_option_a_multiple_symbols_same_line(self):
        source = "int main() {\n    cout << \"Hello\" << endl;\n}\n"
        diag1 = UnqualifiedNamespaceDiagnostic(symbol="cout", namespace="std", line=2, col=5, length=4)
        diag2 = UnqualifiedNamespaceDiagnostic(symbol="endl", namespace="std", line=2, col=24, length=4)
        patched = self.engine.generate_qualification_patch(source, [diag1, diag2])
        self.assertIn("std::cout << \"Hello\" << std::endl;", patched)

    def test_option_a_user_namespace_function_and_class(self):
        source = "int main() {\n    Circle c;\n    double a = area(5.0);\n}\n"
        diag_cls = UnqualifiedNamespaceDiagnostic(symbol="Circle", namespace="Geometry", line=2, col=5, length=6)
        diag_fn = UnqualifiedNamespaceDiagnostic(symbol="area", namespace="Geometry", line=3, col=16, length=4)
        patched = self.engine.generate_qualification_patch(source, [diag_cls, diag_fn])
        self.assertIn("Geometry::Circle c;", patched)
        self.assertIn("double a = Geometry::area(5.0);", patched)

    def test_option_b_std_using_directive_after_includes(self):
        source = "#include <iostream>\n\nint main() {\n    cout << 10;\n}\n"
        diag = UnqualifiedNamespaceDiagnostic(symbol="cout", namespace="std", line=4, col=5, length=4)
        patched = self.engine.generate_using_patch(source, [diag])
        self.assertIn("using namespace std;", patched)
        # Placed before int main()
        self.assertTrue(patched.index("using namespace std;") < patched.index("int main()"))

    def test_option_b_user_namespace_using_directive_after_def(self):
        source = "namespace Geometry {\n    double area(double r) { return 3.14 * r * r; }\n}\n\nint main() {\n    double a = area(2.0);\n}\n"
        diag = UnqualifiedNamespaceDiagnostic(symbol="area", namespace="Geometry", line=6, col=16, length=4)
        patched = self.engine.generate_using_patch(source, [diag])
        self.assertIn("using Geometry::area;", patched)
        self.assertTrue(patched.index("using Geometry::area;") < patched.index("int main()"))

    def test_option_b_idempotent_no_duplicate(self):
        source = "#include <iostream>\nusing namespace std;\n\nint main() {\n    cout << 10;\n}\n"
        diag = UnqualifiedNamespaceDiagnostic(symbol="cout", namespace="std", line=5, col=5, length=4)
        patched = self.engine.generate_using_patch(source, [diag])
        self.assertEqual(patched.count("using namespace std;"), 1)


class TestSemanticNamespaceDiagnostics(unittest.TestCase):
    """Tests semantic analyzer diagnostic emission for unqualified symbols."""

    def test_pattern_1_unqualified_cout_with_iostream(self):
        code = "#include <iostream>\n\nint main() {\n    cout << \"Hello\" << endl;\n    return 0;\n}\n"
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", included_headers=prep.included_headers, exit_on_error=False)
        sem.analyze(ast)

        self.assertGreaterEqual(len(sem.namespace_diagnostics), 2)
        sym_names = [d.symbol for d in sem.namespace_diagnostics]
        self.assertIn("cout", sym_names)
        self.assertIn("endl", sym_names)
        for d in sem.namespace_diagnostics:
            self.assertEqual(d.namespace, "std")

    def test_pattern_1_unqualified_vector_and_string(self):
        code = "#include <vector>\n#include <string>\n\nint main() {\n    vector<int> v;\n    string s = \"hi\";\n    return 0;\n}\n"
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", included_headers=prep.included_headers, exit_on_error=False)
        sem.analyze(ast)

        sym_names = [d.symbol for d in sem.namespace_diagnostics]
        self.assertIn("vector", sym_names)
        self.assertIn("string", sym_names)

    def test_pattern_2_user_namespace_unqualified_call(self):
        code = "namespace Geometry {\n    double area(double r) { return 3.14 * r * r; }\n}\n\nint main() {\n    double a = area(5.0);\n    return 0;\n}\n"
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", included_headers=prep.included_headers, exit_on_error=False)
        sem.analyze(ast)

        self.assertGreaterEqual(len(sem.namespace_diagnostics), 1)
        diag = sem.namespace_diagnostics[0]
        self.assertEqual(diag.symbol, "area")
        self.assertEqual(diag.namespace, "Geometry")
        self.assertEqual(diag.fix_option_a, "Geometry::area")
        self.assertEqual(diag.fix_option_b, "using Geometry::area;")

    def test_user_namespace_class_and_variable(self):
        code = """namespace Math {
    int CONSTANT_VAL = 42;
    class Calculator {
    public:
        int add(int a, int b) { return a + b; }
    };
}

int main() {
    Calculator calc;
    int v = CONSTANT_VAL;
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", included_headers=prep.included_headers, exit_on_error=False)
        sem.analyze(ast)

        sym_names = [d.symbol for d in sem.namespace_diagnostics]
        self.assertIn("Calculator", sym_names)
        self.assertIn("CONSTANT_VAL", sym_names)
        for d in sem.namespace_diagnostics:
            self.assertEqual(d.namespace, "Math")

    def test_using_namespace_directive_silences_diagnostic(self):
        code = "#include <iostream>\nusing namespace std;\n\nint main() {\n    cout << 42 << endl;\n    return 0;\n}\n"
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", included_headers=prep.included_headers, exit_on_error=False)
        sem.analyze(ast)

        self.assertEqual(len(sem.namespace_diagnostics), 0)
        self.assertEqual(sem.errors_count, 0)

    def test_using_declaration_specific_symbol_silences_diagnostic(self):
        code = "namespace Geometry {\n    int compute() { return 100; }\n}\n\nusing Geometry::compute;\n\nint main() {\n    return compute();\n}\n"
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", included_headers=prep.included_headers, exit_on_error=False)
        sem.analyze(ast)

        self.assertEqual(len(sem.namespace_diagnostics), 0)
        self.assertEqual(sem.errors_count, 0)

    def test_explicit_qualification_causes_no_errors(self):
        code = "namespace Geometry {\n    int compute() { return 100; }\n}\n\nint main() {\n    return Geometry::compute();\n}\n"
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", included_headers=prep.included_headers, exit_on_error=False)
        sem.analyze(ast)

        self.assertEqual(len(sem.namespace_diagnostics), 0)
        self.assertEqual(sem.errors_count, 0)

    def test_multiple_unqualified_symbols_in_same_expression(self):
        code = """#include <iostream>
#include <string>

int main() {
    std::string s = "hello";
    cout << s.length() << endl;
    return 0;
}
"""
        repaired = repair_source("<test>", code, confidence_policy="all")
        self.assertTrue(repaired.success)
        self.assertIn("std::cout << s.length() << std::endl;", repaired.updated_source)

    def test_symbol_collisions_multiple_namespaces(self):
        code = """namespace Geometry {
    double area(double r) { return 3.14 * r * r; }
}
namespace Physics {
    double area(double r) { return r * r; }
}

int main() {
    double a = area(2.0);
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        # First defined namespace Geometry takes priority
        self.assertEqual(len(sem.namespace_diagnostics), 1)
        diag = sem.namespace_diagnostics[0]
        self.assertEqual(diag.namespace, "Geometry")
        self.assertEqual(diag.fix_option_a, "Geometry::area")

    def test_base_class_unqualified_namespace(self):
        code = """namespace Shapes {
    class BaseShape {
    public:
        int id;
    };
}

class Square : public BaseShape {
public:
    int side;
};

int main() {
    Square sq;
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        self.assertGreaterEqual(len(sem.namespace_diagnostics), 1)
        diag = sem.namespace_diagnostics[0]
        self.assertEqual(diag.symbol, "BaseShape")
        self.assertEqual(diag.namespace, "Shapes")

    def test_typo_safety_prefers_local_variable_over_namespace(self):
        code = """int main() {
    int count = 10;
    cont++;
    return 0;
}
"""
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(processed, "<test>", exit_on_error=False)
        sem.analyze(ast)

        # 'cont' is NOT in any namespace, so namespace_diagnostics must be empty
        self.assertEqual(len(sem.namespace_diagnostics), 0)
        # Should report undeclared identifier E001
        self.assertGreaterEqual(sem.errors_count, 1)


class TestAutoFixNamespaceRepairs(unittest.TestCase):
    """Tests automatic repair execution for Option 1 and Option 2."""

    def test_autofix_qualifies_std_symbols(self):
        code = "#include <iostream>\n\nint main() {\n    cout << 42;\n    return 0;\n}\n"
        repaired = repair_source("<test>", code, confidence_policy="all")
        self.assertTrue(repaired.success)
        self.assertIn("std::cout", repaired.updated_source)

    def test_autofix_qualifies_user_namespace_symbols(self):
        code = "namespace Math {\n    int square(int x) { return x * x; }\n}\n\nint main() {\n    int res = square(5);\n    return 0;\n}\n"
        repaired = repair_source("<test>", code, confidence_policy="all")
        self.assertTrue(repaired.success)
        self.assertIn("Math::square(5)", repaired.updated_source)

    def test_autofix_option_2_using_declaration(self):
        code = "namespace Geometry {\n    double area(double r) { return 3.14 * r * r; }\n}\n\nint main() {\n    double a = area(5.0);\n    return 0;\n}\n"
        prep = Preprocessor()
        processed = prep.process(code, "<test>")
        tokens = Lexer(processed, "<test>").tokenize()
        ast = Parser(tokens, processed, "<test>").parse()
        sem = SemanticAnalyzer(
            processed,
            "<test>",
            included_headers=prep.included_headers,
            exit_on_error=False,
        )
        sem.analyze(ast)

        # Option 2 remains a pure patch-generation choice; application and
        # verification are owned by the shared coordinator/wizard layer.
        repaired = sem.namespace_engine.generate_using_patch(
            sem.source, sem.namespace_diagnostics
        )
        self.assertIn("using Geometry::area;", repaired)


class TestErrorCatalogueE016(unittest.TestCase):
    """Tests error catalogue registration for E016."""

    def test_e016_registered(self):
        self.assertIn("E016", ERROR_CATALOGUE)
        entry = ERROR_CATALOGUE["E016"]
        self.assertEqual(entry["title"], "Unqualified Namespace Symbol")
        self.assertIn("cout", entry["example_bad"])
        self.assertIn("std::cout", entry["example_good"])


class TestNamespaceResolutionCLIE2E(unittest.TestCase):
    """End-to-end command-line tests for c++ check, fix, and explain with E016."""

    def test_cli_check_fails_with_e016(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as f:
            f.write("#include <iostream>\n\nint main() {\n    cout << 100;\n    return 0;\n}\n")
            temp_path = f.name

        try:
            res = subprocess.run(
                ["python", "main.py", "check", temp_path],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("error[E016]", res.stdout)
            self.assertIn("std::cout", res.stdout)
            self.assertIn("using namespace std;", res.stdout)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_cli_explain_e016(self):
        res = subprocess.run(
            ["python", "main.py", "explain", "E016"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("E016: Unqualified Namespace Symbol", res.stdout)
        self.assertIn("Erroneous Code Example", res.stdout)
        self.assertIn("Recommended Fix", res.stdout)

    def test_cli_fix_in_place(self):
        with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False, encoding="utf-8") as f:
            f.write("#include <iostream>\n\nint main() {\n    cout << 100 << endl;\n    return 0;\n}\n")
            temp_path = f.name

        try:
            res = subprocess.run(
                ["python", "main.py", "fix", "-w", temp_path],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)

            with open(temp_path, "r", encoding="utf-8") as f:
                fixed_content = f.read()

            self.assertIn("std::cout", fixed_content)
            self.assertIn("std::endl", fixed_content)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
