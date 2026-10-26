import json
import os
import subprocess
import sys
import tempfile
import unittest

from src.benchmarks.benchmark_repair import (
    BenchmarkCase,
    BenchmarkRunner,
    BenchmarkSummary,
    CaseResult,
    CategoryMetrics,
)


class TestBenchmarkRepair(unittest.TestCase):
    """Exhaustive tests for the Error Repair & Recommendation Benchmark Suite (Idea 11)."""

    def setUp(self):
        self.runner = BenchmarkRunner()

    def test_corpus_loading_all_cases(self):
        cases = self.runner.load_corpus()
        self.assertGreaterEqual(len(cases), 120, "Corpus should contain at least 120 curated cases")
        categories = {c.category for c in cases}
        expected_categories = {
            "Syntax_Delimiters",
            "Expression_Repairs",
            "Cross_Language",
            "Missing_Headers_NS",
            "Operator_Misuse",
            "Clean_Control",
        }
        self.assertEqual(categories, expected_categories)

    def test_corpus_filtering_by_category(self):
        cases = self.runner.load_corpus(category_filter="Syntax")
        self.assertEqual(len(cases), 25)
        for c in cases:
            self.assertEqual(c.category, "Syntax_Delimiters")

    def test_run_single_clean_case(self):
        clean_case = BenchmarkCase(
            id="CLN_TEST",
            category="Clean_Control",
            difficulty="Easy",
            description="Clean code",
            buggy_code="int main() { return 0; }\n",
            expected_fix="int main() { return 0; }\n",
            expected_error_code="",
        )
        res = self.runner.run_case(clean_case)
        self.assertTrue(res.semantic_compile_pass)
        self.assertFalse(res.false_positive)
        self.assertTrue(res.exact_match)
        self.assertEqual(res.initial_error_count, 0)
        self.assertEqual(res.final_error_count, 0)

    def test_run_single_syntax_repair_case(self):
        syntax_case = BenchmarkCase(
            id="SYN_TEST",
            category="Syntax_Delimiters",
            difficulty="Easy",
            description="Missing semicolon",
            buggy_code="int main() {\n    int a = 10\n    return a;\n}",
            expected_fix="int main() {\n    int a = 10;\n    return a;\n}",
            expected_error_code="P003",
        )
        res = self.runner.run_case(syntax_case)
        self.assertTrue(res.semantic_compile_pass)
        self.assertTrue(res.expected_error_detected)
        self.assertIn("int a = 10;", res.repaired_code)

    def test_run_suite_metrics_and_formatting(self):
        summary = self.runner.run_suite(category_filter="Clean_Control")
        self.assertEqual(summary.total_cases, 20)
        self.assertEqual(summary.overall_false_positive_rate, 0.0)
        self.assertEqual(summary.overall_semantic_pass_rate, 100.0)

        terminal_text = self.runner.format_terminal_report(summary)
        self.assertIn("Clean_Control", terminal_text)
        self.assertIn("OVERALL CORPUS", terminal_text)

        md_text = self.runner.generate_markdown_report(summary)
        self.assertIn("# 📊 C++ Error Repair & Recommendation Benchmark", md_text)
        self.assertIn("Clean_Control", md_text)

    def test_export_markdown_and_json(self):
        summary = self.runner.run_suite(category_filter="Clean_Control")
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = os.path.join(tmpdir, "report.md")
            json_path = os.path.join(tmpdir, "report.json")

            self.runner.export_markdown_report(summary, md_path)
            self.assertTrue(os.path.exists(md_path))
            with open(md_path, "r", encoding="utf-8") as f:
                md_content = f.read()
            self.assertIn("Clean_Control", md_content)

            self.runner.export_json_report(summary, json_path)
            self.assertTrue(os.path.exists(json_path))
            with open(json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)
            self.assertEqual(json_data["total_cases"], 20)

    def test_cli_subcommand_bench_repair_json(self):
        main_py = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))
        proc = subprocess.run(
            [sys.executable, main_py, "bench-repair", "--category", "Clean_Control", "--json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertEqual(data["total_cases"], 20)
        self.assertIn("Clean_Control", data["categories"])


if __name__ == "__main__":
    unittest.main()
