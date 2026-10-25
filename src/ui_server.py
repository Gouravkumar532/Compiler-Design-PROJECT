"""
Interactive C++ Compiler Workbench — Zero-Dependency HTTP & Session Server
==============================================================================
Provides a local web server (http.server) serving a 3-pane developer workbench:
  1. Code Editor (main.cpp)
  2. Output & Diagnostics Pane (Rust-style error cards & pedagogical catalogue)
  3. Interactive Terminal Console (Full ANSI colors, CLI execution, fix -i wizard)

Strictly zero third-party dependencies (Python 3.10+ standard library only).
==============================================================================
"""

import sys
import os
import json
import time
import io
import contextlib
import threading
import queue
import tempfile
import webbrowser
import urllib.parse
import subprocess
import shutil
import secrets
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any, List, Tuple

from src.formatter import Formatter
from src.errors import explain_error, list_error_codes, ERROR_CATALOGUE, Colors
from src.tui_wizard import PatchReviewWizard
from src.analyzer import analyze_translation_unit
from src.repair_coordinator import repair_source
from src.diagnostics import diagnostic_to_dict, render_diagnostics
from src.paths import same_file


# ==============================================================================
# 1. SHOWCASE PRESETS
# ==============================================================================

from src.presets import PRESETS


# ==============================================================================
# 2. INTERACTIVE TERMINAL SESSION MANAGER
# ==============================================================================

class InteractiveSession:
    """Manages background interactive wizard sessions for step-by-step patch review."""

    def __init__(self, temp_file: str, initial_code: str):
        self.temp_file = temp_file
        self.initial_code = initial_code
        self.input_queue: queue.Queue = queue.Queue()
        self.output_buffer: List[str] = []
        self.current_prompt: str = ""
        self.is_interactive: bool = True
        self.updated_code: Optional[str] = None
        self.event_prompt_ready: threading.Event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None

    def start(self):
        self.worker_thread = threading.Thread(target=self._run_wizard, daemon=True)
        self.worker_thread.start()

    def _output_callback(self, text: str):
        self.output_buffer.append(text)

    def _input_callback(self, prompt: str) -> str:
        self.current_prompt = prompt
        self.event_prompt_ready.set()
        # Wait for user keystroke from UI
        val = self.input_queue.get()
        self.event_prompt_ready.clear()
        return val

    def _run_wizard(self):
        try:
            wizard = PatchReviewWizard(
                files=[self.temp_file],
                backup=False,
                verbose=False,
                color=True,
                input_fn=self._input_callback,
                output_fn=self._output_callback,
            )
            wizard.run()
        except (Exception, SystemExit) as e:
            self.output_buffer.append(f"\n{Colors.RED}Wizard session error: {e}{Colors.RESET}\n")
        finally:
            self.is_interactive = False
            # Read updated file if changed
            if os.path.isfile(self.temp_file):
                try:
                    with open(self.temp_file, "r", encoding="utf-8") as f:
                        self.updated_code = f.read()
                except OSError:
                    pass
            self.event_prompt_ready.set()

    def deliver_input(self, user_input: str) -> Tuple[str, bool, str, Optional[str]]:
        self.output_buffer.clear()
        self.input_queue.put(user_input)
        # Wait until next prompt is ready or wizard finishes
        self.event_prompt_ready.wait(timeout=10.0)
        output_text = "".join(self.output_buffer)
        return output_text, self.is_interactive, self.current_prompt, self.updated_code


# Interactive sessions are isolated per browser tab/request.
_sessions: Dict[str, InteractiveSession] = {}
_session_lock = threading.Lock()


# ==============================================================================
# 3. COMPILER COMMAND RUNNER & DIAGNOSTIC EXTRACTOR
# ==============================================================================

def find_cpp_compiler() -> Optional[str]:
    """Finds an available C++ compiler executable on the host system."""
    for candidate in ["g++", "clang++", "clang"]:
        path = shutil.which(candidate)
        if path:
            return path
    return None


def execute_cpp_program(code: str):
    """
    Checks, compiles, and runs the user's C++ code, streaming compiler diagnostics
    or actual program runtime stdout/stderr into sys.stdout with color styling.
    """
    compiler = find_cpp_compiler()
    if not compiler:
        print(f"\n{Colors.RED}No C++ compiler (g++ or clang) was detected on your system PATH.{Colors.RESET}")
        print(f"{Colors.DIM}Please ensure MinGW (g++) or LLVM (clang) is installed to run C++ code.{Colors.RESET}\n")
        return

    compiler_name = os.path.basename(compiler).lower()

    # Step 1: Pre-run check with our canonical compiler frontend
    result = analyze_translation_unit("<sandbox>", code, enable_suggestions=True)
    if not result.complete:
        print(f"\n{Colors.BOLD}{Colors.RED}Internal analysis failure prevents execution.{Colors.RESET}\n")
        return
    if result.candidate_patches:
        print(f"\n{Colors.BOLD}{Colors.YELLOW}[check] Found {len(result.candidate_patches)} syntax issue(s) before running:{Colors.RESET}")
        for p in result.candidate_patches:
            print(f"  {Colors.RED}--> Line {p.line_start}, Col {p.col_start}:{Colors.RESET} {p.summary}")
            if p.explanations:
                print(f"      {Colors.DIM}{p.explanations[0]}{Colors.RESET}")
        print(f"\n{Colors.CYAN}Tip: Use 'fix' or click 'Fix All' to automatically repair these before running.{Colors.RESET}\n")
        return
    syntax_errors = [d for d in result.diagnostics if d.source_stage in ("lexer", "parser") and d.severity == "error"]
    if syntax_errors:
        print(f"\n{Colors.BOLD}{Colors.YELLOW}[check] Found {len(syntax_errors)} syntax issue(s) before running:{Colors.RESET}")
        for d in syntax_errors:
            print(f"  {Colors.RED}--> Line {d.line}, Col {d.col}:{Colors.RESET} {d.message}")
        return

    # Step 2: Write temporary .cpp and compile
    src_file = None
    exe_file = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".cpp", delete=False, encoding="utf-8") as tf:
            tf.write(code)
            src_file = tf.name

        exe_file = src_file.replace(".cpp", ".exe" if sys.platform == "win32" else "")

        print(f"{Colors.DIM}[Compiling with {compiler_name}...]{Colors.RESET}")
        t0 = time.time()
        comp = subprocess.run(
            [compiler, src_file, "-o", exe_file],
            capture_output=True,
            text=True,
            timeout=15,
        )
        comp_time = time.time() - t0

        if comp.returncode != 0:
            print(f"\n{Colors.BOLD}{Colors.RED}Compilation Failed ({compiler_name} exited with code {comp.returncode}):{Colors.RESET}")
            if comp.stderr:
                print(comp.stderr)
            elif comp.stdout:
                print(comp.stdout)
            return

        # Step 3: Execute binary
        print(f"{Colors.DIM}[Executing program...]{Colors.RESET}")
        print(f"{Colors.CYAN}{'-' * 70}{Colors.RESET}")
        t_exec_start = time.time()
        try:
            proc = subprocess.run(
                [exe_file],
                capture_output=True,
                text=True,
                timeout=10,
            )
            elapsed = time.time() - t_exec_start

            if proc.stdout:
                sys.stdout.write(proc.stdout)
                if not proc.stdout.endswith("\n"):
                    sys.stdout.write("\n")

            if proc.stderr:
                print(f"{Colors.RED}{proc.stderr}{Colors.RESET}", end="" if proc.stderr.endswith("\n") else "\n")

            print(f"{Colors.CYAN}{'-' * 70}{Colors.RESET}")
            status_color = Colors.GREEN if proc.returncode == 0 else Colors.RED
            print(f"{status_color}Program exited with code {proc.returncode}{Colors.RESET} {Colors.DIM}(compile: {comp_time:.3f}s, runtime: {elapsed:.3f}s){Colors.RESET}\n")

        except subprocess.TimeoutExpired:
            print(f"{Colors.CYAN}{'-' * 70}{Colors.RESET}")
            print(f"\n{Colors.RED}Execution timed out after 10.0 seconds.{Colors.RESET}\n")

    except Exception as e:
        print(f"\n{Colors.RED}Execution error: {e}{Colors.RESET}\n")
    finally:
        for p in (src_file, exe_file):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


def execute_cli_command(command: str, code: str, file_path: str = "main.cpp") -> Dict[str, Any]:
    """
    Executes a compiler command ('check', 'fix', 'fix -i', 'suggest', 'explain', 'fmt', 'tokens', 'help')
    in-memory with stdout/stderr capture, returning ANSI-styled output and updated source if modified.
    """
    parts = command.strip().split()
    if not parts:
        return {"output": "", "is_interactive": False, "prompt": "c++ > ", "updated_code": None}

    cmd = parts[0].lower()
    if cmd == "c++":
        parts = parts[1:]
        if not parts:
            cmd = "help"
        else:
            cmd = parts[0].lower()

    args = parts[1:]

    # Interactive Fix Wizard (`fix -i`)
    if cmd == "fix" and ("-i" in args or "--interactive" in args):
        with _session_lock:
            if any(session.is_interactive for session in _sessions.values()):
                return {"error": "An interactive session is already active.", "status": 409}
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode="w", suffix=".cpp", delete=False, encoding="utf-8") as tf:
                tf.write(code)
                tf_path = tf.name

            session = InteractiveSession(tf_path, code)
            session_id = str(uuid.uuid4())
            _sessions[session_id] = session
            session.start()
            # Wait for first prompt
            session.event_prompt_ready.wait(timeout=5.0)
            initial_output = "".join(session.output_buffer)
            return {
                "output": initial_output,
                "is_interactive": session.is_interactive,
                "prompt": session.current_prompt,
                "updated_code": session.updated_code,
                "session_id": session_id,
            }

    # Non-interactive commands capture stdout/stderr
    buf = io.StringIO()
    updated_code = None

    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".cpp", delete=False, encoding="utf-8") as tf:
                tf.write(code)
                tf_path = tf.name

            if cmd == "check":
                result = analyze_translation_unit(file_path, code, enable_suggestions=True)
                render_diagnostics(result.diagnostics, result.display_names)
                if not result.complete:
                    print(f"\n{Colors.RED}Analysis failed due to internal compiler error.{Colors.RESET}")
                elif result.error_count == 0 and result.warning_count == 0:
                    print(f"{Colors.GREEN}Check passed without errors or warnings for {file_path}.{Colors.RESET}")
                elif result.error_count == 0:
                    print(f"{Colors.YELLOW}Check completed with {result.warning_count} warning(s).{Colors.RESET}")
                else:
                    print(f"\n{Colors.RED}Found {result.error_count} error(s) and {result.warning_count} warning(s).{Colors.RESET}")

            elif cmd == "fix":
                repair = repair_source(
                    file_path,
                    code,
                    confidence_policy="all",
                    max_rounds=5,
                )
                if repair.changed and repair.success:
                    updated_code = repair.updated_source
                if repair.status == "complete":
                    print(f"{Colors.GREEN}[fix] {repair.message}.{Colors.RESET}")
                elif repair.status == "partial":
                    print(f"{Colors.YELLOW}[fix] Partial repair: {repair.message}.{Colors.RESET}")
                elif repair.status == "unchanged":
                    print(f"{Colors.CYAN}[fix] {repair.message}.{Colors.RESET}")
                else:
                    print(f"{Colors.RED}[fix] Repair rejected: {repair.message}.{Colors.RESET}")

            elif cmd == "suggest":
                result = analyze_translation_unit(file_path, code, enable_suggestions=True)
                if not result.safe_to_write:
                    render_diagnostics(result.diagnostics, result.display_names)
                    print(f"{Colors.RED}Suggestions unavailable due to internal analysis failure.{Colors.RESET}")
                else:
                    patches = [p for p in result.candidate_patches if same_file(p.file_path, file_path)]
                    if not patches:
                        print(f"{Colors.CYAN}No proposed code repairs for {file_path}.{Colors.RESET}")
                    else:
                        print(f"\n{Colors.BOLD}{Colors.CYAN}Found {len(patches)} proposed repair(s) for {file_path}:{Colors.RESET}\n")
                        from src.patch_model import UnifiedDiffRenderer
                        for idx, p in enumerate(patches, 1):
                            card = UnifiedDiffRenderer.render_summary_card(p, idx, len(patches), code, color=True)
                            print(card)

            elif cmd == "explain":
                code_arg = args[0] if args else None
                if code_arg:
                    explain_error(code_arg.upper())
                else:
                    list_error_codes()

            elif cmd == "fmt":
                formatter = Formatter()
                formatted = formatter.format_source(code, file_path)
                updated_code = formatted
                print(f"{Colors.GREEN}Formatted {file_path} according to standard C++ styling.{Colors.RESET}")

            elif cmd == "tokens":
                result = analyze_translation_unit(file_path, code, enable_suggestions=False)
                tokens = result.tokens
                print(f"\n{Colors.BOLD}{Colors.CYAN}--- Token Stream for {file_path} ({len(tokens)} tokens) ---{Colors.RESET}")
                for t in tokens:
                    print(f"  Line {t.line:3d}, Col {t.col:2d}: {t.type.name:<18} {repr(t.lexeme)}")

            elif cmd == "run":
                execute_cpp_program(code)

            elif cmd in ("help", "?"):
                print(f"\n{Colors.BOLD}Available C++ Compiler Commands:{Colors.RESET}")
                print(f"  {Colors.GREEN}run{Colors.RESET}               Compile and execute program natively (stdout in terminal)")
                print(f"  {Colors.CYAN}check{Colors.RESET}             Analyze source code for syntax and semantic errors")
                print(f"  {Colors.CYAN}fix{Colors.RESET}               Batch auto-repair detected syntax & expression errors")
                print(f"  {Colors.CYAN}fix -i{Colors.RESET}            Launch step-by-step Interactive Patch Review Wizard")
                print(f"  {Colors.CYAN}suggest{Colors.RESET}           Display proposed code repairs and diffs without modifying code")
                print(f"  {Colors.CYAN}explain [code]{Colors.RESET}   Display pedagogical explanation (e.g. 'explain P002')")
                print(f"  {Colors.CYAN}fmt{Colors.RESET}               Format source code according to C++ style guide")
                print(f"  {Colors.CYAN}tokens{Colors.RESET}            Inspect the raw token stream emitted by the lexer")
                print(f"  {Colors.CYAN}clear{Colors.RESET}             Clear terminal output console\n")

            else:
                print(f"{Colors.RED}Unknown command '{command}'. Type 'help' for available commands.{Colors.RESET}")

        except SystemExit:
            # Compiler diagnostics and syntax errors legitimately exit; do not crash server
            pass
        except Exception as e:
            print(f"{Colors.RED}Error: {e}{Colors.RESET}")
        finally:
            if os.path.exists(tf_path):
                try:
                    os.remove(tf_path)
                except OSError:
                    pass

        response = {
            "output": buf.getvalue(),
            "is_interactive": False,
            "prompt": "c++ > ",
            "updated_code": updated_code,
        }
        if cmd == "fix" and "repair" in locals():
            response.update({
                "repair_status": repair.status,
                "applied_count": len(repair.applied_patches),
                "remaining_count": len(repair.remaining_patches),
                "remaining_errors": repair.final_analysis.error_count,
                "diagnostics": [diagnostic_to_dict(d) for d in repair.final_analysis.diagnostics],
            })
        return response


def extract_structured_diagnostics(code: str, file_path: str = "<sandbox>") -> Dict[str, Any]:
    """
    Runs the canonical compiler pipeline in-memory and returns structured diagnostics
    for the Output & Error Inspection pane.
    """
    result = analyze_translation_unit(file_path, code, enable_suggestions=True)
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    for diag in result.diagnostics:
        d_dict = diagnostic_to_dict(diag)
        if diag.severity in ("error", "internal"):
            errors.append(d_dict)
        else:
            warnings.append(d_dict)

    return {
        "errors": errors,
        "warnings": warnings,
        "complete": result.complete,
        "safe_to_write": result.safe_to_write,
    }


# ==============================================================================
# 4. HTTP SERVER & REST API HANDLER
# ==============================================================================

_initial_file_content: Optional[str] = None


class WorkbenchHandler(BaseHTTPRequestHandler):
    """HTTP request handler for serving workbench web assets and API endpoints."""

    def log_message(self, format, *args):
        # Silence default access log to keep console clean
        pass

    def do_OPTIONS(self):
        self._send_json({"error": "Cross-origin requests are not supported."}, status=403)

    def _authorized(self) -> bool:
        return secrets.compare_digest(
            self.headers.get("X-Workbench-Token", ""),
            getattr(self.server, "session_token", ""),
        )

    def do_GET(self):
        try:
            url = urllib.parse.urlparse(self.path)
            path = url.path

            if path.startswith("/api/") and not self._authorized():
                self._send_json({"error": "Invalid or missing workbench token."}, status=403)
                return

            # Static assets
            web_dir = os.path.join(os.path.dirname(__file__), "web")

            if path in ("/", "/index.html"):
                self._serve_file(os.path.join(web_dir, "index.html"), "text/html; charset=utf-8", inject_token=True)
            elif path == "/colors.css":
                self._serve_file(os.path.join(web_dir, "colors.css"), "text/css; charset=utf-8")
            elif path == "/workbench.css":
                self._serve_file(os.path.join(web_dir, "workbench.css"), "text/css; charset=utf-8")
            elif path == "/workbench.js":
                self._serve_file(os.path.join(web_dir, "workbench.js"), "application/javascript; charset=utf-8")
            elif path == "/api/presets":
                self._send_json(PRESETS)
            elif path == "/api/initial":
                self._send_json({"code": _initial_file_content})
            elif path == "/api/capabilities":
                self._send_json({"native_run": bool(self.server.enable_native_run)})
            elif path == "/api/errors":
                qs = urllib.parse.parse_qs(url.query)
                code = qs.get("code", [""])[0].upper()
                entry = ERROR_CATALOGUE.get(code)
                self._send_json({"entry": entry})
            else:
                self.send_error(404, "File not found")
        except Exception:
            self._send_json({"error": "Internal server error."}, status=500)

    def do_POST(self):
        try:
            url = urllib.parse.urlparse(self.path)
            path = url.path
            if not path.startswith("/api/"):
                self._send_json({"error": "Endpoint not found."}, status=404)
                return
            if not self._authorized():
                self._send_json({"error": "Invalid or missing workbench token."}, status=403)
                return
            body = self._read_json_body()
            if body is None:
                return

            if path == "/api/terminal/command":
                cmd = body.get("command", "")
                code = body.get("code", "")
                if not isinstance(cmd, str) or not isinstance(code, str):
                    self._send_json({"error": "command and code must be strings."}, status=400)
                    return
                command_parts = cmd.strip().lower().split()
                requests_native_run = bool(command_parts) and (
                    command_parts[0] == "run"
                    or (command_parts[0] == "c++" and len(command_parts) > 1 and command_parts[1] == "run")
                )
                if requests_native_run and not self.server.enable_native_run:
                    self._send_json({"error": "Native execution is disabled because the workbench is running in safe mode."}, status=403)
                    return
                result = execute_cli_command(cmd, code)
                self._send_json(result, status=result.pop("status", 200))

            elif path == "/api/terminal/input":
                user_input = body.get("input", "")
                session_id = body.get("session_id", "")
                if not isinstance(user_input, str) or not isinstance(session_id, str):
                    self._send_json({"error": "input and session_id must be strings."}, status=400)
                    return
                with _session_lock:
                    session = _sessions.get(session_id)
                    if session and session.is_interactive:
                        out, is_int, prompt, updated = session.deliver_input(user_input)
                        self._send_json({
                            "output": out,
                            "is_interactive": is_int,
                            "prompt": prompt,
                            "updated_code": updated,
                            "session_id": session_id,
                        })
                        if not is_int:
                            _sessions.pop(session_id, None)
                            try:
                                os.remove(session.temp_file)
                            except OSError:
                                pass
                    else:
                        self._send_json({"error": "Session is not awaiting interactive input."}, status=409)

            elif path == "/api/diagnostics":
                code = body.get("code", "")
                if not isinstance(code, str):
                    self._send_json({"error": "code must be a string."}, status=400)
                    return
                diags = extract_structured_diagnostics(code)
                self._send_json(diags)

            elif path == "/api/format":
                code = body.get("code", "")
                if not isinstance(code, str):
                    self._send_json({"error": "code must be a string."}, status=400)
                    return
                try:
                    formatted = Formatter().format_source(code, "main.cpp")
                    self._send_json({"formatted_code": formatted})
                except (Exception, SystemExit) as e:
                    self._send_json({"formatted_code": None, "error": "Cannot format code containing syntax errors."})

            elif path == "/api/run":
                code = body.get("code", "")
                if not isinstance(code, str):
                    self._send_json({"error": "code must be a string."}, status=400)
                    return
                if not self.server.enable_native_run:
                    self._send_json({"error": "Native execution is disabled because the workbench is running in safe mode."}, status=403)
                    return
                result = execute_cli_command("run", code)
                self._send_json(result)
            else:
                self._send_json({"error": "Endpoint not found."}, status=404)
        except Exception:
            self._send_json({"error": "Internal server error."}, status=500)

    def _serve_file(self, filepath: str, content_type: str, inject_token: bool = False):
        if not os.path.isfile(filepath):
            self.send_error(404, "File not found")
            return
        with open(filepath, "rb") as f:
            content = f.read()
        if inject_token:
            marker = b"</head>"
            meta = (
                '<meta name="workbench-token" content="'
                + getattr(self.server, "session_token", "") + '">\n'
            ).encode("utf-8")
            content = content.replace(marker, meta + marker, 1)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(content)

    def _read_json_body(self) -> Optional[Dict[str, Any]]:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length."}, status=400)
            return None
        if content_length > 1024 * 1024:
            self._send_json({"error": "Request body exceeds 1 MiB."}, status=413)
            return None
        if content_length > 0:
            raw = self.rfile.read(content_length).decode("utf-8")
            try:
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise TypeError
                return value
            except (ValueError, TypeError):
                self._send_json({"error": "Invalid JSON object."}, status=400)
                return None
        return {}

    def _send_json(self, data: Any, status: int = 200):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)


# ==============================================================================
# 5. SERVER ENTRYPOINT
# ==============================================================================

class WorkbenchServer(ThreadingHTTPServer):
    """Threading HTTP server with strict single-binding on Windows to prevent port conflicts."""
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, server_address, handler_class, *, enable_native_run: bool = False):
        super().__init__(server_address, handler_class)
        self.session_token = secrets.token_urlsafe(32)
        self.enable_native_run = enable_native_run


def start_workbench(
    port: int = 8080,
    open_browser: bool = True,
    initial_file: Optional[str] = None,
    enable_native_run: bool = True,
):
    """Starts the C++ Compiler Workbench HTTP server and launches the user's browser."""
    global _initial_file_content

    if initial_file and os.path.isfile(initial_file):
        with open(initial_file, "r", encoding="utf-8") as f:
            _initial_file_content = f.read()

    # Attempt to bind to requested port, fallback to sequential ports if in use
    server = None
    bind_port = port
    for attempt in range(20):
        try:
            server = WorkbenchServer(("127.0.0.1", bind_port), WorkbenchHandler)
            server.session_token = secrets.token_urlsafe(32)
            server.enable_native_run = enable_native_run
            break
        except OSError:
            bind_port += 1

    if not server:
        print(f"{Colors.RED}Failed to bind workbench server to ports {port}-{bind_port}.{Colors.RESET}")
        sys.exit(1)

    url = f"http://127.0.0.1:{bind_port}"
    print(f"\n{Colors.BOLD}{Colors.CYAN}======================================================================{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.GREEN}[*] C++ Compiler Workbench running at: {Colors.CYAN}{url}{Colors.RESET}")
    run_status = "enabled" if enable_native_run else "disabled (safe mode)"
    run_color = Colors.GREEN if enable_native_run else Colors.YELLOW
    print(f"{run_color}Native compilation and execution: {run_status}{Colors.RESET}")
    print(f"{Colors.DIM}Zero external dependencies | Pure Python 3.10+ standard library{Colors.RESET}")
    print(f"{Colors.DIM}Press Ctrl+C in this terminal to shut down the workbench.{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}======================================================================{Colors.RESET}\n", flush=True)

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Shutting down C++ Compiler Workbench.{Colors.RESET}")
        server.shutdown()
        server.server_close()
