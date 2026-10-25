import os
from typing import Dict, List, Optional, Set, Tuple, Any
from src.ast_nodes import *

class CodeGenerator:
    """LLVM IR Code Generator for C++ (Phases 0-6)."""
    def __init__(self, opt_level: int = 0, debug_info: bool = False, source_file: str = "main.cpp"):
        self.opt_level = opt_level
        self.debug_info = debug_info
        self.source_file = source_file
        self.dbg_metadata: List[str] = []
        self.current_dbg_sp: Optional[str] = None
        self.code: List[str] = []
        self.reg_count: int = 1
        self.label_count: int = 1
        self.strings: Dict[str, str] = {}
        self.string_count: int = 0
        
        self.env: List[Dict[str, Tuple[str, str]]] = []          # scope -> dict(name -> (ptr, llvm_type))
        self.raw_type_env: List[Dict[str, str]] = []             # scope -> dict(name -> raw_type_str)
        self.is_ref_env: List[Dict[str, bool]] = []              # scope -> dict(name -> bool)
        self.global_raw_types: Dict[str, str] = {}
        self.functions: Dict[str, str] = {}                      # mangled_name or unmangled -> llvm_ret_type
        self.defined_funcs: Set[str] = set()
        self.global_constants: Dict[str, Tuple[str, str]] = {}   # name -> (val_str, llvm_type)
        self.structs: Dict[str, StructDef] = {}
        self.classes: Dict[str, ClassDef] = {}
        self.class_field_indices: Dict[str, Dict[str, int]] = {}
        self.class_field_types: Dict[str, Dict[str, str]] = {}
        self.class_vtable_entries: Dict[str, List[Tuple[str, str, str]]] = {}
        self.class_vtable_indices: Dict[str, Dict[str, int]] = {}
        self.class_has_vptr: Dict[str, bool] = {}
        self.current_catch_label: Optional[str] = None
        self.lambda_count: int = 0
        self.loop_stack: List[Tuple[str, str]] = []              # (break_label, continue_label)
        self.globals: Dict[str, Tuple[str, str]] = {}            # name -> (ptr, llvm_type)
        self.active_namespaces: Set[str] = set()
        self.func_signatures: List[Dict[str, Any]] = []          # list of signature dicts
        self.current_class: Optional[ClassDef] = None
        self.current_function: Optional[FunctionDef] = None
        self.destructors_to_call: List[List[Tuple[str, str]]] = [] # scope -> list of (ptr, class_name)

    def get_reg(self) -> str:
        r = f"%{self.reg_count}"
        self.reg_count += 1
        return r
        
    def get_label(self) -> str:
        l = f"L{self.label_count}"
        self.label_count += 1
        return l

    def push_env(self):
        self.env.append({})
        self.raw_type_env.append({})
        self.is_ref_env.append({})
        self.destructors_to_call.append([])

    def pop_env(self):
        if self.destructors_to_call and self.destructors_to_call[-1]:
            for obj_ptr, cls_name in reversed(self.destructors_to_call[-1]):
                cls_def = self.classes.get(cls_name)
                if cls_def and self._has_destructor(cls_def):
                    dtor_mangled = self.mangle_function(cls_name, [], class_name=cls_name, is_destructor=True)
                    self.code.append(f"  call void @{dtor_mangled}(ptr {obj_ptr})")
        self.destructors_to_call.pop()
        self.env.pop()
        self.raw_type_env.pop()
        self.is_ref_env.pop()

    def resolve(self, name: str) -> Optional[Tuple[str, str]]:
        if name in ["cout", "std::cout"]:
            return ("@_ZN3std4coutE", "ptr")
        if name in ["cin", "std::cin"]:
            return ("@_ZN3std3cinE", "ptr")
        if name in ["endl", "std::endl"]:
            return ("@_ZN3std4endlE", "i8")
        for scope in reversed(self.env):
            if name in scope:
                return scope[name]
        for ns in self.active_namespaces:
            ns_name = f"{ns}::{name}"
            for scope in reversed(self.env):
                if ns_name in scope:
                    return scope[ns_name]
            if ns_name in self.globals:
                return self.globals[ns_name]
        if name in self.globals:
            return self.globals[name]
        return None

    def get_raw_type(self, name: str) -> str:
        if name in ["cout", "std::cout"]:
            return "std::ostream"
        if name in ["cin", "std::cin"]:
            return "std::istream"
        if name in ["endl", "std::endl"]:
            return "char"
        for scope in reversed(self.raw_type_env):
            if name in scope:
                return scope[name]
        for ns in self.active_namespaces:
            ns_name = f"{ns}::{name}"
            for scope in reversed(self.raw_type_env):
                if ns_name in scope:
                    return scope[ns_name]
            if ns_name in self.global_raw_types:
                return self.global_raw_types[ns_name]
        if name in self.global_raw_types:
            return self.global_raw_types[name]
        return "int"

    def is_ref(self, name: str) -> bool:
        for scope in reversed(self.is_ref_env):
            if name in scope:
                return scope[name]
        return False

    def _get_llvm_type(self, t: str) -> str:
        clean = t.replace("const ", "").strip()
        if clean.endswith("&"):
            return "ptr"
        if clean in ["string", "std::string"]:
            return "ptr"
        if clean == "bool":
            return "i1"
        if clean == "int":
            return "i32"
        if clean in ["float", "double"]:
            return "double"
        if clean == "char":
            return "i8"
        if clean == "void":
            return "void"
        if clean.startswith("struct "):
            return f"%{clean.replace(' ', '.')}"
        if clean in self.classes:
            return f"%class.{clean}"
        if clean in self.structs:
            return f"%struct.{clean}"
        if "*" in clean or clean == "ptr":
            return "ptr"
        return "i32"

    def _convert_llvm_type(self, val: str, from_t: str, to_t: str) -> str:
        if from_t == to_t:
            return val
        if to_t == "double" and from_t in ["i32", "i8", "i1"]:
            conv = self.get_reg()
            self.code.append(f"  {conv} = sitofp {from_t} {val} to double")
            return conv
        if to_t in ["i32", "i8", "i1"] and from_t == "double":
            conv = self.get_reg()
            self.code.append(f"  {conv} = fptosi double {val} to {to_t}")
            return conv
        if to_t == "i32" and from_t == "i1":
            conv = self.get_reg()
            self.code.append(f"  {conv} = zext i1 {val} to i32")
            return conv
        if to_t == "i32" and from_t == "i8":
            conv = self.get_reg()
            self.code.append(f"  {conv} = sext i8 {val} to i32")
            return conv
        if to_t in ["i8", "i1"] and from_t == "i32":
            conv = self.get_reg()
            self.code.append(f"  {conv} = trunc i32 {val} to {to_t}")
            return conv
        if to_t == "ptr" and from_t == "i32" and val == "0":
            return "null"
        return val

    def _llvm_type_to_raw(self, lt: str) -> str:
        if lt == "i1": return "bool"
        if lt == "i32": return "int"
        if lt == "double": return "double"
        if lt == "i8": return "char"
        if lt == "ptr": return "ptr"
        if lt.startswith("%class."): return lt.replace("%class.", "")
        if lt.startswith("%struct."): return lt.replace("%struct.", "")
        return "int"

    def _mangle_type(self, t: str) -> str:
        clean = t.replace("const ", "").strip()
        if clean.endswith("&"):
            return "R" + self._mangle_type(clean[:-1].strip())
        if clean.endswith("*"):
            return "P" + self._mangle_type(clean[:-1].strip())
        if clean == "int": return "i"
        if clean == "double": return "d"
        if clean == "float": return "f"
        if clean == "char": return "c"
        if clean == "bool": return "b"
        if clean == "void": return "v"
        return f"{len(clean)}{clean}"

    def mangle_function(self, name: str, param_types: List[str], class_name: Optional[str] = None,
                        is_constructor: bool = False, is_destructor: bool = False) -> str:
        if not class_name and "::" not in name:
            if name in ["main", "printf", "malloc", "free"]:
                return name

        clean_name = name.replace("<", "_").replace(">", "_").replace(",", "_").replace(" ", "")
        clean_class = class_name.replace("<", "_").replace(">", "_").replace(",", "_").replace(" ", "") if class_name else None

        if is_constructor and clean_class:
            param_str = "".join(self._mangle_type(p) for p in param_types) if param_types else "v"
            return f"_ZN{len(clean_class)}{clean_class}C1E{param_str}"

        if is_destructor and clean_class:
            return f"_ZN{len(clean_class)}{clean_class}D1Ev"

        if clean_class:
            op_mangles = {
                "operator+": "pl",
                "operator-": "mi",
                "operator*": "ml",
                "operator/": "dv",
                "operator==": "eq",
                "operator!=": "ne",
                "operator<": "lt",
                "operator>": "gt",
                "operator<<": "ls",
                "operator>>": "rs",
            }
            m_code = op_mangles.get(clean_name, f"{len(clean_name)}{clean_name}")
            param_str = "".join(self._mangle_type(p) for p in param_types) if param_types else "v"
            return f"_ZN{len(clean_class)}{clean_class}{m_code}E{param_str}"

        if "::" in clean_name:
            parts = clean_name.split("::")
            param_str = "".join(self._mangle_type(p) for p in param_types) if param_types else "v"
            prefix = "".join(f"{len(p)}{p}" for p in parts)
            return f"_ZN{prefix}E{param_str}"

        param_str = "".join(self._mangle_type(p) for p in param_types) if param_types else "v"
        return f"_Z{len(clean_name)}{clean_name}{param_str}"

    def _has_destructor(self, class_def: ClassDef) -> bool:
        for m in class_def.members:
            if isinstance(m.decl, DestructorDef) and m.decl.body is not None:
                return True
        return False

    def _has_default_constructor(self, class_def: ClassDef) -> bool:
        for m in class_def.members:
            if isinstance(m.decl, ConstructorDef) and len(m.decl.params) == 0:
                return True
        has_any_ctor = any(isinstance(m.decl, ConstructorDef) for m in class_def.members)
        return not has_any_ctor

    def _get_class_fields(self, cls_name: str) -> List[VarDeclaration]:
        if cls_name not in self.classes:
            return []
        cls = self.classes[cls_name]
        base_fields = []
        if getattr(cls, "base_class", None):
            base_fields = self._get_class_fields(cls.base_class)
        own_fields = [m.decl for m in cls.members if isinstance(m.decl, VarDeclaration)]
        return base_fields + own_fields

    def _has_virtual_methods(self, cls_name: str) -> bool:
        if cls_name not in self.classes:
            return False
        cls = self.classes[cls_name]
        if getattr(cls, "base_class", None) and self._has_virtual_methods(cls.base_class):
            return True
        return any(isinstance(m.decl, FunctionDef) and (getattr(m.decl, "is_virtual", False) or getattr(m.decl, "is_pure_virtual", False) or getattr(m.decl, "is_override", False)) for m in cls.members)

    def _build_vtable_entries(self, cls_name: str) -> List[Tuple[str, str, str]]:
        if cls_name not in self.classes:
            return []
        cls = self.classes[cls_name]
        entries = []
        if getattr(cls, "base_class", None) and self._has_virtual_methods(cls.base_class):
            entries = list(self._build_vtable_entries(cls.base_class))
        for m in cls.members:
            if isinstance(m.decl, FunctionDef) and (getattr(m.decl, "is_virtual", False) or getattr(m.decl, "is_pure_virtual", False) or getattr(m.decl, "is_override", False)):
                m_param_types = [(p.param_type + "&" if p.is_reference else p.param_type) for p in m.decl.params]
                m_mangled = self.mangle_function(m.decl.name, m_param_types, class_name=cls_name)
                ret_t = self._get_llvm_type(m.decl.return_type)
                found_idx = -1
                for idx, e in enumerate(entries):
                    if e[0] == m.decl.name:
                        found_idx = idx
                        break
                if found_idx != -1:
                    entries[found_idx] = (m.decl.name, m_mangled, ret_t)
                else:
                    entries.append((m.decl.name, m_mangled, ret_t))
        return entries

    def _emit_default_constructor(self, class_def: ClassDef):
        class_name = class_def.name
        ctor_mangled = self.mangle_function(class_name, [], class_name=class_name, is_constructor=True)
        if ctor_mangled in self.defined_funcs:
            return
        self.defined_funcs.add(ctor_mangled)
        self.code.append(f"define void @{ctor_mangled}(ptr %this_arg) {{")
        self.code.append("entry:")
        if getattr(class_def, "base_class", None):
            base_ctor_mangled = self.mangle_function(class_def.base_class, [], class_name=class_def.base_class, is_constructor=True)
            self.code.append(f"  call void @{base_ctor_mangled}(ptr %this_arg)")
        if self.class_has_vptr.get(class_name, False):
            vtable_name = f"_ZTV{len(class_name)}{class_name}"
            vptr_gep = f"%vptr_{self.reg_count}"
            self.reg_count += 1
            self.code.append(f"  {vptr_gep} = getelementptr %class.{class_name}, ptr %this_arg, i32 0, i32 0")
            self.code.append(f"  store ptr @{vtable_name}, ptr {vptr_gep}")
        self.code.append("  ret void")
        self.code.append("}")
        self.code.append("")

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

    def generate(self, program: Program) -> str:
        self.code.append("declare i32 @printf(ptr, ...)")
        self.code.append("declare i32 @scanf(ptr, ...)")
        self.code.append("declare ptr @malloc(i64)")
        self.code.append("declare void @free(ptr)")
        self.code.append("declare void @exit(i32)")
        self.code.append("declare i64 @strlen(ptr)")
        self.code.append("")
        self.code.append("@.fmt_d = private unnamed_addr constant [3 x i8] c\"%d\\00\"")
        self.code.append("@.fmt_f = private unnamed_addr constant [3 x i8] c\"%f\\00\"")
        self.code.append("@.fmt_s = private unnamed_addr constant [3 x i8] c\"%s\\00\"")
        self.code.append("@.fmt_c = private unnamed_addr constant [3 x i8] c\"%c\\00\"")
        self.code.append("@.fmt_endl = private unnamed_addr constant [2 x i8] c\"\\0A\\00\"")
        self.code.append("@.fmt_in_d = private unnamed_addr constant [3 x i8] c\"%d\\00\"")
        self.code.append("@.fmt_in_f = private unnamed_addr constant [4 x i8] c\"%lf\\00\"")
        self.code.append("@.fmt_in_c = private unnamed_addr constant [4 x i8] c\" %c\\00\"")
        self.code.append("@_ZN3std4coutE = global i8 0")
        self.code.append("@_ZN3std3cinE = global i8 0")
        self.code.append("@_ZN3std4endlE = global i8 10")
        self.code.append("@cout = global i8 0")
        self.code.append("@cin = global i8 0")
        self.code.append("@endl = global i8 10")
        self.code.append("@__cxx_exception_val = global i32 0")
        self.code.append("@__cxx_exception_active = global i1 0")
        self.code.append("")

        # 1. Unpack top-level declarations and namespaces
        top_decls = []
        for decl in program.declarations:
            if isinstance(decl, NamespaceDef):
                self._collect_namespace(decl, "", top_decls)
            else:
                top_decls.append(decl)

        # 2. Process structs
        for decl in top_decls:
            if isinstance(decl, StructDef):
                member_types = [self._get_llvm_type(m.param_type) for m in decl.members]
                self.code.append(f"%struct.{decl.name} = type {{ {', '.join(member_types)} }}")
                self.structs[decl.name] = decl

        # Register all classes first
        for decl in top_decls:
            if isinstance(decl, ClassDef):
                self.classes[decl.name] = decl

        # 3. Process classes and layout
        for decl in top_decls:
            if isinstance(decl, ClassDef):
                fields = self._get_class_fields(decl.name)
                has_v = self._has_virtual_methods(decl.name)
                self.class_has_vptr[decl.name] = has_v
                offset = 1 if has_v else 0
                self.class_field_indices[decl.name] = {f.name: i + offset for i, f in enumerate(fields)}
                self.class_field_types[decl.name] = {f.name: f.var_type for f in fields}
                member_types = []
                if has_v:
                    member_types.append("ptr")
                for f in fields:
                    member_types.append(self._get_llvm_type(f.var_type))
                if not member_types:
                    member_types = ["i8"]
                self.code.append(f"%class.{decl.name} = type {{ {', '.join(member_types)} }}")

                if has_v:
                    v_entries = self._build_vtable_entries(decl.name)
                    self.class_vtable_entries[decl.name] = v_entries
                    self.class_vtable_indices[decl.name] = {e[0]: i for i, e in enumerate(v_entries)}
                    v_ptrs = []
                    for e in v_entries:
                        v_ptrs.append(f"ptr @{e[1]}")
                    n_entries = max(len(v_ptrs), 1)
                    v_ptrs_str = ", ".join(v_ptrs) if v_ptrs else "ptr null"
                    vtable_name = f"_ZTV{len(decl.name)}{decl.name}"
                    self.code.append(f"@{vtable_name} = constant [{n_entries} x ptr] [{v_ptrs_str}]")

        # 4. Register function signatures
        for decl in top_decls:
            if isinstance(decl, FunctionDef):
                param_types = [(p.param_type + "&" if p.is_reference else p.param_type) for p in decl.params]
                m_name = self.mangle_function(decl.name, param_types)
                ret_lt = self._get_llvm_type(decl.return_type)
                self.functions[m_name] = ret_lt
                self.functions[decl.name] = ret_lt
                self.func_signatures.append({
                    "name": decl.name,
                    "mangled_name": m_name,
                    "return_type": ret_lt,
                    "param_types": param_types,
                    "is_method": False,
                    "class_name": None
                })
                if decl.body is not None:
                    self.defined_funcs.add(m_name)
                    self.defined_funcs.add(decl.name)
            elif isinstance(decl, ClassDef):
                for m in decl.members:
                    if isinstance(m.decl, FunctionDef):
                        param_types = [(p.param_type + "&" if p.is_reference else p.param_type) for p in m.decl.params]
                        m_name = self.mangle_function(m.decl.name, param_types, class_name=decl.name)
                        ret_lt = self._get_llvm_type(m.decl.return_type)
                        self.functions[m_name] = ret_lt
                        self.func_signatures.append({
                            "name": m.decl.name,
                            "mangled_name": m_name,
                            "return_type": ret_lt,
                            "param_types": param_types,
                            "is_method": True,
                            "class_name": decl.name
                        })
                        if m.decl.body is not None:
                            self.defined_funcs.add(m_name)
                    elif isinstance(m.decl, ConstructorDef):
                        param_types = [(p.param_type + "&" if p.is_reference else p.param_type) for p in m.decl.params]
                        m_name = self.mangle_function(decl.name, param_types, class_name=decl.name, is_constructor=True)
                        self.functions[m_name] = "void"
                        self.func_signatures.append({
                            "name": decl.name,
                            "mangled_name": m_name,
                            "return_type": "void",
                            "param_types": param_types,
                            "is_method": False,
                            "is_constructor": True,
                            "class_name": decl.name
                        })
                        if m.decl.body is not None:
                            self.defined_funcs.add(m_name)
                    elif isinstance(m.decl, DestructorDef):
                        m_name = self.mangle_function(decl.name, [], class_name=decl.name, is_destructor=True)
                        self.functions[m_name] = "void"
                        self.func_signatures.append({
                            "name": f"~{decl.name}",
                            "mangled_name": m_name,
                            "return_type": "void",
                            "param_types": [],
                            "is_method": False,
                            "is_destructor": True,
                            "class_name": decl.name
                        })
                        if m.decl.body is not None:
                            self.defined_funcs.add(m_name)

        # 5. Process global variables, enums, arrays
        for decl in top_decls:
            if isinstance(decl, EnumDef):
                for name, val in decl.enumerators:
                    self.global_constants[name] = (str(val), "i32")
            elif isinstance(decl, VarDeclaration):
                t = self._get_llvm_type(decl.var_type)
                init_val = "null" if ("*" in decl.var_type or t == "ptr") else "0"
                self.code.append(f"@{decl.name} = global {t} {init_val}")
                self.globals[decl.name] = (f"@{decl.name}", t)
                self.global_raw_types[decl.name] = decl.var_type
            elif isinstance(decl, ArrayDeclaration):
                t = self._get_llvm_type(decl.var_type)
                size = decl.size if decl.size else 1
                arr_t = f"[{size} x {t}]"
                self.code.append(f"@{decl.name} = global {arr_t} zeroinitializer")
                self.globals[decl.name] = (f"@{decl.name}", arr_t)
                self.global_raw_types[decl.name] = f"{decl.var_type}[]"
            elif isinstance(decl, StructDeclaration):
                t = f"%struct.{decl.struct_name}"
                self.code.append(f"@{decl.name} = global {t} zeroinitializer")
                self.globals[decl.name] = (f"@{decl.name}", t)
                self.global_raw_types[decl.name] = f"struct {decl.struct_name}"

        self.code.append("")

        # 6. Pre-process string constants
        for decl in top_decls:
            if isinstance(decl, FunctionDef):
                self._collect_strings(decl)
            elif isinstance(decl, ClassDef):
                for m in decl.members:
                    if hasattr(m.decl, "body") and m.decl.body:
                        self._collect_strings(m.decl.body)
            elif isinstance(decl, VarDeclaration):
                self._collect_strings(decl)

        for s, name in self.strings.items():
            s_escaped = s.replace('\\n', '\\0A').replace('\\t', '\\09') + "\\00"
            s_len = len(s.replace('\\n', 'n').replace('\\t', 't')) + 1
            self.code.append(f"@{name} = private unnamed_addr constant [{s_len} x i8] c\"{s_escaped}\"")
        self.code.append("")

        # 7. Emit Class methods, constructors, destructors
        for decl in top_decls:
            if isinstance(decl, ClassDef):
                has_ctor = any(isinstance(m.decl, ConstructorDef) for m in decl.members)
                if not has_ctor:
                    self._emit_default_constructor(decl)
                for m in decl.members:
                    if isinstance(m.decl, ConstructorDef):
                        self.visit_constructor(m.decl, decl.name)
                    elif isinstance(m.decl, DestructorDef):
                        self.visit_destructor(m.decl, decl.name)
                    elif isinstance(m.decl, FunctionDef):
                        self.visit_method(m.decl, decl.name)

        # 8. Emit functions
        for decl in top_decls:
            if isinstance(decl, FunctionDef):
                self.visit_function(decl)

        if self.debug_info:
            self._emit_debug_metadata()

        return "\n".join(self.code)

    def _emit_debug_metadata(self):
        filename = os.path.basename(self.source_file)
        directory = os.path.dirname(os.path.abspath(self.source_file)).replace("\\", "/")
        if not directory:
            directory = "."
        self.code.append("")
        self.code.append("!llvm.dbg.cu = !{!0}")
        self.code.append("!llvm.module.flags = !{!1, !2}")
        self.code.append("!llvm.ident = !{!3}")
        self.code.append("")
        self.code.append(f'!0 = distinct !DICompileUnit(language: DW_LANG_C_plus_plus, file: !4, producer: "c++ compiler (Phase 6)", isOptimized: {"true" if self.opt_level > 0 else "false"}, runtimeVersion: 0, emissionKind: FullDebug)')
        self.code.append('!1 = !{i32 2, !"Dwarf Version", i32 4}')
        self.code.append('!2 = !{i32 2, !"Debug Info Version", i32 3}')
        self.code.append('!3 = !{!"c++ version 1.0.0"}')
        self.code.append(f'!4 = !DIFile(filename: "{filename}", directory: "{directory}")')
        for md in self.dbg_metadata:
            self.code.append(md)

    def _collect_namespace(self, ns: NamespaceDef, prefix: str, out: List[ASTNode]):
        current_prefix = f"{prefix}{ns.name}::"
        for d in ns.declarations:
            if isinstance(d, NamespaceDef):
                self._collect_namespace(d, current_prefix, out)
            elif isinstance(d, FunctionDef):
                d.name = f"{current_prefix}{d.name}"
                out.append(d)
            elif isinstance(d, ClassDef):
                d.name = f"{current_prefix}{d.name}"
                out.append(d)
            elif isinstance(d, VarDeclaration):
                d.name = f"{current_prefix}{d.name}"
                out.append(d)
            else:
                out.append(d)

    def _collect_strings(self, node: Any):
        if not node:
            return
        if isinstance(node, StringLiteral):
            if node.value not in self.strings:
                self.strings[node.value] = f"str.{self.string_count}"
                self.string_count += 1
        if isinstance(node, list):
            for item in node:
                self._collect_strings(item)
            return
        if isinstance(node, ASTNode):
            for attr_name, attr_val in vars(node).items():
                if isinstance(attr_val, (ASTNode, list)):
                    self._collect_strings(attr_val)

    def visit_constructor(self, node: ConstructorDef, class_name: str):
        if node.body is None:
            return
        self.reg_count = 1
        class_def = self.classes[class_name]
        arg_types = [(p.param_type + "&" if p.is_reference else p.param_type) for p in node.params]
        mangled_name = self.mangle_function(class_name, arg_types, class_name=class_name, is_constructor=True)

        params = ["ptr %this_arg"]
        for p in node.params:
            pt = "ptr" if (p.is_reference or p.param_type.endswith("&")) else self._get_llvm_type(p.param_type)
            params.append(f"{pt} %{p.name}_arg")

        self.code.append(f"define void @{mangled_name}({', '.join(params)}) {{")
        self.code.append("entry:")
        self.push_env()

        this_ptr = self.get_reg()
        self.code.append(f"  {this_ptr} = alloca ptr")
        self.code.append(f"  store ptr %this_arg, ptr {this_ptr}")
        self.env[-1]["this"] = (this_ptr, "ptr")
        self.raw_type_env[-1]["this"] = f"{class_name}*"
        self.is_ref_env[-1]["this"] = False

        for p in node.params:
            if p.is_reference or p.param_type.endswith("&"):
                ptr = self.get_reg()
                self.code.append(f"  {ptr} = alloca ptr")
                self.code.append(f"  store ptr %{p.name}_arg, ptr {ptr}")
                self.env[-1][p.name] = (ptr, "ptr")
                self.raw_type_env[-1][p.name] = p.param_type + "&"
                self.is_ref_env[-1][p.name] = True
            else:
                pt = self._get_llvm_type(p.param_type)
                ptr = self.get_reg()
                self.code.append(f"  {ptr} = alloca {pt}")
                self.code.append(f"  store {pt} %{p.name}_arg, ptr {ptr}")
                self.env[-1][p.name] = (ptr, pt)
                self.raw_type_env[-1][p.name] = p.param_type
                self.is_ref_env[-1][p.name] = False

        old_class = self.current_class
        self.current_class = class_def

        if getattr(class_def, "base_class", None):
            base_ctor_mangled = self.mangle_function(class_def.base_class, [], class_name=class_def.base_class, is_constructor=True)
            self.code.append(f"  call void @{base_ctor_mangled}(ptr %this_arg)")
        if self.class_has_vptr.get(class_name, False):
            vtable_name = f"_ZTV{len(class_name)}{class_name}"
            vptr_gep = self.get_reg()
            self.code.append(f"  {vptr_gep} = getelementptr %class.{class_name}, ptr %this_arg, i32 0, i32 0")
            self.code.append(f"  store ptr @{vtable_name}, ptr {vptr_gep}")

        self.visit_block_content(node.body)

        self.pop_env()
        last_inst = self.code[-1].strip() if self.code else ""
        if not (last_inst.startswith("ret ") or last_inst == "ret void"):
            self.code.append("  ret void")

        self.code.append("}")
        self.code.append("")
        self.current_class = old_class

    def visit_destructor(self, node: DestructorDef, class_name: str):
        if node.body is None:
            return
        self.reg_count = 1
        class_def = self.classes[class_name]
        mangled_name = self.mangle_function(class_name, [], class_name=class_name, is_destructor=True)

        self.code.append(f"define void @{mangled_name}(ptr %this_arg) {{")
        self.code.append("entry:")
        self.push_env()

        this_ptr = self.get_reg()
        self.code.append(f"  {this_ptr} = alloca ptr")
        self.code.append(f"  store ptr %this_arg, ptr {this_ptr}")
        self.env[-1]["this"] = (this_ptr, "ptr")
        self.raw_type_env[-1]["this"] = f"{class_name}*"
        self.is_ref_env[-1]["this"] = False

        old_class = self.current_class
        self.current_class = class_def

        self.visit_block_content(node.body)

        self.pop_env()
        last_inst = self.code[-1].strip() if self.code else ""
        if not (last_inst.startswith("ret ") or last_inst == "ret void"):
            self.code.append("  ret void")

        self.code.append("}")
        self.code.append("")
        self.current_class = old_class

    def visit_method(self, node: FunctionDef, class_name: str):
        if node.body is None:
            return
        self.reg_count = 1
        class_def = self.classes[class_name]
        ret_type = self._get_llvm_type(node.return_type)
        arg_types = [(p.param_type + "&" if p.is_reference else p.param_type) for p in node.params]
        mangled_name = self.mangle_function(node.name, arg_types, class_name=class_name)

        params = ["ptr %this_arg"]
        for p in node.params:
            pt = "ptr" if (p.is_reference or p.param_type.endswith("&")) else self._get_llvm_type(p.param_type)
            params.append(f"{pt} %{p.name}_arg")

        self.code.append(f"define {ret_type} @{mangled_name}({', '.join(params)}) {{")
        self.code.append("entry:")
        self.push_env()

        this_ptr = self.get_reg()
        self.code.append(f"  {this_ptr} = alloca ptr")
        self.code.append(f"  store ptr %this_arg, ptr {this_ptr}")
        self.env[-1]["this"] = (this_ptr, "ptr")
        self.raw_type_env[-1]["this"] = f"{class_name}*"
        self.is_ref_env[-1]["this"] = False

        for p in node.params:
            if p.is_reference or p.param_type.endswith("&"):
                ptr = self.get_reg()
                self.code.append(f"  {ptr} = alloca ptr")
                self.code.append(f"  store ptr %{p.name}_arg, ptr {ptr}")
                self.env[-1][p.name] = (ptr, "ptr")
                self.raw_type_env[-1][p.name] = p.param_type + "&"
                self.is_ref_env[-1][p.name] = True
            else:
                pt = self._get_llvm_type(p.param_type)
                ptr = self.get_reg()
                self.code.append(f"  {ptr} = alloca {pt}")
                self.code.append(f"  store {pt} %{p.name}_arg, ptr {ptr}")
                self.env[-1][p.name] = (ptr, pt)
                self.raw_type_env[-1][p.name] = p.param_type
                self.is_ref_env[-1][p.name] = False

        old_class = self.current_class
        self.current_class = class_def

        self.visit_block_content(node.body)

        self.pop_env()
        last_inst = self.code[-1].strip() if self.code else ""
        if not (last_inst.startswith("ret ") or last_inst == "ret void"):
            if node.return_type == "void":
                self.code.append("  ret void")
            elif ret_type == "i32":
                self.code.append("  ret i32 0")
            elif ret_type == "i1":
                self.code.append("  ret i1 0")
            elif ret_type == "i8":
                self.code.append("  ret i8 0")
            elif ret_type == "ptr":
                self.code.append("  ret ptr null")
            else:
                self.code.append("  ret double 0.0")

        self.code.append("}")
        self.code.append("")
        self.current_class = old_class

    def visit_function(self, node: FunctionDef):
        param_types = [(p.param_type + "&" if p.is_reference else p.param_type) for p in node.params]
        mangled_name = self.mangle_function(node.name, param_types)
        ret_type = self._get_llvm_type(node.return_type)

        if node.body is None:
            if mangled_name != "printf" and mangled_name not in self.defined_funcs:
                params = [("ptr" if (p.is_reference or p.param_type.endswith("&")) else self._get_llvm_type(p.param_type)) for p in node.params]
                self.code.append(f"declare {ret_type} @{mangled_name}({', '.join(params)})")
                self.code.append("")
            return

        self.reg_count = 1
        params = []
        for p in node.params:
            pt = "ptr" if (p.is_reference or p.param_type.endswith("&")) else self._get_llvm_type(p.param_type)
            params.append(f"{pt} %{p.name}_arg")

        fn_attrs = ""
        if getattr(node, "is_always_inline", False) or (self.opt_level >= 2 and node.name != "main" and node.body and len(node.body.statements) <= 3):
            fn_attrs = " alwaysinline"
        fn_dbg = ""
        if self.debug_info:
            sp_idx = 5 + len(self.dbg_metadata)
            type_idx = sp_idx + 1
            sp_id = f"!{sp_idx}"
            type_id = f"!{type_idx}"
            self.dbg_metadata.append(f'{sp_id} = distinct !DISubprogram(name: "{node.name}", scope: !4, file: !4, line: {node.line}, type: {type_id}, scopeLine: {node.line}, flags: DIFlagPrototyped, spFlags: DISPFlagDefinition, unit: !0)')
            self.dbg_metadata.append(f'{type_id} = !DISubroutineType(types: !{{null}})')
            fn_dbg = f" !dbg {sp_id}"
            self.current_dbg_sp = sp_id
        self.code.append(f"define {ret_type} @{mangled_name}({', '.join(params)}){fn_attrs}{fn_dbg} {{")
        self.code.append("entry:")
        self.push_env()

        for p in node.params:
            if p.is_reference or p.param_type.endswith("&"):
                ptr = self.get_reg()
                self.code.append(f"  {ptr} = alloca ptr")
                self.code.append(f"  store ptr %{p.name}_arg, ptr {ptr}")
                self.env[-1][p.name] = (ptr, "ptr")
                self.raw_type_env[-1][p.name] = p.param_type + "&"
                self.is_ref_env[-1][p.name] = True
            else:
                pt = self._get_llvm_type(p.param_type)
                ptr = self.get_reg()
                self.code.append(f"  {ptr} = alloca {pt}")
                self.code.append(f"  store {pt} %{p.name}_arg, ptr {ptr}")
                self.env[-1][p.name] = (ptr, pt)
                self.raw_type_env[-1][p.name] = p.param_type
                self.is_ref_env[-1][p.name] = False

        self.current_function = node
        self.visit_block_content(node.body)
        self.current_function = None

        self.pop_env()
        last_inst = self.code[-1].strip() if self.code else ""
        if not (last_inst.startswith("ret ") or last_inst == "ret void"):
            if node.return_type == "void":
                self.code.append("  ret void")
            elif ret_type == "i32":
                self.code.append("  ret i32 0")
            elif ret_type == "i1":
                self.code.append("  ret i1 0")
            elif ret_type == "i8":
                self.code.append("  ret i8 0")
            elif ret_type == "ptr":
                self.code.append("  ret ptr null")
            else:
                self.code.append("  ret double 0.0")

        self.code.append("}")
        self.code.append("")

    def _is_terminated(self) -> bool:
        if not self.code:
            return False
        last = self.code[-1].strip()
        return last.startswith("ret ") or last == "ret void" or last.startswith("br ") or last.startswith("switch ")

    def visit_block_content(self, node: Block):
        for stmt in node.statements:
            if self._is_terminated():
                break
            self.visit_statement(stmt)

    def visit_statement(self, node: Statement):
        if isinstance(node, Block):
            self.push_env()
            self.visit_block_content(node)
            self.pop_env()
        elif isinstance(node, UsingNamespace):
            self.active_namespaces.add(node.name)
        elif isinstance(node, VarDeclaration):
            clean_type = node.var_type.replace("const ", "").strip()
            if clean_type in self.classes and not node.is_reference and not clean_type.endswith("*"):
                cls_t = f"%class.{clean_type}"
                ptr = self.get_reg()
                self.code.append(f"  {ptr} = alloca {cls_t}")
                self.env[-1][node.name] = (ptr, cls_t)
                self.raw_type_env[-1][node.name] = clean_type
                self.is_ref_env[-1][node.name] = False
                cls_def = self.classes[clean_type]
                if self._has_default_constructor(cls_def):
                    ctor_mangled = self.mangle_function(clean_type, [], class_name=clean_type, is_constructor=True)
                    self.code.append(f"  call void @{ctor_mangled}(ptr {ptr})")
                if self._has_destructor(cls_def):
                    if self.destructors_to_call:
                        self.destructors_to_call[-1].append((ptr, clean_type))
            elif node.is_reference or clean_type.endswith("&"):
                ptr = self.get_reg()
                self.code.append(f"  {ptr} = alloca ptr")
                self.env[-1][node.name] = (ptr, "ptr")
                self.raw_type_env[-1][node.name] = clean_type
                self.is_ref_env[-1][node.name] = True
                if node.initializer:
                    if isinstance(node.initializer, Identifier):
                        init_resolved = self.resolve(node.initializer.name)
                        if init_resolved:
                            target_ptr, _ = init_resolved
                            if self.is_ref(node.initializer.name):
                                loaded_ptr = self.get_reg()
                                self.code.append(f"  {loaded_ptr} = load ptr, ptr {target_ptr}")
                                target_ptr = loaded_ptr
                            self.code.append(f"  store ptr {target_ptr}, ptr {ptr}")
                    else:
                        init_val, _ = self.visit_expression(node.initializer)
                        self.code.append(f"  store ptr {init_val}, ptr {ptr}")
            else:
                val = None
                t = None
                if node.initializer:
                    val, t = self.visit_expression(node.initializer)
                pt = t if (node.var_type == "auto" and t) else self._get_llvm_type(node.var_type)
                ptr = self.get_reg()
                self.code.append(f"  {ptr} = alloca {pt}")
                self.env[-1][node.name] = (ptr, pt)
                self.raw_type_env[-1][node.name] = node.var_type
                self.is_ref_env[-1][node.name] = False
                if node.initializer:
                    val = self._convert_llvm_type(val, t, pt)
                    self.code.append(f"  store {pt} {val}, ptr {ptr}")
                elif pt == "ptr":
                    self.code.append(f"  store ptr null, ptr {ptr}")
        elif isinstance(node, ClassInstanceDeclaration):
            if node.class_name in ["string", "std::string"]:
                ptr = self.get_reg()
                self.code.append(f"  {ptr} = alloca ptr")
                self.env[-1][node.name] = (ptr, "ptr")
                self.raw_type_env[-1][node.name] = node.class_name
                self.is_ref_env[-1][node.name] = False
                if node.args:
                    val, t = self.visit_expression(node.args[0])
                    val = self._convert_llvm_type(val, t, "ptr")
                    self.code.append(f"  store ptr {val}, ptr {ptr}")
                else:
                    self.code.append(f"  store ptr null, ptr {ptr}")
                return
            cls_t = f"%class.{node.class_name}"
            ptr = self.get_reg()
            self.code.append(f"  {ptr} = alloca {cls_t}")
            self.env[-1][node.name] = (ptr, cls_t)
            self.raw_type_env[-1][node.name] = node.class_name
            self.is_ref_env[-1][node.name] = False

            args_evaluated = []
            arg_types = []
            for arg in node.args:
                v, t = self.visit_expression(arg)
                args_evaluated.append((v, t))
                arg_types.append(self._llvm_type_to_raw(t))

            # Find matching constructor
            cls_def = self.classes.get(node.class_name)
            best_ctor_params = arg_types
            if cls_def:
                for m in cls_def.members:
                    if isinstance(m.decl, ConstructorDef) and len(m.decl.params) == len(node.args):
                        c_param_types = [(p.param_type + "&" if p.is_reference else p.param_type) for p in m.decl.params]
                        clean_c_types = [p.rstrip("&").strip() for p in c_param_types]
                        if clean_c_types == arg_types:
                            best_ctor_params = c_param_types
                            break

            ctor_mangled = self.mangle_function(node.class_name, best_ctor_params, class_name=node.class_name, is_constructor=True)
            call_args = [f"ptr {ptr}"] + [f"{t} {v}" for v, t in args_evaluated]
            self.code.append(f"  call void @{ctor_mangled}({', '.join(call_args)})")

            if cls_def and self._has_destructor(cls_def):
                if self.destructors_to_call:
                    self.destructors_to_call[-1].append((ptr, node.class_name))
        elif isinstance(node, DeleteStatement):
            ptr_val, _ = self.visit_expression(node.expr)
            if isinstance(node.expr, Identifier):
                raw_t = self.get_raw_type(node.expr.name)
                clean_cls = raw_t.rstrip("*")
                if clean_cls in self.classes:
                    cls_def = self.classes[clean_cls]
                    if self._has_destructor(cls_def):
                        dtor_mangled = self.mangle_function(clean_cls, [], class_name=clean_cls, is_destructor=True)
                        self.code.append(f"  call void @{dtor_mangled}(ptr {ptr_val})")
            self.code.append(f"  call void @free(ptr {ptr_val})")
        elif isinstance(node, ArrayDeclaration):
            pt = self._get_llvm_type(node.var_type)
            size = node.size if node.size else 1
            arr_t = f"[{size} x {pt}]"
            ptr = self.get_reg()
            self.code.append(f"  {ptr} = alloca {arr_t}")
            self.env[-1][node.name] = (ptr, arr_t)
            self.raw_type_env[-1][node.name] = f"{node.var_type}[]"
            self.is_ref_env[-1][node.name] = False
            if node.elements:
                for i, el in enumerate(node.elements):
                    val, t = self.visit_expression(el)
                    val = self._convert_llvm_type(val, t, pt)
                    elem_ptr = self.get_reg()
                    self.code.append(f"  {elem_ptr} = getelementptr {arr_t}, ptr {ptr}, i32 0, i32 {i}")
                    self.code.append(f"  store {pt} {val}, ptr {elem_ptr}")
        elif isinstance(node, StructDeclaration):
            t = f"%struct.{node.struct_name}"
            ptr = self.get_reg()
            self.code.append(f"  {ptr} = alloca {t}")
            self.env[-1][node.name] = (ptr, t)
            self.raw_type_env[-1][node.name] = f"struct {node.struct_name}"
            self.is_ref_env[-1][node.name] = False
        elif isinstance(node, ExpressionStatement):
            self.visit_expression(node.expr)
        elif isinstance(node, ReturnStatement):
            for scope in reversed(self.destructors_to_call):
                for obj_ptr, cls_name in reversed(scope):
                    cls_def = self.classes.get(cls_name)
                    if cls_def and self._has_destructor(cls_def):
                        dtor_mangled = self.mangle_function(cls_name, [], class_name=cls_name, is_destructor=True)
                        self.code.append(f"  call void @{dtor_mangled}(ptr {obj_ptr})")
                scope.clear()
            if node.expr:
                val, t = self.visit_expression(node.expr)
                if self.current_function:
                    expected_t = self._get_llvm_type(self.current_function.return_type)
                    if expected_t != "void" and expected_t != t:
                        val = self._convert_llvm_type(val, t, expected_t)
                        t = expected_t
                self.code.append(f"  ret {t} {val}")
            else:
                self.code.append("  ret void")
        elif isinstance(node, IfStatement):
            cond_val, t = self.visit_expression(node.condition)
            if t != "i1":
                cmp_reg = self.get_reg()
                self.code.append(f"  {cmp_reg} = icmp ne {t} {cond_val}, 0")
                cond_val = cmp_reg

            then_label = self.get_label()
            else_label = self.get_label()
            merge_label = self.get_label()

            if node.else_branch:
                self.code.append(f"  br i1 {cond_val}, label %{then_label}, label %{else_label}")
            else:
                self.code.append(f"  br i1 {cond_val}, label %{then_label}, label %{merge_label}")

            self.code.append(f"{then_label}:")
            self.visit_statement(node.then_branch)
            if not self._is_terminated():
                self.code.append(f"  br label %{merge_label}")

            if node.else_branch:
                self.code.append(f"{else_label}:")
                self.visit_statement(node.else_branch)
                if not self._is_terminated():
                    self.code.append(f"  br label %{merge_label}")

            self.code.append(f"{merge_label}:")
        elif isinstance(node, WhileStatement):
            cond_label = self.get_label()
            body_label = self.get_label()
            end_label = self.get_label()

            self.loop_stack.append((end_label, cond_label))
            self.code.append(f"  br label %{cond_label}")
            self.code.append(f"{cond_label}:")
            cond_val, t = self.visit_expression(node.condition)
            if t != "i1":
                cmp_reg = self.get_reg()
                self.code.append(f"  {cmp_reg} = icmp ne {t} {cond_val}, 0")
                cond_val = cmp_reg
            self.code.append(f"  br i1 {cond_val}, label %{body_label}, label %{end_label}")

            self.code.append(f"{body_label}:")
            self.visit_statement(node.body)
            if not self._is_terminated():
                self.code.append(f"  br label %{cond_label}")

            self.code.append(f"{end_label}:")
            self.loop_stack.pop()
        elif isinstance(node, DoWhileStatement):
            body_label = self.get_label()
            cond_label = self.get_label()
            end_label = self.get_label()

            self.loop_stack.append((end_label, cond_label))
            self.code.append(f"  br label %{body_label}")
            self.code.append(f"{body_label}:")
            self.visit_statement(node.body)
            if not self._is_terminated():
                self.code.append(f"  br label %{cond_label}")

            self.code.append(f"{cond_label}:")
            cond_val, t = self.visit_expression(node.condition)
            if t != "i1":
                cmp_reg = self.get_reg()
                self.code.append(f"  {cmp_reg} = icmp ne {t} {cond_val}, 0")
                cond_val = cmp_reg
            self.code.append(f"  br i1 {cond_val}, label %{body_label}, label %{end_label}")

            self.code.append(f"{end_label}:")
            self.loop_stack.pop()
        elif isinstance(node, ForStatement):
            cond_label = self.get_label()
            body_label = self.get_label()
            update_label = self.get_label()
            end_label = self.get_label()

            self.push_env()
            if node.init:
                self.visit_statement(node.init)

            self.loop_stack.append((end_label, update_label))
            self.code.append(f"  br label %{cond_label}")

            self.code.append(f"{cond_label}:")
            if node.condition:
                cond_val, t = self.visit_expression(node.condition)
                if t != "i1":
                    cmp_reg = self.get_reg()
                    self.code.append(f"  {cmp_reg} = icmp ne {t} {cond_val}, 0")
                    cond_val = cmp_reg
                self.code.append(f"  br i1 {cond_val}, label %{body_label}, label %{end_label}")
            else:
                self.code.append(f"  br label %{body_label}")

            self.code.append(f"{body_label}:")
            self.visit_statement(node.body)
            if not self._is_terminated():
                self.code.append(f"  br label %{update_label}")

            self.code.append(f"{update_label}:")
            if node.update:
                self.visit_expression(node.update)
            if not self._is_terminated():
                self.code.append(f"  br label %{cond_label}")

            self.code.append(f"{end_label}:")
            self.loop_stack.pop()
            self.pop_env()
        elif isinstance(node, BreakStatement):
            if self.loop_stack:
                self.code.append(f"  br label %{self.loop_stack[-1][0]}")
        elif isinstance(node, ContinueStatement):
            if self.loop_stack:
                self.code.append(f"  br label %{self.loop_stack[-1][1]}")
        elif isinstance(node, SwitchStatement):
            val, t = self.visit_expression(node.expr)
            end_label = self.get_label()
            default_label = end_label

            self.loop_stack.append((end_label, ""))

            for case in node.cases:
                if not case.value:
                    default_label = f"L_switch_def_{self.label_count}"
                    self.label_count += 1

            switch_reg = self.get_reg() if t != "i32" else val
            if t != "i32":
                self.code.append(f"  {switch_reg} = sext {t} {val} to i32")

            case_labels = []
            for case in node.cases:
                if case.value:
                    c_val, _ = self.visit_expression(case.value)
                    case_labels.append((c_val, f"L_switch_case_{self.label_count}"))
                    self.label_count += 1
                else:
                    case_labels.append((None, default_label))

            self.code.append(f"  switch i32 {switch_reg}, label %{default_label} [")
            for case in case_labels:
                if case[0] is not None:
                    self.code.append(f"    i32 {case[0]}, label %{case[1]}")
            self.code.append("  ]")

            for i, case in enumerate(node.cases):
                l = case_labels[i][1]
                self.code.append(f"{l}:")
                for stmt in case.statements:
                    self.visit_statement(stmt)

            self.code.append(f"{end_label}:")
            self.loop_stack.pop()
        elif isinstance(node, RangeForStatement):
            arr_res = self.resolve(node.iterable.name) if isinstance(node.iterable, Identifier) else None
            size = 10
            elem_llvm_t = self._get_llvm_type(node.var_type)
            arr_t = f"[{size} x {elem_llvm_t}]"
            arr_ptr = None
            if arr_res:
                arr_ptr, resolved_t = arr_res
                if resolved_t.startswith("[") and " x " in resolved_t:
                    arr_t = resolved_t
                    try:
                        size = int(resolved_t[1:].split(" x ")[0])
                        elem_llvm_t = resolved_t.split(" x ")[1].rstrip("]")
                    except Exception:
                        pass
            if not arr_ptr:
                arr_ptr, _ = self.visit_expression(node.iterable)

            idx_ptr = self.get_reg()
            self.code.append(f"  {idx_ptr} = alloca i32")
            self.code.append(f"  store i32 0, ptr {idx_ptr}")

            cond_label = self.get_label()
            body_label = self.get_label()
            update_label = self.get_label()
            end_label = self.get_label()

            self.loop_stack.append((end_label, update_label))
            self.code.append(f"  br label %{cond_label}")

            self.code.append(f"{cond_label}:")
            curr_idx = self.get_reg()
            self.code.append(f"  {curr_idx} = load i32, ptr {idx_ptr}")
            cond_reg = self.get_reg()
            self.code.append(f"  {cond_reg} = icmp slt i32 {curr_idx}, {size}")
            self.code.append(f"  br i1 {cond_reg}, label %{body_label}, label %{end_label}")

            self.code.append(f"{body_label}:")
            self.push_env()

            elem_ptr = self.get_reg()
            self.code.append(f"  {elem_ptr} = getelementptr {arr_t}, ptr {arr_ptr}, i32 0, i32 {curr_idx}")
            elem_val = self.get_reg()
            self.code.append(f"  {elem_val} = load {elem_llvm_t}, ptr {elem_ptr}")

            var_ptr = self.get_reg()
            self.code.append(f"  {var_ptr} = alloca {elem_llvm_t}")
            self.code.append(f"  store {elem_llvm_t} {elem_val}, ptr {var_ptr}")
            self.env[-1][node.var_name] = (var_ptr, elem_llvm_t)
            self.raw_type_env[-1][node.var_name] = node.var_type
            self.is_ref_env[-1][node.var_name] = False

            self.visit_statement(node.body)
            self.pop_env()
            self.code.append(f"  br label %{update_label}")

            self.code.append(f"{update_label}:")
            curr_idx2 = self.get_reg()
            self.code.append(f"  {curr_idx2} = load i32, ptr {idx_ptr}")
            next_idx = self.get_reg()
            self.code.append(f"  {next_idx} = add i32 {curr_idx2}, 1")
            self.code.append(f"  store i32 {next_idx}, ptr {idx_ptr}")
            self.code.append(f"  br label %{cond_label}")

            self.code.append(f"{end_label}:")
            self.loop_stack.pop()
        elif isinstance(node, TryCatchStatement):
            catch_label = self.get_label()
            end_label = self.get_label()
            old_catch = self.current_catch_label
            self.current_catch_label = catch_label

            self.push_env()
            for stmt in node.try_block.statements:
                self.visit_statement(stmt)
            self.pop_env()

            last_inst = self.code[-1].strip() if self.code else ""
            if not (last_inst.startswith("br ") or last_inst.startswith("ret ")):
                self.code.append(f"  br label %{end_label}")

            self.current_catch_label = old_catch
            self.code.append(f"{catch_label}:")
            self.code.append("  store i1 0, ptr @__cxx_exception_active")

            for clause in node.catch_clauses:
                self.push_env()
                if clause.param_name:
                    pt = self._get_llvm_type(clause.param_type) if clause.param_type != "..." else "i32"
                    p_ptr = self.get_reg()
                    self.code.append(f"  {p_ptr} = alloca {pt}")
                    val_reg = self.get_reg()
                    self.code.append(f"  {val_reg} = load i32, ptr @__cxx_exception_val")
                    if pt == "i32":
                        self.code.append(f"  store i32 {val_reg}, ptr {p_ptr}")
                    else:
                        conv = self.get_reg()
                        self.code.append(f"  {conv} = trunc i32 {val_reg} to {pt}")
                        self.code.append(f"  store {pt} {conv}, ptr {p_ptr}")
                    self.env[-1][clause.param_name] = (p_ptr, pt)
                    self.raw_type_env[-1][clause.param_name] = clause.param_type
                    self.is_ref_env[-1][clause.param_name] = False

                for stmt in clause.body.statements:
                    self.visit_statement(stmt)
                self.pop_env()
                last_inst = self.code[-1].strip() if self.code else ""
                if not (last_inst.startswith("br ") or last_inst.startswith("ret ")):
                    self.code.append(f"  br label %{end_label}")

            self.code.append(f"{end_label}:")
        elif isinstance(node, ThrowStatement):
            val, t = self.visit_expression(node.expr)
            if t != "i32":
                conv = self.get_reg()
                if t in ["i8", "i1"]:
                    self.code.append(f"  {conv} = zext {t} {val} to i32")
                elif t == "double":
                    self.code.append(f"  {conv} = fptosi double {val} to i32")
                else:
                    self.code.append(f"  {conv} = ptrtoint {t} {val} to i32")
                val = conv
            self.code.append(f"  store i32 {val}, ptr @__cxx_exception_val")
            self.code.append("  store i1 1, ptr @__cxx_exception_active")
            if self.current_catch_label:
                self.code.append(f"  br label %{self.current_catch_label}")
            else:
                self.code.append("  call void @exit(i32 1)")
                self.code.append("  unreachable")
            dummy = self.get_label()
            self.code.append(f"{dummy}:")

    def visit_expression(self, node: Expression) -> Tuple[str, str]:
        if isinstance(node, IntLiteral):
            return str(node.value), "i32"
        elif isinstance(node, FloatLiteral):
            return str(node.value), "double"
        elif isinstance(node, BoolLiteral):
            return ("1" if node.value else "0"), "i1"
        elif isinstance(node, StringLiteral):
            name = self.strings[node.value]
            return f"@{name}", "ptr"
        elif isinstance(node, ThisExpr):
            this_ptr, _ = self.resolve("this")
            val = self.get_reg()
            self.code.append(f"  {val} = load ptr, ptr {this_ptr}")
            return val, "ptr"
        elif isinstance(node, ScopeResolution):
            full_name = f"{node.namespace}::{node.member}"
            if full_name in self.global_constants:
                return self.global_constants[full_name]
            resolved = self.resolve(full_name)
            if resolved:
                ptr, t = resolved
                val = self.get_reg()
                self.code.append(f"  {val} = load {t}, ptr {ptr}")
                return val, t
            return "0", "i32"
        elif isinstance(node, NewExpr):
            clean_type = node.type_name.replace("const ", "").strip()
            if clean_type in self.classes:
                size_ptr = self.get_reg()
                self.code.append(f"  {size_ptr} = getelementptr %class.{clean_type}, ptr null, i32 1")
                size_val = self.get_reg()
                self.code.append(f"  {size_val} = ptrtoint ptr {size_ptr} to i64")
                mem_ptr = self.get_reg()
                self.code.append(f"  {mem_ptr} = call ptr @malloc(i64 {size_val})")

                args_evaluated = []
                arg_types = []
                for a in node.args:
                    v, t = self.visit_expression(a)
                    args_evaluated.append((v, t))
                    arg_types.append(self._llvm_type_to_raw(t))

                cls_def = self.classes.get(clean_type)
                best_ctor_params = arg_types
                if cls_def:
                    for m in cls_def.members:
                        if isinstance(m.decl, ConstructorDef) and len(m.decl.params) == len(node.args):
                            c_param_types = [(p.param_type + "&" if p.is_reference else p.param_type) for p in m.decl.params]
                            clean_c_types = [p.rstrip("&").strip() for p in c_param_types]
                            if clean_c_types == arg_types:
                                best_ctor_params = c_param_types
                                break

                ctor_mangled = self.mangle_function(clean_type, best_ctor_params, class_name=clean_type, is_constructor=True)
                call_args = [f"ptr {mem_ptr}"] + [f"{t} {v}" for v, t in args_evaluated]
                self.code.append(f"  call void @{ctor_mangled}({', '.join(call_args)})")
                return mem_ptr, "ptr"
            else:
                size_map = {"int": 4, "float": 4, "double": 8, "char": 1, "bool": 1}
                sz = size_map.get(clean_type, 4)
                mem_ptr = self.get_reg()
                self.code.append(f"  {mem_ptr} = call ptr @malloc(i64 {sz})")
                if node.args:
                    val, t = self.visit_expression(node.args[0])
                    self.code.append(f"  store {t} {val}, ptr {mem_ptr}")
                return mem_ptr, "ptr"
        elif isinstance(node, Identifier):
            if node.name in self.global_constants:
                return self.global_constants[node.name]
            resolved = self.resolve(node.name)
            if resolved:
                ptr, t = resolved
                if self.is_ref(node.name):
                    actual_ptr = self.get_reg()
                    self.code.append(f"  {actual_ptr} = load ptr, ptr {ptr}")
                    raw_t = self.get_raw_type(node.name).rstrip("&").strip()
                    val_t = self._get_llvm_type(raw_t)
                    val = self.get_reg()
                    self.code.append(f"  {val} = load {val_t}, ptr {actual_ptr}")
                    return val, val_t
                elif t.startswith("["):
                    elem_ptr = self.get_reg()
                    self.code.append(f"  {elem_ptr} = getelementptr {t}, ptr {ptr}, i32 0, i32 0")
                    return elem_ptr, "ptr"
                else:
                    val = self.get_reg()
                    self.code.append(f"  {val} = load {t}, ptr {ptr}")
                    return val, t
            if self.current_class and node.name in self.class_field_indices.get(self.current_class.name, {}):
                idx = self.class_field_indices[self.current_class.name][node.name]
                raw_f_type = self.class_field_types[self.current_class.name][node.name]
                f_type = self._get_llvm_type(raw_f_type)
                this_ptr, _ = self.resolve("this")
                this_val = self.get_reg()
                self.code.append(f"  {this_val} = load ptr, ptr {this_ptr}")
                elem_ptr = self.get_reg()
                self.code.append(f"  {elem_ptr} = getelementptr %class.{self.current_class.name}, ptr {this_val}, i32 0, i32 {idx}")
                val = self.get_reg()
                self.code.append(f"  {val} = load {f_type}, ptr {elem_ptr}")
                return val, f_type
        elif isinstance(node, MethodCall):
            return self._generate_method_call(node)
        elif isinstance(node, ArrowAccess):
            return self._generate_arrow_access(node)
        elif isinstance(node, ArrowAssignment):
            return self._generate_arrow_assignment(node)
        elif isinstance(node, ArrayAccess):
            ptr, t = self.resolve(node.name)
            idx_val, _ = self.visit_expression(node.index)
            elem_ptr = self.get_reg()
            if t.startswith("["):
                base_type = t.split("x")[1].strip(" ]")
                self.code.append(f"  {elem_ptr} = getelementptr {t}, ptr {ptr}, i32 0, i32 {idx_val}")
            else:
                base_type = "i32"
            val = self.get_reg()
            self.code.append(f"  {val} = load {base_type}, ptr {elem_ptr}")
            return val, base_type
        elif isinstance(node, MemberAccess):
            return self._generate_member_access(node)
        elif isinstance(node, MemberAssignment):
            return self._generate_member_assignment(node)
        elif isinstance(node, AddressOf):
            if isinstance(node.expr, Identifier):
                resolved = self.resolve(node.expr.name)
                if resolved:
                    ptr, _ = resolved
                    if self.is_ref(node.expr.name):
                        loaded_ptr = self.get_reg()
                        self.code.append(f"  {loaded_ptr} = load ptr, ptr {ptr}")
                        return loaded_ptr, "ptr"
                    return ptr, "ptr"
            elif isinstance(node.expr, ArrayAccess):
                ptr, t = self.resolve(node.expr.name)
                idx_val, _ = self.visit_expression(node.expr.index)
                elem_ptr = self.get_reg()
                if t.startswith("["):
                    self.code.append(f"  {elem_ptr} = getelementptr {t}, ptr {ptr}, i32 0, i32 {idx_val}")
                else:
                    elem_ptr = ptr
                return elem_ptr, "ptr"
            elif isinstance(node.expr, Deref):
                return self.visit_expression(node.expr.expr)
            return "null", "ptr"
        elif isinstance(node, Deref):
            ptr_val, _ = self.visit_expression(node.expr)
            pointee_type = "i32"
            if isinstance(node.expr, Identifier):
                raw = self.get_raw_type(node.expr.name)
                if raw.endswith("*"):
                    pointee_type = self._get_llvm_type(raw[:-1].strip())
            val = self.get_reg()
            self.code.append(f"  {val} = load {pointee_type}, ptr {ptr_val}")
            return val, pointee_type
        elif isinstance(node, DerefAssignment):
            ptr_val, _ = self.visit_expression(node.target)
            val, v_t = self.visit_expression(node.expr)
            self.code.append(f"  store {v_t} {val}, ptr {ptr_val}")
            return val, v_t
        elif isinstance(node, Assignment):
            val, t = self.visit_expression(node.expr)
            resolved = self.resolve(node.target)
            if resolved:
                ptr, var_t = resolved
                if self.is_ref(node.target):
                    actual_ptr = self.get_reg()
                    self.code.append(f"  {actual_ptr} = load ptr, ptr {ptr}")
                    raw_t = self.get_raw_type(node.target).rstrip("&").strip()
                    ref_val_t = self._get_llvm_type(raw_t)
                    val = self._convert_llvm_type(val, t, ref_val_t)
                    self.code.append(f"  store {ref_val_t} {val}, ptr {actual_ptr}")
                    return val, ref_val_t
                else:
                    val = self._convert_llvm_type(val, t, var_t)
                    self.code.append(f"  store {var_t} {val}, ptr {ptr}")
                    return val, var_t
            if self.current_class and node.target in self.class_field_indices.get(self.current_class.name, {}):
                idx = self.class_field_indices[self.current_class.name][node.target]
                raw_f_type = self.class_field_types[self.current_class.name][node.target]
                f_type = self._get_llvm_type(raw_f_type)
                this_ptr, _ = self.resolve("this")
                this_val = self.get_reg()
                self.code.append(f"  {this_val} = load ptr, ptr {this_ptr}")
                elem_ptr = self.get_reg()
                self.code.append(f"  {elem_ptr} = getelementptr %class.{self.current_class.name}, ptr {this_val}, i32 0, i32 {idx}")
                val = self._convert_llvm_type(val, t, f_type)
                self.code.append(f"  store {f_type} {val}, ptr {elem_ptr}")
                return val, f_type
            return val, t
        elif isinstance(node, ArrayAssignment):
            ptr, t = self.resolve(node.name)
            idx_val, _ = self.visit_expression(node.index)
            val, v_t = self.visit_expression(node.expr)
            elem_ptr = self.get_reg()
            if t.startswith("["):
                base_type = t.split("x")[1].strip(" ]")
                val = self._convert_llvm_type(val, v_t, base_type)
                self.code.append(f"  {elem_ptr} = getelementptr {t}, ptr {ptr}, i32 0, i32 {idx_val}")
                self.code.append(f"  store {base_type} {val}, ptr {elem_ptr}")
                return val, base_type
            return val, v_t
        elif isinstance(node, CastExpression):
            val, t = self.visit_expression(node.expr)
            target_t = self._get_llvm_type(node.target_type)
            res = self.get_reg()
            if t in ["i32", "i8", "i1"] and target_t == "double":
                self.code.append(f"  {res} = sitofp {t} {val} to double")
            elif t == "double" and target_t in ["i32", "i8", "i1"]:
                self.code.append(f"  {res} = fptosi double {val} to {target_t}")
            elif t == "i32" and target_t in ["i8", "i1"]:
                self.code.append(f"  {res} = trunc i32 {val} to {target_t}")
            elif t in ["i8", "i1"] and target_t == "i32":
                self.code.append(f"  {res} = sext {t} {val} to i32")
            else:
                return val, t
            return res, target_t
        elif isinstance(node, TernaryOp):
            cond_val, t = self.visit_expression(node.condition)
            if t != "i1":
                cmp_reg = self.get_reg()
                self.code.append(f"  {cmp_reg} = icmp ne {t} {cond_val}, 0")
                cond_val = cmp_reg

            true_l = self.get_label()
            false_l = self.get_label()
            merge_l = self.get_label()

            self.code.append(f"  br i1 {cond_val}, label %{true_l}, label %{false_l}")
            self.code.append(f"{true_l}:")
            t_val, t_t = self.visit_expression(node.true_expr)
            self.code.append(f"  br label %{merge_l}")

            self.code.append(f"{false_l}:")
            f_val, f_t = self.visit_expression(node.false_expr)
            self.code.append(f"  br label %{merge_l}")

            self.code.append(f"{merge_l}:")
            res = self.get_reg()
            self.code.append(f"  {res} = phi {t_t} [ {t_val}, %{true_l} ], [ {f_val}, %{false_l} ]")
            return res, t_t
        elif isinstance(node, BinaryOp):
            return self._generate_binary_op(node)
        elif isinstance(node, UnaryOp):
            val, t = self.visit_expression(node.expr)
            res = self.get_reg()
            if node.op == "-":
                if t == "double":
                    self.code.append(f"  {res} = fsub double 0.0, {val}")
                else:
                    self.code.append(f"  {res} = sub {t} 0, {val}")
                return res, t
            elif node.op == "!":
                if t != "i1":
                    cmp_reg = self.get_reg()
                    self.code.append(f"  {cmp_reg} = icmp eq {t} {val}, 0")
                    return cmp_reg, "i1"
                self.code.append(f"  {res} = xor i1 {val}, 1")
                return res, "i1"
        elif isinstance(node, (PreIncrement, PreDecrement)):
            ptr, t = self.resolve(node.target.name)
            val = self.get_reg()
            self.code.append(f"  {val} = load {t}, ptr {ptr}")
            new_val = self.get_reg()
            op = "add" if isinstance(node, PreIncrement) else "sub"
            self.code.append(f"  {new_val} = {op} {t} {val}, 1")
            self.code.append(f"  store {t} {new_val}, ptr {ptr}")
            return new_val, t
        elif isinstance(node, (PostIncrement, PostDecrement)):
            ptr, t = self.resolve(node.target.name)
            val = self.get_reg()
            self.code.append(f"  {val} = load {t}, ptr {ptr}")
            new_val = self.get_reg()
            op = "add" if isinstance(node, PostIncrement) else "sub"
            self.code.append(f"  {new_val} = {op} {t} {val}, 1")
            self.code.append(f"  store {t} {new_val}, ptr {ptr}")
            return val, t
        elif isinstance(node, FunctionCall):
            return self._generate_function_call(node)
        elif isinstance(node, LambdaExpr):
            self.lambda_count += 1
            lambda_name = f"__lambda_{self.lambda_count}"
            ret_type = self._get_llvm_type(node.return_type) if node.return_type else "i32"

            saved_code = self.code
            saved_reg = self.reg_count
            saved_label = self.label_count
            saved_env = self.env
            saved_raw = self.raw_type_env
            saved_ref = self.is_ref_env
            saved_current_fn = self.current_function

            self.code = []
            self.reg_count = 1
            self.label_count = 1
            self.env = []
            self.raw_type_env = []
            self.is_ref_env = []

            params = []
            for p in node.params:
                pt = "ptr" if (p.is_reference or p.param_type.endswith("&")) else self._get_llvm_type(p.param_type)
                params.append(f"{pt} %{p.name}_arg")

            self.code.append(f"define {ret_type} @{lambda_name}({', '.join(params)}) {{")
            self.code.append("entry:")
            self.push_env()

            for p in node.params:
                if p.is_reference or p.param_type.endswith("&"):
                    ptr = self.get_reg()
                    self.code.append(f"  {ptr} = alloca ptr")
                    self.code.append(f"  store ptr %{p.name}_arg, ptr {ptr}")
                    self.env[-1][p.name] = (ptr, "ptr")
                    self.raw_type_env[-1][p.name] = p.param_type + "&"
                    self.is_ref_env[-1][p.name] = True
                else:
                    pt = self._get_llvm_type(p.param_type)
                    ptr = self.get_reg()
                    self.code.append(f"  {ptr} = alloca {pt}")
                    self.code.append(f"  store {pt} %{p.name}_arg, ptr {ptr}")
                    self.env[-1][p.name] = (ptr, pt)
                    self.raw_type_env[-1][p.name] = p.param_type
                    self.is_ref_env[-1][p.name] = False

            self.visit_block_content(node.body)

            self.pop_env()
            last_inst = self.code[-1].strip() if self.code else ""
            if not (last_inst.startswith("ret ") or last_inst == "ret void"):
                if ret_type == "void":
                    self.code.append("  ret void")
                elif ret_type == "i32":
                    self.code.append("  ret i32 0")
                elif ret_type == "i8":
                    self.code.append("  ret i8 0")
                elif ret_type == "i1":
                    self.code.append("  ret i1 0")
                elif ret_type == "ptr":
                    self.code.append("  ret ptr null")
                else:
                    self.code.append("  ret double 0.0")

            self.code.append("}")
            self.code.append("")
            lambda_body = self.code

            self.code = lambda_body + saved_code
            self.reg_count = saved_reg
            self.label_count = saved_label
            self.env = saved_env
            self.raw_type_env = saved_raw
            self.is_ref_env = saved_ref
            self.current_function = saved_current_fn

            param_types = [(p.param_type + "&" if p.is_reference else p.param_type) for p in node.params]
            self.functions[lambda_name] = ret_type
            self.func_signatures.append({
                "name": lambda_name,
                "mangled_name": lambda_name,
                "return_type": ret_type,
                "param_types": param_types,
                "is_method": False,
                "class_name": None
            })

            return f"@{lambda_name}", "ptr"
        return "0", "i32"

    def _generate_method_call(self, node: MethodCall) -> Tuple[str, str]:
        if node.is_arrow:
            this_val, _ = self.visit_expression(node.object_expr)
            this_ptr = this_val
            if isinstance(node.object_expr, ThisExpr):
                class_name = self.current_class.name
            elif isinstance(node.object_expr, Identifier):
                raw = self.get_raw_type(node.object_expr.name)
                class_name = raw.rstrip("*&").strip()
            else:
                class_name = ""
        else:
            if isinstance(node.object_expr, Identifier):
                resolved = self.resolve(node.object_expr.name)
                this_ptr, _ = resolved
                if self.is_ref(node.object_expr.name):
                    actual_ptr = self.get_reg()
                    self.code.append(f"  {actual_ptr} = load ptr, ptr {this_ptr}")
                    this_ptr = actual_ptr
                raw = self.get_raw_type(node.object_expr.name)
                class_name = raw.rstrip("&").strip()
            else:
                this_val, t = self.visit_expression(node.object_expr)
                temp = self.get_reg()
                self.code.append(f"  {temp} = alloca {t}")
                self.code.append(f"  store {t} {this_val}, ptr {temp}")
                this_ptr = temp
                class_name = t.replace("%class.", "")

        args_evaluated = []
        arg_types = []
        for a in node.args:
            v, t = self.visit_expression(a)
            args_evaluated.append((v, t))
            arg_types.append(self._llvm_type_to_raw(t))

        if class_name in ["string", "std::string"]:
            str_ptr = self.get_reg()
            self.code.append(f"  {str_ptr} = load ptr, ptr {this_ptr}")
            if node.method_name in ["length", "size"]:
                len_64 = self.get_reg()
                self.code.append(f"  {len_64} = call i64 @strlen(ptr {str_ptr})")
                len_32 = self.get_reg()
                self.code.append(f"  {len_32} = trunc i64 {len_64} to i32")
                return len_32, "i32"
            elif node.method_name == "c_str":
                return str_ptr, "ptr"

        cls_def = self.classes.get(class_name)
        ret_type = "i32"
        best_method = None
        method_owner_class = class_name
        curr = cls_def
        while curr:
            for m in curr.members:
                if isinstance(m.decl, FunctionDef) and m.decl.name == node.method_name:
                    if len(m.decl.params) == len(node.args):
                        m_param_types = [(p.param_type + "&" if p.is_reference else p.param_type) for p in m.decl.params]
                        clean_m_types = [p.rstrip("&").strip() for p in m_param_types]
                        if clean_m_types == arg_types:
                            best_method = (m.decl, m_param_types)
                            method_owner_class = curr.name
                            break
                        if best_method is None:
                            best_method = (m.decl, m_param_types)
                            method_owner_class = curr.name
            if best_method:
                break
            if getattr(curr, "base_class", None):
                curr = self.classes.get(curr.base_class)
            else:
                break

        # Virtual method dispatch
        if class_name in self.class_vtable_indices and node.method_name in self.class_vtable_indices[class_name]:
            vtable_idx = self.class_vtable_indices[class_name][node.method_name]
            v_entry = self.class_vtable_entries[class_name][vtable_idx]
            ret_type = v_entry[2]
            vptr_gep = self.get_reg()
            self.code.append(f"  {vptr_gep} = getelementptr %class.{class_name}, ptr {this_ptr}, i32 0, i32 0")
            vtable_ptr = self.get_reg()
            self.code.append(f"  {vtable_ptr} = load ptr, ptr {vptr_gep}")
            fn_slot = self.get_reg()
            self.code.append(f"  {fn_slot} = getelementptr ptr, ptr {vtable_ptr}, i32 {vtable_idx}")
            fn_ptr = self.get_reg()
            self.code.append(f"  {fn_ptr} = load ptr, ptr {fn_slot}")
            call_args = [f"ptr {this_ptr}"] + [f"{t} {v}" for v, t in args_evaluated]
            if ret_type == "void":
                self.code.append(f"  call void {fn_ptr}({', '.join(call_args)})")
                return "", "void"
            else:
                res = self.get_reg()
                self.code.append(f"  {res} = call {ret_type} {fn_ptr}({', '.join(call_args)})")
                return res, ret_type

        if best_method:
            m_decl, m_param_types = best_method
            ret_type = self._get_llvm_type(m_decl.return_type)
            mangled_name = self.mangle_function(node.method_name, m_param_types, class_name=method_owner_class)
        else:
            mangled_name = self.mangle_function(node.method_name, arg_types, class_name=class_name)

        call_args = [f"ptr {this_ptr}"] + [f"{t} {v}" for v, t in args_evaluated]
        if ret_type == "void":
            self.code.append(f"  call void @{mangled_name}({', '.join(call_args)})")
            return "", "void"
        else:
            res = self.get_reg()
            self.code.append(f"  {res} = call {ret_type} @{mangled_name}({', '.join(call_args)})")
            return res, ret_type

    def _generate_arrow_access(self, node: ArrowAccess) -> Tuple[str, str]:
        if isinstance(node.object_expr, ThisExpr):
            this_ptr, _ = self.resolve("this")
            this_val = self.get_reg()
            self.code.append(f"  {this_val} = load ptr, ptr {this_ptr}")
            class_name = self.current_class.name
        elif isinstance(node.object_expr, Identifier):
            this_val, _ = self.visit_expression(node.object_expr)
            raw = self.get_raw_type(node.object_expr.name)
            class_name = raw.rstrip("*&").strip()
        else:
            this_val, _ = self.visit_expression(node.object_expr)
            class_name = ""

        idx = self.class_field_indices[class_name][node.member]
        raw_f_type = self.class_field_types[class_name][node.member]
        f_type = self._get_llvm_type(raw_f_type)
        elem_ptr = self.get_reg()
        self.code.append(f"  {elem_ptr} = getelementptr %class.{class_name}, ptr {this_val}, i32 0, i32 {idx}")
        val = self.get_reg()
        self.code.append(f"  {val} = load {f_type}, ptr {elem_ptr}")
        return val, f_type

    def _generate_arrow_assignment(self, node: ArrowAssignment) -> Tuple[str, str]:
        if isinstance(node.object_expr, ThisExpr):
            this_ptr, _ = self.resolve("this")
            this_val = self.get_reg()
            self.code.append(f"  {this_val} = load ptr, ptr {this_ptr}")
            class_name = self.current_class.name
        elif isinstance(node.object_expr, Identifier):
            this_val, _ = self.visit_expression(node.object_expr)
            raw = self.get_raw_type(node.object_expr.name)
            class_name = raw.rstrip("*&").strip()
        else:
            this_val, _ = self.visit_expression(node.object_expr)
            class_name = ""

        idx = self.class_field_indices[class_name][node.member]
        raw_f_type = self.class_field_types[class_name][node.member]
        f_type = self._get_llvm_type(raw_f_type)
        val, _ = self.visit_expression(node.expr)
        elem_ptr = self.get_reg()
        self.code.append(f"  {elem_ptr} = getelementptr %class.{class_name}, ptr {this_val}, i32 0, i32 {idx}")
        self.code.append(f"  store {f_type} {val}, ptr {elem_ptr}")
        return val, f_type

    def _generate_member_access(self, node: MemberAccess) -> Tuple[str, str]:
        ptr, t = self.resolve(node.object_expr.name)
        if t.startswith("%class."):
            class_name = t.replace("%class.", "")
            idx = self.class_field_indices[class_name][node.member]
            raw_f_type = self.class_field_types[class_name][node.member]
            f_type = self._get_llvm_type(raw_f_type)
            elem_ptr = self.get_reg()
            self.code.append(f"  {elem_ptr} = getelementptr {t}, ptr {ptr}, i32 0, i32 {idx}")
            val = self.get_reg()
            self.code.append(f"  {val} = load {f_type}, ptr {elem_ptr}")
            return val, f_type
        else:
            struct_name = t.replace("%struct.", "")
            struct_def = self.structs[struct_name]
            idx = 0
            for i, m in enumerate(struct_def.members):
                if m.name == node.member:
                    idx = i
                    break
            base_type = self._get_llvm_type(struct_def.members[idx].param_type)
            elem_ptr = self.get_reg()
            self.code.append(f"  {elem_ptr} = getelementptr {t}, ptr {ptr}, i32 0, i32 {idx}")
            val = self.get_reg()
            self.code.append(f"  {val} = load {base_type}, ptr {elem_ptr}")
            return val, base_type

    def _generate_member_assignment(self, node: MemberAssignment) -> Tuple[str, str]:
        ptr, t = self.resolve(node.object_expr.name)
        val, _ = self.visit_expression(node.expr)
        if t.startswith("%class."):
            class_name = t.replace("%class.", "")
            idx = self.class_field_indices[class_name][node.member]
            raw_f_type = self.class_field_types[class_name][node.member]
            f_type = self._get_llvm_type(raw_f_type)
            elem_ptr = self.get_reg()
            self.code.append(f"  {elem_ptr} = getelementptr {t}, ptr {ptr}, i32 0, i32 {idx}")
            self.code.append(f"  store {f_type} {val}, ptr {elem_ptr}")
            return val, f_type
        else:
            struct_name = t.replace("%struct.", "")
            struct_def = self.structs[struct_name]
            idx = 0
            for i, m in enumerate(struct_def.members):
                if m.name == node.member:
                    idx = i
                    break
            base_type = self._get_llvm_type(struct_def.members[idx].param_type)
            elem_ptr = self.get_reg()
            self.code.append(f"  {elem_ptr} = getelementptr {t}, ptr {ptr}, i32 0, i32 {idx}")
            self.code.append(f"  store {base_type} {val}, ptr {elem_ptr}")
            return val, base_type

    def _generate_binary_op(self, node: BinaryOp) -> Tuple[str, str]:
        if node.op == "<<" and self._is_cout_expr(node.left):
            if not (isinstance(node.left, Identifier) and node.left.name in ["cout", "std::cout"]) and not (isinstance(node.left, ScopeResolution) and node.left.namespace == "std" and node.left.member == "cout"):
                self.visit_expression(node.left)
            is_endl = (isinstance(node.right, Identifier) and node.right.name in ["endl", "std::endl"]) or (isinstance(node.right, ScopeResolution) and node.right.namespace == "std" and node.right.member == "endl")
            if is_endl:
                res = self.get_reg()
                self.code.append(f"  {res} = call i32 (ptr, ...) @printf(ptr @.fmt_endl)")
                return "@_ZN3std4coutE", "ptr"
            r_val, r_type = self.visit_expression(node.right)
            res = self.get_reg()
            if r_type == "i32":
                self.code.append(f"  {res} = call i32 (ptr, ...) @printf(ptr @.fmt_d, i32 {r_val})")
            elif r_type == "double":
                self.code.append(f"  {res} = call i32 (ptr, ...) @printf(ptr @.fmt_f, double {r_val})")
            elif r_type == "i8":
                conv = self.get_reg()
                self.code.append(f"  {conv} = sext i8 {r_val} to i32")
                res = self.get_reg()
                self.code.append(f"  {res} = call i32 (ptr, ...) @printf(ptr @.fmt_c, i32 {conv})")
            elif r_type == "i1":
                conv = self.get_reg()
                self.code.append(f"  {conv} = zext i1 {r_val} to i32")
                res = self.get_reg()
                self.code.append(f"  {res} = call i32 (ptr, ...) @printf(ptr @.fmt_d, i32 {conv})")
            elif r_type == "ptr":
                self.code.append(f"  {res} = call i32 (ptr, ...) @printf(ptr @.fmt_s, ptr {r_val})")
            return "@_ZN3std4coutE", "ptr"

        if node.op == ">>" and self._is_cin_expr(node.left):
            if not (isinstance(node.left, Identifier) and node.left.name in ["cin", "std::cin"]) and not (isinstance(node.left, ScopeResolution) and node.left.namespace == "std" and node.left.member == "cin"):
                self.visit_expression(node.left)
            if isinstance(node.right, Identifier):
                res_target = self.resolve(node.right.name)
                if res_target:
                    target_ptr, target_t = res_target
                    if self.is_ref(node.right.name):
                        loaded_p = self.get_reg()
                        self.code.append(f"  {loaded_p} = load ptr, ptr {target_ptr}")
                        target_ptr = loaded_p
                    res = self.get_reg()
                    if target_t == "i32":
                        self.code.append(f"  {res} = call i32 (ptr, ...) @scanf(ptr @.fmt_in_d, ptr {target_ptr})")
                    elif target_t == "double":
                        self.code.append(f"  {res} = call i32 (ptr, ...) @scanf(ptr @.fmt_in_f, ptr {target_ptr})")
                    elif target_t == "i8":
                        self.code.append(f"  {res} = call i32 (ptr, ...) @scanf(ptr @.fmt_in_c, ptr {target_ptr})")
            return "@_ZN3std3cinE", "ptr"

        if isinstance(node.left, Identifier):
            raw_l = self.get_raw_type(node.left.name).rstrip("&").strip()
            if raw_l in self.classes:
                cls_def = self.classes[raw_l]
                op_name = f"operator{node.op}"
                for m in cls_def.members:
                    if isinstance(m.decl, FunctionDef) and m.decl.name == op_name:
                        this_ptr, _ = self.resolve(node.left.name)
                        r_val, r_t = self.visit_expression(node.right)
                        arg_raw = self._llvm_type_to_raw(r_t)
                        mangled_name = self.mangle_function(op_name, [arg_raw], class_name=raw_l)
                        ret_lt = self._get_llvm_type(m.decl.return_type)
                        res = self.get_reg()
                        self.code.append(f"  {res} = call {ret_lt} @{mangled_name}(ptr {this_ptr}, {r_t} {r_val})")
                        return res, ret_lt

        l_val, l_type = self.visit_expression(node.left)
        r_val, r_type = self.visit_expression(node.right)

        if l_type == "double" and r_type in ["i32", "i8", "i1"]:
            conv = self.get_reg()
            self.code.append(f"  {conv} = sitofp {r_type} {r_val} to double")
            r_val, r_type = conv, "double"
        elif r_type == "double" and l_type in ["i32", "i8", "i1"]:
            conv = self.get_reg()
            self.code.append(f"  {conv} = sitofp {l_type} {l_val} to double")
            l_val, l_type = conv, "double"

        res = self.get_reg()
        if l_type in ["i32", "i8", "i1"]:
            op_map = {'+': 'add', '-': 'sub', '*': 'mul', '/': 'sdiv', '%': 'srem', '<<': 'shl', '>>': 'ashr', '&': 'and', '|': 'or', '^': 'xor'}
            cmp_map = {'==': 'eq', '!=': 'ne', '<': 'slt', '<=': 'sle', '>': 'sgt', '>=': 'sge'}
            if node.op in op_map:
                self.code.append(f"  {res} = {op_map[node.op]} {l_type} {l_val}, {r_val}")
                return res, l_type
            elif node.op in cmp_map:
                self.code.append(f"  {res} = icmp {cmp_map[node.op]} {l_type} {l_val}, {r_val}")
                return res, "i1"
            elif node.op in ["&&", "||"]:
                return self._generate_logical(node.op, l_val, r_val, l_type, r_type)
        elif l_type == "double":
            op_map = {'+': 'fadd', '-': 'fsub', '*': 'fmul', '/': 'fdiv'}
            cmp_map = {'==': 'oeq', '!=': 'one', '<': 'olt', '<=': 'ole', '>': 'ogt', '>=': 'oge'}
            if node.op in op_map:
                self.code.append(f"  {res} = {op_map[node.op]} double {l_val}, {r_val}")
                return res, "double"
            elif node.op in cmp_map:
                self.code.append(f"  {res} = fcmp {cmp_map[node.op]} double {l_val}, {r_val}")
                return res, "i1"
        elif l_type == "ptr":
            if node.op in ['==', '!=']:
                cmp_code = 'eq' if node.op == '==' else 'ne'
                self.code.append(f"  {res} = icmp {cmp_code} ptr {l_val}, {r_val}")
                return res, "i1"
        return "0", "i32"

    def _generate_function_call(self, node: FunctionCall) -> Tuple[str, str]:
        if node.name in ["string", "std::string"]:
            if node.args:
                val, t = self.visit_expression(node.args[0])
                return self._convert_llvm_type(val, t, "ptr"), "ptr"
            return "null", "ptr"
        if node.name == "printf":
            args = []
            for a in node.args:
                val, t = self.visit_expression(a)
                args.append(f"{t} {val}")
            res = self.get_reg()
            self.code.append(f"  {res} = call i32 (ptr, ...) @printf({', '.join(args)})")
            return res, "i32"
        elif node.name == "malloc":
            val, t = self.visit_expression(node.args[0])
            res = self.get_reg()
            self.code.append(f"  {res} = call ptr @malloc({t} {val})")
            return res, "ptr"
        elif node.name == "free":
            val, t = self.visit_expression(node.args[0])
            self.code.append(f"  call void @free({t} {val})")
            return "", "void"

        # Check if node.name is a local variable holding a function pointer (e.g., lambda)
        for scope in reversed(self.env):
            if node.name in scope:
                var_ptr, var_t = scope[node.name]
                args_evaluated = []
                for a in node.args:
                    val, t = self.visit_expression(a)
                    args_evaluated.append(f"{t} {val}")
                fn_reg = self.get_reg()
                self.code.append(f"  {fn_reg} = load ptr, ptr {var_ptr}")
                res = self.get_reg()
                self.code.append(f"  {res} = call i32 {fn_reg}({', '.join(args_evaluated)})")
                return res, "i32"

        candidates = [node.name] + [f"{ns}::{node.name}" for ns in self.active_namespaces]
        matching_sigs = []
        for cand in candidates:
            for sig in self.func_signatures:
                if sig["name"] == cand and len(sig["param_types"]) == len(node.args):
                    matching_sigs.append(sig)

        # Pre-evaluate arguments
        args_evaluated = []
        arg_raw_types = []
        for a in node.args:
            val, t = self.visit_expression(a)
            args_evaluated.append((val, t))
            arg_raw_types.append(self._llvm_type_to_raw(t))

        # Find best signature by matching types
        best_sig = None
        for sig in matching_sigs:
            clean_sig_types = [p.rstrip("&").strip() for p in sig["param_types"]]
            if clean_sig_types == arg_raw_types:
                best_sig = sig
                break
        if not best_sig and matching_sigs:
            best_sig = matching_sigs[0]

        call_args = []
        for i, a in enumerate(node.args):
            is_ref_param = (best_sig and (best_sig["param_types"][i].endswith("&") or best_sig["param_types"][i] == "ptr"))
            if is_ref_param and isinstance(a, Identifier):
                p_resolved = self.resolve(a.name)
                if p_resolved:
                    ptr, _ = p_resolved
                    if self.is_ref(a.name):
                        loaded_p = self.get_reg()
                        self.code.append(f"  {loaded_p} = load ptr, ptr {ptr}")
                        ptr = loaded_p
                    call_args.append(f"ptr {ptr}")
                    continue
            val, t = args_evaluated[i]
            if best_sig:
                expected_t = self._get_llvm_type(best_sig["param_types"][i])
                if expected_t == "double" and t in ["i32", "i8", "i1"]:
                    conv = self.get_reg()
                    self.code.append(f"  {conv} = sitofp {t} {val} to double")
                    val, t = conv, "double"
                elif expected_t == "i32" and t == "i1":
                    conv = self.get_reg()
                    self.code.append(f"  {conv} = zext i1 {val} to i32")
                    val, t = conv, "i32"
            call_args.append(f"{t} {val}")

        if best_sig:
            mangled_name = best_sig["mangled_name"]
            ret_t = best_sig["return_type"]
        else:
            mangled_name = self.mangle_function(node.name, arg_raw_types)
            ret_t = self.functions.get(mangled_name, self.functions.get(node.name, "i32"))

        call_prefix = "tail call" if (getattr(node, "is_tail_call", False) or (self.opt_level >= 2 and getattr(node, "is_tail_call", False))) else "call"
        if ret_t == "void":
            self.code.append(f"  {call_prefix} void @{mangled_name}({', '.join(call_args)})")
            return "", "void"
        else:
            res = self.get_reg()
            self.code.append(f"  {res} = {call_prefix} {ret_t} @{mangled_name}({', '.join(call_args)})")
            return res, ret_t

    def _generate_logical(self, op: str, l_val: str, r_val: str, l_t: str, r_t: str) -> Tuple[str, str]:
        res = self.get_reg()
        if op == "&&":
            self.code.append(f"  {res} = and i1 {l_val}, {r_val}")
        else:
            self.code.append(f"  {res} = or i1 {l_val}, {r_val}")
        return res, "i1"
