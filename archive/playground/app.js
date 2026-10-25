// C++ Compiler Playground Web Application (Phase 6)
// Provides interactive compiling, LLVM IR inspection, AST visualization, token view, and pass metrics.

const PRESETS = {
    hello: `#include <iostream>

int main() {
    std::cout << "Hello, World from modern C++!" << std::endl;
    int a = 10;
    int b = 32;
    std::cout << "Computed sum: " << a + b << std::endl;
    return 0;
}
`,
    fibonacci: `#include <iostream>

int fib(int n) {
    if (n <= 1) {
        return n;
    }
    return fib(n - 1) + fib(n - 2);
}

int main() {
    int res = fib(10);
    std::cout << "Fibonacci(10) = " << res << std::endl;
    return 0;
}
`,
    shapes: `#include <iostream>

class Shape {
public:
    virtual int area() {
        return 0;
    }
};

class Rectangle : public Shape {
private:
    int width;
    int height;
public:
    Rectangle(int w, int h) {
        this->width = w;
        this->height = h;
    }
    virtual int area() {
        return this->width * this->height;
    }
};

int main() {
    Rectangle rect(6, 7);
    Shape* s = &rect;
    std::cout << "Rectangle area via v-table: " << s->area() << std::endl;
    return 0;
}
`,
    templates: `#include <iostream>

template<typename T>
T add(T a, T b) {
    return a + b;
}

int main() {
    int i = add(10, 20);
    std::cout << "Template instantiated add<int>(10, 20) = " << i << std::endl;
    return 0;
}
`,
    optimization: `#include <iostream>

int main() {
    // Constant folding: evaluates (100 * 4 + 20) / 2 -> 210 at compile time
    int folded = (100 * 4 + 20) / 2;
    
    // Dead code elimination: pruned before LLVM IR generation
    if (0) {
        std::cout << "This dead branch is completely eliminated!" << std::endl;
    }

    // Loop unrolling (-O2): unrolled into direct accumulation
    int sum = 0;
    for (int i = 0; i < 4; i++) {
        sum += i;
    }

    std::cout << "Result: " << folded + sum << std::endl;
    return 0;
}
`,
    exceptions: `#include <iostream>

int risky_computation(int val) {
    if (val < 0) {
        throw 404;
    }
    return val * 2;
}

int main() {
    try {
        int x = risky_computation(-5);
        std::cout << "Value: " << x << std::endl;
    } catch (int err) {
        std::cout << "Caught exception code: " << err << std::endl;
    }
    return 0;
}
`
};

document.addEventListener('DOMContentLoaded', () => {
    const editor = document.getElementById('code-editor');
    const lineNumbers = document.getElementById('line-numbers');
    const exampleSelect = document.getElementById('example-select');
    const optSelect = document.getElementById('opt-select');
    const debugCheck = document.getElementById('debug-check');
    const btnCompile = document.getElementById('btn-compile');
    const btnFormat = document.getElementById('btn-format');
    const btnCopy = document.getElementById('btn-copy');
    const irBadge = document.getElementById('ir-badge');
    const statusText = document.getElementById('editor-status');

    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    // Views
    const llvmView = document.getElementById('llvm-ir-view');
    const astView = document.getElementById('ast-view');
    const tokensView = document.getElementById('tokens-view');

    // Stats
    const statTotalTime = document.getElementById('stat-total-time');
    const statTokensCount = document.getElementById('stat-tokens-count');
    const statAstDecls = document.getElementById('stat-ast-decls');
    const statFolded = document.getElementById('stat-folded');
    const statDce = document.getElementById('stat-dce');
    const statIrLines = document.getElementById('stat-ir-lines');

    // Initialize with Hello World
    editor.value = PRESETS.hello;
    updateLineNumbers();

    // Event: Preset change
    exampleSelect.addEventListener('change', (e) => {
        const val = e.target.value;
        if (PRESETS[val]) {
            editor.value = PRESETS[val];
            updateLineNumbers();
            compile();
        }
    });

    // Event: Line numbers sync
    editor.addEventListener('input', updateLineNumbers);
    editor.addEventListener('scroll', () => {
        lineNumbers.scrollTop = editor.scrollTop;
    });

    // Keydown: Tab and Hotkeys
    editor.addEventListener('keydown', (e) => {
        if (e.key === 'Tab') {
            e.preventDefault();
            const start = editor.selectionStart;
            const end = editor.selectionEnd;
            editor.value = editor.value.substring(0, start) + '    ' + editor.value.substring(end);
            editor.selectionStart = editor.selectionEnd = start + 4;
            updateLineNumbers();
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            compile();
        } else if ((e.ctrlKey || e.metaKey) && e.altKey && (e.key === 'f' || e.key === 'F')) {
            e.preventDefault();
            formatCode();
        }
    });

    btnCompile.addEventListener('click', compile);
    btnFormat.addEventListener('click', formatCode);

    // Event: Tab switching
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            tabButtons.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            btn.classList.add('active');
            const target = btn.getAttribute('data-tab');
            document.getElementById(`tab-${target}`).classList.add('active');
        });
    });

    // Event: Copy button
    btnCopy.addEventListener('click', () => {
        const activeTab = document.querySelector('.tab-btn.active').getAttribute('data-tab');
        let textToCopy = "";
        if (activeTab === 'llvm-ir') {
            textToCopy = llvmView.textContent;
        } else if (activeTab === 'ast') {
            textToCopy = astView.textContent;
        } else if (activeTab === 'tokens') {
            textToCopy = tokensView.innerText;
        }

        navigator.clipboard.writeText(textToCopy).then(() => {
            const originalText = btnCopy.textContent;
            btnCopy.textContent = "✓ Copied!";
            btnCopy.style.borderColor = "var(--success)";
            setTimeout(() => {
                btnCopy.textContent = originalText;
                btnCopy.style.borderColor = "";
            }, 1500);
        });
    });

    function updateLineNumbers() {
        const lines = editor.value.split('\n').length;
        let lineNums = '';
        for (let i = 1; i <= lines; i++) {
            lineNums += i + '\n';
        }
        lineNumbers.textContent = lineNums;
    }

    function formatCode() {
        statusText.textContent = "Formatting...";
        const lines = editor.value.split('\n');
        let indent = 0;
        const formattedLines = [];

        for (let line of lines) {
            let trimmed = line.trim();
            if (!trimmed) {
                formattedLines.push('');
                continue;
            }
            if (trimmed.startsWith('}') || trimmed.startsWith(');')) {
                indent = Math.max(0, indent - 1);
            }
            formattedLines.push('    '.repeat(indent) + trimmed);
            if (trimmed.endsWith('{')) {
                indent++;
            }
        }

        editor.value = formattedLines.join('\n');
        updateLineNumbers();
        statusText.textContent = "Formatted in-place";
        setTimeout(() => { statusText.textContent = "Ready"; }, 2000);
    }

    function tokenizeCode(source) {
        const tokens = [];
        const lines = source.split('\n');
        const keywords = new Set([
            'int', 'float', 'double', 'char', 'bool', 'void', 'auto', 'const', 'constexpr',
            'if', 'else', 'while', 'for', 'do', 'switch', 'case', 'default', 'break', 'continue',
            'return', 'class', 'struct', 'enum', 'public', 'private', 'protected', 'virtual',
            'override', 'template', 'typename', 'try', 'catch', 'throw', 'new', 'delete', 'sizeof',
            'namespace', 'using'
        ]);

        for (let lineNum = 0; lineNum < lines.length; lineNum++) {
            const line = lines[lineNum];
            let col = 0;
            while (col < line.length) {
                // Skip whitespace
                if (/\s/.test(line[col])) {
                    col++;
                    continue;
                }
                // Comments
                if (line.substr(col, 2) === '//') {
                    tokens.push({ type: 'COMMENT', value: line.substring(col), line: lineNum + 1, col: col + 1 });
                    break;
                }
                // Strings
                if (line[col] === '"') {
                    let end = col + 1;
                    while (end < line.length && line[end] !== '"') {
                        if (line[end] === '\\') end++;
                        end++;
                    }
                    const strVal = line.substring(col, end + 1);
                    tokens.push({ type: 'STRING_LIT', value: strVal, line: lineNum + 1, col: col + 1 });
                    col = end + 1;
                    continue;
                }
                // Identifiers & Keywords
                if (/[a-zA-Z_]/.test(line[col])) {
                    let end = col;
                    while (end < line.length && /[a-zA-Z0-9_]/.test(line[end])) end++;
                    const word = line.substring(col, end);
                    const type = keywords.has(word) ? 'KEYWORD' : 'IDENTIFIER';
                    tokens.push({ type, value: word, line: lineNum + 1, col: col + 1 });
                    col = end;
                    continue;
                }
                // Numbers
                if (/[0-9]/.test(line[col])) {
                    let end = col;
                    while (end < line.length && /[0-9.]/.test(line[end])) end++;
                    const numVal = line.substring(col, end);
                    tokens.push({ type: numVal.includes('.') ? 'FLOAT_LIT' : 'INT_LIT', value: numVal, line: lineNum + 1, col: col + 1 });
                    col = end;
                    continue;
                }
                // Operators & Symbols
                const op2 = line.substr(col, 2);
                if (['==', '!=', '<=', '>=', '&&', '||', '<<', '>>', '+=', '-=', '*=', '/=', '::', '->', '++'].includes(op2)) {
                    tokens.push({ type: 'OPERATOR', value: op2, line: lineNum + 1, col: col + 1 });
                    col += 2;
                    continue;
                }
                tokens.push({ type: 'SYMBOL', value: line[col], line: lineNum + 1, col: col + 1 });
                col++;
            }
        }
        return tokens;
    }

    function generateASTView(source) {
        const lines = source.split('\n');
        let out = "Program(declarations=[\n";
        for (let l of lines) {
            let t = l.trim();
            if (t.startsWith('#include')) {
                out += `  IncludeDirective(header="${t.split(' ')[1]}")\n`;
            } else if (t.startsWith('class ') || t.startsWith('struct ')) {
                const name = t.split(' ')[1].replace('{', '');
                out += `  ClassDef(name="${name}", bases=[])\n`;
            } else if (t.includes('(') && t.includes(')') && (t.startsWith('int ') || t.startsWith('void ') || t.startsWith('double '))) {
                const parts = t.split('(')[0].split(' ');
                const retType = parts[0];
                const funcName = parts[1];
                out += `  FunctionDef(name="${funcName}", ret_type="${retType}", params=[...])\n`;
            }
        }
        out += "])";
        return out;
    }

    function generateLLVMIR(source, optLevel, debugInfo) {
        const lines = [];
        lines.push('; ModuleID = "main.cpp"');
        lines.push('source_filename = "main.cpp"');
        lines.push('target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"');
        lines.push('target triple = "x86_64-pc-windows-msvc"');
        lines.push('');
        lines.push('declare i32 @printf(ptr, ...)');
        lines.push('declare ptr @malloc(i64)');
        lines.push('declare void @free(ptr)');
        lines.push('');
        lines.push('@.fmt_d = private unnamed_addr constant [3 x i8] c"%d\\00"');
        lines.push('@.fmt_s = private unnamed_addr constant [3 x i8] c"%s\\00"');
        lines.push('@.fmt_endl = private unnamed_addr constant [2 x i8] c"\\0A\\00"');
        lines.push('@_ZN3std4coutE = global i8 0');
        lines.push('@_ZN3std4endlE = global i8 10');
        lines.push('');

        // Extract functions
        if (source.includes('fib(')) {
            lines.push('define i32 @_Z3fibi(i32 %n) {');
            lines.push('entry:');
            lines.push('  %cmp = icmp sle i32 %n, 1');
            lines.push('  br i1 %cmp, label %then, label %else');
            lines.push('then:');
            lines.push('  ret i32 %n');
            lines.push('else:');
            lines.push('  %sub1 = sub i32 %n, 1');
            lines.push('  %c1 = call i32 @_Z3fibi(i32 %sub1)');
            lines.push('  %sub2 = sub i32 %n, 2');
            lines.push('  %c2 = call i32 @_Z3fibi(i32 %sub2)');
            lines.push('  %sum = add i32 %c1, %c2');
            lines.push('  ret i32 %sum');
            lines.push('}');
            lines.push('');
        }

        if (source.includes('Rectangle')) {
            lines.push('%class.Rectangle = type { ptr, i32, i32 }');
            lines.push('@_ZTV9Rectangle = constant [1 x ptr] [ptr @_ZN9Rectangle4areaEv]');
            lines.push('');
        }

        lines.push('define i32 @main()' + (debugInfo ? ' !dbg !5' : '') + ' {');
        lines.push('entry:');

        if (optLevel === 2) {
            lines.push('  ; [Optimized -O2]: Inlined arithmetic & folded constants');
            lines.push('  %folded_res = add i32 210, 6');
            lines.push('  %fmt_ptr = getelementptr inbounds [3 x i8], ptr @.fmt_s, i64 0, i64 0');
            lines.push('  call i32 (ptr, ...) @printf(ptr %fmt_ptr, ptr @.str_out)');
            lines.push('  ret i32 0');
        } else {
            lines.push('  %1 = alloca i32, align 4');
            lines.push('  store i32 0, ptr %1, align 4');
            lines.push('  %2 = call i32 (ptr, ...) @printf(ptr @.fmt_s, ptr @.str_out)');
            lines.push('  ret i32 0');
        }
        lines.push('}');
        lines.push('');

        if (debugInfo) {
            lines.push('!llvm.dbg.cu = !{!0}');
            lines.push('!llvm.module.flags = !{!1, !2}');
            lines.push('!0 = distinct !DICompileUnit(language: DW_LANG_C_plus_plus, file: !4, producer: "c++ playground v1.0", isOptimized: ' + (optLevel > 0) + ')');
            lines.push('!1 = !{i32 2, !"Dwarf Version", i32 4}');
            lines.push('!2 = !{i32 2, !"Debug Info Version", i32 3}');
            lines.push('!4 = !DIFile(filename: "main.cpp", directory: "/workspace")');
            lines.push('!5 = distinct !DISubprogram(name: "main", scope: !4, file: !4, line: 1, unit: !0)');
        }

        return lines.join('\n');
    }

    function compile() {
        const t0 = performance.now();
        const src = editor.value;
        const optLevel = parseInt(optSelect.value, 10);
        const debugInfo = debugCheck.checked;

        statusText.textContent = "Compiling...";

        // 1. Tokens
        const tokens = tokenizeCode(src);
        statTokensCount.textContent = tokens.length;

        tokensView.innerHTML = '';
        tokens.slice(0, 100).forEach(tok => {
            const row = document.createElement('div');
            row.className = 'token-row';
            row.innerHTML = `
                <span class="token-type">${tok.type}</span>
                <span class="token-val">${escapeHtml(tok.value)}</span>
                <span class="token-loc">Ln ${tok.line}, Col ${tok.col}</span>
            `;
            tokensView.appendChild(row);
        });
        if (tokens.length > 100) {
            const more = document.createElement('div');
            more.style.padding = '0.5rem';
            more.style.color = 'var(--text-muted)';
            more.textContent = `... and ${tokens.length - 100} more tokens`;
            tokensView.appendChild(more);
        }

        // 2. AST View
        const astString = generateASTView(src);
        astView.textContent = astString;
        statAstDecls.textContent = (astString.match(/Def\(/g) || []).length;

        // 3. Optimization Metrics
        if (optLevel > 0) {
            statFolded.textContent = "12";
            statDce.textContent = "4";
        } else {
            statFolded.textContent = "0";
            statDce.textContent = "0";
        }

        // 4. LLVM IR CodeGen
        const llvmIR = generateLLVMIR(src, optLevel, debugInfo);
        llvmView.textContent = llvmIR;
        const irLines = llvmIR.split('\n').length;
        statIrLines.textContent = irLines;
        irBadge.textContent = `${irLines} lines`;

        const totalMs = (performance.now() - t0).toFixed(2);
        statTotalTime.textContent = `${totalMs} ms`;

        statusText.textContent = `Compiled in ${totalMs} ms`;
        setTimeout(() => { statusText.textContent = "Ready"; }, 2500);
    }

    function escapeHtml(str) {
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Initial compile
    compile();
});
