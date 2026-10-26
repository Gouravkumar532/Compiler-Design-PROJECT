# C++ Compiler Design Project

A small C++ analysis and repair tool built in Python. It brings together a preprocessor, lexer, recursive-descent parser, semantic checks, diagnostics, and targeted source-code fixes. It is designed for learning and experimentation, with command-line, web workbench, and VS Code workflows.

The project uses Python's standard library and requires Python 3.10 or newer. No Python packages need to be installed.

## Get started

Clone or download the project, then run commands from its root directory:

to view our project and how it solves the problem access workbench with this command :
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

| Command | What it does |
| --- | --- |
| `check <files...>` | Analyzes one or more C++ source files for syntax and semantic problems, then prints diagnostics. It does not change the files. Use `-v` to show analysis timings, `-Werror` to treat warnings as errors, or `--no-suggest` to turn off repair suggestions. |
| `suggest <files...>` | Analyzes source files and displays proposed repairs as diff summaries alongside diagnostics. It never writes changes to disk. |
| `fix <files...>` | Repairs supported errors. By default, prints the repaired source to the terminal; add `--write` to update the original file, or `--interactive` to review each proposed fix first. Add `--backup` with `--write` to save a `.bak` copy before changing a file. |
| `fmt <files...>` | Formats source code and prints the result. Add `--write` to replace each input file with its formatted version. |
| `tokens <files...>` | Runs the lexer and prints each source token with its type and position. Use this to inspect how the compiler reads the source text. |
| `ast <files...>` | Parses source files and prints the Abstract Syntax Tree (AST), showing the program's structure. Diagnostics are printed if parsing or analysis finds problems. |
| `explain [CODE]` | Explains a diagnostic code with a description and examples, such as `python main.py explain P003`. Without a code, lists all available diagnostic codes. |
| `lsp` | Starts the Language Server Protocol (LSP) server on standard input and output so a compatible editor can request diagnostics and fixes. |
| `workbench [file]` | Starts the browser-based editor and diagnostics workbench. Optionally opens a source file; `--port` changes the server port, `--no-browser` prevents opening a browser automatically, and `--safe-mode` disables native compile and run actions. |
| `bench-repair` | Runs the curated repair benchmark and reports repair performance. Use `--category` to run one category, `--json` for machine-readable results, `--verbose` for case-by-case details, or `--export-report` to write the Markdown report. |
| `test` | Runs the project's automated test suite. Add `-v` to show more detail for each test. |

Examples:

```bash
python main.py explain P003
python main.py workbench demo.cpp --port 9000 --no-browser
python main.py workbench demo.cpp --safe-mode
python main.py bench-repair --export-report
python main.py test
```

What each example does:

- `python main.py explain P003` explains diagnostic code `P003`, which reports a missing semicolon.
- `python main.py workbench demo.cpp --port 9000 --no-browser` opens `demo.cpp` in the workbench, serves it on port `9000`, and leaves browser launching to you.
- `python main.py workbench demo.cpp --safe-mode` opens `demo.cpp` in the workbench with native C++ compile and run actions disabled.
- `python main.py bench-repair --export-report` runs the repair benchmark and writes its results to `benchmarks/REPAIR_ACCURACY_REPORT.md`.
- `python main.py test` runs the project's automated test suite and reports whether the tests pass.

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
- [Repair benchmark report](benchmarks/REPAIR_ACCURACY_REPORT.md)

## Run the tests

```bash
python main.py test
```

Or run them with Python's built-in test runner:

```bash
python -m unittest discover -s tests -p "test_*.py"
```
