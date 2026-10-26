"""Automated Error Repair Benchmark Suite and Academic Evaluation Engine.

Provides quantitative scientific benchmarking across a curated corpus of
realistic C++ compilation mistakes:
  1. Exact Match Rate (EM)
  2. Semantic Compilation Rate (SCR)
  3. False Positive Rate (FPR)
  4. Diagnosis & Repair Latency (ms)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from src.analyzer import analyze_translation_unit
from src.errors import Colors
from src.repair_coordinator import repair_source


@dataclass
class BenchmarkCase:
    id: str
    category: str
    difficulty: str
    description: str
    buggy_code: str
    expected_fix: str
    expected_error_code: str = ""


@dataclass
class CaseResult:
    case_id: str
    category: str
    latency_ms: float
    detected_error_codes: List[str]
    expected_error_code: str
    expected_error_detected: bool
    exact_match: bool
    semantic_compile_pass: bool
    false_positive: bool
    initial_error_count: int
    final_error_count: int
    repaired_code: str


@dataclass
class CategoryMetrics:
    category: str
    total: int = 0
    exact_matches: int = 0
    semantic_passes: int = 0
    false_positives: int = 0
    total_latency_ms: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.total if self.total > 0 else 0.0

    @property
    def exact_match_rate(self) -> float:
        return (self.exact_matches / self.total * 100.0) if self.total > 0 else 0.0

    @property
    def semantic_pass_rate(self) -> float:
        return (self.semantic_passes / self.total * 100.0) if self.total > 0 else 0.0

    @property
    def false_positive_rate(self) -> float:
        return (self.false_positives / self.total * 100.0) if self.total > 0 else 0.0


@dataclass
class BenchmarkSummary:
    timestamp: str
    total_cases: int
    categories: Dict[str, CategoryMetrics]
    overall_exact_match_rate: float
    overall_semantic_pass_rate: float
    overall_false_positive_rate: float
    avg_latency_ms: float
    case_results: List[CaseResult] = field(default_factory=list)


class BenchmarkRunner:
    """Orchestrates test case loading, speculative execution, metric collection, and report generation."""

    def __init__(self, corpus_dir: Optional[str] = None):
        if corpus_dir is None:
            # Default to benchmarks/corpus relative to project root
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            self.corpus_dir = os.path.join(project_root, "benchmarks", "corpus")
        else:
            self.corpus_dir = os.path.abspath(corpus_dir)

    def load_corpus(self, category_filter: Optional[str] = None) -> List[BenchmarkCase]:
        cases: List[BenchmarkCase] = []
        if not os.path.exists(self.corpus_dir):
            return cases

        json_files = sorted(f for f in os.listdir(self.corpus_dir) if f.endswith(".json"))
        for fname in json_files:
            file_path = os.path.join(self.corpus_dir, fname)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            case = BenchmarkCase(
                                id=item.get("id", ""),
                                category=item.get("category", ""),
                                difficulty=item.get("difficulty", "Easy"),
                                description=item.get("description", ""),
                                buggy_code=item.get("buggy_code", ""),
                                expected_fix=item.get("expected_fix", ""),
                                expected_error_code=item.get("expected_error_code", ""),
                            )
                            if category_filter:
                                if category_filter.lower() not in case.category.lower():
                                    continue
                            cases.append(case)
            except Exception as e:
                print(f"Warning: failed reading corpus file {fname}: {e}")

        return cases

    def run_case(self, case: BenchmarkCase) -> CaseResult:
        is_clean_control = (case.category.lower() == "clean_control") or (not case.expected_error_code)

        t0 = time.perf_counter()
        # 1. Non-destructive diagnostic analysis
        initial_res = analyze_translation_unit(
            f"<{case.id}>",
            case.buggy_code,
            enable_suggestions=True,
        )

        # 2. Speculative automated repair
        repair_res = repair_source(
            f"<{case.id}>",
            case.buggy_code,
            confidence_policy="all",
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        detected_codes = [d.code for d in initial_res.diagnostics]
        expected_detected = (
            True if is_clean_control else (case.expected_error_code in detected_codes)
        )

        repaired_source = repair_res.updated_source
        exact_match = repaired_source.strip() == case.expected_fix.strip()

        # 3. Semantic compilation check on repaired code
        if is_clean_control:
            # Control code is expected to have zero errors initially and zero changes
            false_pos = repair_res.changed or (len(initial_res.errors) > 0)
            sem_pass = (len(initial_res.errors) == 0) and not repair_res.changed
            final_errors = len(initial_res.errors)
        else:
            false_pos = False
            # Reparse updated source to verify error count dropped to zero
            final_res = analyze_translation_unit(
                f"<{case.id}>",
                repaired_source,
                enable_suggestions=False,
            )
            # A semantic pass means 0 syntax errors and error count reduced
            sem_syntax_errors = [d for d in final_res.diagnostics if d.code.startswith("P") or d.severity == "error"]
            sem_pass = (len(sem_syntax_errors) == 0)
            final_errors = len(sem_syntax_errors)

        return CaseResult(
            case_id=case.id,
            category=case.category,
            latency_ms=latency_ms,
            detected_error_codes=detected_codes,
            expected_error_code=case.expected_error_code,
            expected_error_detected=expected_detected,
            exact_match=exact_match,
            semantic_compile_pass=sem_pass,
            false_positive=false_pos,
            initial_error_count=len(initial_res.errors),
            final_error_count=final_errors,
            repaired_code=repaired_source,
        )

    def run_suite(
        self,
        category_filter: Optional[str] = None,
        verbose: bool = False,
    ) -> BenchmarkSummary:
        cases = self.load_corpus(category_filter=category_filter)
        results: List[CaseResult] = []
        cat_metrics: Dict[str, CategoryMetrics] = {}

        for case in cases:
            res = self.run_case(case)
            results.append(res)

            cat = case.category
            if cat not in cat_metrics:
                cat_metrics[cat] = CategoryMetrics(category=cat)

            m = cat_metrics[cat]
            m.total += 1
            if res.exact_match:
                m.exact_matches += 1
            if res.semantic_compile_pass:
                m.semantic_passes += 1
            if res.false_positive:
                m.false_positives += 1
            m.total_latency_ms += res.latency_ms

            if verbose:
                status = "[PASS]" if res.semantic_compile_pass else "[FAIL]"
                em_flag = "EM" if res.exact_match else "--"
                print(f"  {status} {case.id:<10} {case.category:<22} {em_flag} ({res.latency_ms:5.1f}ms) - {case.description[:40]}")

        total_cases = len(results)
        total_em = sum(m.exact_matches for m in cat_metrics.values())
        total_sem = sum(m.semantic_passes for m in cat_metrics.values())
        total_fp = sum(m.false_positives for m in cat_metrics.values())
        total_lat = sum(m.total_latency_ms for m in cat_metrics.values())

        overall_em_rate = (total_em / total_cases * 100.0) if total_cases > 0 else 0.0
        overall_sem_rate = (total_sem / total_cases * 100.0) if total_cases > 0 else 0.0
        overall_fp_rate = (total_fp / total_cases * 100.0) if total_cases > 0 else 0.0
        avg_lat = (total_lat / total_cases) if total_cases > 0 else 0.0

        return BenchmarkSummary(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            total_cases=total_cases,
            categories=cat_metrics,
            overall_exact_match_rate=overall_em_rate,
            overall_semantic_pass_rate=overall_sem_rate,
            overall_false_positive_rate=overall_fp_rate,
            avg_latency_ms=avg_lat,
            case_results=results,
        )

    def format_terminal_report(self, summary: BenchmarkSummary) -> str:
        lines: List[str] = []
        c = Colors
        lines.append(f"\n{c.BOLD}========================================================================================{c.RESET}")
        lines.append(f"{c.BOLD}{c.CYAN}       C++ AUTOMATED ERROR REPAIR & RECOMMENDATION BENCHMARK EVALUATION{c.RESET}")
        lines.append(f"{c.BOLD}========================================================================================{c.RESET}")
        lines.append(f" Timestamp: {summary.timestamp} | Total Test Cases: {summary.total_cases}")
        lines.append(f"----------------------------------------------------------------------------------------")
        lines.append(f" {'Category':<24} {'Total':<7} {'Exact Match':<13} {'Valid Compile':<15} {'Latency (avg)':<14} {'Pass Rate'}")
        lines.append(f"----------------------------------------------------------------------------------------")

        for cat, m in sorted(summary.categories.items()):
            color = c.GREEN if m.semantic_pass_rate >= 90.0 else (c.YELLOW if m.semantic_pass_rate >= 75.0 else c.RED)
            pass_str = f"{m.semantic_passes}/{m.total}"
            em_str = f"{m.exact_matches} ({m.exact_match_rate:4.1f}%)"
            lat_str = f"{m.avg_latency_ms:4.2f} ms"
            rate_str = f"{color}{m.semantic_pass_rate:5.1f}%{c.RESET}"
            lines.append(f" {cat:<24} {m.total:<7} {em_str:<13} {pass_str:<15} {lat_str:<14} {rate_str}")

        lines.append(f"----------------------------------------------------------------------------------------")
        overall_color = c.GREEN if summary.overall_semantic_pass_rate >= 90.0 else c.YELLOW
        lines.append(f" {c.BOLD}{'OVERALL CORPUS':<24} {summary.total_cases:<7} {summary.overall_exact_match_rate:4.1f}% EM       {summary.overall_semantic_pass_rate:4.1f}% Compile    {summary.avg_latency_ms:4.2f} ms        {overall_color}{summary.overall_semantic_pass_rate:5.1f}%{c.RESET}")
        lines.append(f"{c.BOLD}========================================================================================{c.RESET}")
        lines.append(f" False Positive Rate (Control): {summary.overall_false_positive_rate:3.1f}% | Evaluation Speed: < {summary.avg_latency_ms:3.1f} ms/case\n")
        return "\n".join(lines)

    def generate_markdown_report(self, summary: BenchmarkSummary) -> str:
        lines: List[str] = [
            "# 📊 C++ Error Repair & Recommendation Benchmark Accuracy Report",
            "",
            f"**Generated:** {summary.timestamp}  ",
            f"**Total Benchmark Cases:** {summary.total_cases}  ",
            f"**Average Latency:** {summary.avg_latency_ms:.2f} ms / test case  ",
            f"**False Positive Rate:** {summary.overall_false_positive_rate:.1f}%  ",
            "",
            "## 📈 Quantitative Performance Summary",
            "",
            "| Category | Total | Exact Match (EM) | Valid Compile (SCR) | Average Latency | Success Rate |",
            "|---|---|---|---|---|---|",
        ]

        for cat, m in sorted(summary.categories.items()):
            lines.append(
                f"| **{cat}** | {m.total} | {m.exact_matches} ({m.exact_match_rate:.1f}%) | {m.semantic_passes} ({m.semantic_pass_rate:.1f}%) | {m.avg_latency_ms:.2f} ms | **{m.semantic_pass_rate:.1f}%** |"
            )

        lines.extend([
            f"| **TOTAL / OVERALL** | **{summary.total_cases}** | **{summary.overall_exact_match_rate:.1f}%** | **{summary.overall_semantic_pass_rate:.1f}%** | **{summary.avg_latency_ms:.2f} ms** | **{summary.overall_semantic_pass_rate:.1f}%** |",
            "",
            "## 🔬 Evaluation Methodology",
            "",
            "1. **Exact Match (EM):** The automatically repaired source string exactly matches the expected ground-truth solution character-by-character.",
            "2. **Semantic Compilation Rate (SCR):** The automatically repaired source passes the canonical analysis engine with zero syntax errors (`P001`-`P006`) and successful AST creation.",
            "3. **False Positive Rate (FPR):** Measures the rate at which valid, bug-free C++ programs trigger unnecessary repairs (Target: 0.0%).",
            "4. **Latency:** End-to-end execution time for tokenization, AST parsing, diagnostic detection, multi-pass repair synthesis, and speculative in-memory verification.",
        ])

        return "\n".join(lines)

    def export_markdown_report(self, summary: BenchmarkSummary, output_path: str) -> None:
        md = self.generate_markdown_report(summary)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(md)

    def export_json_report(self, summary: BenchmarkSummary, output_path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        data = asdict(summary)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
