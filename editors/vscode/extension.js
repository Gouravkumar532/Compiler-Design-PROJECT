// C++ Compiler & Diagnostics Language Client Extension for Visual Studio Code
const vscode = require('vscode');
const child_process = require('child_process');
const path = require('path');
const fs = require('fs');

let lspProcess = null;
let diagnosticCollection = null;
let messageBuffer = Buffer.alloc(0);
let nextId = 1;

function activate(context) {
    diagnosticCollection = vscode.languages.createDiagnosticCollection('cpp');
    context.subscriptions.push(diagnosticCollection);

    function startServer() {
        if (lspProcess) {
            return;
        }

        const config = vscode.workspace.getConfiguration('cpp');
        const pythonPath = config.get('pythonPath') || 'python';
        let serverPath = config.get('serverPath');

        if (!serverPath) {
            const workspaceFolders = vscode.workspace.workspaceFolders;
            if (workspaceFolders && workspaceFolders.length > 0) {
                const candidate = path.join(workspaceFolders[0].uri.fsPath, 'main.py');
                if (fs.existsSync(candidate)) {
                    serverPath = candidate;
                }
            }
            if (!serverPath) {
                const parentCandidate = path.resolve(__dirname, '..', '..', 'main.py');
                if (fs.existsSync(parentCandidate)) {
                    serverPath = parentCandidate;
                } else {
                    serverPath = 'main.py';
                }
            }
        }

        try {
            lspProcess = child_process.spawn(pythonPath, [serverPath, 'lsp'], {
                stdio: ['pipe', 'pipe', 'pipe']
            });
        } catch (err) {
            vscode.window.showErrorMessage(`Failed to start C++ LSP server: ${err.message}`);
            return;
        }

        lspProcess.on('error', (err) => {
            vscode.window.showErrorMessage(`C++ LSP server process error: ${err.message}`);
            lspProcess = null;
        });

        lspProcess.on('exit', () => {
            lspProcess = null;
        });

        lspProcess.stdout.on('data', (data) => {
            handleServerData(data);
        });

        // Initialize handshake
        sendRequest('initialize', {
            processId: process.pid,
            rootUri: vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0]
                ? vscode.workspace.workspaceFolders[0].uri.toString()
                : null,
            capabilities: {
                textDocument: {
                    publishDiagnostics: { relatedInformation: true }
                }
            }
        });

        sendNotification('initialized', {});

        // Send open documents
        vscode.workspace.textDocuments.forEach((doc) => {
            if (doc.languageId === 'cpp') {
                sendNotification('textDocument/didOpen', {
                    textDocument: {
                        uri: doc.uri.toString(),
                        languageId: 'cpp',
                        version: doc.version,
                        text: doc.getText()
                    }
                });
            }
        });
    }

    function stopServer() {
        if (!lspProcess) return;
        messageBuffer = Buffer.alloc(0);
        try {
            sendRequest('shutdown', {});
            sendNotification('exit', {});
            setTimeout(() => {
                if (lspProcess) {
                    lspProcess.kill();
                    lspProcess = null;
                }
            }, 1000);
        } catch (e) {
            if (lspProcess) {
                lspProcess.kill();
                lspProcess = null;
            }
        }
    }

    function restartServer() {
        stopServer();
        setTimeout(startServer, 500);
    }

    context.subscriptions.push(vscode.commands.registerCommand('cpp.startServer', startServer));
    context.subscriptions.push(vscode.commands.registerCommand('cpp.stopServer', stopServer));
    context.subscriptions.push(vscode.commands.registerCommand('cpp.restartServer', restartServer));

    context.subscriptions.push(vscode.workspace.onDidOpenTextDocument((doc) => {
        if (doc.languageId === 'cpp' && lspProcess) {
            sendNotification('textDocument/didOpen', {
                textDocument: {
                    uri: doc.uri.toString(),
                    languageId: 'cpp',
                    version: doc.version,
                    text: doc.getText()
                }
            });
        }
    }));

    context.subscriptions.push(vscode.workspace.onDidChangeTextDocument((event) => {
        if (event.document.languageId === 'cpp' && lspProcess) {
            sendNotification('textDocument/didChange', {
                textDocument: {
                    uri: event.document.uri.toString(),
                    version: event.document.version
                },
                contentChanges: [{ text: event.document.getText() }]
            });
        }
    }));

    context.subscriptions.push(vscode.workspace.onDidCloseTextDocument((doc) => {
        if (doc.languageId === 'cpp') {
            diagnosticCollection.delete(doc.uri);
            if (lspProcess) {
                sendNotification('textDocument/didClose', {
                    textDocument: { uri: doc.uri.toString() }
                });
            }
        }
    }));

    // Auto-start server when activated
    startServer();
}

function sendRequest(method, params) {
    if (!lspProcess || !lspProcess.stdin) return;
    const msg = {
        jsonrpc: '2.0',
        id: nextId++,
        method: method,
        params: params
    };
    const body = JSON.stringify(msg);
    const header = `Content-Length: ${Buffer.byteLength(body, 'utf-8')}\r\n\r\n`;
    lspProcess.stdin.write(header + body);
}

function sendNotification(method, params) {
    if (!lspProcess || !lspProcess.stdin) return;
    const msg = {
        jsonrpc: '2.0',
        method: method,
        params: params
    };
    const body = JSON.stringify(msg);
    const header = `Content-Length: ${Buffer.byteLength(body, 'utf-8')}\r\n\r\n`;
    lspProcess.stdin.write(header + body);
}

function handleServerData(chunk) {
    const chunkBuf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk, 'utf-8');
    messageBuffer = Buffer.concat([messageBuffer, chunkBuf]);
    const headerDelimiter = Buffer.from('\r\n\r\n');

    while (true) {
        const headerEnd = messageBuffer.indexOf(headerDelimiter);
        if (headerEnd === -1) break;

        const headerText = messageBuffer.subarray(0, headerEnd).toString('ascii');
        const match = headerText.match(/Content-Length:\s*(\d+)/i);
        if (!match) {
            messageBuffer = messageBuffer.subarray(headerEnd + 4);
            continue;
        }

        const length = parseInt(match[1], 10);
        const bodyStart = headerEnd + 4;
        if (messageBuffer.length < bodyStart + length) {
            break;
        }

        const bodyBytes = messageBuffer.subarray(bodyStart, bodyStart + length);
        messageBuffer = messageBuffer.subarray(bodyStart + length);

        try {
            const bodyText = bodyBytes.toString('utf-8');
            const parsed = JSON.parse(bodyText);
            handleLspMessage(parsed);
        } catch (e) {
            // Ignore parse errors from malformed bodies
        }
    }
}

function handleLspMessage(msg) {
    if (msg.method === 'textDocument/publishDiagnostics' && msg.params) {
        const { uri, diagnostics } = msg.params;
        const targetUri = vscode.Uri.parse(uri);
        const vsDiagnostics = (diagnostics || []).map((d) => {
            const startLine = d.range && d.range.start ? d.range.start.line : 0;
            const startChar = d.range && d.range.start ? d.range.start.character : 0;
            const endLine = d.range && d.range.end ? d.range.end.line : startLine;
            const endChar = d.range && d.range.end ? d.range.end.character : startChar + 1;

            let severity = vscode.DiagnosticSeverity.Error;
            if (d.severity === 2) severity = vscode.DiagnosticSeverity.Warning;
            else if (d.severity === 3) severity = vscode.DiagnosticSeverity.Information;
            else if (d.severity === 4) severity = vscode.DiagnosticSeverity.Hint;

            const diag = new vscode.Diagnostic(
                new vscode.Range(startLine, startChar, endLine, endChar),
                d.message || '',
                severity
            );
            if (d.code) diag.code = d.code;
            if (d.source) diag.source = d.source;
            return diag;
        });

        diagnosticCollection.set(targetUri, vsDiagnostics);
    }
}

function deactivate() {
    if (lspProcess) {
        try {
            sendRequest('shutdown', {});
            sendNotification('exit', {});
            lspProcess.kill();
        } catch (e) {
            // Ignore on shutdown
        }
        lspProcess = null;
    }
    if (diagnosticCollection) {
        diagnosticCollection.clear();
        diagnosticCollection.dispose();
    }
}

module.exports = {
    activate,
    deactivate
};
