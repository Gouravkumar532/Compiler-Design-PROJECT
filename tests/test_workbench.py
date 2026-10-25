"""
Automated Unit Tests for C++ Compiler Workbench (ui_server.py)
==============================================================================
Validates HTTP endpoints, static asset delivery, CLI command execution,
interactive wizard sessions, structured diagnostics, and zero-dependency compliance.
==============================================================================
"""

import unittest
import json
import threading
import time
import urllib.request
import urllib.error
from http.server import HTTPServer

from src.ui_server import (
    WorkbenchServer,
    WorkbenchHandler,
    execute_cli_command,
    extract_structured_diagnostics,
    find_cpp_compiler,
    PRESETS,
)
from src.analyzer import analyze_translation_unit


class TestWorkbenchEndpoints(unittest.TestCase):
    """Tests HTTP endpoints and web asset serving."""

    @classmethod
    def setUpClass(cls):
        # Start test HTTP server on an available localhost port
        cls.server = None
        for port in range(18880, 18900):
            try:
                cls.server = WorkbenchServer(("127.0.0.1", port), WorkbenchHandler, enable_native_run=True)
                cls.port = port
                break
            except OSError:
                continue

        if not cls.server:
            raise RuntimeError("Could not bind test workbench server to port.")

        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()
            cls.server.server_close()

    def _get(self, path: str):
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"X-Workbench-Token": self.server.session_token},
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.headers.get_content_type(), resp.read()

    def _post(self, path: str, data: dict):
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Workbench-Token": self.server.session_token,
            },
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_01_index_html(self):
        status, ctype, content = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"C++ Compiler Workbench", content)
        self.assertIn(b"code-editor", content)
        self.assertIn(b"terminal-output", content)

    def test_02_colors_css_centralization(self):
        """Verifies that all colors are kept separately in colors.css."""
        status, ctype, content = self._get("/colors.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", ctype)
        text = content.decode("utf-8")
        self.assertIn("--bg-page:", text)
        self.assertIn("--accent-primary:", text)
        self.assertIn("--color-error:", text)
        self.assertIn("--ansi-red:", text)

    def test_03_workbench_css(self):
        status, ctype, content = self._get("/workbench.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", ctype)
        text = content.decode("utf-8")
        self.assertIn("@import url('colors.css')", text)

    def test_04_workbench_js(self):
        status, ctype, content = self._get("/workbench.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", ctype)
        text = content.decode("utf-8")
        self.assertIn("ansiToHtml", text)
        self.assertIn("runTerminalCommand", text)

    def test_05_presets_api(self):
        status, data = self._post("/api/diagnostics", {"code": "int main() { return 0; }"})
        self.assertEqual(status, 200)

        # GET /api/presets
        status, ctype, content = self._get("/api/presets")
        self.assertEqual(status, 200)
        presets = json.loads(content.decode("utf-8"))
        self.assertIn("cross_language", presets)
        self.assertIn("missing_delimiters", presets)
        self.assertIn("operator_misuse", presets)
        self.assertIn("clean_hello", presets)

    def test_06_error_catalogue_api(self):
        status, ctype, content = self._get("/api/errors?code=P002")
        self.assertEqual(status, 200)
        res = json.loads(content.decode("utf-8"))
        self.assertIn("entry", res)
        self.assertIsNotNone(res["entry"])
        self.assertIn("title", res["entry"])

    def test_07_format_api(self):
        ugly_code = "int   main(  ) {int  x=10;return    x;}"
        status, res = self._post("/api/format", {"code": ugly_code})
        self.assertEqual(status, 200)
        self.assertIn("formatted_code", res)
        self.assertIn("int main()", res["formatted_code"])

    def test_08_cors_options(self):
        req = urllib.request.Request(f"{self.base_url}/api/terminal/command", method="OPTIONS")
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(req)
        self.assertEqual(raised.exception.code, 403)
        self.assertIsNone(raised.exception.headers.get("Access-Control-Allow-Origin"))

    def test_09_check_with_syntax_errors_does_not_crash_server(self):
        """Verifies that running check on broken code returns 200 with diagnostics and does not terminate server."""
        broken_code = PRESETS["cross_language"]["code"]
        status, res = self._post("/api/terminal/command", {"command": "check", "code": broken_code})
        self.assertEqual(status, 200)
        self.assertIn("output", res)
        self.assertIn("error[P005]", res["output"])

        # Server should still be alive for subsequent requests
        status, ctype, _ = self._get("/")
        self.assertEqual(status, 200)

    def test_10_format_with_syntax_errors_does_not_crash_server(self):
        broken_code = "def foo(): broken C++ syntax"
        status, res = self._post("/api/format", {"code": broken_code})
        self.assertEqual(status, 200)
        self.assertIn("error", res)

    def test_11_api_run_endpoint(self):
        if not find_cpp_compiler():
            self.skipTest("No native C++ compiler available")
        code = "#include <iostream>\nint main() { std::cout << \"Workbench Run Works!\" << std::endl; return 0; }"
        status, res = self._post("/api/run", {"code": code})
        self.assertEqual(status, 200)
        self.assertIn("Workbench Run Works!", res["output"])

    def test_12_uncredentialed_api_is_rejected(self):
        req = urllib.request.Request(f"{self.base_url}/api/presets")
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(req)
        self.assertEqual(raised.exception.code, 403)

    def test_13_fix_endpoint_returns_verified_repaired_source(self):
        code = PRESETS["auto_include"]["code"]
        status, res = self._post(
            "/api/terminal/command",
            {"command": "fix", "code": code},
        )
        self.assertEqual(status, 200)
        self.assertEqual(res["repair_status"], "complete")
        self.assertGreaterEqual(res["applied_count"], 3)
        self.assertEqual(res["remaining_errors"], 0)
        self.assertIn("#include <iostream>", res["updated_code"])
        self.assertIn("std::cout", res["updated_code"])

    def test_14_capabilities_report_native_run(self):
        status, _, content = self._get("/api/capabilities")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(content.decode("utf-8"))["native_run"])

    def test_15_safe_mode_blocks_native_run(self):
        safe_server = WorkbenchServer(("127.0.0.1", 0), WorkbenchHandler, enable_native_run=False)
        thread = threading.Thread(target=safe_server.serve_forever, daemon=True)
        thread.start()
        try:
            body = json.dumps({"code": "int main() { return 0; }"}).encode("utf-8")
            req = urllib.request.Request(
                f"http://127.0.0.1:{safe_server.server_port}/api/run",
                data=body,
                headers={"Content-Type": "application/json", "X-Workbench-Token": safe_server.session_token},
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(req)
            self.assertEqual(raised.exception.code, 403)
        finally:
            safe_server.shutdown()
            safe_server.server_close()

    def test_16_showcase_presets_fix_then_run_through_http(self):
        if not find_cpp_compiler():
            self.skipTest("No native C++ compiler available")
        for preset_name in ("cross_language", "missing_delimiters", "expression_repair"):
            with self.subTest(preset=preset_name):
                status, fixed = self._post(
                    "/api/terminal/command",
                    {"command": "fix", "code": PRESETS[preset_name]["code"]},
                )
                self.assertEqual(status, 200)
                self.assertEqual(fixed["repair_status"], "complete")
                status, run = self._post("/api/run", {"code": fixed["updated_code"]})
                self.assertEqual(status, 200)
                self.assertIn("Program exited with code", run["output"])
                self.assertNotIn("Compilation Failed", run["output"])


class TestCompilerExecutionEngine(unittest.TestCase):
    """Tests backend execution of CLI commands and diagnostic extraction."""

    def test_01_execute_check_clean(self):
        code = "#include <iostream>\nint main() { return 0; }"
        res = execute_cli_command("check", code)
        self.assertFalse(res["is_interactive"])
        self.assertIn("Check passed", res["output"])

    def test_02_execute_tokens(self):
        code = "int x = 42;"
        res = execute_cli_command("tokens", code)
        self.assertFalse(res["is_interactive"])
        self.assertIn("Token Stream", res["output"])
        self.assertIn("INT_LIT", res["output"])

    def test_03_execute_fmt(self):
        code = "int main(){int x=5;return x;}"
        res = execute_cli_command("fmt", code)
        self.assertFalse(res["is_interactive"])
        self.assertIsNotNone(res["updated_code"])
        self.assertIn("return x;", res["updated_code"])

    def test_04_execute_explain(self):
        res = execute_cli_command("explain P003", "")
        self.assertIn("Missing Semicolon", res["output"])

    def test_05_execute_fix(self):
        code = "int main() {\n    int x = 10\n    return 0;\n}"
        res = execute_cli_command("fix", code)
        self.assertFalse(res["is_interactive"])
        self.assertIsNotNone(res["updated_code"])
        self.assertIn("int x = 10;", res["updated_code"])

    def test_05a_fix_all_repairs_every_showcase_preset(self):
        for preset_name, preset in PRESETS.items():
            with self.subTest(preset=preset_name):
                res = execute_cli_command("fix", preset["code"])
                if preset_name.startswith("clean_"):
                    self.assertEqual(res["repair_status"], "unchanged")
                    self.assertIsNone(res["updated_code"])
                    continue

                self.assertEqual(res["repair_status"], "complete")
                self.assertIsNotNone(res["updated_code"])
                final = analyze_translation_unit(
                    "main.cpp", res["updated_code"], enable_suggestions=True
                )
                self.assertTrue(final.complete)
                self.assertEqual(final.error_count, 0)

    def test_05b_fix_chains_headers_into_namespace_repairs(self):
        code = "int main(){ cout << 1 << endl; vector<int> v; return 0; }"
        res = execute_cli_command("fix", code)
        self.assertEqual(res["repair_status"], "complete")
        self.assertIn("#include <iostream>", res["updated_code"])
        self.assertIn("#include <vector>", res["updated_code"])
        self.assertIn("std::cout", res["updated_code"])
        self.assertIn("std::vector", res["updated_code"])

    def test_05c_fix_reports_structured_counts(self):
        code = "int main() {\n    int x = 10\n    return 0;\n}"
        res = execute_cli_command("fix", code)
        self.assertEqual(res["repair_status"], "complete")
        self.assertGreaterEqual(res["applied_count"], 1)
        self.assertEqual(res["remaining_errors"], 0)
        self.assertEqual(res["remaining_count"], 0)

    def test_06_structured_diagnostics_detection(self):
        # Code with missing semicolon, operator misuse, and array bounds hazard
        code = (
            "#include <iostream>\n"
            "int main() {\n"
            "    int arr[5];\n"
            "    arr[5] = 10;\n"
            "    if (x = 5) {}\n"
            "    return 0\n"
            "}\n"
        )
        diags = extract_structured_diagnostics(code)
        self.assertIn("errors", diags)
        self.assertIn("warnings", diags)
        error_codes = [e["code"] for e in diags["errors"]]
        warning_codes = [w["code"] for w in diags["warnings"]]
        self.assertTrue(len(error_codes) > 0)
        self.assertTrue("W006" in warning_codes or "W002" in warning_codes)

    def test_07_execute_run_clean(self):
        code = "#include <iostream>\nint main() { std::cout << \"Execution Successful!\" << std::endl; return 0; }"
        res = execute_cli_command("run", code)
        self.assertFalse(res["is_interactive"])
        self.assertIn("Execution Successful!", res["output"])
        self.assertIn("Program exited with code 0", res["output"])

    def test_08_execute_run_with_syntax_errors(self):
        broken_code = PRESETS["cross_language"]["code"]
        res = execute_cli_command("run", broken_code)
        self.assertFalse(res["is_interactive"])
        self.assertIn("Found", res["output"])
        self.assertIn("syntax issue(s) before running", res["output"])


if __name__ == "__main__":
    unittest.main()
