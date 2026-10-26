# 📊 C++ Error Repair & Recommendation Benchmark Accuracy Report

**Generated:** 2026-10-25 22:07:46  
**Total Benchmark Cases:** 25  
**Average Latency:** 3.20 ms / test case  
**False Positive Rate:** 0.0%  

## 📈 Quantitative Performance Summary

| Category | Total | Exact Match (EM) | Valid Compile (SCR) | Average Latency | Success Rate |
|---|---|---|---|---|---|
| **Syntax_Delimiters** | 25 | 22 (88.0%) | 25 (100.0%) | 3.20 ms | **100.0%** |
| **TOTAL / OVERALL** | **25** | **88.0%** | **100.0%** | **3.20 ms** | **100.0%** |

## 🔬 Evaluation Methodology

1. **Exact Match (EM):** The automatically repaired source string exactly matches the expected ground-truth solution character-by-character.
2. **Semantic Compilation Rate (SCR):** The automatically repaired source passes the canonical analysis engine with zero syntax errors (`P001`-`P006`) and successful AST creation.
3. **False Positive Rate (FPR):** Measures the rate at which valid, bug-free C++ programs trigger unnecessary repairs (Target: 0.0%).
4. **Latency:** End-to-end execution time for tokenization, AST parsing, diagnostic detection, multi-pass repair synthesis, and speculative in-memory verification.