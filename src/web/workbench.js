/* ==============================================================================
   C++ COMPILER WORKBENCH — CLIENT-SIDE SCRIPT
   ==============================================================================
   Handles:
     1. Code Editor (Line numbers, tab handling, auto-closing pairs, cursor tracking)
     2. Output & Diagnostics Pane (Rust-style diagnostic cards, error catalogue modal)
     3. Interactive Terminal (ANSI color rendering, CLI execution, fix -i wizard)
     4. Preset template loading
   ============================================================================== */

(function () {
    'use strict';

    // --- DOM Elements ---
    const editor = document.getElementById('code-editor');
    const lineNumbers = document.getElementById('line-numbers');
    const cursorInfo = document.getElementById('editor-cursor');
    const lengthInfo = document.getElementById('editor-length');

    const btnRun = document.getElementById('btn-run');
    const btnCheck = document.getElementById('btn-check');
    const btnFix = document.getElementById('btn-fix');
    const btnWizard = document.getElementById('btn-wizard');
    const btnFormat = document.getElementById('btn-format');
    const btnClear = document.getElementById('btn-clear');
    const presetSelect = document.getElementById('preset-select');

    const diagnosticsBody = document.getElementById('diagnostics-body');
    const badgeErrors = document.getElementById('badge-errors');
    const badgeWarnings = document.getElementById('badge-warnings');
    const badgeOk = document.getElementById('badge-ok');

    const terminalOutput = document.getElementById('terminal-output');
    const terminalInput = document.getElementById('terminal-input');
    const terminalPrompt = document.getElementById('terminal-prompt');
    const terminalIndicator = document.getElementById('terminal-status-indicator');
    const terminalStatusText = document.getElementById('terminal-status-text');
    const btnClearTerminal = document.getElementById('btn-clear-terminal');

    const modalBackdrop = document.getElementById('modal-backdrop');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    const modalClose = document.getElementById('modal-close');

    // --- State ---
    let isInteractive = false;
    let commandHistory = [];
    let historyIdx = -1;
    let presetsCache = {};
    let interactiveSessionId = null;
    let diagnosticsTimer = null;
    let diagnosticsController = null;
    let diagnosticsSequence = 0;
    let nativeRunEnabled = false;
    const workbenchToken = document.querySelector('meta[name="workbench-token"]')?.content || '';

    function apiFetch(url, options = {}) {
        const headers = new Headers(options.headers || {});
        headers.set('X-Workbench-Token', workbenchToken);
        return fetch(url, { ...options, headers });
    }

    // ==============================================================================
    // 1. ANSI ESCAPE CODE TO HTML COLORIZER
    // ==============================================================================

    function ansiToHtml(text) {
        if (!text) return '';

        // Escape HTML characters first
        let escaped = text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');

        // State stack for ANSI styles
        let openSpans = 0;

        // ANSI code mapping
        const codeMap = {
            '0': 'reset',
            '1': 'ansi-bold',
            '2': 'ansi-dim',
            '31': 'ansi-red',
            '32': 'ansi-green',
            '33': 'ansi-yellow',
            '34': 'ansi-blue',
            '35': 'ansi-magenta',
            '36': 'ansi-cyan',
            '37': 'ansi-white',
            '90': 'ansi-dim',
            '91': 'ansi-bright-red',
            '92': 'ansi-bright-green',
            '93': 'ansi-bright-yellow',
            '94': 'ansi-blue',
            '95': 'ansi-magenta',
            '96': 'ansi-bright-cyan',
            '97': 'ansi-white',
        };

        // Regex matching ANSI escape sequences: \033[...m or \x1b[...m
        const ansiRegex = /(?:\u001b|\x1b|\[0m)?\[([0-9;]+)m/g;

        escaped = escaped.replace(ansiRegex, (match, codesStr) => {
            const codes = codesStr.split(';');
            let result = '';

            for (const c of codes) {
                if (c === '0') {
                    // Reset: close all open spans
                    while (openSpans > 0) {
                        result += '</span>';
                        openSpans--;
                    }
                } else if (codeMap[c]) {
                    result += `<span class="${codeMap[c]}">`;
                    openSpans++;
                }
            }
            return result;
        });

        // Close any lingering spans
        while (openSpans > 0) {
            escaped += '</span>';
            openSpans--;
        }

        return escaped;
    }

    function appendTerminalOutput(text, isCommand = false) {
        if (!text && !isCommand) return;
        const html = ansiToHtml(text);
        terminalOutput.innerHTML += html;
        terminalOutput.scrollTop = terminalOutput.scrollHeight;
    }

    // ==============================================================================
    // 2. CODE EDITOR HANDLING
    // ==============================================================================

    function updateLineNumbers() {
        const lines = editor.value.split('\n').length;
        let numbers = '';
        for (let i = 1; i <= lines; i++) {
            numbers += i + '\n';
        }
        lineNumbers.textContent = numbers;
        lengthInfo.textContent = `${editor.value.length} chars`;
    }

    function updateCursorInfo() {
        const pos = editor.selectionStart;
        const textBefore = editor.value.substring(0, pos);
        const lines = textBefore.split('\n');
        const curLine = lines.length;
        const curCol = lines[lines.length - 1].length + 1;
        cursorInfo.textContent = `Ln ${curLine}, Col ${curCol}`;
    }

    // Synchronize scrolling between textarea and gutter
    editor.addEventListener('scroll', () => {
        lineNumbers.scrollTop = editor.scrollTop;
    });

    editor.addEventListener('input', () => {
        updateLineNumbers();
        updateCursorInfo();
        clearTimeout(diagnosticsTimer);
        diagnosticsTimer = setTimeout(() => fetchDiagnostics(), 300);
    });

    editor.addEventListener('click', updateCursorInfo);
    editor.addEventListener('keyup', updateCursorInfo);

    // Tab key, Auto-closing pairs & Shortcuts
    editor.addEventListener('keydown', (e) => {
        // Tab / Shift+Tab handling
        if (e.key === 'Tab') {
            e.preventDefault();
            const start = editor.selectionStart;
            const end = editor.selectionEnd;

            if (e.shiftKey) {
                // Outdent
                const before = editor.value.substring(0, start);
                const after = editor.value.substring(end);
                // Remove up to 4 spaces before cursor
                const lastLineStart = before.lastIndexOf('\n') + 1;
                const currentLine = before.substring(lastLineStart);
                if (currentLine.startsWith('    ')) {
                    editor.value = before.substring(0, lastLineStart) + currentLine.substring(4) + after;
                    editor.selectionStart = editor.selectionEnd = Math.max(lastLineStart, start - 4);
                }
            } else {
                // Indent with 4 spaces
                editor.value = editor.value.substring(0, start) + '    ' + editor.value.substring(end);
                editor.selectionStart = editor.selectionEnd = start + 4;
            }
            updateLineNumbers();
            updateCursorInfo();
            return;
        }

        // Bracket & quote auto-pairing
        const pairs = { '(': ')', '[': ']', '{': '}', '"': '"', "'": "'" };
        if (pairs[e.key]) {
            const start = editor.selectionStart;
            const end = editor.selectionEnd;
            if (start === end) {
                e.preventDefault();
                const closeChar = pairs[e.key];
                editor.value = editor.value.substring(0, start) + e.key + closeChar + editor.value.substring(end);
                editor.selectionStart = editor.selectionEnd = start + 1;
                updateLineNumbers();
                updateCursorInfo();
                return;
            }
        }

        // Hotkeys
        if (e.key === 'F5' || ((e.ctrlKey || e.metaKey) && (e.key === 'r' || e.key === 'R'))) {
            e.preventDefault();
            runTerminalCommand('run');
        } else if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            if (e.shiftKey) {
                // Ctrl+Shift+Enter: Interactive Fix Wizard
                runTerminalCommand('fix -i');
            } else {
                // Ctrl+Enter: Check
                runTerminalCommand('check');
            }
        } else if ((e.ctrlKey || e.metaKey) && e.altKey && (e.key === 'f' || e.key === 'F')) {
            e.preventDefault();
            runFormat();
        }
    });

    // ==============================================================================
    // 3. TERMINAL CONSOLE & INTERACTIVE WIZARD
    // ==============================================================================

    function setTerminalInteractive(interactive, promptText = 'c++ > ') {
        isInteractive = interactive;
        if (interactive) {
            terminalIndicator.classList.add('interactive');
            terminalStatusText.textContent = '(Interactive Fix Wizard)';
            terminalPrompt.textContent = promptText || 'Apply [y/n/e/a/d/q]:';
            terminalInput.placeholder = 'Type y (apply), n (skip), e (explain), a (all), d (diff), q (quit)...';
        } else {
            terminalIndicator.classList.remove('interactive');
            terminalStatusText.textContent = '(Ready)';
            terminalPrompt.textContent = 'c++ >';
            terminalInput.placeholder = 'Type a command (check, fix, fix -i, suggest, explain, fmt, tokens, help)...';
        }
    }

    async function runTerminalCommand(commandStr) {
        commandStr = commandStr.trim();
        if (!commandStr) return;
        const isFixCommand = /^(?:c\+\+\s+)?fix(?:\s|$)/i.test(commandStr);
        if (isFixCommand) {
            btnFix.disabled = true;
            btnFix.setAttribute('aria-busy', 'true');
        }

        // Print command in terminal
        appendTerminalOutput(`\n\x1b[1m\x1b[34mc++ > ${commandStr}\x1b[0m\n`);

        // Handle client-side 'clear' command
        if (commandStr === 'clear' || commandStr === 'cls') {
            terminalOutput.innerHTML = '';
            return;
        }

        try {
            const res = await apiFetch('/api/terminal/command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    command: commandStr,
                    code: editor.value,
                }),
            });

            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
            appendTerminalOutput(data.output);
            interactiveSessionId = data.session_id || null;

            if (data.updated_code !== null && data.updated_code !== undefined) {
                editor.value = data.updated_code;
                updateLineNumbers();
                updateCursorInfo();
                appendTerminalOutput('\x1b[32m⚡ [workbench] Code in editor updated automatically.\x1b[0m\n');
            }

            setTerminalInteractive(data.is_interactive, data.prompt);

            // Also refresh diagnostics in the Output & Diagnostics pane
            fetchDiagnostics();

        } catch (err) {
            appendTerminalOutput(`\n\x1b[31mError executing command: ${err.message}\x1b[0m\n`);
            setTerminalInteractive(false);
        } finally {
            if (isFixCommand) {
                btnFix.disabled = false;
                btnFix.removeAttribute('aria-busy');
            }
        }
    }

    async function sendTerminalInput(inputStr) {
        // Echo input into terminal
        appendTerminalOutput(`${inputStr}\n`);

        try {
            const res = await apiFetch('/api/terminal/input', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ input: inputStr, session_id: interactiveSessionId }),
            });

            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
            appendTerminalOutput(data.output);

            if (data.updated_code !== null && data.updated_code !== undefined) {
                editor.value = data.updated_code;
                updateLineNumbers();
                updateCursorInfo();
                appendTerminalOutput('\x1b[32m⚡ [workbench] Code in editor updated automatically.\x1b[0m\n');
            }

            setTerminalInteractive(data.is_interactive, data.prompt);

            if (!data.is_interactive) {
                interactiveSessionId = null;
                // Session concluded, refresh diagnostics
                fetchDiagnostics();
            }

        } catch (err) {
            appendTerminalOutput(`\n\x1b[31mError delivering keystroke: ${err.message}\x1b[0m\n`);
            setTerminalInteractive(false);
        }
    }

    // Terminal Input Event Listener
    terminalInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            const val = terminalInput.value.trim();
            terminalInput.value = '';

            if (isInteractive) {
                sendTerminalInput(val || 'y'); // Default Enter to 'y' in wizard
            } else {
                if (val) {
                    commandHistory.push(val);
                    historyIdx = commandHistory.length;
                    runTerminalCommand(val);
                }
            }
        } else if (!isInteractive) {
            // History navigation
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (historyIdx > 0) {
                    historyIdx--;
                    terminalInput.value = commandHistory[historyIdx] || '';
                }
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (historyIdx < commandHistory.length - 1) {
                    historyIdx++;
                    terminalInput.value = commandHistory[historyIdx] || '';
                } else {
                    historyIdx = commandHistory.length;
                    terminalInput.value = '';
                }
            }
        }
    });

    btnClearTerminal.addEventListener('click', () => {
        terminalOutput.innerHTML = '';
    });

    // ==============================================================================
    // 4. OUTPUT & ERROR DIAGNOSTICS PANE
    // ==============================================================================

    async function fetchDiagnostics() {
        const sequence = ++diagnosticsSequence;
        if (diagnosticsController) diagnosticsController.abort();
        diagnosticsController = new AbortController();
        try {
            const res = await apiFetch('/api/diagnostics', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: editor.value }),
                signal: diagnosticsController.signal,
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
            if (sequence !== diagnosticsSequence) return;
            renderDiagnostics(data);
        } catch (err) {
            if (err.name !== 'AbortError') console.error('Failed to fetch diagnostics:', err);
        }
    }

    function renderDiagnostics(data) {
        const errors = data.errors || [];
        const warnings = data.warnings || [];
        const totalIssues = errors.length + warnings.length;

        // Update Header Badges
        if (errors.length > 0) {
            badgeErrors.textContent = `${errors.length} Error${errors.length > 1 ? 's' : ''}`;
            badgeErrors.style.display = 'inline-block';
        } else {
            badgeErrors.style.display = 'none';
        }

        if (warnings.length > 0) {
            badgeWarnings.textContent = `${warnings.length} Warning${warnings.length > 1 ? 's' : ''}`;
            badgeWarnings.style.display = 'inline-block';
        } else {
            badgeWarnings.style.display = 'none';
        }

        if (totalIssues === 0) {
            badgeOk.style.display = 'inline-block';
            badgeOk.textContent = 'Check Passed';
            diagnosticsBody.innerHTML = `
                <div class="empty-state">
                    <span class="empty-state-icon">✅</span>
                    <p><strong>Clean Code! No Errors or Warnings.</strong></p>
                    <p style="font-size: 11px;">Your C++ source code passed syntax and semantic checks with 0 diagnostics.</p>
                </div>
            `;
            return;
        }

        badgeOk.style.display = 'none';
        diagnosticsBody.innerHTML = '';

        // Combine all diagnostics
        const allDiags = [...errors, ...warnings];

        for (const item of allDiags) {
            const card = document.createElement('div');
            const isError = item.severity === 'error';
            card.className = `diag-card ${isError ? 'error' : 'warning'}`;

            card.innerHTML = `
                <div class="diag-header">
                    <div class="diag-tag-group">
                        <span class="diag-code">${item.code}</span>
                        <span class="diag-location">main.cpp:${item.line}:${item.col}</span>
                    </div>
                </div>
                <div class="diag-message">${escapeHtml(item.message)}</div>
                ${item.snippet ? `<pre class="diag-snippet">${escapeHtml(item.snippet)}</pre>` : ''}
                ${item.help ? `
                    <div class="diag-help">
                        <span class="diag-help-icon">💡</span>
                        <span>${escapeHtml(item.help)}</span>
                    </div>
                ` : ''}
                <div class="diag-actions">
                    <button class="btn btn-sm btn-secondary btn-goto" data-line="${item.line}" data-col="${item.col}">
                        Jump to line ${item.line}
                    </button>
                    <button class="btn btn-sm btn-secondary btn-explain" data-code="${item.code}">
                        View in Catalogue
                    </button>
                </div>
            `;

            diagnosticsBody.appendChild(card);
        }

        // Attach card button handlers
        diagnosticsBody.querySelectorAll('.btn-goto').forEach(btn => {
            btn.addEventListener('click', () => {
                const line = parseInt(btn.getAttribute('data-line'), 10);
                const col = parseInt(btn.getAttribute('data-col'), 10);
                gotoLineCol(line, col);
            });
        });

        diagnosticsBody.querySelectorAll('.btn-explain').forEach(btn => {
            btn.addEventListener('click', () => {
                const code = btn.getAttribute('data-code');
                openCatalogueModal(code);
            });
        });
    }

    function gotoLineCol(line, col) {
        const lines = editor.value.split('\n');
        let pos = 0;
        for (let i = 0; i < line - 1 && i < lines.length; i++) {
            pos += lines[i].length + 1; // +1 for newline
        }
        pos += Math.max(0, col - 1);
        editor.focus();
        editor.setSelectionRange(pos, pos);
        updateCursorInfo();
    }

    function escapeHtml(text) {
        if (!text) return '';
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    // ==============================================================================
    // 5. PEDAGOGICAL ERROR CATALOGUE MODAL
    // ==============================================================================

    async function openCatalogueModal(code) {
        try {
            const res = await apiFetch(`/api/errors?code=${encodeURIComponent(code)}`);
            const data = await res.json();
            const entry = data.entry;

            if (!entry) {
                modalTitle.textContent = `Diagnostic Information: ${code}`;
                modalBody.innerHTML = `<p>No detailed catalogue entry found for error code <code>${code}</code>.</p>`;
            } else {
                modalTitle.textContent = `${code}: ${entry.title || 'Error Details'}`;
                modalBody.innerHTML = `
                    <div>
                        <h4 style="color: var(--text-primary); margin-bottom: 6px;">Description</h4>
                        <p>${escapeHtml(entry.description || 'No description available.')}</p>
                    </div>
                    ${entry.cause ? `
                        <div>
                            <h4 style="color: var(--text-primary); margin-bottom: 6px;">Common Cause</h4>
                            <p>${escapeHtml(entry.cause)}</p>
                        </div>
                    ` : ''}
                    ${(entry.bad_code || entry.good_code) ? `
                        <div>
                            <h4 style="color: var(--text-primary); margin-bottom: 8px;">Code Comparison</h4>
                            <div class="modal-code-comparison">
                                <div>
                                    <span style="font-size: 11px; font-weight: bold; color: var(--color-error);">Erroneous Code:</span>
                                    <div class="code-box code-box-bad">${escapeHtml(entry.bad_code || '')}</div>
                                </div>
                                <div>
                                    <span style="font-size: 11px; font-weight: bold; color: var(--color-success);">Recommended Fix:</span>
                                    <div class="code-box code-box-good">${escapeHtml(entry.good_code || '')}</div>
                                </div>
                            </div>
                        </div>
                    ` : ''}
                `;
            }

            modalBackdrop.classList.add('active');
        } catch (err) {
            console.error('Error opening catalogue modal:', err);
        }
    }

    modalClose.addEventListener('click', () => {
        modalBackdrop.classList.remove('active');
    });

    modalBackdrop.addEventListener('click', (e) => {
        if (e.target === modalBackdrop) {
            modalBackdrop.classList.remove('active');
        }
    });

    // ==============================================================================
    // 6. FORMATTER & PRESET ACTION BUTTONS
    // ==============================================================================

    async function runFormat() {
        try {
            appendTerminalOutput('\n\x1b[1m\x1b[34mc++ > fmt\x1b[0m\n');
            const res = await apiFetch('/api/format', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: editor.value }),
            });
            const data = await res.json();
            if (data.formatted_code) {
                editor.value = data.formatted_code;
                updateLineNumbers();
                updateCursorInfo();
                appendTerminalOutput('\x1b[32mFormatted and updated source in editor.\x1b[0m\n');
            } else if (data.error) {
                appendTerminalOutput(`\x1b[31mFormat Error: ${data.error}\x1b[0m\n`);
            }
        } catch (err) {
            appendTerminalOutput(`\x1b[31mFormat failed: ${err.message}\x1b[0m\n`);
        }
    }

    btnRun.addEventListener('click', () => runTerminalCommand('run'));
    btnCheck.addEventListener('click', () => runTerminalCommand('check'));
    btnFix.addEventListener('click', () => runTerminalCommand('fix'));
    btnWizard.addEventListener('click', () => runTerminalCommand('fix -i'));
    btnFormat.addEventListener('click', runFormat);

    btnClear.addEventListener('click', () => {
        if (confirm('Clear editor content?')) {
            editor.value = '';
            updateLineNumbers();
            updateCursorInfo();
            diagnosticsBody.innerHTML = `
                <div class="empty-state">
                    <span class="empty-state-icon">📝</span>
                    <p><strong>Editor is empty.</strong></p>
                    <p>Type C++ code or pick a preset from the toolbar above.</p>
                </div>
            `;
            badgeErrors.style.display = 'none';
            badgeWarnings.style.display = 'none';
            badgeOk.style.display = 'inline-block';
            badgeOk.textContent = 'Ready';
        }
    });

    // Presets Dropdown
    async function loadPresets() {
        try {
            const res = await apiFetch('/api/presets');
            presetsCache = await res.json();

            // Populate preset select dropdown grouped by category
            const currentVal = presetSelect.value;
            presetSelect.innerHTML = '<option value="">-- Select a showcase preset --</option>';

            const categories = {};
            for (const [key, preset] of Object.entries(presetsCache)) {
                const cat = preset.category || 'General Presets';
                if (!categories[cat]) {
                    categories[cat] = [];
                }
                categories[cat].push({ key, preset });
            }

            let index = 1;
            for (const [catName, items] of Object.entries(categories)) {
                const group = document.createElement('optgroup');
                group.label = catName;
                for (const item of items) {
                    const opt = document.createElement('option');
                    opt.value = item.key;
                    opt.textContent = `${index}. ${item.preset.title}`;
                    group.appendChild(opt);
                    index++;
                }
                presetSelect.appendChild(group);
            }

            if (currentVal && presetsCache[currentVal]) {
                presetSelect.value = currentVal;
            }
        } catch (err) {
            console.error('Failed to load presets:', err);
        }
    }

    presetSelect.addEventListener('change', () => {
        const key = presetSelect.value;
        if (key && presetsCache[key]) {
            editor.value = presetsCache[key].code;
            updateLineNumbers();
            updateCursorInfo();
            appendTerminalOutput(`\n\x1b[36m[preset] Loaded: ${presetsCache[key].title}\x1b[0m\n`);
            runTerminalCommand('check');
        }
    });

    // ==============================================================================
    // 7. INITIALIZATION ON PAGE LOAD
    // ==============================================================================

    async function init() {
        try {
            const capabilityRes = await apiFetch('/api/capabilities');
            const capabilities = await capabilityRes.json();
            nativeRunEnabled = capabilityRes.ok && capabilities.native_run === true;
        } catch (err) {
            nativeRunEnabled = false;
        }
        btnRun.disabled = !nativeRunEnabled;
        btnRun.title = nativeRunEnabled
            ? 'Compile & Run program natively (F5 or Ctrl+R)'
            : 'Native execution is disabled because the workbench is running in safe mode';

        await loadPresets();

        // Print welcome banner in terminal
        const banner = 
`\x1b[1m\x1b[96m================================================================================\x1b[0m
\x1b[1m\x1b[96m  C++ Intelligent Error Correction & Recommendation Workbench (v1.0)\x1b[0m
\x1b[1m\x1b[96m================================================================================\x1b[0m
\x1b[90mPowered by Pure Python Standard Library (Zero External Dependencies)\x1b[0m
Native compilation and execution: ${nativeRunEnabled ? '\x1b[32menabled' : '\x1b[33mdisabled (safe mode)'}\x1b[0m
Type \x1b[1mcheck\x1b[0m, \x1b[1mfix\x1b[0m, \x1b[1mfix -i\x1b[0m, \x1b[1msuggest\x1b[0m, \x1b[1mexplain [code]\x1b[0m, \x1b[1mfmt\x1b[0m, \x1b[1mtokens\x1b[0m, or \x1b[1mhelp\x1b[0m.

`;
        appendTerminalOutput(banner);

        // Fetch initial editor file if server provided one, or load default preset
        try {
            const initialRes = await apiFetch('/api/initial');
            const initialData = await initialRes.json();
            if (initialData.code) {
                editor.value = initialData.code;
            } else if (presetsCache['cross_language']) {
                presetSelect.value = 'cross_language';
                editor.value = presetsCache['cross_language'].code;
            }
        } catch (e) {
            if (presetsCache['cross_language']) {
                editor.value = presetsCache['cross_language'].code;
            }
        }

        updateLineNumbers();
        updateCursorInfo();
        fetchDiagnostics();
    }

    // Run on startup
    window.addEventListener('DOMContentLoaded', init);

})();
