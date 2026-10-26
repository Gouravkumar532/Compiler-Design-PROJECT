# 📊 C++ Error Repair & Recommendation Benchmark Accuracy Report

**Generated:** 2026-10-26 22:41:32  
**Total Benchmark Cases:** 120  
**Average Latency:** 3.66 ms / test case  
**False Positive Rate:** 0.0%  

## 📈 Quantitative Performance Summary

| Category | Total | Exact Match (EM) | Valid Compile (SCR) | Average Latency | Success Rate |
|---|---|---|---|---|---|
| **Clean_Control** | 20 | 20 (100.0%) | 20 (100.0%) | 3.80 ms | **100.0%** |
| **Cross_Language** | 15 | 14 (93.3%) | 15 (100.0%) | 3.74 ms | **100.0%** |
| **Expression_Repairs** | 25 | 20 (80.0%) | 22 (88.0%) | 4.40 ms | **88.0%** |
| **Missing_Headers_NS** | 20 | 18 (90.0%) | 16 (80.0%) | 2.85 ms | **80.0%** |
| **Operator_Misuse** | 15 | 11 (73.3%) | 15 (100.0%) | 4.35 ms | **100.0%** |
| **Syntax_Delimiters** | 25 | 22 (88.0%) | 25 (100.0%) | 3.01 ms | **100.0%** |
| **TOTAL / OVERALL** | **120** | **87.5%** | **94.2%** | **3.66 ms** | **94.2%** |

## 🔬 Evaluation Methodology

1. **Exact Match (EM):** The automatically repaired source string exactly matches the expected ground-truth solution character-by-character.
2. **Semantic Compilation Rate (SCR):** The automatically repaired source passes the canonical analysis engine with zero syntax errors (`P001`-`P006`) and successful AST creation.
3. **False Positive Rate (FPR):** Measures the rate at which valid, bug-free C++ programs trigger unnecessary repairs (Target: 0.0%).
4. **Latency:** End-to-end execution time for tokenization, AST parsing, diagnostic detection, multi-pass repair synthesis, and speculative in-memory verification.