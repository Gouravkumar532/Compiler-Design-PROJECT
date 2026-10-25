import os
import sys
import time
import glob
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple, Any

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.errors import Colors
from src.preprocessor import Preprocessor
from src.lexer import Lexer
from src.parser import Parser

try:
    from archive.src.optimizer import Optimizer
    from archive.src.codegen import CodeGenerator
except ImportError:
    from src.optimizer import Optimizer
    from src.codegen import CodeGenerator

def get_clang_bin() -> Optional[str]:
    return shutil.which("clang") or shutil.which("clang++")

def legacy_compile(file_path: str, prep: Preprocessor, opt_level: int = 0) -> Tuple[Any, Any, str]:
    with open(file_path, "r", encoding="utf-8") as f:
        src = f.read()
    preprocessed = prep.process(src, file_path)
    tokens = Lexer(preprocessed, file_path).tokenize()
    ast = Parser(tokens, preprocessed, file_path).parse()
    opt = Optimizer(level=opt_level)
    opt_ast = opt.optimize(ast)
    codegen = CodeGenerator(opt_level=opt_level, source_file=file_path)
    ir = codegen.generate(opt_ast)
    return tokens, opt_ast, ir

def time_executable(exe_path: str, iterations: int = 3) -> Optional[float]:
    """Runs the executable N times and returns the average wall-clock duration."""
    if not os.path.exists(exe_path):
        return None
    durations = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        res = subprocess.run([exe_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        t1 = time.perf_counter()
        if res.returncode != 0:
            return None
        durations.append(t1 - t0)
    return sum(durations) / len(durations) if durations else None

def benchmark_compilation(file_path: str, opt_level: int, iterations: int = 5) -> Tuple[float, int, int]:
    """
    Measures compiler throughput (seconds), generated IR line count, and constants folded.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        src = f.read()

    durations = []
    ir_lines = 0
    folded_count = 0

    for _ in range(iterations):
        t0 = time.perf_counter()
        prep = Preprocessor()
        preprocessed = prep.process(src, file_path)
        tokens = Lexer(preprocessed, file_path).tokenize()
        ast = Parser(tokens, preprocessed, file_path).parse()
        opt = Optimizer(level=opt_level)
        opt_ast = opt.optimize(ast)
        folded_count = opt.stats.get("constants_folded", 0)
        codegen = CodeGenerator(opt_level=opt_level, source_file=file_path)
        ir = codegen.generate(opt_ast)
        ir_lines = len(ir.splitlines())
        t1 = time.perf_counter()
        durations.append(t1 - t0)

    avg_time = sum(durations) / len(durations)
    return avg_time, ir_lines, folded_count

def run_all_benchmarks(iterations: int = 3):
    bench_dir = os.path.dirname(os.path.abspath(__file__))
    bin_dir = os.path.join(bench_dir, "bin")
    os.makedirs(bin_dir, exist_ok=True)

    bench_files = sorted(glob.glob(os.path.join(bench_dir, "bench_*.cpp")))
    if not bench_files:
        print(f"{Colors.YELLOW}No benchmark files found in {bench_dir}.{Colors.RESET}")
        return

    clang_bin = get_clang_bin()
    clang_available = clang_bin is not None

    print(f"\n{Colors.BOLD}{Colors.CYAN}[c++ bench]{Colors.RESET} Running Performance Benchmark Suite")
    print(f"Clang native toolchain: {'Available (running execution benchmarks)' if clang_available else 'Not detected (benchmarking compiler pass throughput & IR metrics)'}")
    print(f"Iterations: {iterations}")
    print(f"{Colors.DIM}{'=' * 85}{Colors.RESET}")

    if clang_available:
        print(f"{'Benchmark':<18} {'Our -O0':<12} {'Our -O1':<12} {'Our -O2':<12} {'Clang -O2':<12} {'Speedup (-O2/-O0)'}")
        print(f"{Colors.DIM}{'-' * 85}{Colors.RESET}")

        for bench_file in bench_files:
            base_name = os.path.splitext(os.path.basename(bench_file))[0].replace("bench_", "")
            times: Dict[str, Optional[float]] = {}

            for opt in [0, 1, 2]:
                ll_path = os.path.join(bin_dir, f"{base_name}_opt{opt}.ll")
                exe_path = os.path.join(bin_dir, f"{base_name}_opt{opt}" + (".exe" if os.name == "nt" else ""))
                try:
                    prep = Preprocessor()
                    _, _, ir = legacy_compile(bench_file, prep, opt_level=opt)
                    with open(ll_path, "w", encoding="utf-8") as f:
                        f.write(ir)
                    link_res = subprocess.run([clang_bin, f"-O{opt}", "-Wno-override-module", ll_path, "-o", exe_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if link_res.returncode == 0:
                        times[f"c++_O{opt}"] = time_executable(exe_path, iterations)
                    else:
                        times[f"c++_O{opt}"] = None
                except Exception:
                    times[f"c++_O{opt}"] = None

            clang_exe = os.path.join(bin_dir, f"{base_name}_clang_O2" + (".exe" if os.name == "nt" else ""))
            clang_res = subprocess.run([clang_bin, "-O2", bench_file, "-o", clang_exe], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if clang_res.returncode == 0:
                times["clang_O2"] = time_executable(clang_exe, iterations)
            else:
                times["clang_O2"] = None

            t_o0 = f"{times.get('c++_O0', 0):.4f}s" if times.get('c++_O0') is not None else "N/A"
            t_o1 = f"{times.get('c++_O1', 0):.4f}s" if times.get('c++_O1') is not None else "N/A"
            t_o2 = f"{times.get('c++_O2', 0):.4f}s" if times.get('c++_O2') is not None else "N/A"
            t_clang = f"{times.get('clang_O2', 0):.4f}s" if times.get('clang_O2') is not None else "N/A"

            if times.get('c++_O0') and times.get('c++_O2') and times['c++_O2'] > 0:
                ratio = times['c++_O0'] / times['c++_O2']
                speedup_str = f"{Colors.GREEN}{ratio:.2f}x faster{Colors.RESET}"
            else:
                speedup_str = f"{Colors.DIM}1.00x{Colors.RESET}"

            print(f"{base_name:<18} {t_o0:<12} {t_o1:<12} {t_o2:<12} {t_clang:<12} {speedup_str}")

    else:
        # Compiler throughput & optimization efficiency metrics
        print(f"{'Benchmark':<16} {'Pass -O0 (ms)':<16} {'Pass -O1 (ms)':<16} {'Pass -O2 (ms)':<16} {'IR Reduction'}")
        print(f"{Colors.DIM}{'-' * 85}{Colors.RESET}")

        for bench_file in bench_files:
            base_name = os.path.splitext(os.path.basename(bench_file))[0].replace("bench_", "")
            t0, ir0, _ = benchmark_compilation(bench_file, opt_level=0, iterations=iterations)
            t1, ir1, _ = benchmark_compilation(bench_file, opt_level=1, iterations=iterations)
            t2, ir2, f2 = benchmark_compilation(bench_file, opt_level=2, iterations=iterations)

            reduction = f"{ir0} -> {ir2} lines ({((ir0 - ir2) / ir0 * 100) if ir0 > 0 else 0:.1f}%)"
            print(f"{base_name:<16} {t0*1000:<16.2f} {t1*1000:<16.2f} {t2*1000:<16.2f} {Colors.GREEN}{reduction}{Colors.RESET}")

    print(f"{Colors.DIM}{'=' * 85}{Colors.RESET}\n")

if __name__ == "__main__":
    run_all_benchmarks()
