import os
import sys
import glob
import time
from typing import List, Optional

from src.errors import Colors
from src.preprocessor import Preprocessor

class TestRunner:
    """
    Built-in Unit Test Runner for C++ compiler (Phase 6).
    Discovers, compiles, and verifies .cpp test suites with detailed pass/fail analytics.
    """
    def __init__(self, target_path: str = "tests", opt_level: int = 0, pattern: Optional[str] = None, verbose: bool = False):
        self.target_path = target_path
        self.opt_level = opt_level
        self.pattern = pattern
        self.verbose = verbose

    def run(self) -> int:
        test_files = self._discover_tests()
        if not test_files:
            print(f"{Colors.YELLOW}No tests found matching criteria in '{self.target_path}'.{Colors.RESET}")
            return 0

        print(f"\n{Colors.BOLD}{Colors.CYAN}[c++ test]{Colors.RESET} Running {len(test_files)} test suite(s) (opt: -O{self.opt_level})...\n")
        print(f"{Colors.DIM}{'=' * 65}{Colors.RESET}")

        start_total = time.time()
        passed = 0
        failed = 0
        results = []

        from main import compile_source

        for file_path in test_files:
            t0 = time.time()
            prep = Preprocessor()
            try:
                compile_source(file_path, prep, opt_level=self.opt_level, verbose=False)
                duration = time.time() - t0
                passed += 1
                results.append((file_path, True, duration, None))
                print(f"  {Colors.GREEN}[PASS]{Colors.RESET} {file_path:<42} {duration:.4f}s")
            except Exception as e:
                duration = time.time() - t0
                failed += 1
                results.append((file_path, False, duration, str(e)))
                print(f"  {Colors.RED}[FAIL]{Colors.RESET} {file_path:<42} {duration:.4f}s")
                if self.verbose:
                    print(f"       {Colors.RED}Error: {e}{Colors.RESET}")
            except SystemExit as se:
                duration = time.time() - t0
                if se.code == 0:
                    passed += 1
                    results.append((file_path, True, duration, None))
                    print(f"  {Colors.GREEN}[PASS]{Colors.RESET} {file_path:<42} {duration:.4f}s")
                else:
                    failed += 1
                    results.append((file_path, False, duration, f"Exit code {se.code}"))
                    print(f"  {Colors.RED}[FAIL]{Colors.RESET} {file_path:<42} {duration:.4f}s")

        total_time = time.time() - start_total
        print(f"{Colors.DIM}{'=' * 65}{Colors.RESET}")

        pass_rate = (passed / len(test_files)) * 100
        summary_color = Colors.GREEN if failed == 0 else Colors.RED

        print(f"\n{summary_color}{Colors.BOLD}Test Results: {passed}/{len(test_files)} passed ({pass_rate:.1f}%){Colors.RESET}")
        print(f"Total Duration: {total_time:.3f}s\n")

        return 0 if failed == 0 else 1

    def _discover_tests(self) -> List[str]:
        if os.path.isfile(self.target_path):
            return [self.target_path]
        
        all_files = glob.glob(os.path.join(self.target_path, "**", "*.cpp"), recursive=True)
        if not all_files:
            all_files = glob.glob(os.path.join(self.target_path, "*.cpp"))
        
        all_files = sorted(all_files)
        if self.pattern:
            all_files = [f for f in all_files if self.pattern.lower() in os.path.basename(f).lower()]
        return all_files
