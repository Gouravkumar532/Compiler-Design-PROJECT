import sys
import json
import re
import os
import urllib.parse
from typing import Dict, List, Optional, Any, Tuple

from src.lexer import Lexer
from src.tokens import TokenType, KEYWORDS
from src.parser import Parser
from src.semantic import SemanticAnalyzer
from src.preprocessor import Preprocessor
from src.analyzer import analyze_translation_unit
from src.diagnostics import diagnostic_to_lsp
from src.ast_nodes import *

class LanguageServer:
    """
    Language Server Protocol (LSP) Server for C++ Compiler (Phase 6).
    Compliant with Language Server Protocol v3.17 over JSON-RPC.
    Features:
      - Live diagnostics (errors & warnings as you type)
      - Hover information (type signatures, symbol docs)
      - Autocompletion (keywords, types, variables, methods)
      - Go-to-definition (navigation to variable & function definitions)
    """
    def __init__(self):
        self.documents: Dict[str, str] = {}
        self.doc_symbols: Dict[str, Dict[str, Any]] = {}
        self.running = True

    def run(self):
        """Main stdio loop reading JSON-RPC messages."""
        while self.running:
            msg = self._read_message()
            if msg is None:
                break
            response = self.handle_message(msg)
            if response is not None:
                self._send_message(response)

    def _read_message(self) -> Optional[dict]:
        """Reads a JSON-RPC message with Content-Length header from stdin (binary UTF-8 safe)."""
        content_length = None
        stdin_buf = getattr(sys.stdin, "buffer", sys.stdin)
        while True:
            raw_line = stdin_buf.readline()
            if not raw_line:
                return None
            line = raw_line.decode("latin-1", errors="replace").strip() if isinstance(raw_line, bytes) else raw_line.strip()
            if not line:
                break
            if line.lower().startswith("content-length:"):
                try:
                    content_length = int(line.split(":", 1)[1].strip())
                except ValueError:
                    return None

        if content_length is None:
            return None

        body_data = stdin_buf.read(content_length)
        if not body_data or len(body_data) < content_length:
            return None
        try:
            body = body_data.decode("utf-8") if isinstance(body_data, bytes) else body_data
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _send_message(self, msg: dict):
        """Sends a JSON-RPC response or notification to stdout (binary UTF-8 safe)."""
        body = json.dumps(msg, separators=(',', ':'))
        body_bytes = body.encode("utf-8")
        header = f"Content-Length: {len(body_bytes)}\r\n\r\n".encode("ascii")
        stdout_buf = getattr(sys.stdout, "buffer", sys.stdout)
        if hasattr(stdout_buf, "write"):
            if isinstance(header, bytes) and not hasattr(stdout_buf, "buffer") and hasattr(stdout_buf, "encoding"):
                stdout_buf.write(header.decode("ascii") + body)
            else:
                stdout_buf.write(header + body_bytes)
            stdout_buf.flush()

    def handle_message(self, msg: dict) -> Optional[dict]:
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "capabilities": {
                        "textDocumentSync": 1,  # Full text sync
                        "hoverProvider": True,
                        "completionProvider": {
                            "resolveProvider": False,
                            "triggerCharacters": [".", ":", ">"]
                        },
                        "definitionProvider": True
                    },
                    "serverInfo": {
                        "name": "c++-language-server",
                        "version": "1.0.0"
                    }
                }
            }

        elif method == "initialized":
            return None

        elif method == "shutdown":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": None
            }

        elif method == "exit":
            self.running = False
            return None

        elif method == "textDocument/didOpen":
            doc = params.get("textDocument", {})
            uri = doc.get("uri", "")
            text = doc.get("text", "")
            self.documents[uri] = text
            self._validate_document(uri, text)
            return None

        elif method == "textDocument/didChange":
            doc = params.get("textDocument", {})
            uri = doc.get("uri", "")
            changes = params.get("contentChanges", [])
            if changes:
                text = changes[-1].get("text", "")
                self.documents[uri] = text
                self._validate_document(uri, text)
            return None

        elif method == "textDocument/didSave":
            doc = params.get("textDocument", {})
            uri = doc.get("uri", "")
            text = self.documents.get(uri, "")
            self._validate_document(uri, text)
            return None

        elif method == "textDocument/hover":
            uri = params.get("textDocument", {})["uri"]
            pos = params.get("position", {})
            line = pos.get("line", 0) + 1
            character = pos.get("character", 0) + 1
            hover_res = self._get_hover(uri, line, character)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": hover_res
            }

        elif method == "textDocument/completion":
            uri = params.get("textDocument", {})["uri"]
            pos = params.get("position", {})
            items = self._get_completions(uri, pos.get("line", 0) + 1, pos.get("character", 0) + 1)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": items
            }

        elif method == "textDocument/definition":
            uri = params.get("textDocument", {})["uri"]
            pos = params.get("position", {})
            defn = self._get_definition(uri, pos.get("line", 0) + 1, pos.get("character", 0) + 1)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": defn
            }

        if msg_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' not found"
                }
            }
        return None

    def _validate_document(self, uri: str, text: str):
        """Parses and type-checks the document via canonical analyzer, publishing LSP diagnostics."""
        clean_uri = urllib.parse.unquote(uri)
        file_path = clean_uri.replace("file:///", "").replace("file://", "")
        if os.name == "nt" and re.match(r"^/[A-Za-z]:", file_path):
            file_path = file_path[1:]

        result = analyze_translation_unit(file_path, text, enable_suggestions=True)
        if result.ast is not None:
            self._extract_symbols(uri, result.ast)

        diagnostics = [diagnostic_to_lsp(d) for d in result.diagnostics]

        # Send publishDiagnostics notification
        self._send_message({
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": uri,
                "diagnostics": diagnostics
            }
        })

    def _extract_symbols(self, uri: str, ast: Program):
        """Extracts symbol definitions and positions for definition and hover."""
        sym_map = {}
        for decl in ast.declarations:
            if isinstance(decl, FunctionDef):
                sym_map[decl.name] = {
                    "kind": "function",
                    "type": decl.return_type,
                    "params": [f"{p.param_type} {p.name}" for p in decl.params],
                    "line": decl.line,
                    "col": decl.col,
                    "is_constexpr": getattr(decl, "is_constexpr", False),
                    "is_virtual": getattr(decl, "is_virtual", False),
                }
            elif isinstance(decl, ClassDef):
                sym_map[decl.name] = {
                    "kind": "class",
                    "base": decl.base_class,
                    "line": decl.line,
                    "col": decl.col,
                    "members": {m.decl.name: m for m in decl.members if hasattr(m.decl, "name")}
                }
            elif isinstance(decl, VarDeclaration):
                sym_map[decl.name] = {
                    "kind": "variable",
                    "type": decl.var_type,
                    "line": decl.line,
                    "col": decl.col,
                    "is_constexpr": getattr(decl, "is_constexpr", False),
                    "is_const": decl.is_const,
                }
        self.doc_symbols[uri] = sym_map

    def _get_hover(self, uri: str, line: int, col: int) -> Optional[dict]:
        """Returns hover information for the symbol under cursor."""
        text = self.documents.get(uri, "")
        token_word = self._get_word_at_position(text, line, col)
        if not token_word:
            return None

        # Check document symbols
        syms = self.doc_symbols.get(uri, {})
        if token_word in syms:
            info = syms[token_word]
            if info["kind"] == "function":
                sig = f"{'constexpr ' if info['is_constexpr'] else ''}{'virtual ' if info['is_virtual'] else ''}{info['type']} {token_word}({', '.join(info['params'])})"
                md = f"```cpp\n{sig}\n```\n*User-defined function*"
            elif info["kind"] == "class":
                base_str = f" : public {info['base']}" if info['base'] else ""
                md = f"```cpp\nclass {token_word}{base_str}\n```\n*User-defined class*"
            elif info["kind"] == "variable":
                prefix = "constexpr " if info["is_constexpr"] else ("const " if info["is_const"] else "")
                md = f"```cpp\n{prefix}{info['type']} {token_word}\n```\n*Variable declaration*"
            else:
                md = f"**{token_word}**"
            return {"contents": {"kind": "markdown", "value": md}}

        # Check standard C++ keywords
        if token_word in KEYWORDS:
            return {
                "contents": {
                    "kind": "markdown",
                    "value": f"```cpp\n(keyword) {token_word}\n```\nC++ keyword."
                }
            }

        return None

    def _get_completions(self, uri: str, line: int, col: int) -> List[dict]:
        """Returns autocomplete items."""
        items = []

        # 1. Keywords
        for kw in sorted(KEYWORDS.keys()):
            items.append({
                "label": kw,
                "kind": 14, # Keyword
                "detail": "keyword"
            })

        # 2. Primitive Types
        types = ["int", "float", "double", "char", "void", "bool", "auto", "string"]
        for t in types:
            items.append({
                "label": t,
                "kind": 7, # Class / Type
                "detail": "primitive type"
            })

        # 3. Document symbols
        syms = self.doc_symbols.get(uri, {})
        for name, info in syms.items():
            kind_num = 3 if info["kind"] == "function" else (7 if info["kind"] == "class" else 6)
            items.append({
                "label": name,
                "kind": kind_num,
                "detail": f"{info['kind']}: {info.get('type', '')}"
            })

        # 4. Standard I/O library
        std_items = [
            ("cout", 6, "std::cout standard output stream"),
            ("cin", 6, "std::cin standard input stream"),
            ("endl", 6, "std::endl newline and flush"),
            ("printf", 3, "extern printf formatting"),
            ("scanf", 3, "extern scanf formatting"),
        ]
        for name, k, det in std_items:
            items.append({
                "label": name,
                "kind": k,
                "detail": det
            })

        return items

    def _get_definition(self, uri: str, line: int, col: int) -> Optional[dict]:
        """Returns go-to-definition location."""
        text = self.documents.get(uri, "")
        token_word = self._get_word_at_position(text, line, col)
        if not token_word:
            return None

        syms = self.doc_symbols.get(uri, {})
        if token_word in syms:
            info = syms[token_word]
            defn_line = max(0, info["line"] - 1)
            defn_col = max(0, info["col"] - 1)
            return {
                "uri": uri,
                "range": {
                    "start": {"line": defn_line, "character": defn_col},
                    "end": {"line": defn_line, "character": defn_col + len(token_word)}
                }
            }
        return None

    def _get_word_at_position(self, text: str, line: int, col: int) -> Optional[str]:
        lines = text.splitlines()
        if line - 1 >= len(lines):
            return None
        current_line = lines[line - 1]
        char_idx = col - 1

        if char_idx >= len(current_line):
            char_idx = len(current_line) - 1
        if char_idx < 0:
            return None

        # Look for word boundaries
        start = char_idx
        while start > 0 and (current_line[start - 1].isalnum() or current_line[start - 1] == '_'):
            start -= 1

        end = char_idx
        while end < len(current_line) and (current_line[end].isalnum() or current_line[end] == '_'):
            end += 1

        word = current_line[start:end]
        return word if word else None
