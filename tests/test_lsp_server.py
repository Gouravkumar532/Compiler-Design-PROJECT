import json
import os
import subprocess
import sys
import tempfile
import time
import unittest


class TestPhase9VSCodeLSP(unittest.TestCase):
    """Smoke tests for the Language Server Protocol (LSP) server."""

    @classmethod
    def setUpClass(cls):
        cls.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        cls.main_py_path = os.path.join(cls.project_root, "main.py")

    def test_lsp_server_initialize_shutdown_exit_lifecycle(self):
        """Test full stdio JSON-RPC handshake against 'python main.py lsp'."""
        proc = subprocess.Popen(
            [sys.executable, self.main_py_path, "lsp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )

        def send_msg(msg_dict):
            body = json.dumps(msg_dict).encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
            proc.stdin.write(header + body)
            proc.stdin.flush()

        def read_msg(timeout_sec=5.0):
            start = time.time()
            content_length = None
            while time.time() - start < timeout_sec:
                line = proc.stdout.readline()
                if not line:
                    continue
                line_str = line.decode("utf-8").strip()
                if line_str.startswith("Content-Length:"):
                    content_length = int(line_str.split(":")[1].strip())
                elif line_str == "" and content_length is not None:
                    body = proc.stdout.read(content_length)
                    return json.loads(body.decode("utf-8"))
            return None

        try:
            # 1. Initialize request
            send_msg({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "processId": os.getpid(),
                    "capabilities": {}
                }
            })

            init_resp = read_msg()
            self.assertIsNotNone(init_resp, "Server should respond to initialize")
            self.assertEqual(init_resp.get("id"), 1)
            self.assertIn("capabilities", init_resp.get("result", {}))

            # 2. Initialized notification
            send_msg({
                "jsonrpc": "2.0",
                "method": "initialized",
                "params": {}
            })

            # 3. Shutdown request
            send_msg({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "shutdown",
                "params": {}
            })

            shutdown_resp = read_msg()
            self.assertIsNotNone(shutdown_resp, "Server should respond to shutdown")
            self.assertEqual(shutdown_resp.get("id"), 2)

            # 4. Exit notification
            send_msg({
                "jsonrpc": "2.0",
                "method": "exit",
                "params": {}
            })

            proc.wait(timeout=5)
            self.assertEqual(proc.returncode, 0)
        finally:
            try:
                if proc.stdin: proc.stdin.close()
                if proc.stdout: proc.stdout.close()
                if proc.stderr: proc.stderr.close()
            except Exception:
                pass
            if proc.poll() is None:
                proc.kill()

    def test_lsp_diagnostics_published_for_broken_cpp_document(self):
        """Test that opening a broken C++ file triggers publishDiagnostics."""
        proc = subprocess.Popen(
            [sys.executable, self.main_py_path, "lsp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )

        def send_msg(msg_dict):
            body = json.dumps(msg_dict).encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
            proc.stdin.write(header + body)
            proc.stdin.flush()

        def read_msg(timeout_sec=5.0):
            start = time.time()
            content_length = None
            while time.time() - start < timeout_sec:
                line = proc.stdout.readline()
                if not line:
                    continue
                line_str = line.decode("utf-8").strip()
                if line_str.startswith("Content-Length:"):
                    content_length = int(line_str.split(":")[1].strip())
                elif line_str == "" and content_length is not None:
                    body = proc.stdout.read(content_length)
                    return json.loads(body.decode("utf-8"))
            return None

        try:
            # Initialize
            send_msg({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"capabilities": {}}
            })
            read_msg()

            send_msg({
                "jsonrpc": "2.0",
                "method": "initialized",
                "params": {}
            })

            # didOpen with missing semicolon
            doc_uri = "file:///test_broken.cpp"
            broken_code = "int main() {\n    int a = 10\n    return a;\n}"
            send_msg({
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": doc_uri,
                        "languageId": "cpp",
                        "version": 1,
                        "text": broken_code
                    }
                }
            })

            # Expect publishDiagnostics notification
            diag_msg = read_msg(timeout_sec=5.0)
            self.assertIsNotNone(diag_msg, "Server should publish diagnostics")
            self.assertEqual(diag_msg.get("method"), "textDocument/publishDiagnostics")
            params = diag_msg.get("params", {})
            self.assertEqual(params.get("uri"), doc_uri)
            diagnostics = params.get("diagnostics", [])
            self.assertTrue(len(diagnostics) > 0, "Should contain at least one diagnostic")
            # Verify code is P003 (missing semicolon)
            codes = [d.get("code") for d in diagnostics]
            self.assertIn("P003", codes)

            # Shutdown & exit
            send_msg({"jsonrpc": "2.0", "id": 2, "method": "shutdown"})
            read_msg()
            send_msg({"jsonrpc": "2.0", "method": "exit"})
            proc.wait(timeout=5)
        finally:
            try:
                if proc.stdin: proc.stdin.close()
                if proc.stdout: proc.stdout.close()
                if proc.stderr: proc.stderr.close()
            except Exception:
                pass
            if proc.poll() is None:
                proc.kill()

    def test_lsp_unicode_framing_non_ascii(self):
        """Test that multibyte Unicode text framing works without message corruption."""
        proc = subprocess.Popen(
            [sys.executable, self.main_py_path, "lsp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )

        def send_msg(msg_dict):
            body = json.dumps(msg_dict, separators=(',', ':')).encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            proc.stdin.write(header + body)
            proc.stdin.flush()

        def read_msg(timeout_sec=5.0):
            start = time.time()
            content_length = None
            while time.time() - start < timeout_sec:
                line = proc.stdout.readline()
                if not line:
                    continue
                line_str = line.decode("latin-1").strip()
                if line_str.lower().startswith("content-length:"):
                    content_length = int(line_str.split(":")[1].strip())
                elif line_str == "" and content_length is not None:
                    body = proc.stdout.read(content_length)
                    return json.loads(body.decode("utf-8"))
            return None

        try:
            unicode_code = "const char* msg = \"Hello \xe2\x80\x94 \xe4\xb8\x96\xe7\x95\x8c \xf0\x9f\x9a\x80 caf\xc3\xa9\";\nint missing_semi = 42\n"
            send_msg({
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": "file:///test_utf8.cpp",
                        "languageId": "cpp",
                        "version": 1,
                        "text": unicode_code
                    }
                }
            })

            resp1 = read_msg()
            self.assertIsNotNone(resp1, "Should receive diagnostics for unicode document")
            self.assertEqual(resp1.get("method"), "textDocument/publishDiagnostics")

            # Subsequent message should parse cleanly
            send_msg({
                "jsonrpc": "2.0",
                "id": 99,
                "method": "shutdown",
                "params": {}
            })
            resp2 = read_msg()
            self.assertIsNotNone(resp2, "Should receive shutdown response after unicode message")
            self.assertEqual(resp2.get("id"), 99)

            send_msg({"jsonrpc": "2.0", "method": "exit", "params": {}})
            proc.wait(timeout=5)
            self.assertEqual(proc.returncode, 0)
        finally:
            try:
                if proc.stdin: proc.stdin.close()
                if proc.stdout: proc.stdout.close()
                if proc.stderr: proc.stderr.close()
            except Exception:
                pass
            if proc.poll() is None:
                proc.kill()


if __name__ == "__main__":
    unittest.main()
