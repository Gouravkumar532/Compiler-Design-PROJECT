"""File watch mode for auto-recompilation on save."""

import os
import time
from typing import List, Dict, Callable
from src.errors import Colors

class Watcher:
    def __init__(self, files: List[str], compile_fn: Callable[[str], None], poll_interval: float = 0.5):
        self.files = [os.path.abspath(f) for f in files]
        self.compile_fn = compile_fn
        self.poll_interval = poll_interval
        self.mtimes: Dict[str, float] = {}

    def get_mtimes(self) -> Dict[str, float]:
        current = {}
        for f in self.files:
            if os.path.exists(f):
                current[f] = os.path.getmtime(f)
        return current

    def start(self):
        print(f"\n{Colors.BOLD}{Colors.CYAN}[c++ watch]{Colors.RESET} Watching {len(self.files)} file(s) for changes...")
        print(f"{Colors.DIM}Press Ctrl+C to stop watching.{Colors.RESET}\n")

        # Initial compilation
        self._trigger_compile()
        self.mtimes = self.get_mtimes()

        try:
            while True:
                time.sleep(self.poll_interval)
                current = self.get_mtimes()
                changed_file = None
                for f, mtime in current.items():
                    if f in self.mtimes and mtime > self.mtimes[f]:
                        changed_file = f
                        break
                    elif f not in self.mtimes:
                        changed_file = f
                        break

                if changed_file:
                    self.mtimes = current
                    now_str = time.strftime("%H:%M:%S")
                    rel_name = os.path.relpath(changed_file)
                    print(f"{Colors.BOLD}{Colors.YELLOW}[c++ watch]{Colors.RESET} Change detected in {rel_name} at {now_str}")
                    self._trigger_compile()
        except KeyboardInterrupt:
            print(f"\n{Colors.CYAN}[c++ watch] Stopped watching.{Colors.RESET}\n")

    def _trigger_compile(self):
        t0 = time.time()
        try:
            for f in self.files:
                self.compile_fn(f)
            elapsed = time.time() - t0
            now_str = time.strftime("%H:%M:%S")
            print(f"{Colors.BOLD}{Colors.GREEN}[c++ watch]{Colors.RESET} Build succeeded in {elapsed:.3f}s at {now_str}\n")
        except SystemExit:
            # Compiler errors are caught and displayed; don't terminate watcher
            print(f"{Colors.RED}[c++ watch] Build failed. Waiting for changes...{Colors.RESET}\n")
        except Exception as e:
            print(f"{Colors.RED}[c++ watch] Error: {e}{Colors.RESET}\n")
