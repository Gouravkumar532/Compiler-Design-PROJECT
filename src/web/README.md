# 🌐 C++ Compiler Workbench — Web Asset Package

This directory contains the self-contained front-end web assets for the **Interactive C++ Compiler Workbench** (`c++ workbench` / `python main.py workbench`).

## File Manifest

| File | Purpose | MIME Type |
|---|---|---|
| [`index.html`](file:///c:/Users/Omkar%20Joshi/Desktop/COMPILER/Compiler-Design-PROJECT/src/web/index.html) | Semantic 3-pane layout shell with action toolbar, preset selector, and error modal | `text/html; charset=utf-8` |
| [`colors.css`](file:///c:/Users/Omkar%20Joshi/Desktop/COMPILER/Compiler-Design-PROJECT/src/web/colors.css) | Centralized theme variables, color tokens, and diagnostic status colors | `text/css; charset=utf-8` |
| [`workbench.css`](file:///c:/Users/Omkar%20Joshi/Desktop/COMPILER/Compiler-Design-PROJECT/src/web/workbench.css) | Responsive grid layout, card components, buttons, and terminal styling | `text/css; charset=utf-8` |
| [`workbench.js`](file:///c:/Users/Omkar%20Joshi/Desktop/COMPILER/Compiler-Design-PROJECT/src/web/workbench.js) | Reactive state controller, live diagnostics, ANSI terminal parser, and API client | `application/javascript` |

## Architecture & Integration
These files are served directly by `WorkbenchHandler` in [`src/ui_server.py`](file:///c:/Users/Omkar%20Joshi/Desktop/COMPILER/Compiler-Design-PROJECT/src/ui_server.py) with zero external server dependencies.

For complete architectural details, layout schematics, and REST API specifications, see [`GUI.md`](file:///c:/Users/Omkar%20Joshi/Desktop/COMPILER/Compiler-Design-PROJECT/GUI.md) at the repository root.
