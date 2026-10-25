import os
import sys
import json
import shutil
import subprocess
from typing import Optional

from src.errors import Colors
from src.preprocessor import Preprocessor
from src.lexer import Lexer
from src.parser import Parser

class PackageManager:
    """
    Package & Project Manager for C++ compiler (Phase 6).
    Manages project initialization, compilation, testing, and lifecycle.
    Manifest file: c++pm.json
    """
    MANIFEST_FILE = "c++pm.json"

    def __init__(self, project_dir: str = "."):
        self.project_dir = os.path.abspath(project_dir)
        self.manifest_path = os.path.join(self.project_dir, self.MANIFEST_FILE)

    def init(self, name: Optional[str] = None):
        """Initializes a new C++ project in the current or specified directory."""
        project_name = name or os.path.basename(self.project_dir) or "my_cxx_project"
        target_dir = os.path.join(self.project_dir, name) if name else self.project_dir
        os.makedirs(os.path.join(target_dir, "src"), exist_ok=True)
        os.makedirs(os.path.join(target_dir, "tests"), exist_ok=True)
        os.makedirs(os.path.join(target_dir, "bin"), exist_ok=True)

        manifest = {
            "name": project_name,
            "version": "0.1.0",
            "description": f"C++ project {project_name}",
            "main": "src/main.cpp",
            "opt_level": 2,
            "debug": False,
            "target": f"bin/{project_name}"
        }

        manifest_file = os.path.join(target_dir, self.MANIFEST_FILE)
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        main_cpp = os.path.join(target_dir, "src", "main.cpp")
        if not os.path.exists(main_cpp):
            with open(main_cpp, "w", encoding="utf-8") as f:
                f.write("""#include <iostream>

int main() {
    std::cout << "Hello from " << \"""" + project_name + """\" << "!" << std::endl;
    return 0;
}
""")

        test_cpp = os.path.join(target_dir, "tests", "test_main.cpp")
        if not os.path.exists(test_cpp):
            with open(test_cpp, "w", encoding="utf-8") as f:
                f.write("""int main() {
    int expected = 42;
    int actual = 40 + 2;
    return (expected == actual) ? 0 : 1;
}
""")

        print(f"{Colors.GREEN}Initialized C++ package:{Colors.RESET} {Colors.BOLD}{project_name}{Colors.RESET}")
        print(f"Created manifest at: {manifest_file}")
        print(f"Created entry point at: {main_cpp}")

    def load_manifest(self) -> dict:
        if not os.path.exists(self.manifest_path):
            print(f"{Colors.RED}Error:{Colors.RESET} No '{self.MANIFEST_FILE}' found in {self.project_dir}.")
            print("Run 'c++ pkg init' to initialize a new project.")
            sys.exit(1)
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def build(self, opt_level: Optional[int] = None, debug: Optional[bool] = None) -> str:
        """Builds the project defined in c++pm.json."""
        manifest = self.load_manifest()
        main_rel = manifest.get("main", "src/main.cpp")
        main_path = os.path.join(self.project_dir, main_rel)

        if not os.path.exists(main_path):
            print(f"{Colors.RED}Error:{Colors.RESET} Entry file '{main_path}' not found.")
            sys.exit(1)

        opt = opt_level if opt_level is not None else manifest.get("opt_level", 2)
        dbg = debug if debug is not None else manifest.get("debug", False)
        out_rel = manifest.get("target", f"bin/{manifest.get('name', 'app')}")
        out_base = os.path.join(self.project_dir, out_rel)
        os.makedirs(os.path.dirname(out_base), exist_ok=True)

        ll_file = out_base + ".ll"
        exe_file = out_base + (".exe" if os.name == "nt" else "")

        # Compile to LLVM IR
        prep = Preprocessor()
        with open(main_path, "r", encoding="utf-8") as f:
            src = f.read()
        preprocessed = prep.process(src, main_path)
        tokens = Lexer(preprocessed, main_path).tokenize()
        ast = Parser(tokens, preprocessed, main_path).parse()
        try:
            from archive.src.optimizer import Optimizer
            from archive.src.codegen import CodeGenerator
        except ImportError:
            from src.optimizer import Optimizer
            from src.codegen import CodeGenerator
        opt_ast = Optimizer(level=opt).optimize(ast)
        codegen = CodeGenerator(opt_level=opt, debug_info=dbg, source_file=main_path)
        ir = codegen.generate(opt_ast)

        with open(ll_file, "w", encoding="utf-8") as f:
            f.write(ir)

        # Link with Clang
        clang_bin = shutil.which("clang") or shutil.which("clang++") or "clang"
        cmd = [clang_bin, f"-O{opt}"]
        if dbg:
            cmd.append("-g")
        cmd.extend([ll_file, "-o", exe_file])
        res = subprocess.run(cmd)
        if res.returncode != 0:
            print(f"{Colors.RED}Linking failed.{Colors.RESET}")
            sys.exit(res.returncode)

        print(f"{Colors.GREEN}Successfully built package '{manifest.get('name')}':{Colors.RESET} {exe_file}")
        return exe_file

    def run(self, args: Optional[list] = None):
        """Builds and executes the package entrypoint."""
        exe_file = self.build()
        print(f"\n{Colors.CYAN}--- Executing {os.path.basename(exe_file)} ---{Colors.RESET}")
        cmd = [exe_file] + (args or [])
        res = subprocess.run(cmd)
        sys.exit(res.returncode)

    def clean(self):
        """Cleans build artifacts."""
        bin_dir = os.path.join(self.project_dir, "bin")
        if os.path.exists(bin_dir):
            shutil.rmtree(bin_dir)
            print(f"{Colors.GREEN}Cleaned build directory:{Colors.RESET} {bin_dir}")
        else:
            print("Already clean.")
