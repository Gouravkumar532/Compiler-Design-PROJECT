import unittest
from src.formatter import Formatter

class TestFormatter(unittest.TestCase):
    def setUp(self):
        self.formatter = Formatter()

    def test_format_preserves_ifdef_else_endif(self):
        src = (
            "#ifdef FOO\n"
            "int get_val() {\n"
            "    return 1;\n"
            "}\n"
            "#else\n"
            "int get_val() {\n"
            "    return 2;\n"
            "}\n"
            "#endif\n"
            "\n"
            "int main() {\n"
            "    return get_val();\n"
            "}\n"
        )
        formatted = self.formatter.format_source(src, "main.cpp")
        self.assertIn("#ifdef FOO", formatted)
        self.assertIn("#else", formatted)
        self.assertIn("#endif", formatted)
        self.assertIn("return 1;", formatted)
        self.assertIn("return 2;", formatted)
        self.assertIn("int main() {", formatted)

    def test_format_preserves_conditional_inside_function(self):
        src = (
            "int calculate() {\n"
            "#if defined(FAST)\n"
            "    return 10;\n"
            "#elif defined(SLOW)\n"
            "    return 20;\n"
            "#else\n"
            "    return 0;\n"
            "#endif\n"
            "}\n"
        )
        formatted = self.formatter.format_source(src, "main.cpp")
        self.assertIn("#if defined(FAST)", formatted)
        self.assertIn("#elif defined(SLOW)", formatted)
        self.assertIn("#else", formatted)
        self.assertIn("#endif", formatted)
        self.assertIn("return 10;", formatted)
        self.assertIn("return 20;", formatted)
        self.assertIn("return 0;", formatted)

    def test_format_normal_source(self):
        src = (
            "#include <iostream>\n"
            "int main() {\n"
            "int a = 1;\n"
            "return a;\n"
            "}\n"
        )
        formatted = self.formatter.format_source(src, "main.cpp")
        self.assertIn("#include <iostream>", formatted)
        self.assertIn("int main() {", formatted)
        self.assertIn("    int a = 1;", formatted)
        self.assertIn("    return a;", formatted)

if __name__ == "__main__":
    unittest.main()
