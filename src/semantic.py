from typing import Dict, List, Optional, Set, Any, Tuple
import os
import re
from src.ast_nodes import *
from src.errors import report_error, report_warning, find_closest_match, Colors, report_missing_header, report_unqualified_namespace
from src.stdlib_registry import registry, StdlibRegistry
from src.auto_include import AutoIncludeEngine, MissingHeaderDiagnostic
from src.namespace_resolution import NamespaceResolutionEngine, UnqualifiedNamespaceDiagnostic
from src.operator_misuse import OperatorMisuseEngine, OperatorDiagnostic
from src.array_bounds import ArrayBoundsEngine, ArrayBoundsDiagnostic
from src.diagnostics import DiagnosticSink, make_diagnostic
from src.paths import canonical_path, same_file

class Symbol:
    def __init__(self, name: str, s_type: str, line: int = 1, col: int = 1, is_const: bool = False, is_reference: bool = False, is_constexpr: bool = False, const_value: Any = None, array_size: Optional[int] = None, array_dimensions: Optional[List[int]] = None, file: Optional[str] = None, macro_generated: bool = False):
        self.name = name
        self.s_type = s_type
        self.line = line
        self.col = col
        self.is_used = False
        self.is_const = is_const
        self.is_reference = is_reference
        self.is_constexpr = is_constexpr
        self.const_value = const_value
        self.array_size = array_size
        self.array_dimensions = array_dimensions if array_dimensions is not None else ([array_size] if array_size is not None else [])
        self.file = file
        self.macro_generated = macro_generated

class StructSymbol:
    def __init__(self, name: str, members: List[Parameter]):
        self.name = name
        self.members = members

class ClassSymbol:
    def __init__(self, name: str, members: List[ClassMember], base_class: Optional[str] = None, base_access: str = "public"):
        self.name = name
        self.members = members
        self.base_class = base_class
        self.base_access = base_access
        self.fields = {} # name -> (type, access, is_const, is_ref)
        self.methods = {} # name -> List[(FunctionDef, access)]
        self.constructors = [] # List[(ConstructorDef, access)]
        self.destructors = [] # List[(DestructorDef, access)]
        self.is_abstract = False
        self.pure_virtual_methods: Set[str] = set()
        self.virtual_methods: Dict[str, FunctionDef] = {}
        for m in members:
            if isinstance(m.decl, VarDeclaration):
                self.fields[m.decl.name] = (m.decl.var_type, m.access, m.decl.is_const, m.decl.is_reference)
            elif isinstance(m.decl, FunctionDef):
                self.methods.setdefault(m.decl.name, []).append((m.decl, m.access))
                if m.decl.is_pure_virtual:
                    self.is_abstract = True
                    self.pure_virtual_methods.add(m.decl.name)
                if m.decl.is_virtual or m.decl.is_pure_virtual or m.decl.is_override:
                    self.virtual_methods[m.decl.name] = m.decl
            elif isinstance(m.decl, ConstructorDef):
                self.constructors.append((m.decl, m.access))
            elif isinstance(m.decl, DestructorDef):
                self.destructors.append((m.decl, m.access))

    def inherit_from(self, base_sym: 'ClassSymbol'):
        # Inherit fields
        new_fields = {}
        for f_name, f_info in base_sym.fields.items():
            f_type, f_acc, f_const, f_ref = f_info
            effective_acc = f_acc
            if self.base_access == "private":
                effective_acc = "private"
            elif self.base_access == "protected" and f_acc == "public":
                effective_acc = "protected"
            new_fields[f_name] = (f_type, effective_acc, f_const, f_ref)
        new_fields.update(self.fields)
        self.fields = new_fields

        # Inherit methods
        for m_name, m_list in base_sym.methods.items():
            if m_name not in self.methods:
                self.methods[m_name] = list(m_list)

        # Inherit pure virtual methods
        for pvm in base_sym.pure_virtual_methods:
            if pvm not in self.methods or any(m.is_pure_virtual for m, _ in self.methods[pvm]):
                self.pure_virtual_methods.add(pvm)
                self.is_abstract = True

        # Inherit virtual methods
        for vm_name, vm_def in base_sym.virtual_methods.items():
            if vm_name not in self.virtual_methods:
                self.virtual_methods[vm_name] = vm_def

class SymbolTable:
    def __init__(self, parent=None):
        self.symbols: Dict[str, Symbol] = {}
        self.structs: Dict[str, StructSymbol] = {}
        self.classes: Dict[str, ClassSymbol] = {}
        self.functions: Dict[str, List[FunctionDef]] = {}
        self.active_namespaces: Set[str] = set()
        self.parent = parent

    def define(self, name: str, s_type: str, line: int = 1, col: int = 1, is_const: bool = False, is_reference: bool = False, is_constexpr: bool = False, const_value: Any = None, array_size: Optional[int] = None, array_dimensions: Optional[List[int]] = None, file: Optional[str] = None, macro_generated: bool = False) -> Symbol:
        sym = Symbol(name, s_type, line, col, is_const=is_const, is_reference=is_reference, is_constexpr=is_constexpr, const_value=const_value, array_size=array_size, array_dimensions=array_dimensions, file=file, macro_generated=macro_generated)
        self.symbols[name] = sym
        return sym
        
    def define_struct(self, name: str, members: List[Parameter]):
        self.structs[name] = StructSymbol(name, members)

    def define_class(self, name: str, members: List[ClassMember], base_class: Optional[str] = None, base_access: str = "public") -> ClassSymbol:
        sym = ClassSymbol(name, members, base_class=base_class, base_access=base_access)
        self.classes[name] = sym
        return sym

    def define_function(self, func: FunctionDef):
        self.functions.setdefault(func.name, []).append(func)
        self.define(
            func.name,
            func.return_type,
            func.line,
            func.col,
            file=getattr(func, "file", None),
            macro_generated=bool(getattr(func, "macro_generated", False)),
        )

    def get_active_namespaces(self) -> Set[str]:
        ns = set(self.active_namespaces)
        if self.parent:
            ns.update(self.parent.get_active_namespaces())
        return ns

    def resolve(self, name: str) -> Optional[Symbol]:
        if name in self.symbols:
            return self.symbols[name]
        for ns in self.get_active_namespaces():
            ns_name = f"{ns}::{name}"
            if ns_name in self.symbols:
                return self.symbols[ns_name]
        if self.parent:
            return self.parent.resolve(name)
        return None
        
    def resolve_struct(self, name: str) -> Optional[StructSymbol]:
        if name in self.structs:
            return self.structs[name]
        if self.parent:
            return self.parent.resolve_struct(name)
        return None

    def resolve_class(self, name: str) -> Optional[ClassSymbol]:
        if name in self.classes:
            return self.classes[name]
        for ns in self.get_active_namespaces():
            ns_name = f"{ns}::{name}"
            curr = self
            while curr:
                if ns_name in curr.classes:
                    return curr.classes[ns_name]
                curr = curr.parent
        if self.parent:
            return self.parent.resolve_class(name)
        return None

    def _find_function_in_tree(self, name: str, arg_count: Optional[int] = None) -> Optional[FunctionDef]:
        curr = self
        while curr:
            if name in curr.functions:
                funcs = curr.functions[name]
                if arg_count is None:
                    return funcs[0]
                for f in funcs:
                    if len(f.params) == arg_count:
                        return f
                return funcs[0]
            curr = curr.parent
        return None

    def _find_all_functions_in_tree(self, name: str) -> List[FunctionDef]:
        curr = self
        res = []
        while curr:
            if name in curr.functions:
                res.extend(curr.functions[name])
            curr = curr.parent
        return res

    def resolve_function(self, name: str, arg_count: Optional[int] = None) -> Optional[FunctionDef]:
        found = self._find_function_in_tree(name, arg_count)
        if found:
            return found
        for ns in self.get_active_namespaces():
            ns_name = f"{ns}::{name}"
            found = self._find_function_in_tree(ns_name, arg_count)
            if found:
                return found
        return None

    def resolve_all_functions(self, name: str) -> List[FunctionDef]:
        funcs = self._find_all_functions_in_tree(name)
        if funcs:
            return funcs
        for ns in self.get_active_namespaces():
            ns_name = f"{ns}::{name}"
            funcs = self._find_all_functions_in_tree(ns_name)
            if funcs:
                return funcs
        return []

    def all_names(self) -> List[str]:
        names = set(self.symbols.keys())
        names.update(self.classes.keys())
        names.update(self.functions.keys())
        if self.parent:
            names.update(self.parent.all_names())
        return list(names)

class SemanticAnalyzer:
    def __init__(
        self,
        source: str,
        filename: str,
        warn_as_error: bool = False,
        included_headers: Optional[Set[str]] = None,
        auto_include: bool = True,
        exit_on_error: bool = False,
        patch_recorder: Optional[List[Any]] = None,
        preproc_result: Optional[Any] = None,
        diag_sink: Optional[DiagnosticSink] = None,
    ):
        self.filename = filename
        self.preproc_result = preproc_result
        self.entry_file = preproc_result.entry_file if preproc_result is not None else canonical_path(filename)
        if preproc_result is not None and self.entry_file in preproc_result.file_sources and source == preproc_result.analysis_source:
            self.source = preproc_result.file_sources[self.entry_file]
        else:
            self.source = source
        self.warn_as_error = warn_as_error
        self.exit_on_error = exit_on_error
        self.patch_recorder = patch_recorder
        self.global_scope = SymbolTable()
        self.current_scope = self.global_scope
        self.current_function = None
        self.current_class: Optional[ClassSymbol] = None
        self.loop_depth = 0
        self.tracked_variables: List[Symbol] = []
        self.warnings_count = 0
        self.errors_count = 0
        self.templates: Dict[str, TemplateDef] = {}
        self.ast: Optional[Program] = None

        display_names = dict(preproc_result.display_names) if preproc_result is not None else {self.entry_file: filename}
        self.sink: DiagnosticSink = diag_sink if diag_sink is not None else DiagnosticSink(emit=True, display_names=display_names)
        self.diagnostics = self.sink.diagnostics
        self._emit_console = self.sink.emit

        self.registry = registry
        self.auto_include = auto_include
        self.auto_include_engine = AutoIncludeEngine(
            self.source,
            filename,
            enable_repair=auto_include,
            stdlib_reg=self.registry,
        )
        scanned_headers = self.auto_include_engine.scan_included_headers(source) | self.auto_include_engine.scan_included_headers(self.source)
        if preproc_result is not None and getattr(preproc_result, "included_headers", None):
            scanned_headers |= set(preproc_result.included_headers)
        if included_headers is not None:
            scanned_headers |= set(included_headers)
        self.included_headers = scanned_headers
        self.missing_headers: List[str] = []
        self.missing_header_diagnostics: List[MissingHeaderDiagnostic] = []
        self._recorded_header_patches: Set[Tuple[str, str]] = set()

        self.namespace_engine = NamespaceResolutionEngine(
            self.source,
            filename,
            enable_repair=auto_include,
            stdlib_reg=self.registry,
        )
        self.namespace_diagnostics: List[UnqualifiedNamespaceDiagnostic] = []

        self.operator_engine = OperatorMisuseEngine(
            self.source,
            filename,
            enable_repair=auto_include,
            warn_as_error=warn_as_error,
        )
        self.operator_diagnostics: List[OperatorDiagnostic] = []

        self.array_bounds_engine = ArrayBoundsEngine(
            self.source,
            filename,
            enable_repair=auto_include,
            warn_as_error=warn_as_error,
        )
        self.array_bounds_diagnostics: List[ArrayBoundsDiagnostic] = []

        # Built-in standard library
        self._init_std_library()

    def _init_std_library(self):
        # Always available C++ primitives / language constants
        for null_sym in ["nullptr", "NULL"]:
            s_null = self.global_scope.define(null_sym, "nullptr", 1, 1, is_const=True)
            s_null.is_used = True

        # Header: <iostream>
        if self.registry.is_header_included("iostream", self.included_headers):
            ostream_members = [
                ClassMember(FunctionDef("std::ostream&", "operator<<", [Parameter("int", "v", 1, 1)], is_method=True, class_name="std::ostream"), "public", 1, 1),
                ClassMember(FunctionDef("std::ostream&", "operator<<", [Parameter("double", "v", 1, 1)], is_method=True, class_name="std::ostream"), "public", 1, 1),
                ClassMember(FunctionDef("std::ostream&", "operator<<", [Parameter("char", "v", 1, 1)], is_method=True, class_name="std::ostream"), "public", 1, 1),
                ClassMember(FunctionDef("std::ostream&", "operator<<", [Parameter("char*", "v", 1, 1)], is_method=True, class_name="std::ostream"), "public", 1, 1),
                ClassMember(FunctionDef("std::ostream&", "operator<<", [Parameter("bool", "v", 1, 1)], is_method=True, class_name="std::ostream"), "public", 1, 1),
            ]
            self.global_scope.define_class("std::ostream", ostream_members)

            istream_members = [
                ClassMember(FunctionDef("std::istream&", "operator>>", [Parameter("int", "v", 1, 1, is_reference=True)], is_method=True, class_name="std::istream"), "public", 1, 1),
                ClassMember(FunctionDef("std::istream&", "operator>>", [Parameter("double", "v", 1, 1, is_reference=True)], is_method=True, class_name="std::istream"), "public", 1, 1),
                ClassMember(FunctionDef("std::istream&", "operator>>", [Parameter("char", "v", 1, 1, is_reference=True)], is_method=True, class_name="std::istream"), "public", 1, 1),
            ]
            self.global_scope.define_class("std::istream", istream_members)

            for sym_name, ret_t in [("cout", "std::ostream"), ("cin", "std::istream"), ("cerr", "std::ostream"), ("clog", "std::ostream")]:
                self.global_scope.define(f"std::{sym_name}", ret_t, 1, 1).is_used = True
            self.global_scope.define("std::endl", "char", 1, 1, is_const=True).is_used = True

        # Header: <string>
        if self.registry.is_header_included("string", self.included_headers):
            str_members = [
                ClassMember(ConstructorDef("string", [], None, 1, 1), "public", 1, 1),
                ClassMember(ConstructorDef("string", [Parameter("char*", "s", 1, 1)], None, 1, 1), "public", 1, 1),
                ClassMember(ConstructorDef("string", [Parameter("string", "s", 1, 1)], None, 1, 1), "public", 1, 1),
                ClassMember(FunctionDef("char*", "c_str", [], is_method=True, class_name="std::string"), "public", 1, 1),
                ClassMember(FunctionDef("int", "length", [], is_method=True, class_name="std::string"), "public", 1, 1),
                ClassMember(FunctionDef("int", "size", [], is_method=True, class_name="std::string"), "public", 1, 1),
            ]
            self.global_scope.define_class("std::string", str_members)
            for fn in ["to_string", "stoi", "stol", "stoll", "stod", "stof", "getline"]:
                self.global_scope.define(f"std::{fn}", "string" if "to_" in fn else "int", 1, 1).is_used = True

        # Header: <vector>
        if self.registry.is_header_included("vector", self.included_headers):
            vec_members = [
                ClassMember(FunctionDef("void", "push_back", [Parameter("int", "v", 1, 1)], is_method=True, class_name="std::vector"), "public", 1, 1),
                ClassMember(FunctionDef("int", "size", [], is_method=True, class_name="std::vector"), "public", 1, 1),
                ClassMember(FunctionDef("void", "clear", [], is_method=True, class_name="std::vector"), "public", 1, 1),
            ]
            self.global_scope.define_class("std::vector", vec_members)

        # Header: <cstdio> / <stdio.h>
        if self.registry.is_header_included("cstdio", self.included_headers):
            for fn in ["printf", "scanf", "sprintf", "snprintf", "fprintf", "fscanf", "fopen", "fclose", "fread", "fwrite", "puts", "getchar", "putchar", "fputs", "fgets"]:
                self.global_scope.define(fn, "int", 1, 1).is_used = True
                self.global_scope.define(f"std::{fn}", "int", 1, 1).is_used = True
            self.global_scope.define_class("FILE", [])
            self.global_scope.define_class("std::FILE", [])

        # Header: <cstdlib> / <stdlib.h>
        if self.registry.is_header_included("cstdlib", self.included_headers):
            for fn, ret_t in [
                ("malloc", "ptr"), ("free", "void"), ("calloc", "ptr"), ("realloc", "ptr"),
                ("exit", "void"), ("abort", "void"), ("rand", "int"), ("srand", "void"),
                ("atoi", "int"), ("atol", "int"), ("atof", "double"), ("system", "int")
            ]:
                self.global_scope.define(fn, ret_t, 1, 1).is_used = True
                self.global_scope.define(f"std::{fn}", ret_t, 1, 1).is_used = True

        # Header: <cmath> / <math.h>
        if self.registry.is_header_included("cmath", self.included_headers):
            for fn in ["sqrt", "pow", "abs", "fabs", "sin", "cos", "tan", "floor", "ceil", "round", "log", "log10", "exp", "hypot"]:
                self.global_scope.define(fn, "double", 1, 1).is_used = True
                self.global_scope.define(f"std::{fn}", "double", 1, 1).is_used = True

        # Header: <algorithm>
        if self.registry.is_header_included("algorithm", self.included_headers):
            for fn in ["sort", "reverse", "max", "min", "find", "count", "accumulate"]:
                self.global_scope.define(fn, "void", 1, 1).is_used = True
                self.global_scope.define(f"std::{fn}", "void", 1, 1).is_used = True

        # Header: <map>
        if self.registry.is_header_included("map", self.included_headers):
            self.global_scope.define_class("std::map", [])

        # Header: <set>
        if self.registry.is_header_included("set", self.included_headers):
            self.global_scope.define_class("std::set", [])

        # Header: <unordered_map>
        if self.registry.is_header_included("unordered_map", self.included_headers):
            self.global_scope.define_class("std::unordered_map", [])

        # Header: <memory>
        if self.registry.is_header_included("memory", self.included_headers):
            self.global_scope.define_class("std::unique_ptr", [])
            self.global_scope.define_class("std::shared_ptr", [])
            for fn in ["make_unique", "make_shared"]:
                self.global_scope.define(f"std::{fn}", "ptr", 1, 1).is_used = True

    def _add_diag(self, diag: Any) -> bool:
        added = self.sink.add(diag)
        if added:
            if diag.severity in ("error", "internal"):
                self.errors_count += 1
            elif diag.severity == "warning":
                self.warnings_count += 1
        return added

    def _is_current_file(self, target: Any = None) -> bool:
        if target is None:
            return True
        if isinstance(target, str):
            return same_file(target, self.entry_file)
        t_file = getattr(target, "file", None)
        if not t_file:
            return True
        return same_file(t_file, self.entry_file)

    def _emit_missing_header(self, node: ASTNode, sym_name: str, header: str, col_override: Optional[int] = None):
        origin_file, file_source = self._get_file_and_source(node)
        node_line = getattr(node, "line", 1)
        sym_col = col_override if col_override is not None else getattr(node, "col", 1)
        is_gen = bool(getattr(node, "macro_generated", False))
        can_patch = not is_gen

        diag = self.auto_include_engine.create_diagnostic(
            symbol=sym_name,
            header=header,
            line=node_line,
            col=sym_col,
            length=len(sym_name),
            file=origin_file,
            source_override=file_source,
            macro_generated=is_gen,
        )
        if not self.auto_include_engine.report_diagnostic(diag, emit=False, filename_override=origin_file, source_override=file_source):
            return

        self.missing_header_diagnostics.append(diag)
        if can_patch and self._is_current_file(origin_file) and header not in self.missing_headers:
            self.missing_headers.append(header)

        patch_obj = None
        if can_patch:
            from src.patch_model import CodePatch
            patch_obj = CodePatch(
                file_path=origin_file,
                line_start=diag.insertion_line,
                line_end=diag.insertion_line,
                col_start=1,
                col_end=1,
                original_text="",
                replacement_text=f"#include <{header}>\n",
                error_code="E015",
                summary=f"Missing Header: add '#include <{header}>'",
                explanations=[f"Standard library symbol requires header '<{header}>'."],
                confidence="safe",
            )
            if self.patch_recorder is not None and (origin_file, header) not in self._recorded_header_patches:
                self._recorded_header_patches.add((origin_file, header))
                self.patch_recorder.append(patch_obj)

        canon_diag = make_diagnostic(
            code="E015",
            severity="error",
            message=f"use of undeclared identifier '{sym_name}'",
            file_path=origin_file,
            line=node_line,
            col=sym_col,
            end_line=node_line,
            end_col=sym_col + max(1, len(sym_name)),
            source=file_source,
            help_text=f"'{sym_name}' is defined in header '<{header}>'",
            stage="semantic",
            style="missing_header",
            suggestion=f"#include <{header}>" if can_patch else None,
            explanations=[f"'{sym_name}' is defined in header '<{header}>'"],
            fixability="auto" if can_patch else "none",
            patch=patch_obj,
            macro_generated=is_gen,
            extra={"action": f"add '#include <{header}>' at line {diag.insertion_line}"},
        )
        self._add_diag(canon_diag)

    def _emit_unqualified_namespace(
        self,
        node: ASTNode,
        sym_name: str,
        target_ns: str,
        kind: str = "identifier",
        col_override: Optional[int] = None,
        other_namespaces: Optional[List[str]] = None,
    ):
        origin_file, file_source = self._get_file_and_source(node)
        node_line = getattr(node, "line", 1)
        sym_col = col_override if col_override is not None else getattr(node, "col", 1)
        is_gen = bool(getattr(node, "macro_generated", False))
        can_patch = not is_gen

        diag = self.namespace_engine.create_diagnostic(
            symbol=sym_name,
            namespace=target_ns,
            line=node_line,
            col=sym_col,
            length=len(sym_name),
            kind=kind,
            file=origin_file,
            source_override=file_source,
            macro_generated=is_gen,
        )
        if not self.namespace_engine.report_diagnostic(
            diag,
            other_namespaces=other_namespaces,
            emit=False,
            filename_override=origin_file,
            source_override=file_source,
        ):
            return

        self.namespace_diagnostics.append(diag)

        patch_obj = None
        if can_patch:
            from src.patch_model import CodePatch
            patch_obj = CodePatch(
                file_path=origin_file,
                line_start=diag.line,
                line_end=diag.line,
                col_start=diag.col,
                col_end=diag.col + diag.length,
                original_text=diag.symbol,
                replacement_text=diag.fix_option_a,
                error_code="E016",
                summary=f"Unqualified Namespace Symbol: '{diag.symbol}' -> '{diag.fix_option_a}'",
                explanations=[f"Symbol '{diag.symbol}' belongs to namespace '{diag.namespace}'."],
                confidence="review" if other_namespaces else "safe",
            )
            if self.patch_recorder is not None:
                self.patch_recorder.append(patch_obj)

        note_text = f"'{sym_name}' is defined in namespace '{target_ns}'"
        if other_namespaces:
            others_str = ", ".join(f"'{ns}'" for ns in other_namespaces)
            note_text += f" (also found in {others_str})"

        canon_diag = make_diagnostic(
            code="E016",
            severity="error",
            message=f"'{sym_name}' was not declared in this scope; did you mean '{diag.fix_option_a}'?",
            file_path=origin_file,
            line=node_line,
            col=sym_col,
            end_line=node_line,
            end_col=sym_col + max(1, len(sym_name)),
            source=file_source,
            notes=[note_text],
            stage="semantic",
            style="namespace",
            suggestion=diag.fix_option_a if can_patch else None,
            explanations=[note_text],
            fixability="auto" if can_patch else "none",
            patch=patch_obj,
            macro_generated=is_gen,
            extra={
                "option1": diag.fix_option_a,
                "option2": diag.fix_option_b,
                "directive_line": diag.insertion_line,
            },
        )
        self._add_diag(canon_diag)

    def _check_type_headers(self, node: ASTNode, type_str: str):
        """Extracts standard library types from type string and checks for missing headers."""
        if not type_str:
            return
        raw_types = re.findall(r'[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*', type_str)
        primitive_types = {
            "int", "float", "double", "char", "bool", "void", "auto",
            "short", "long", "signed", "unsigned", "const", "struct", "class",
        }
        _, file_source = self._get_file_and_source(node)
        lines = file_source.splitlines()
        node_line = getattr(node, "line", 1)
        node_col = getattr(node, "col", 1)
        line_text = lines[node_line - 1] if 0 <= node_line - 1 < len(lines) else ""

        for t in raw_types:
            if t in primitive_types or t == "std":
                continue
            if self.current_scope.resolve_class(t) or self.current_scope.resolve_struct(t):
                continue
            header = self.registry.lookup(t)
            if header:
                sym_col = node_col
                if not getattr(node, "macro_generated", False) and t in line_text:
                    sym_col = line_text.find(t) + 1

                if not self.registry.is_header_included(header, self.included_headers):
                    self._emit_missing_header(node, t, header, col_override=sym_col)
                    clean_t = t.replace("std::", "")
                    self.current_scope.define_class(t, [])
                    self.current_scope.define_class(clean_t, [])
                else:
                    active_ns = self.current_scope.get_active_namespaces()
                    if "std" not in active_ns and not t.startswith("std::"):
                        self._emit_unqualified_namespace(node, t, "std", kind="type", col_override=sym_col)
                        clean_t = t.replace("std::", "")
                        self.current_scope.define_class(t, [])
                        self.current_scope.define_class(clean_t, [])
            else:
                active_ns = self.current_scope.get_active_namespaces()
                candidate_ns = self.namespace_engine.find_candidate_namespaces(
                    t,
                    active_namespaces=active_ns,
                    included_headers=self.included_headers,
                )
                if candidate_ns:
                    target_ns = candidate_ns[0]
                    sym_col = node_col
                    if not getattr(node, "macro_generated", False) and t in line_text:
                        sym_col = line_text.find(t) + 1
                    self._emit_unqualified_namespace(
                        node,
                        t,
                        target_ns,
                        kind="type",
                        col_override=sym_col,
                        other_namespaces=candidate_ns[1:] if len(candidate_ns) > 1 else None,
                    )
                    self.current_scope.define_class(t, [])
                    self.current_scope.define_class(f"{target_ns}::{t}", [])

    def _is_cout_expr(self, node: Expression) -> bool:
        if isinstance(node, Identifier) and node.name in ["cout", "std::cout"]:
            return True
        if isinstance(node, ScopeResolution) and node.namespace == "std" and node.member == "cout":
            return True
        if isinstance(node, BinaryOp) and node.op == "<<" and self._is_cout_expr(node.left):
            return True
        return False

    def _is_cin_expr(self, node: Expression) -> bool:
        if isinstance(node, Identifier) and node.name in ["cin", "std::cin"]:
            return True
        if isinstance(node, ScopeResolution) and node.namespace == "std" and node.member == "cin":
            return True
        if isinstance(node, BinaryOp) and node.op == ">>" and self._is_cin_expr(node.left):
            return True
        return False

    def is_lvalue(self, node: Expression) -> bool:
        if isinstance(node, (Identifier, ArrayAccess, MemberAccess, ArrowAccess, Deref)):
            return True
        return False

    def normalize_type(self, t: str) -> str:
        if not t:
            return "int"
        t = t.strip()
        while t.startswith("const "):
            t = t[6:].strip()
        while t.endswith("&"):
            t = t[:-1].strip()
        if t == "float":
            return "double"
        if t == "std::string":
            return "string"
        if t in ["long", "short", "int32_t", "size_t", "uint32_t"]:
            return "int"
        return t

    def is_numeric_type(self, t: str) -> bool:
        norm = self.normalize_type(t)
        return norm in ["int", "double", "char", "bool"]

    def is_integral_type(self, t: str) -> bool:
        norm = self.normalize_type(t)
        return norm in ["int", "char", "bool"]

    def is_subclass_of(self, derived: str, base: str) -> bool:
        curr = self.current_scope.resolve_class(derived)
        while curr and curr.base_class:
            if curr.base_class == base:
                return True
            curr = self.current_scope.resolve_class(curr.base_class)
        return False

    def is_type_compatible(self, target: str, source: str, source_node: Optional[Expression] = None) -> bool:
        t_norm = self.normalize_type(target)
        s_norm = self.normalize_type(source)

        if t_norm == s_norm:
            return True
        if t_norm == "auto" or s_norm == "auto":
            return True
        if t_norm in ["ptr", "void*"] and (s_norm.endswith("*") or s_norm == "ptr"):
            return True
        if s_norm in ["ptr", "void*"] and (t_norm.endswith("*") or t_norm == "ptr"):
            return True

        # Numeric conversions
        if self.is_numeric_type(t_norm) and self.is_numeric_type(s_norm):
            return True

        # Null pointer constant (0 assigned to pointer)
        if t_norm.endswith("*") or t_norm == "ptr":
            if source_node and isinstance(source_node, IntLiteral) and source_node.value == 0:
                return True
            if s_norm in ["nullptr", "null"]:
                return True

        # Pointer to pointer conversions (inheritance)
        if t_norm.endswith("*") and s_norm.endswith("*"):
            t_base = t_norm[:-1].strip()
            s_base = s_norm[:-1].strip()
            if t_base == s_base:
                return True
            if t_base in ["void", "ptr"] or s_base in ["void", "ptr"]:
                return True
            if self.is_subclass_of(s_base, t_base):
                return True
            return False

        # Array decay to pointer
        if t_norm.endswith("*") and s_norm.endswith("[]"):
            t_base = t_norm[:-1].strip()
            s_base = s_norm[:-2].strip()
            return t_base == s_base or t_base in ["void", "ptr"]

        # String literal / char* to std::string or string
        if s_norm == "char*" and t_norm in ["std::string", "string"]:
            return True

        # Class constructor single-argument conversion
        cls = self.current_scope.resolve_class(t_norm)
        if cls:
            for ctor, _ in cls.constructors:
                if len(ctor.params) == 1:
                    p_type = self.normalize_type(ctor.params[0].param_type)
                    if self.is_type_compatible(p_type, s_norm):
                        return True

        return False

    def analyze(self, ast: Program):
        self.ast = ast
        # Register templates
        for decl in ast.declarations:
            if isinstance(decl, TemplateDef):
                self.templates[decl.decl.name] = decl

        # Register top-level definitions
        for decl in ast.declarations:
            if not isinstance(decl, TemplateDef):
                self._register_decl(decl, "")
        
        # Visit bodies
        for decl in list(ast.declarations):
            if isinstance(decl, FunctionDef):
                self.visit_function(decl)
            elif isinstance(decl, ClassDef):
                self.visit_class_def(decl)
            elif isinstance(decl, NamespaceDef):
                self.visit_namespace_def(decl)
            elif isinstance(decl, UsingNamespace):
                self.current_scope.active_namespaces.add(decl.name)
            elif isinstance(decl, UsingDeclaration):
                full_name = f"{decl.namespace}::{decl.member}"
                sym = self.global_scope.resolve(full_name)
                if sym:
                    self.current_scope.symbols[decl.member] = sym
                if full_name in self.global_scope.functions:
                    self.current_scope.functions[decl.member] = self.global_scope.functions[full_name]
                cls = self.global_scope.resolve_class(full_name)
                if cls:
                    self.current_scope.classes[decl.member] = cls
                st = self.global_scope.resolve_struct(full_name)
                if st:
                    self.current_scope.structs[decl.member] = st
            elif isinstance(decl, MultiVarDeclaration):
                for declaration in decl.declarations:
                    self._check_type_headers(declaration, declaration.var_type)
                    if declaration.initializer:
                        self.visit_expression(declaration.initializer)
                        init_t = self.get_expr_type(declaration.initializer)
                        if not self.is_type_compatible(declaration.var_type, init_t, declaration.initializer):
                            self.error(
                                declaration,
                                f"Cannot initialize variable of type '{declaration.var_type}' with an rvalue of type '{init_t}'",
                                code="E002",
                            )
            elif isinstance(decl, VarDeclaration):
                self._check_type_headers(decl, decl.var_type)
                if decl.initializer:
                    self.visit_expression(decl.initializer)
                    init_t = self.get_expr_type(decl.initializer)
                    if not self.is_type_compatible(decl.var_type, init_t, decl.initializer):
                        self.error(decl, f"Cannot initialize variable of type '{decl.var_type}' with an rvalue of type '{init_t}'", code="E002")
            elif isinstance(decl, ClassInstanceDeclaration):
                self._check_type_headers(decl, decl.class_name)
                for arg in decl.args:
                    self.visit_expression(arg)
            elif isinstance(decl, ArrayDeclaration):
                self._check_type_headers(decl, decl.var_type)
                if decl.elements:
                    for el in decl.elements:
                        self.visit_expression(el)

        # Check for unused variables (Warning system)
        self._check_warnings()

        # Check for operator misuse (Idea 6: W002, W003, W004, W005)
        self._check_operator_misuse(ast)

        # Check for array bounds and off-by-one errors (Idea 8: W006, W007)
        self._check_array_bounds(ast)

        # If any semantic errors were encountered, display summary and stop compilation
        if self.errors_count > 0 and self.exit_on_error:
            import sys
            print(f"{Colors.BOLD}{Colors.RED}Compilation failed with {self.errors_count} error(s).{Colors.RESET}\n")
            sys.exit(1)

    def _register_decl(self, decl: ASTNode, prefix: str):
        decl_file = getattr(decl, "file", None) or self.entry_file
        decl_gen = bool(getattr(decl, "macro_generated", False))
        if isinstance(decl, FunctionDef):
            full_name = f"{prefix}{decl.name}"
            decl.mangled_name = full_name
            self.global_scope.functions.setdefault(full_name, []).append(decl)
            self.global_scope.define(full_name, decl.return_type, decl.line, decl.col, file=decl_file, macro_generated=decl_gen)
        elif isinstance(decl, StructDef):
            self.global_scope.define_struct(f"{prefix}{decl.name}", decl.members)
        elif isinstance(decl, ClassDef):
            cls_sym = self.global_scope.define_class(f"{prefix}{decl.name}", decl.members, base_class=decl.base_class, base_access=decl.base_access)
            if decl.base_class:
                base_sym = self.global_scope.resolve_class(decl.base_class)
                if base_sym:
                    cls_sym.inherit_from(base_sym)
                else:
                    candidates = self.namespace_engine.find_candidate_namespaces(
                        decl.base_class,
                        self.global_scope.get_active_namespaces(),
                        self.included_headers,
                    )
                    if candidates:
                        target_ns = candidates[0]
                        self._emit_unqualified_namespace(
                            decl,
                            decl.base_class,
                            target_ns,
                            kind="class",
                            other_namespaces=candidates[1:] if len(candidates) > 1 else None,
                        )
                        resolved_base = self.global_scope.resolve_class(f"{target_ns}::{decl.base_class}")
                        if resolved_base:
                            cls_sym.inherit_from(resolved_base)
                    else:
                        self.error(decl, f"Base class '{decl.base_class}' not found for class '{decl.name}'", code="E001")
        elif isinstance(decl, NamespaceDef):
            new_prefix = f"{prefix}{decl.name}::"
            self.namespace_engine.register_user_namespace(decl.name)
            for sub_decl in decl.declarations:
                self._register_decl(sub_decl, new_prefix)
                if hasattr(sub_decl, "name"):
                    self.namespace_engine.register_symbol(decl.name, sub_decl.name)
                elif isinstance(sub_decl, EnumDef):
                    for e_name, _ in sub_decl.enumerators:
                        self.namespace_engine.register_symbol(decl.name, e_name)
        elif isinstance(decl, UsingNamespace):
            self.global_scope.active_namespaces.add(decl.name)
        elif isinstance(decl, UsingDeclaration):
            full_name = f"{decl.namespace}::{decl.member}"
            sym = self.global_scope.resolve(full_name)
            if sym:
                self.global_scope.symbols[decl.member] = sym
            if full_name in self.global_scope.functions:
                self.global_scope.functions[decl.member] = self.global_scope.functions[full_name]
            cls = self.global_scope.resolve_class(full_name)
            if cls:
                self.global_scope.classes[decl.member] = cls
            st = self.global_scope.resolve_struct(full_name)
            if st:
                self.global_scope.structs[decl.member] = st
        elif isinstance(decl, EnumDef):
            for e_name, e_val in decl.enumerators:
                self.global_scope.define(f"{prefix}{e_name}", "int", decl.line, decl.col, file=decl_file, macro_generated=decl_gen).is_used = True
        elif isinstance(decl, MultiVarDeclaration):
            for declaration in decl.declarations:
                self._register_decl(declaration, prefix)
        elif isinstance(decl, VarDeclaration):
            self._check_type_headers(decl, decl.var_type)
            const_val = None
            if (decl.is_const or getattr(decl, "is_constexpr", False)) and decl.initializer:
                const_val, _ = self.eval_constexpr_expr(decl.initializer)
            sym = self.global_scope.define(f"{prefix}{decl.name}", decl.var_type, decl.line, decl.col, is_const=decl.is_const, is_reference=decl.is_reference, is_constexpr=getattr(decl, "is_constexpr", False), const_value=const_val, file=decl_file, macro_generated=decl_gen)
            self.tracked_variables.append(sym)
        elif isinstance(decl, ClassInstanceDeclaration):
            self._check_type_headers(decl, decl.class_name)
            sym = self.global_scope.define(f"{prefix}{decl.name}", decl.class_name, decl.line, decl.col, file=decl_file, macro_generated=decl_gen)
            self.tracked_variables.append(sym)
        elif isinstance(decl, ArrayDeclaration):
            self._check_type_headers(decl, decl.var_type)
            arr_size = decl.size
            arr_dims = list(getattr(decl, "dimensions", []))
            if getattr(decl, "dim_exprs", None):
                resolved_dims = []
                for de in decl.dim_exprs:
                    if de is not None:
                        val, ok = self.eval_constexpr_expr(de)
                        resolved_dims.append(val if (ok and isinstance(val, int)) else None)
                    else:
                        resolved_dims.append(None)
                if any(d is not None for d in resolved_dims):
                    arr_dims = [d if d is not None else (arr_dims[i] if i < len(arr_dims) else None) for i, d in enumerate(resolved_dims)]
                    if arr_dims and arr_dims[0] is not None:
                        arr_size = arr_dims[0]
            if arr_size is None and decl.elements:
                arr_size = len(decl.elements)
                if not arr_dims:
                    arr_dims = [arr_size]
            sym = self.global_scope.define(f"{prefix}{decl.name}", f"{decl.var_type}[]", decl.line, decl.col, array_size=arr_size, array_dimensions=arr_dims, file=decl_file, macro_generated=decl_gen)
            self.tracked_variables.append(sym)

    def _check_warnings(self):
        for sym in self.tracked_variables:
            if not sym.is_used and not sym.name.startswith("_") and sym.name != "main":
                origin_file, file_source = self._get_file_and_source(sym)
                is_gen = bool(getattr(sym, "macro_generated", False))
                w_diag = make_diagnostic(
                    code="W001",
                    severity="warning",
                    message=f"unused variable '{sym.name}'",
                    file_path=origin_file,
                    line=sym.line,
                    col=sym.col,
                    end_line=sym.line,
                    end_col=sym.col + max(1, len(sym.name)),
                    source=file_source,
                    help_text=f"if this is intentional, prefix with an underscore: '_{sym.name}'",
                    stage="semantic",
                    length=len(sym.name),
                    macro_generated=is_gen,
                )
                self._add_diag(w_diag)
                if self.warn_as_error:
                    e_diag = make_diagnostic(
                        code="W001",
                        severity="error",
                        message=f"warnings treated as errors: unused variable '{sym.name}'",
                        file_path=origin_file,
                        line=sym.line,
                        col=sym.col,
                        end_line=sym.line,
                        end_col=sym.col + max(1, len(sym.name)),
                        source=file_source,
                        stage="semantic",
                        length=len(sym.name),
                        macro_generated=is_gen,
                    )
                    self._add_diag(e_diag)

    def _check_operator_misuse(self, ast: ASTNode):
        self.operator_engine.source = self.source
        diags = self.operator_engine.scan(ast, self)
        for diag in diags:
            self.operator_diagnostics.append(diag)
            origin_file, file_source = self._get_file_and_source(diag.node)
            is_gen = bool(getattr(diag.node, "macro_generated", False))
            can_patch = not is_gen
            patch_obj = None
            if can_patch:
                from src.patch_model import CodePatch, locate_whitespace_flexible_span
                try:
                    exact_col, start_offset, end_offset, expected_text = locate_whitespace_flexible_span(
                        file_source, diag.line, diag.col, diag.original_snippet
                    )
                    patch_obj = CodePatch(
                        file_path=origin_file,
                        line_start=diag.line,
                        line_end=diag.line,
                        col_start=exact_col,
                        col_end=exact_col + len(expected_text),
                        original_text=expected_text,
                        replacement_text=diag.repaired_snippet,
                        error_code=diag.code,
                        summary=f"{diag.code}: {diag.message}",
                        explanations=[diag.help_text],
                        start_offset=start_offset,
                        end_offset=end_offset,
                        expected_text=expected_text,
                        confidence={"W003": "heuristic", "W002": "review"}.get(diag.code, "safe"),
                    )
                    if self.patch_recorder is not None:
                        self.patch_recorder.append(patch_obj)
                except ValueError:
                    patch_obj = None
            w_diag = make_diagnostic(
                code=diag.code,
                severity="warning",
                message=diag.message,
                file_path=origin_file,
                line=diag.line,
                col=diag.col,
                end_line=diag.line,
                end_col=diag.col + max(1, diag.length),
                source=file_source,
                help_text=diag.help_text,
                stage="semantic",
                length=diag.length,
                suggestion=diag.repaired_snippet if can_patch else None,
                explanations=[diag.help_text],
                fixability="auto" if can_patch else "none",
                patch=patch_obj,
                macro_generated=is_gen,
            )
            self._add_diag(w_diag)
            if self.warn_as_error:
                e_diag = make_diagnostic(
                    code=diag.code,
                    severity="error",
                    message=f"warning treated as error: {diag.message}",
                    file_path=origin_file,
                    line=diag.line,
                    col=diag.col,
                    end_line=diag.line,
                    end_col=diag.col + max(1, diag.length),
                    source=file_source,
                    stage="semantic",
                    length=diag.length,
                    macro_generated=is_gen,
                )
                self._add_diag(e_diag)

    def _check_array_bounds(self, ast: ASTNode):
        self.array_bounds_engine.source = self.source
        diags = self.array_bounds_engine.scan(ast, self)
        for diag in diags:
            self.array_bounds_diagnostics.append(diag)
            origin_file, file_source = self._get_file_and_source(diag.node)
            is_gen = bool(getattr(diag.node, "macro_generated", False))
            can_patch = not is_gen
            patch_obj = None
            if can_patch:
                from src.patch_model import CodePatch, locate_snippet_span
                try:
                    exact_col, start_offset, end_offset = locate_snippet_span(
                        file_source, diag.line, diag.col, diag.original_snippet
                    )
                    patch_obj = CodePatch(
                        file_path=origin_file,
                        line_start=diag.line,
                        line_end=diag.line,
                        col_start=exact_col,
                        col_end=exact_col + len(diag.original_snippet),
                        original_text=diag.original_snippet,
                        replacement_text=diag.repaired_snippet,
                        error_code=diag.code,
                        summary=f"{diag.code}: {diag.message}",
                        explanations=[diag.help_text],
                        start_offset=start_offset,
                        end_offset=end_offset,
                        expected_text=diag.original_snippet,
                        confidence=(
                            "safe"
                            if diag.code == "W007"
                            and bool(diag.var_name and diag.array_name)
                            and diag.array_size is not None
                            and diag.accessed_index == diag.array_size
                            and "<=" in diag.original_snippet
                            and "<" in diag.repaired_snippet
                            else "review"
                        ),
                    )
                    if self.patch_recorder is not None:
                        self.patch_recorder.append(patch_obj)
                except ValueError:
                    patch_obj = None
            w_diag = make_diagnostic(
                code=diag.code,
                severity="warning",
                message=diag.message,
                file_path=origin_file,
                line=diag.line,
                col=diag.col,
                end_line=diag.line,
                end_col=diag.col + max(1, diag.length),
                source=file_source,
                help_text=diag.help_text,
                stage="semantic",
                length=diag.length,
                suggestion=diag.repaired_snippet if can_patch else None,
                explanations=[diag.help_text],
                fixability="auto" if can_patch else "none",
                patch=patch_obj,
                macro_generated=is_gen,
            )
            self._add_diag(w_diag)
            if self.warn_as_error:
                e_diag = make_diagnostic(
                    code=diag.code,
                    severity="error",
                    message=f"warning treated as error: {diag.message}",
                    file_path=origin_file,
                    line=diag.line,
                    col=diag.col,
                    end_line=diag.line,
                    end_col=diag.col + max(1, diag.length),
                    source=file_source,
                    stage="semantic",
                    length=diag.length,
                    macro_generated=is_gen,
                )
                self._add_diag(e_diag)

    def visit_class_def(self, node: ClassDef):
        class_sym = self.global_scope.resolve_class(node.name)
        old_class = self.current_class
        self.current_class = class_sym
        for m in node.members:
            if isinstance(m.decl, ConstructorDef):
                self.visit_constructor(m.decl)
            elif isinstance(m.decl, DestructorDef):
                self.visit_destructor(m.decl)
            elif isinstance(m.decl, FunctionDef):
                self.visit_function(m.decl)
            elif isinstance(m.decl, VarDeclaration):
                if m.decl.initializer:
                    self.visit_expression(m.decl.initializer)
        self.current_class = old_class

    def visit_constructor(self, node: ConstructorDef):
        if node.body:
            self.push_scope()
            this_sym = self.current_scope.define("this", f"{node.class_name}*", node.line, node.col)
            this_sym.is_used = True
            for param in node.params:
                sym = self.current_scope.define(param.name, param.param_type, param.line, param.col, is_const=param.is_const, is_reference=param.is_reference)
                sym.is_used = True
            if self.current_class:
                for f_name, (f_type, f_acc, f_const, f_ref) in self.current_class.fields.items():
                    if f_name not in self.current_scope.symbols:
                        s = self.current_scope.define(f_name, f_type, node.line, node.col, is_const=f_const, is_reference=f_ref)
                        s.is_used = True
            self.visit_block(node.body)
            self.pop_scope()

    def visit_destructor(self, node: DestructorDef):
        if node.body:
            self.push_scope()
            this_sym = self.current_scope.define("this", f"{node.class_name}*", node.line, node.col)
            this_sym.is_used = True
            if self.current_class:
                for f_name, (f_type, f_acc, f_const, f_ref) in self.current_class.fields.items():
                    if f_name not in self.current_scope.symbols:
                        s = self.current_scope.define(f_name, f_type, node.line, node.col, is_const=f_const, is_reference=f_ref)
                        s.is_used = True
            self.visit_block(node.body)
            self.pop_scope()

    def visit_namespace_def(self, node: NamespaceDef):
        self.push_scope()
        self.current_scope.active_namespaces.add(node.name)
        try:
            for decl in node.declarations:
                if isinstance(decl, FunctionDef):
                    self.visit_function(decl)
                elif isinstance(decl, ClassDef):
                    self.visit_class_def(decl)
                elif isinstance(decl, NamespaceDef):
                    self.visit_namespace_def(decl)
                elif isinstance(decl, VarDeclaration):
                    if decl.initializer:
                        self.visit_expression(decl.initializer)
        finally:
            self.pop_scope()

    def visit_function(self, node: FunctionDef):
        self.current_function = node
        self._check_type_headers(node, node.return_type)
        for param in node.params:
            self._check_type_headers(param, param.param_type)
        if node.body:
            self.push_scope()
            if self.current_class:
                this_sym = self.current_scope.define("this", f"{self.current_class.name}*", node.line, node.col)
                this_sym.is_used = True
                for f_name, (f_type, f_acc, f_const, f_ref) in self.current_class.fields.items():
                    if f_name not in self.current_scope.symbols:
                        s = self.current_scope.define(f_name, f_type, node.line, node.col, is_const=f_const, is_reference=f_ref)
                        s.is_used = True
            for param in node.params:
                sym = self.current_scope.define(param.name, param.param_type, param.line, param.col, is_const=param.is_const, is_reference=param.is_reference)
                sym.is_used = True
            self.visit_block(node.body)
            self.pop_scope()
        self.current_function = None

    def visit_block(self, node: Block):
        self.push_scope()
        for stmt in node.statements:
            self.visit_statement(stmt)
        self.pop_scope()

    def visit_statement(self, node: Statement):
        if isinstance(node, MultiVarDeclaration):
            for declaration in node.declarations:
                self.visit_statement(declaration)
        elif isinstance(node, VarDeclaration):
            self._check_type_headers(node, node.var_type)
            if node.initializer:
                self.visit_expression(node.initializer)
            if node.var_type == "auto":
                if node.initializer:
                    node.var_type = self.get_expr_type(node.initializer)
                else:
                    self.error(node, "Declaration of 'auto' variable requires an initializer", code="E003")
                    node.var_type = "int"
            elif node.initializer:
                init_t = self.get_expr_type(node.initializer)
                if not self.is_type_compatible(node.var_type, init_t, node.initializer):
                    self.error(node, f"Cannot initialize variable '{node.name}' of type '{node.var_type}' with an expression of type '{init_t}'", code="E002")
                elif node.is_reference and not node.is_const and not self.is_lvalue(node.initializer):
                    self.error(node, f"Cannot bind non-const lvalue reference '{node.name}' of type '{node.var_type}&' to an rvalue of type '{init_t}'", code="E002")
            if self.current_scope.symbols.get(node.name) and self.current_scope != self.global_scope:
                self.error(node, f"Variable '{node.name}' already declared in this scope", code="E005")
            if node.is_reference and node.initializer is None:
                self.error(node, f"Reference variable '{node.name}' must be initialized", code="E011")
            
            const_val = None
            if getattr(node, "is_constexpr", False):
                if node.initializer is None:
                    self.error(node, f"constexpr variable '{node.name}' must have an initializer", code="E014")
                else:
                    const_val, is_eval = self.eval_constexpr_expr(node.initializer)
                    if not is_eval:
                        self.error(node, f"Expression in constexpr declaration of '{node.name}' is not a compile-time constant", code="E014")
            elif node.is_const and node.initializer is not None:
                const_val, _ = self.eval_constexpr_expr(node.initializer)

            clean_type = node.var_type.replace("const ", "").strip()
            if not node.is_reference and not clean_type.endswith("*"):
                self._instantiate_template_class(clean_type, node)
                cls = self.current_scope.resolve_class(clean_type)
                if cls and cls.is_abstract:
                    self.error(node, f"Cannot instantiate abstract class '{clean_type}' with pure virtual methods: {', '.join(cls.pure_virtual_methods)}", code="E013")
            sym = self.current_scope.define(node.name, node.var_type, node.line, node.col, is_const=node.is_const, is_reference=node.is_reference, is_constexpr=getattr(node, "is_constexpr", False), const_value=const_val, file=getattr(node, "file", None) or self.entry_file, macro_generated=bool(getattr(node, "macro_generated", False)))
            self.tracked_variables.append(sym)
        elif isinstance(node, ClassInstanceDeclaration):
            self._check_type_headers(node, node.class_name)
            for arg in node.args:
                self.visit_expression(arg)
            self._instantiate_template_class(node.class_name, node)
            cls = self.current_scope.resolve_class(node.class_name)
            if not cls:
                self.error(node, f"Undefined class '{node.class_name}'", code="E001")
            elif cls.is_abstract:
                self.error(node, f"Cannot instantiate abstract class '{node.class_name}' with pure virtual methods: {', '.join(cls.pure_virtual_methods)}", code="E013")
            else:
                if cls.constructors:
                    matched_ctor = False
                    for ctor_def, ctor_acc in cls.constructors:
                        if len(ctor_def.params) == len(node.args):
                            if all(self.is_type_compatible(p.param_type, self.get_expr_type(a), a) for p, a in zip(ctor_def.params, node.args)):
                                matched_ctor = True
                                if ctor_acc in ["private", "protected"] and (not self.current_class or self.current_class.name != cls.name):
                                    self.error(node, f"Constructor of class '{cls.name}' is {ctor_acc}", code="E009")
                                break
                    if not matched_ctor:
                        arg_types_str = ", ".join(self.get_expr_type(a) for a in node.args)
                        self.error(node, f"No matching constructor for initialization of '{node.class_name}' with argument types ({arg_types_str})", code="E002")
                elif len(node.args) > 0:
                    self.error(node, f"Class '{node.class_name}' has no constructor taking {len(node.args)} argument(s)", code="E002")
            if self.current_scope.symbols.get(node.name) and self.current_scope != self.global_scope:
                self.error(node, f"Variable '{node.name}' already declared in this scope", code="E005")
            sym = self.current_scope.define(node.name, node.class_name, node.line, node.col, file=getattr(node, "file", None) or self.entry_file, macro_generated=bool(getattr(node, "macro_generated", False)))
            self.tracked_variables.append(sym)
        elif isinstance(node, RangeForStatement):
            self.visit_expression(node.iterable)
            iter_type = self.get_expr_type(node.iterable)
            elem_type = iter_type.rstrip("[]*")
            if not elem_type: elem_type = "int"
            if node.var_type == "auto":
                node.var_type = elem_type
            elif not self.is_type_compatible(node.var_type, elem_type):
                self.error(node, f"Range-for loop variable of type '{node.var_type}' cannot bind to element of type '{elem_type}'", code="E002")
            self.push_scope()
            sym = self.current_scope.define(node.var_name, node.var_type, node.line, node.col)
            sym.is_used = True
            self.loop_depth += 1
            self.visit_statement(node.body)
            self.loop_depth -= 1
            self.pop_scope()
        elif isinstance(node, TryCatchStatement):
            self.visit_block(node.try_block)
            for clause in node.catch_clauses:
                self.push_scope()
                sym = self.current_scope.define(clause.param_name, clause.param_type, clause.line, clause.col)
                sym.is_used = True
                self.visit_block(clause.body)
                self.pop_scope()
        elif isinstance(node, ThrowStatement):
            self.visit_expression(node.expr)
        elif isinstance(node, DeleteStatement):
            self.visit_expression(node.expr)
            del_t = self.normalize_type(self.get_expr_type(node.expr))
            if not (del_t.endswith("*") or del_t == "ptr"):
                self.error(node, f"Cannot delete expression of non-pointer type '{del_t}'", code="E002")
        elif isinstance(node, UsingNamespace):
            self.current_scope.active_namespaces.add(node.name)
        elif isinstance(node, UsingDeclaration):
            full_name = f"{node.namespace}::{node.member}"
            sym = self.global_scope.resolve(full_name)
            if sym:
                self.current_scope.symbols[node.member] = sym
            if full_name in self.global_scope.functions:
                self.current_scope.functions[node.member] = self.global_scope.functions[full_name]
            cls = self.global_scope.resolve_class(full_name)
            if cls:
                self.current_scope.classes[node.member] = cls
            st = self.global_scope.resolve_struct(full_name)
            if st:
                self.current_scope.structs[node.member] = st
        elif isinstance(node, ClassDef):
            self.visit_class_def(node)
        elif isinstance(node, NamespaceDef):
            self.visit_namespace_def(node)
        elif isinstance(node, ArrayDeclaration):
            self._check_type_headers(node, node.var_type)
            if self.current_scope.symbols.get(node.name) and self.current_scope != self.global_scope:
                self.error(node, f"Variable '{node.name}' already declared in this scope", code="E005")
            arr_size = node.size
            arr_dims = list(getattr(node, "dimensions", []))
            if getattr(node, "dim_exprs", None):
                resolved_dims = []
                for de in node.dim_exprs:
                    if de is not None:
                        val, ok = self.eval_constexpr_expr(de)
                        resolved_dims.append(val if (ok and isinstance(val, int)) else None)
                    else:
                        resolved_dims.append(None)
                if any(d is not None for d in resolved_dims):
                    arr_dims = [d if d is not None else (arr_dims[i] if i < len(arr_dims) else None) for i, d in enumerate(resolved_dims)]
                    if arr_dims and arr_dims[0] is not None:
                        arr_size = arr_dims[0]
            if arr_size is None and node.elements:
                arr_size = len(node.elements)
                if not arr_dims:
                    arr_dims = [arr_size]
            sym = self.current_scope.define(node.name, f"{node.var_type}[]", node.line, node.col, array_size=arr_size, array_dimensions=arr_dims, file=getattr(node, "file", None) or self.entry_file, macro_generated=bool(getattr(node, "macro_generated", False)))
            self.tracked_variables.append(sym)
            if node.elements:
                for el in node.elements:
                    self.visit_expression(el)
                    el_t = self.get_expr_type(el)
                    if not self.is_type_compatible(node.var_type, el_t, el):
                        self.error(node, f"Cannot initialize array element of type '{node.var_type}' with an expression of type '{el_t}'", code="E002")
        elif isinstance(node, StructDef):
            if self.current_scope.structs.get(node.name):
                self.error(node, f"Struct '{node.name}' already defined", code="E005")
            self.current_scope.define_struct(node.name, node.members)
        elif isinstance(node, StructDeclaration):
            if not self.current_scope.resolve_struct(node.struct_name):
                self.error(node, f"Undefined struct '{node.struct_name}'", code="E001")
            if self.current_scope.symbols.get(node.name) and self.current_scope != self.global_scope:
                self.error(node, f"Variable '{node.name}' already declared", code="E005")
            sym = self.current_scope.define(node.name, f"struct {node.struct_name}", node.line, node.col, file=getattr(node, "file", None) or self.entry_file, macro_generated=bool(getattr(node, "macro_generated", False)))
            self.tracked_variables.append(sym)
            if node.elements:
                for el in node.elements:
                    self.visit_expression(el)
        elif isinstance(node, EnumDef):
            for e_name, e_val in node.enumerators:
                self.current_scope.define(e_name, "int", node.line, node.col).is_used = True
        elif isinstance(node, ExpressionStatement):
            self.visit_expression(node.expr)
        elif isinstance(node, IfStatement):
            self.visit_expression(node.condition)
            self.visit_statement(node.then_branch)
            if node.else_branch:
                self.visit_statement(node.else_branch)
        elif isinstance(node, WhileStatement):
            self.visit_expression(node.condition)
            self.loop_depth += 1
            self.visit_statement(node.body)
            self.loop_depth -= 1
        elif isinstance(node, DoWhileStatement):
            self.loop_depth += 1
            self.visit_statement(node.body)
            self.loop_depth -= 1
            self.visit_expression(node.condition)
        elif isinstance(node, ForStatement):
            self.push_scope()
            if node.init:
                self.visit_statement(node.init)
            if node.condition:
                self.visit_expression(node.condition)
            if node.update:
                self.visit_expression(node.update)
            self.loop_depth += 1
            self.visit_statement(node.body)
            self.loop_depth -= 1
            self.pop_scope()
        elif isinstance(node, SwitchStatement):
            self.visit_expression(node.expr)
            sw_t = self.get_expr_type(node.expr)
            if not self.is_integral_type(sw_t):
                self.error(node, f"Switch quantity must be an integer, got '{sw_t}'", code="E002")
            self.loop_depth += 1
            for case in node.cases:
                if case.value:
                    self.visit_expression(case.value)
                for stmt in case.statements:
                    self.visit_statement(stmt)
            self.loop_depth -= 1
        elif isinstance(node, BreakStatement):
            if self.loop_depth == 0:
                self.error(node, "break statement not within loop or switch", code="E007")
        elif isinstance(node, ContinueStatement):
            if self.loop_depth == 0:
                self.error(node, "continue statement not within loop", code="E007")
        elif isinstance(node, ReturnStatement):
            if node.expr:
                self.visit_expression(node.expr)
                if self.current_function:
                    ret_t = self.get_expr_type(node.expr)
                    if self.current_function.return_type == "void":
                        self.error(node, "Void function cannot return a value", code="E002")
                    elif not self.is_type_compatible(self.current_function.return_type, ret_t, node.expr):
                        self.error(node, f"Cannot return value of type '{ret_t}' from function returning '{self.current_function.return_type}'", code="E002")
            elif self.current_function and self.current_function.return_type != "void":
                self.error(node, "Missing return value", code="E008")
        elif isinstance(node, Block):
            self.visit_block(node)

    def visit_expression(self, node: Expression):
        if isinstance(node, BoolLiteral):
            pass
        elif isinstance(node, ThisExpr):
            if not self.current_class:
                self.error(node, "'this' can only be used inside a class member function", code="E012")
        elif isinstance(node, NewExpr):
            for arg in node.args:
                self.visit_expression(arg)
            self._instantiate_template_class(node.type_name, node)
            cls = self.current_scope.resolve_class(node.type_name)
            if cls:
                if cls.is_abstract:
                    self.error(node, f"Cannot instantiate abstract class '{node.type_name}' with pure virtual methods: {', '.join(cls.pure_virtual_methods)}", code="E013")
                elif cls.constructors:
                    matched_ctor = any(
                        len(c_def.params) == len(node.args) and
                        all(self.is_type_compatible(p.param_type, self.get_expr_type(a), a) for p, a in zip(c_def.params, node.args))
                        for c_def, _ in cls.constructors
                    )
                    if not matched_ctor:
                        arg_types_str = ", ".join(self.get_expr_type(a) for a in node.args)
                        self.error(node, f"No matching constructor for 'new {node.type_name}' with argument types ({arg_types_str})", code="E002")
            elif len(node.args) == 1:
                arg_t = self.get_expr_type(node.args[0])
                if not self.is_type_compatible(node.type_name, arg_t, node.args[0]):
                    self.error(node, f"Cannot initialize 'new {node.type_name}' with value of type '{arg_t}'", code="E002")
        elif isinstance(node, MethodCall):
            self.visit_expression(node.object_expr)
            for arg in node.args:
                self.visit_expression(arg)
            obj_raw_t = self.get_expr_type(node.object_expr)
            clean_type = obj_raw_t.replace("const ", "").rstrip("*&").strip()
            cls = self.current_scope.resolve_class(clean_type)
            if cls:
                if node.method_name not in cls.methods:
                    self.error(node, f"Class '{cls.name}' has no member function named '{node.method_name}'", code="E001")
                else:
                    matched_method = False
                    for m_def, m_acc in cls.methods[node.method_name]:
                        if m_acc in ["private", "protected"] and (not self.current_class or (self.current_class.name != cls.name and not self.is_subclass_of(self.current_class.name, cls.name))):
                            self.error(node, f"Member function '{node.method_name}' of class '{cls.name}' is {m_acc}", code="E009")
                        if len(m_def.params) == len(node.args):
                            if all(self.is_type_compatible(p.param_type, self.get_expr_type(a), a) for p, a in zip(m_def.params, node.args)):
                                matched_method = True
                                break
                    if not matched_method:
                        arg_types_str = ", ".join(self.get_expr_type(a) for a in node.args)
                        self.error(node, f"No matching member function for call to '{cls.name}::{node.method_name}' with argument types ({arg_types_str})", code="E002")
        elif isinstance(node, (MemberAccess, ArrowAccess)):
            self.visit_expression(node.object_expr)
            obj_raw_t = self.get_expr_type(node.object_expr)
            clean_type = obj_raw_t.replace("struct ", "").replace("const ", "").rstrip("*&").strip()
            cls = self.current_scope.resolve_class(clean_type)
            st = self.current_scope.resolve_struct(clean_type)
            if cls:
                if node.member in cls.fields:
                    f_type, f_acc, f_const, f_ref = cls.fields[node.member]
                    if f_acc in ["private", "protected"] and (not self.current_class or (self.current_class.name != cls.name and not self.is_subclass_of(self.current_class.name, cls.name))):
                        self.error(node, f"Member '{node.member}' of class '{cls.name}' is {f_acc}", code="E009")
                elif node.member not in cls.methods:
                    self.error(node, f"Class '{cls.name}' has no member named '{node.member}'", code="E001")
            elif st:
                if not any(m.name == node.member for m in st.members):
                    self.error(node, f"Struct '{st.name}' has no member named '{node.member}'", code="E001")
        elif isinstance(node, (MemberAssignment, ArrowAssignment)):
            self.visit_expression(node.object_expr)
            self.visit_expression(node.expr)
            rhs_t = self.get_expr_type(node.expr)
            obj_raw_t = self.get_expr_type(node.object_expr)
            clean_type = obj_raw_t.replace("struct ", "").replace("const ", "").rstrip("*&").strip()
            cls = self.current_scope.resolve_class(clean_type)
            st = self.current_scope.resolve_struct(clean_type)
            if cls:
                if node.member in cls.fields:
                    f_type, f_acc, f_const, f_ref = cls.fields[node.member]
                    if f_acc in ["private", "protected"] and (not self.current_class or (self.current_class.name != cls.name and not self.is_subclass_of(self.current_class.name, cls.name))):
                        self.error(node, f"Member '{node.member}' of class '{cls.name}' is {f_acc}", code="E009")
                    if f_const:
                        self.error(node, f"Cannot assign to const member '{node.member}'", code="E010")
                    if not self.is_type_compatible(f_type, rhs_t, node.expr):
                        self.error(node, f"Cannot assign value of type '{rhs_t}' to member '{node.member}' of type '{f_type}'", code="E002")
                else:
                    self.error(node, f"Class '{cls.name}' has no member named '{node.member}'", code="E001")
            elif st:
                member_param = next((m for m in st.members if m.name == node.member), None)
                if not member_param:
                    self.error(node, f"Struct '{st.name}' has no member named '{node.member}'", code="E001")
                elif not self.is_type_compatible(member_param.param_type, rhs_t, node.expr):
                    self.error(node, f"Cannot assign value of type '{rhs_t}' to struct member '{node.member}' of type '{member_param.param_type}'", code="E002")
        elif isinstance(node, ScopeResolution):
            full_name = f"{node.namespace}::{node.member}"
            sym = self.current_scope.resolve(full_name)
            if not sym and not self.current_scope.resolve_class(full_name) and not self.current_scope.resolve_function(full_name):
                self._error_undeclared(node, full_name, "identifier")
            elif sym:
                sym.is_used = True
        elif isinstance(node, Identifier):
            sym = self.current_scope.resolve(node.name)
            if not sym:
                if self.current_class and node.name in self.current_class.fields:
                    pass
                else:
                    self._error_undeclared(node, node.name, "identifier")
            else:
                sym.is_used = True
        elif isinstance(node, Assignment):
            sym = self.current_scope.resolve(node.target)
            target_type = None
            if not sym:
                if self.current_class and node.target in self.current_class.fields:
                    f_type, f_acc, f_const, f_ref = self.current_class.fields[node.target]
                    target_type = f_type
                    if f_const:
                        self.error(node, f"Cannot assign to const variable '{node.target}'", code="E010")
                else:
                    self._error_undeclared(node, node.target, "variable")
            else:
                target_type = sym.s_type
                if sym.is_const:
                    self.error(node, f"Cannot assign to const variable '{node.target}'", code="E010")
                sym.is_used = True
            self.visit_expression(node.expr)
            if target_type:
                rhs_t = self.get_expr_type(node.expr)
                if not self.is_type_compatible(target_type, rhs_t, node.expr):
                    self.error(node, f"Cannot assign value of type '{rhs_t}' to variable '{node.target}' of type '{target_type}'", code="E002")
        elif isinstance(node, ArrayAccess):
            sym = self.current_scope.resolve(node.name)
            if not sym:
                self._error_undeclared(node, node.name, "array")
            else:
                sym.is_used = True
                if not (sym.s_type.endswith("[]") or sym.s_type.endswith("*") or sym.s_type == "ptr"):
                    self.error(node, f"Subscripted value '{node.name}' of type '{sym.s_type}' is not an array or pointer", code="E002")
            self.visit_expression(node.index)
            idx_t = self.get_expr_type(node.index)
            if not self.is_integral_type(idx_t):
                self.error(node, f"Array subscript must be an integer, got '{idx_t}'", code="E002")
        elif isinstance(node, ArrayAssignment):
            sym = self.current_scope.resolve(node.name)
            elem_type = None
            if not sym:
                self._error_undeclared(node, node.name, "array")
            else:
                sym.is_used = True
                if not (sym.s_type.endswith("[]") or sym.s_type.endswith("*") or sym.s_type == "ptr"):
                    self.error(node, f"Subscripted value '{node.name}' of type '{sym.s_type}' is not an array or pointer", code="E002")
                else:
                    elem_type = sym.s_type[:-2] if sym.s_type.endswith("[]") else (sym.s_type[:-1] if sym.s_type.endswith("*") else "int")
            self.visit_expression(node.index)
            idx_t = self.get_expr_type(node.index)
            if not self.is_integral_type(idx_t):
                self.error(node, f"Array subscript must be an integer, got '{idx_t}'", code="E002")
            self.visit_expression(node.expr)
            if elem_type:
                val_t = self.get_expr_type(node.expr)
                if not self.is_type_compatible(elem_type, val_t, node.expr):
                    self.error(node, f"Cannot assign value of type '{val_t}' to array element of type '{elem_type}'", code="E002")
        elif isinstance(node, BinaryOp):
            self.visit_expression(node.left)
            self.visit_expression(node.right)
            if node.op == "<<" and self._is_cout_expr(node.left):
                return
            if node.op == ">>" and self._is_cin_expr(node.left):
                if not self.is_lvalue(node.right):
                    self.error(node, "Invalid target for 'cin >>': right operand must be a modifiable lvalue", code="E006")
                elif isinstance(node.right, Identifier):
                    sym = self.current_scope.resolve(node.right.name)
                    if sym and sym.is_const:
                        self.error(node, f"Cannot extract into const variable '{node.right.name}'", code="E010")
                return

            l_type = self.normalize_type(self.get_expr_type(node.left))
            r_type = self.normalize_type(self.get_expr_type(node.right))

            cls = self.current_scope.resolve_class(l_type)
            if cls:
                op_method = f"operator{node.op}"
                if op_method in cls.methods:
                    matched = any(
                        len(m_def.params) == 1 and self.is_type_compatible(m_def.params[0].param_type, r_type, node.right)
                        for m_def, _ in cls.methods[op_method]
                    )
                    if not matched:
                        self.error(node, f"Invalid operand of type '{r_type}' to overloaded '{op_method}' on class '{cls.name}'", code="E002")
                else:
                    self.error(node, f"No overloaded operator '{node.op}' defined for class '{cls.name}'", code="E002")
                return

            if node.op in ["+", "-", "*", "/"]:
                if isinstance(node.left, StringLiteral) or isinstance(node.right, StringLiteral):
                    self.error(node, f"Invalid operands to binary '{node.op}' ('{l_type}' and '{r_type}')", code="E002")
                elif not (self.is_numeric_type(l_type) and self.is_numeric_type(r_type)):
                    self.error(node, f"Invalid operands to binary '{node.op}' ('{l_type}' and '{r_type}')", code="E002")
            elif node.op in ["%", "&", "|", "^", "<<", ">>"]:
                if not (self.is_integral_type(l_type) and self.is_integral_type(r_type)):
                    self.error(node, f"Invalid operands to binary '{node.op}' ('{l_type}' and '{r_type}'); integral types required", code="E002")
            elif node.op in ["==", "!=", "<", "<=", ">", ">="]:
                if not (self.is_type_compatible(l_type, r_type, node.right) or self.is_type_compatible(r_type, l_type, node.left)):
                    self.error(node, f"Cannot compare incompatible types '{l_type}' and '{r_type}' with '{node.op}'", code="E002")
        elif isinstance(node, UnaryOp):
            self.visit_expression(node.expr)
            op_t = self.normalize_type(self.get_expr_type(node.expr))
            if node.op == "~" and not self.is_integral_type(op_t):
                self.error(node, f"Invalid operand of type '{op_t}' to unary '~'; integral type required", code="E002")
            elif node.op in ["-", "+"] and not self.is_numeric_type(op_t):
                self.error(node, f"Invalid operand of type '{op_t}' to unary '{node.op}'", code="E002")
        elif isinstance(node, (PreIncrement, PreDecrement, PostIncrement, PostDecrement)):
            self.visit_expression(node.target)
            if not self.is_lvalue(node.target):
                self.error(node, "Increment/decrement operand must be a modifiable lvalue", code="E006")
        elif isinstance(node, CastExpression):
            self._check_type_headers(node, node.target_type)
            self.visit_expression(node.expr)
        elif isinstance(node, TernaryOp):
            self.visit_expression(node.condition)
            self.visit_expression(node.true_expr)
            self.visit_expression(node.false_expr)
            t_true = self.get_expr_type(node.true_expr)
            t_false = self.get_expr_type(node.false_expr)
            if not (self.is_type_compatible(t_true, t_false, node.false_expr) or self.is_type_compatible(t_false, t_true, node.true_expr)):
                self.error(node, f"Incompatible operand types ('{t_true}' and '{t_false}') in conditional expression", code="E002")
        elif isinstance(node, AddressOf):
            self.visit_expression(node.expr)
            if not self.is_lvalue(node.expr):
                self.error(node, "Cannot take the address of an rvalue", code="E006")
        elif isinstance(node, Deref):
            self.visit_expression(node.expr)
            t = self.normalize_type(self.get_expr_type(node.expr))
            if not (t.endswith("*") or t == "ptr"):
                self.error(node, f"Indirection requires pointer operand ('{t}' invalid)", code="E002")
        elif isinstance(node, DerefAssignment):
            self.visit_expression(node.target)
            self.visit_expression(node.expr)
            t = self.normalize_type(self.get_expr_type(node.target))
            if not (t.endswith("*") or t == "ptr"):
                self.error(node, f"Indirection requires pointer operand ('{t}' invalid)", code="E002")
            elif t.endswith("*"):
                pointee_t = t[:-1].strip()
                rhs_t = self.get_expr_type(node.expr)
                if pointee_t != "void" and not self.is_type_compatible(pointee_t, rhs_t, node.expr):
                    self.error(node, f"Cannot assign value of type '{rhs_t}' to dereferenced pointer of type '{pointee_t}'", code="E002")
        elif isinstance(node, FunctionCall):
            for arg in node.args:
                self.visit_expression(arg)
            self._instantiate_template_function(node.name, node)
            sym = self.current_scope.resolve(node.name)
            funcs = self.current_scope.resolve_all_functions(node.name)
            if not sym and not funcs:
                cls = self.current_scope.resolve_class(node.name)
                if not cls:
                    self._error_undeclared(node, node.name, "function")
            else:
                if sym:
                    sym.is_used = True
                if node.name == "printf":
                    if len(node.args) < 1:
                        self.error(node, "Function 'printf' requires at least 1 format string argument", code="E002")
                    else:
                        fmt_t = self.normalize_type(self.get_expr_type(node.args[0]))
                        if fmt_t not in ["char*", "ptr"]:
                            self.error(node, f"First argument to 'printf' must be a format string ('char*'), got '{fmt_t}'", code="E002")
                elif node.name == "malloc":
                    if len(node.args) != 1 or not self.is_numeric_type(self.get_expr_type(node.args[0])):
                        self.error(node, "Function 'malloc' requires 1 numeric size argument", code="E002")
                elif node.name == "free":
                    if len(node.args) != 1:
                        self.error(node, "Function 'free' requires 1 pointer argument", code="E002")
                    else:
                        arg_t = self.normalize_type(self.get_expr_type(node.args[0]))
                        if not (arg_t.endswith("*") or arg_t == "ptr"):
                            self.error(node, f"Argument to 'free' must be a pointer, got '{arg_t}'", code="E002")
                elif funcs:
                    matched_fn = None
                    for fn_cand in funcs:
                        if len(fn_cand.params) == len(node.args):
                            if all(self.is_type_compatible(p.param_type, self.get_expr_type(a), a) for p, a in zip(fn_cand.params, node.args)):
                                matched_fn = fn_cand
                                break
                    if not matched_fn:
                        arg_types_str = ", ".join(self.get_expr_type(a) for a in node.args)
                        self.error(node, f"No matching function for call to '{node.name}' with argument types ({arg_types_str})", code="E002")
                    else:
                        for p, a in zip(matched_fn.params, node.args):
                            if p.is_reference and not p.is_const and not self.is_lvalue(a):
                                self.error(node, f"Cannot bind non-const reference parameter '{p.name}' of type '{p.param_type}&' to an rvalue", code="E002")
        elif isinstance(node, LambdaExpr):
            self.push_scope()
            for p in node.params:
                sym = self.current_scope.define(p.name, p.param_type, p.line, p.col)
                sym.is_used = True
            self.visit_block(node.body)
            self.pop_scope()

    def get_expr_type(self, node: Expression) -> str:
        if isinstance(node, IntLiteral):
            return "int"
        elif isinstance(node, FloatLiteral):
            return "double"
        elif isinstance(node, StringLiteral):
            return "char*"
        elif isinstance(node, BoolLiteral):
            return "bool"
        elif isinstance(node, ThisExpr):
            return f"{self.current_class.name}*" if self.current_class else "ptr"
        elif isinstance(node, NewExpr):
            return f"{node.type_name}*"
        elif isinstance(node, Identifier):
            sym = self.current_scope.resolve(node.name)
            if sym:
                return sym.s_type
            if self.current_class and node.name in self.current_class.fields:
                return self.current_class.fields[node.name][0]
            return "int"
        elif isinstance(node, LambdaExpr):
            return "ptr"
        elif isinstance(node, CastExpression):
            return node.target_type
        elif isinstance(node, AddressOf):
            inner_t = self.normalize_type(self.get_expr_type(node.expr))
            return f"{inner_t}*"
        elif isinstance(node, Deref):
            inner_t = self.normalize_type(self.get_expr_type(node.expr))
            if inner_t.endswith("*"):
                return inner_t[:-1].strip()
            return "int"
        elif isinstance(node, (PreIncrement, PreDecrement, PostIncrement, PostDecrement)):
            return self.get_expr_type(node.target)
        elif isinstance(node, TernaryOp):
            t_true = self.normalize_type(self.get_expr_type(node.true_expr))
            t_false = self.normalize_type(self.get_expr_type(node.false_expr))
            if t_true == "double" or t_false == "double":
                return "double"
            return t_true
        elif isinstance(node, BinaryOp):
            if node.op == "<<" and self._is_cout_expr(node.left):
                return "std::ostream&"
            if node.op == ">>" and self._is_cin_expr(node.left):
                return "std::istream&"
            l_type = self.normalize_type(self.get_expr_type(node.left))
            r_type = self.normalize_type(self.get_expr_type(node.right))
            cls = self.current_scope.resolve_class(l_type)
            if cls:
                op_method = f"operator{node.op}"
                if op_method in cls.methods:
                    return cls.methods[op_method][0][0].return_type
            if node.op in ["==", "!=", "<", "<=", ">", ">=", "&&", "||"]:
                return "bool"
            if l_type == "double" or r_type == "double":
                return "double"
            return l_type
        elif isinstance(node, UnaryOp):
            if node.op == "!":
                return "bool"
            elif node.op == "&":
                return f"{self.normalize_type(self.get_expr_type(node.expr))}*"
            elif node.op == "*":
                inner_t = self.normalize_type(self.get_expr_type(node.expr))
                return inner_t[:-1].strip() if inner_t.endswith("*") else "int"
            return self.get_expr_type(node.expr)
        elif isinstance(node, FunctionCall):
            funcs = self.current_scope.resolve_all_functions(node.name)
            if funcs:
                arg_types = [self.normalize_type(self.get_expr_type(a)) for a in node.args]
                for f in funcs:
                    if len(f.params) == len(node.args):
                        if [self.normalize_type(p.param_type) for p in f.params] == arg_types:
                            return f.return_type
                for f in funcs:
                    if len(f.params) == len(node.args):
                        return f.return_type
                return funcs[0].return_type
            sym = self.current_scope.resolve(node.name)
            if sym:
                if sym.s_type == "ptr" and node.name != "malloc":
                    return "int"
                return sym.s_type
            cls = self.current_scope.resolve_class(node.name)
            if cls:
                return cls.name
            return "int"
        elif isinstance(node, MethodCall):
            obj_t = self.get_expr_type(node.object_expr).replace("const ", "").rstrip("*&").strip()
            cls = self.current_scope.resolve_class(obj_t)
            if cls and node.method_name in cls.methods:
                arg_types = [self.normalize_type(self.get_expr_type(a)) for a in node.args]
                for m_def, _ in cls.methods[node.method_name]:
                    if len(m_def.params) == len(node.args):
                        if [self.normalize_type(p.param_type) for p in m_def.params] == arg_types:
                            return m_def.return_type
                return cls.methods[node.method_name][0][0].return_type
            return "int"
        elif isinstance(node, (MemberAccess, ArrowAccess)):
            obj_t = self.get_expr_type(node.object_expr).replace("struct ", "").replace("const ", "").rstrip("*&").strip()
            cls = self.current_scope.resolve_class(obj_t)
            if cls and node.member in cls.fields:
                return cls.fields[node.member][0]
            st = self.current_scope.resolve_struct(obj_t)
            if st:
                for m in st.members:
                    if m.name == node.member:
                        return m.param_type
            return "int"
        elif isinstance(node, ArrayAccess):
            arr_t = self.get_expr_type(Identifier(node.name, node.line, node.col) if isinstance(node.name, str) else node.name)
            if arr_t.endswith("[]"):
                return arr_t[:-2].strip()
            if arr_t.endswith("*"):
                return arr_t[:-1].strip()
            return arr_t
        elif isinstance(node, ScopeResolution):
            full = f"{node.namespace}::{node.member}"
            sym = self.current_scope.resolve(full)
            return sym.s_type if sym else "int"
        return "int"

    def _instantiate_template_function(self, name: str, node: ASTNode) -> Optional[str]:
        if "<" not in name and name in self.templates:
            tpl = self.templates[name]
            if isinstance(tpl.decl, FunctionDef) and hasattr(node, "args") and len(tpl.decl.params) == len(node.args):
                deduced = {}
                for p, arg in zip(tpl.decl.params, node.args):
                    clean_pt = p.param_type.rstrip("&*").strip()
                    if clean_pt in tpl.template_params:
                        deduced[clean_pt] = self.get_expr_type(arg)
                type_args = [deduced.get(tp, "int") for tp in tpl.template_params]
                inst_name = f"{name}<{', '.join(type_args)}>"
                node.name = inst_name
                name = inst_name

        if "<" in name and name.endswith(">"):
            base_name = name[:name.index("<")]
            type_args_str = name[name.index("<") + 1:-1]
            type_args = [t.strip() for t in type_args_str.split(",")]
            if base_name in self.templates:
                tpl = self.templates[base_name]
                if isinstance(tpl.decl, FunctionDef):
                    if name not in self.global_scope.functions:
                        import copy
                        inst_func = copy.deepcopy(tpl.decl)
                        inst_func.name = name
                        type_map = dict(zip(tpl.template_params, type_args))
                        self._substitute_types(inst_func, type_map)
                        if self.ast:
                            self.ast.declarations.append(inst_func)
                        self._register_decl(inst_func, "")
                        self.visit_function(inst_func)
                    return name
        return None

    def _instantiate_template_class(self, class_name: str, node: ASTNode) -> Optional[str]:
        if "<" in class_name and class_name.endswith(">"):
            base_name = class_name[:class_name.index("<")]
            type_args_str = class_name[class_name.index("<") + 1:-1]
            type_args = [t.strip() for t in type_args_str.split(",")]
            if base_name in self.templates:
                tpl = self.templates[base_name]
                if isinstance(tpl.decl, ClassDef):
                    if not self.global_scope.resolve_class(class_name):
                        import copy
                        inst_cls = copy.deepcopy(tpl.decl)
                        inst_cls.name = class_name
                        type_map = dict(zip(tpl.template_params, type_args))
                        self._substitute_types(inst_cls, type_map)
                        if self.ast:
                            self.ast.declarations.append(inst_cls)
                        self._register_decl(inst_cls, "")
                        self.visit_class_def(inst_cls)
                    return class_name
        return None

    def _substitute_types(self, node: Any, type_map: Dict[str, str]):
        if isinstance(node, FunctionDef):
            for old_t, new_t in type_map.items():
                if node.return_type == old_t:
                    node.return_type = new_t
                elif node.return_type == f"{old_t}*":
                    node.return_type = f"{new_t}*"
                elif node.return_type == f"{old_t}&":
                    node.return_type = f"{new_t}&"
            for p in node.params:
                self._substitute_types(p, type_map)
            if node.body:
                self._substitute_types(node.body, type_map)
        elif isinstance(node, Parameter):
            for old_t, new_t in type_map.items():
                if node.param_type == old_t:
                    node.param_type = new_t
                elif node.param_type == f"{old_t}*":
                    node.param_type = f"{new_t}*"
                elif node.param_type == f"{old_t}&":
                    node.param_type = f"{new_t}&"
        elif isinstance(node, VarDeclaration):
            for old_t, new_t in type_map.items():
                if node.var_type == old_t:
                    node.var_type = new_t
                elif node.var_type == f"{old_t}*":
                    node.var_type = f"{new_t}*"
                elif node.var_type == f"{old_t}&":
                    node.var_type = f"{new_t}&"
            if node.initializer:
                self._substitute_types(node.initializer, type_map)
        elif isinstance(node, ClassDef):
            for m in node.members:
                self._substitute_types(m.decl, type_map)
        elif isinstance(node, ConstructorDef):
            for p in node.params:
                self._substitute_types(p, type_map)
            if node.body:
                self._substitute_types(node.body, type_map)
        elif isinstance(node, Block):
            for s in node.statements:
                self._substitute_types(s, type_map)
        elif isinstance(node, (IfStatement, WhileStatement, DoWhileStatement, ForStatement)):
            for attr in ["condition", "then_branch", "else_branch", "body", "init", "update"]:
                if hasattr(node, attr) and getattr(node, attr):
                    self._substitute_types(getattr(node, attr), type_map)
        elif isinstance(node, ExpressionStatement):
            self._substitute_types(node.expr, type_map)
        elif isinstance(node, ReturnStatement):
            if node.expr:
                self._substitute_types(node.expr, type_map)
        elif isinstance(node, (BinaryOp, Assignment)):
            if hasattr(node, "left"): self._substitute_types(node.left, type_map)
            if hasattr(node, "right"): self._substitute_types(node.right, type_map)
            if hasattr(node, "expr"): self._substitute_types(node.expr, type_map)

    def _error_undeclared(self, node: ASTNode, name: str, kind: str):
        # 1. Check standard library registry for missing header
        header = self.registry.lookup(name)
        if header and not self.registry.is_header_included(header, self.included_headers):
            self._emit_missing_header(node, name, header)
            # Error recovery: define a dummy symbol in the current scope
            dummy = self.current_scope.define(name, "int", node.line, node.col, file=getattr(node, "file", None) or self.entry_file)
            dummy.is_used = True
            return

        # 2. Check for inactive namespaces (both std and user-defined namespaces)
        active_ns = self.current_scope.get_active_namespaces()
        candidate_namespaces = self.namespace_engine.find_candidate_namespaces(
            name,
            active_namespaces=active_ns,
            included_headers=self.included_headers,
        )

        if candidate_namespaces:
            target_ns = candidate_namespaces[0]
            other_ns = candidate_namespaces[1:] if len(candidate_namespaces) > 1 else None
            self._emit_unqualified_namespace(node, name, target_ns, kind=kind, other_namespaces=other_ns)
            dummy = self.current_scope.define(name, "int", node.line, node.col, file=getattr(node, "file", None) or self.entry_file)
            dummy.is_used = True
            return

        # 3. Fallback: Typo did-you-mean matcher
        candidates = self.current_scope.all_names() + ["printf", "malloc", "free", "main", "int", "char", "double", "float", "bool"]
        closest = find_closest_match(name, candidates)
        help_text = f"did you mean '{closest}'?" if closest else None
        origin_file, file_source = self._get_file_and_source(node)
        is_gen = bool(getattr(node, "macro_generated", False))
        diag = make_diagnostic(
            code="E001",
            severity="error",
            message=f"Undeclared {kind} '{name}'",
            file_path=origin_file,
            line=node.line,
            col=node.col,
            end_line=node.line,
            end_col=node.col + max(1, len(name)),
            source=file_source,
            help_text=help_text or "",
            stage="semantic",
            length=len(name),
            suggestion=closest if (closest and not is_gen) else None,
            fixability="manual" if (closest and not is_gen) else "none",
            macro_generated=is_gen,
        )
        self._add_diag(diag)
        # Error recovery: define a dummy symbol in the current scope to avoid cascading duplicate errors
        dummy = self.current_scope.define(name, "int", node.line, node.col, file=origin_file)
        dummy.is_used = True

    def push_scope(self):
        self.current_scope = SymbolTable(self.current_scope)

    def pop_scope(self):
        self.current_scope = self.current_scope.parent

    def _get_file_and_source(self, target: Any = None) -> Tuple[str, str]:
        t_file = getattr(target, "file", None) if target else None
        file_path = canonical_path(t_file) if t_file else self.entry_file
        if self.preproc_result:
            if file_path in self.preproc_result.file_sources:
                return file_path, self.preproc_result.file_sources[file_path]
            for k, v in self.preproc_result.file_sources.items():
                if same_file(k, file_path):
                    return k, v
        if same_file(file_path, self.entry_file):
            return file_path, self.source
        return file_path, ""

    def error(self, node: ASTNode, message: str, code: str = "E001", help_text: Optional[str] = None, length: int = 1):
        origin_file, file_source = self._get_file_and_source(node)
        is_gen = bool(getattr(node, "macro_generated", False))
        diag = make_diagnostic(
            code=code,
            severity="error",
            message=message,
            file_path=origin_file,
            line=node.line,
            col=node.col,
            end_line=node.line,
            end_col=node.col + max(1, length),
            source=file_source,
            help_text=help_text or "",
            stage="semantic",
            length=length,
            macro_generated=is_gen,
        )
        self._add_diag(diag)

    def eval_constexpr_expr(self, expr: Expression) -> Tuple[Any, bool]:
        """Evaluates a constant expression at compile time. Returns (value, is_constant)."""
        if isinstance(expr, IntLiteral):
            return expr.value, True
        if isinstance(expr, FloatLiteral):
            return expr.value, True
        if isinstance(expr, BoolLiteral):
            return expr.value, True
        if isinstance(expr, StringLiteral):
            return expr.value, True
        if isinstance(expr, Identifier):
            sym = self.current_scope.resolve(expr.name)
            if sym and (getattr(sym, "is_constexpr", False) or getattr(sym, "is_const", False)) and getattr(sym, "const_value", None) is not None:
                return sym.const_value, True
            return None, False
        if isinstance(expr, UnaryOp):
            val, ok = self.eval_constexpr_expr(expr.expr)
            if not ok: return None, False
            if expr.op == "-": return -val, True
            if expr.op == "+": return +val, True
            if expr.op == "!": return (not val), True
            if expr.op == "~": return ~int(val), True
            return None, False
        if isinstance(expr, BinaryOp):
            l_val, l_ok = self.eval_constexpr_expr(expr.left)
            r_val, r_ok = self.eval_constexpr_expr(expr.right)
            if not (l_ok and r_ok): return None, False
            try:
                if expr.op == "+": return l_val + r_val, True
                if expr.op == "-": return l_val - r_val, True
                if expr.op == "*": return l_val * r_val, True
                if expr.op == "/":
                    if r_val == 0: return None, False
                    return (l_val // r_val if isinstance(l_val, int) and isinstance(r_val, int) else l_val / r_val), True
                if expr.op == "%":
                    if r_val == 0: return None, False
                    return l_val % r_val, True
                if expr.op == "==": return l_val == r_val, True
                if expr.op == "!=": return l_val != r_val, True
                if expr.op == "<": return l_val < r_val, True
                if expr.op == "<=": return l_val <= r_val, True
                if expr.op == ">": return l_val > r_val, True
                if expr.op == ">=": return l_val >= r_val, True
                if expr.op == "&&": return bool(l_val and r_val), True
                if expr.op == "||": return bool(l_val or r_val), True
                if expr.op == "&": return int(l_val) & int(r_val), True
                if expr.op == "|": return int(l_val) | int(r_val), True
                if expr.op == "^": return int(l_val) ^ int(r_val), True
                if expr.op == "<<": return int(l_val) << int(r_val), True
                if expr.op == ">>": return int(l_val) >> int(r_val), True
            except (ArithmeticError, TypeError, ValueError):
                return None, False
        if isinstance(expr, TernaryOp):
            c_val, c_ok = self.eval_constexpr_expr(expr.condition)
            if not c_ok: return None, False
            return self.eval_constexpr_expr(expr.true_expr if c_val else expr.false_expr)
        if isinstance(expr, CastExpression):
            val, ok = self.eval_constexpr_expr(expr.expr)
            if not ok: return None, False
            if expr.target_type == "int": return int(val), True
            if expr.target_type in ("float", "double"): return float(val), True
            if expr.target_type == "bool": return bool(val), True
            if expr.target_type == "char": return int(val) & 0xFF, True
        if isinstance(expr, FunctionCall):
            resolved = self.current_scope.resolve_function(expr.name)
            funcs = resolved if isinstance(resolved, list) else ([resolved] if resolved else [])
            for f in funcs:
                    if getattr(f, "is_constexpr", False) and f.body:
                        arg_vals = []
                        all_const = True
                        for a in expr.args:
                            av, aok = self.eval_constexpr_expr(a)
                            if not aok:
                                all_const = False
                                break
                            arg_vals.append(av)
                        if all_const and len(arg_vals) == len(f.params):
                            res = self._eval_constexpr_function_call(f, arg_vals)
                            if res is not None:
                                return res, True
        return None, False

    def _eval_constexpr_function_call(self, func: FunctionDef, arg_vals: List[Any]) -> Optional[Any]:
        if not func.body or not func.body.statements:
            return None
        env = {p.name: val for p, val in zip(func.params, arg_vals)}
        for s in func.body.statements:
            if isinstance(s, ReturnStatement) and s.expr:
                return self._eval_constexpr_with_env(s.expr, env)
        return None

    def _eval_constexpr_with_env(self, expr: Expression, env: Dict[str, Any]) -> Optional[Any]:
        if isinstance(expr, IntLiteral): return expr.value
        if isinstance(expr, FloatLiteral): return expr.value
        if isinstance(expr, BoolLiteral): return expr.value
        if isinstance(expr, Identifier): return env.get(expr.name)
        if isinstance(expr, UnaryOp):
            v = self._eval_constexpr_with_env(expr.expr, env)
            if v is None: return None
            if expr.op == "-": return -v
            if expr.op == "+": return +v
            if expr.op == "!": return not v
            if expr.op == "~": return ~int(v)
        if isinstance(expr, BinaryOp):
            lv = self._eval_constexpr_with_env(expr.left, env)
            rv = self._eval_constexpr_with_env(expr.right, env)
            if lv is None or rv is None: return None
            try:
                if expr.op == "+": return lv + rv
                if expr.op == "-": return lv - rv
                if expr.op == "*": return lv * rv
                if expr.op == "/": return lv // rv if isinstance(lv, int) and isinstance(rv, int) else lv / rv
                if expr.op == "%": return lv % rv
                if expr.op == "==": return lv == rv
                if expr.op == "!=": return lv != rv
                if expr.op == "<": return lv < rv
                if expr.op == "<=": return lv <= rv
                if expr.op == ">": return lv > rv
                if expr.op == ">=": return lv >= rv
            except (ArithmeticError, TypeError, ValueError):
                return None
        return None
