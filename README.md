# C++ Compiler Design Project

A small C++ analysis and repair tool built in Python. It brings together a preprocessor, lexer, recursive-descent parser, semantic checks, diagnostics, and targeted source-code fixes. It is designed for learning and experimentation, with command-line, web workbench, and VS Code workflows.

The project uses Python's standard library and requires Python 3.10 or newer. No Python packages need to be installed.

## Get started

Clone or download the project, then run commands from its root directory:

to view our main project view workbench with this command :
```bash
python main.py workbench 
```

Try the main features:

```bash
# Review proposed fixes without changing the file
python main.py suggest demo.cpp

# Apply fixes interactively, or write them directly
python main.py fix demo.cpp --interactive
python main.py fix demo.cpp --write

# Inspect tokens and the parsed syntax tree
python main.py tokens demo.cpp
python main.py ast demo.cpp

# Start the browser workbench
python main.py workbench demo.cpp
```

Run `python main.py --help` for the full command list. Use `python main.py <command> --help` for options for a specific command.

## What it can do

- **Analyze C++ source:** preprocess common directives, tokenize source, parse the supported language subset, and report syntax and semantic diagnostics.
- **Suggest and apply repairs:** propose fixes for missing semicolons and delimiters, malformed expressions, and selected C++ mistakes. Interactive mode lets you review proposed changes; `--write` updates files in place. `--backup` creates a backup before writing.
- **Inspect compiler stages:** print the token stream or a readable representation of the abstract syntax tree.
- **Format and explain:** format source files and look up explanations for diagnostic codes.
- **Use an interactive workbench:** edit source, inspect diagnostics, review fixes, and use the browser interface. Native compile/run support can be disabled with `--safe-mode`.
- **Connect an editor:** the included VS Code extension provides C++ syntax support and connects to the built-in Language Server Protocol server.
- **Measure repair behavior:** run the curated benchmark corpus and optionally export a Markdown report.

The analyzer implements a C++ subset for compiler-design learning; it is not a replacement for a standards-complete compiler. The workbench's optional compile/run action invokes a native C++ compiler available on your system.

## Commands

| Command | Purpose |
| --- | --- |
| `check <files...>` | Analyze source and report diagnostics |
| `suggest <files...>` | Show proposed repairs without writing changes |
| `fix <files...>` | Review or apply repairs (`--interactive`, `--write`, `--backup`) |
| `fmt <files...>` | Format source (`--write` to update files) |
| `tokens <files...>` | Display lexer output |
| `ast <files...>` | Display the parsed syntax tree |
| `explain [CODE]` | Explain one diagnostic code or list available codes |
| `lsp` | Start the language server over standard input/output |
| `workbench [file]` | Launch the browser-based workbench |
| `bench-repair` | Run the repair benchmark suite |
| `test` | Run the automated test suite |

Examples:

```bash
python main.py explain P003
python main.py workbench demo.cpp --port 9000 --no-browser
python main.py workbench demo.cpp --safe-mode
python main.py bench-repair --export-report
python main.py test
```

## Project layout

```text
main.py                 Command-line entry point
src/                    Preprocessor, lexer, parser, analysis, repair, and UI code
src/web/                Browser workbench assets
editors/vscode/         VS Code extension
tests/                  Automated tests
benchmarks/             Repair benchmark corpus and reports
implementations/        Feature design and implementation notes
```

## Documentation

- [Workbench guide](GUI.md)
- [VS Code extension guide](editors/vscode/README.md)
- [Architecture notes](.ai/ARCHITECTURE.md)
- [Repair benchmark report](benchmarks/REPAIR_ACCURACY_REPORT.md)
- [Feature notes](implementations/README.md)

## Run the tests

```bash
python main.py test
```

Or run them with Python's built-in test runner:

```bash
python -m unittest discover -s tests -p "test_*.py"
```
