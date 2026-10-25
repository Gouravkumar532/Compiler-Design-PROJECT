"""
Interactive Terminal TUI & Patch Review Wizard (Idea 9)

Presents detected syntax, expression, delimiter, and semantic errors in turn,
displays colorized unified diffs and pedagogical explanations, and prompts the
user with single-keystroke commands ([y] Apply, [n] Skip, [e] Explain, [a] All,
[d] Diff, [q] Quit).
"""

import sys
import os
from typing import List, Optional, Callable, Dict, Any, Tuple, Set

from src.errors import Colors, explain_error
from src.patch_model import (
    CodePatch,
    UnifiedDiffRenderer,
    collect_candidate_patches_with_result,
    apply_patches_to_source,
)
from src.paths import canonical_path, same_file
from src.atomic_writer import atomic_write_many

def read_keystroke(prompt_str: str, input_fn: Optional[Callable[[str], str]] = None) -> str:
    """
    Reads a single keystroke cross-platform without requiring Enter if running in a TTY.
    Falls back gracefully to standard line input for pipes, non-TTY, or test mocks.
    """
    if input_fn is not None:
        return input_fn(prompt_str).strip().lower()

    # If stdin is not a TTY (pipe, redirection, CI, test runner), use standard input()
    if not sys.stdin.isatty():
        sys.stdout.write(prompt_str)
        sys.stdout.flush()
        line = sys.stdin.readline()
        if not line:
            raise EOFError
        return line.strip().lower()

    # Windows TTY: msvcrt
    if sys.platform == "win32":
        try:
            import msvcrt
            sys.stdout.write(prompt_str)
            sys.stdout.flush()
            ch = msvcrt.getwch()
            # If special prefix key (arrow keys, function keys), consume second scancode
            if ch in ("\x00", "\xe0"):
                _ = msvcrt.getwch()
                return ""
            # Handle Ctrl+C or Ctrl+D
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch == "\x04" or ch == "\x1a":
                raise EOFError
            sys.stdout.write(f"{ch}\n")
            sys.stdout.flush()
            return ch.strip().lower()
        except ImportError:
            pass

    # Unix/macOS TTY: termios & tty
    try:
        import termios
        import tty
        sys.stdout.write(prompt_str)
        sys.stdout.flush()
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

        if ch == "\x03":
            raise KeyboardInterrupt
        if ch == "\x04":
            raise EOFError
        sys.stdout.write(f"{ch}\n")
        sys.stdout.flush()
        return ch.strip().lower()
    except Exception:
        # Fallback to standard input
        return input(prompt_str).strip().lower()


class PatchReviewWizard:
    """Interactive TUI wizard for stepping through and reviewing proposed code patches."""

    def __init__(
        self,
        files: List[str],
        backup: bool = False,
        verbose: bool = False,
        color: bool = True,
        input_fn: Optional[Callable[[str], str]] = None,
        output_fn: Optional[Callable[[str], None]] = None,
        allowed_write_files: Optional[Set[str]] = None,
    ):
        self.files = files
        self.backup = backup
        self.verbose = verbose
        self.color = color
        self.input_fn = input_fn
        self.output_fn = output_fn or self._default_output
        if allowed_write_files is not None:
            self.allowed_write_files: Set[str] = {canonical_path(f) for f in allowed_write_files}
        else:
            self.allowed_write_files = {canonical_path(f) for f in files}

    def _default_output(self, text: str):
        sys.stdout.write(text)
        sys.stdout.flush()

    def print(self, text: str = ""):
        self.output_fn(text + "\n")

    def run(self) -> bool:
        """
        Runs the interactive patch review session across all target files.
        Returns True if session completed normally, False if aborted or error.
        """
        self._transaction_active = True
        self._pending_updates: Dict[str, Tuple[str, List[CodePatch], Any, Set[str]]] = {}
        for file_path in self.files:
            success = self.review_file(file_path)
            if not success:
                self._pending_updates.clear()
                return False

        if not self._pending_updates:
            return True

        total = sum(len(item[1]) for item in self._pending_updates.values())
        try:
            answer = read_keystroke(
                f"{Colors.BOLD}Verify and write {total} accepted patch(es) across "
                f"{len(self._pending_updates)} file(s)? [y/N]: {Colors.RESET}",
                self.input_fn,
            )
        except (KeyboardInterrupt, EOFError):
            self.print(f"\n{Colors.YELLOW}Discarded the entire review transaction.{Colors.RESET}")
            return False
        if answer not in ("y", "yes"):
            self.print(f"{Colors.YELLOW}Discarded the entire review transaction.{Colors.RESET}")
            return False

        from src.repair_verifier import RepairVerifier
        from src.repair_coordinator import repair_source
        updates: Dict[str, str] = {}
        total_followups = 0
        for file_path, (source, patches, result, declined_codes) in self._pending_updates.items():
            intermediate, applied = apply_patches_to_source(
                source, patches, target_file=file_path
            )
            if len(applied) != len(patches):
                self.print(
                    f"{Colors.RED}[fix] Accepted patches became stale or conflicted for {file_path}. "
                    f"No files were written.{Colors.RESET}"
                )
                return False

            followup = repair_source(
                file_path,
                intermediate,
                confidence_policy="safe",
                max_rounds=5,
                excluded_codes=tuple(declined_codes),
            )
            if not followup.success:
                self.print(
                    f"{Colors.RED}[fix] Follow-up verification failed for {file_path}: "
                    f"{followup.message}. No files were written.{Colors.RESET}"
                )
                return False
            final_source = followup.updated_source
            all_patches = list(applied) + list(followup.applied_patches)
            total_followups += len(followup.applied_patches)
            verification = RepairVerifier().verify_final_source(
                result,
                source,
                final_source,
                all_patches,
                final_result=followup.final_analysis,
            )
            if not verification.accepted:
                self.print(
                    f"{Colors.RED}[fix] Verification failed for {file_path}: "
                    f"{verification.message}. No files were written.{Colors.RESET}"
                )
                return False
            updates[file_path] = verification.patched_source

        atomic_write_many(updates, backup=self.backup)
        self.print(
            f"{Colors.BOLD}{Colors.GREEN}[fix] Transaction committed: "
            f"{total + total_followups} patch(es) across {len(updates)} file(s).{Colors.RESET}"
        )
        return True

    def review_file(self, file_path: str) -> bool:
        """Reviews candidate patches for a single file interactively."""
        if not os.path.isfile(file_path):
            self.print(f"{Colors.RED}File not found: {file_path}{Colors.RESET}")
            return False

        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()

        raw_patches, result = collect_candidate_patches_with_result(file_path, source)
        if not result.safe_to_write:
            self.print(
                f"{Colors.RED}[fix] Analysis did not complete cleanly for {file_path}; refusing to write.{Colors.RESET}"
            )
            return False

        patches = [
            p for p in raw_patches
            if same_file(p.file_path, file_path) and canonical_path(p.file_path) in self.allowed_write_files
        ]
        whole_source = [
            patch for patch in patches
            if patch.start_offset == 0 and patch.end_offset == len(source)
        ]
        if whole_source:
            patches = whole_source
        if not patches:
            self.print(f"{Colors.GREEN}No errors or proposed patches for {file_path}.{Colors.RESET}")
            return True

        total_patches = len(patches)
        accepted_patches: List[CodePatch] = []
        apply_all_remaining = False
        break_and_save = False

        self.print(f"\n{Colors.BOLD}{Colors.CYAN}Found {total_patches} candidate patch(es) for {file_path}:{Colors.RESET}\n")

        idx = 0
        while idx < total_patches:
            if break_and_save:
                break

            patch = patches[idx]

            if apply_all_remaining:
                patch.applied = True
                accepted_patches.append(patch)
                idx += 1
                continue

            # Render summary card
            card = UnifiedDiffRenderer.render_summary_card(
                patch=patch,
                patch_idx=idx + 1,
                total_patches=total_patches,
                source=source,
                context_lines=2,
                color=self.color,
            )
            self.print(card)

            # Prompt loop for current patch
            while True:
                prompt_text = f"{Colors.BOLD}Apply this patch? [y]es, [n]o, [e]xplain, [a]ll, [d]iff, [q]uit (default 'y'): {Colors.RESET}"
                try:
                    cmd = read_keystroke(prompt_text, self.input_fn)
                except KeyboardInterrupt:
                    self.print(f"\n{Colors.YELLOW}Review session interrupted.{Colors.RESET}")
                    if accepted_patches:
                        try:
                            save_ans = read_keystroke(
                                f"{Colors.BOLD}[v] Verify and write accepted patches, or [d] discard everything: {Colors.RESET}",
                                self.input_fn,
                            )
                            if save_ans in ("v", "verify"):
                                break_and_save = True
                            else:
                                self.print(f"{Colors.YELLOW}Discarded all changes.{Colors.RESET}")
                                return False
                        except Exception:
                            return False
                    else:
                        return False
                    break
                except EOFError:
                    self.print(f"\n{Colors.YELLOW}End of input reached. Aborting.{Colors.RESET}")
                    return False

                if cmd in ("", "y", "yes"):
                    patch.applied = True
                    accepted_patches.append(patch)
                    self.print(f"  {Colors.BOLD}{Colors.GREEN}[Patch {idx + 1} Accepted]{Colors.RESET}\n")
                    idx += 1
                    break
                elif cmd in ("n", "no"):
                    patch.applied = False
                    self.print(f"  {Colors.BOLD}{Colors.YELLOW}[Patch {idx + 1} Skipped]{Colors.RESET}\n")
                    idx += 1
                    break
                elif cmd in ("e", "explain"):
                    self.print()
                    explain_error(patch.error_code)
                    self.print()
                    # Re-prompt for the same patch
                    continue
                elif cmd in ("d", "diff"):
                    self.print(f"\n{Colors.BOLD}--- Detailed 10-line Unified Diff ---{Colors.RESET}")
                    detailed = UnifiedDiffRenderer.render_unified_diff(
                        patch=patch,
                        source=source,
                        context_lines=10,
                        color=self.color,
                    )
                    self.print(detailed)
                    self.print(f"{'-' * 80}\n")
                    # Re-prompt for the same patch
                    continue
                elif cmd in ("a", "all"):
                    patch.applied = True
                    accepted_patches.append(patch)
                    apply_all_remaining = True
                    remaining_count = total_patches - idx
                    self.print(f"  {Colors.BOLD}{Colors.GREEN}[Applying all remaining {remaining_count} patch(es)]{Colors.RESET}\n")
                    idx += 1
                    break
                elif cmd in ("q", "quit"):
                    self.print(f"\n{Colors.YELLOW}Aborted. No changes written to {file_path}.{Colors.RESET}\n")
                    return False
                elif cmd in ("h", "?", "help"):
                    self.print_help()
                else:
                    self.print(f"{Colors.RED}Invalid command '{cmd}'. Please choose [y/n/e/a/d/q].{Colors.RESET}")

        # Stage this file in memory. The run-level transaction performs one
        # final confirmation, full verification, and all-or-nothing commit.
        valid_accepted = [
            p for p in accepted_patches
            if same_file(p.file_path, file_path) and canonical_path(p.file_path) in self.allowed_write_files
        ]
        accepted_ids = {id(patch) for patch in valid_accepted}
        declined_codes = {
            patch.error_code for patch in patches if id(patch) not in accepted_ids
        }
        if valid_accepted:
            repaired_source, applied = apply_patches_to_source(
                source, valid_accepted, target_file=file_path
            )
            if applied and repaired_source != source:
                if getattr(self, "_transaction_active", False):
                    if result is None:
                        self.print(f"{Colors.RED}[fix] Cannot verify mocked analysis result; no files written.{Colors.RESET}")
                        return False
                    self._pending_updates[file_path] = (
                        source, applied, result, declined_codes
                    )
                    self.print(f"{Colors.CYAN}[fix] Staged {len(applied)} patch(es) for {file_path}.{Colors.RESET}\n")
                else:
                    self.print(f"{Colors.RED}[fix] Direct per-file writes are disabled; use run().{Colors.RESET}")
                    return False
            else:
                self.print(f"{Colors.CYAN}[fix] No patches applied to {file_path}. File left untouched.{Colors.RESET}\n")
        else:
            self.print(f"{Colors.CYAN}[fix] No patches applied to {file_path}. File left untouched.{Colors.RESET}\n")

        return True

    def print_help(self):
        """Displays command help menu."""
        self.print(f"\n{Colors.BOLD}Interactive Patch Review Commands:{Colors.RESET}")
        self.print(f"  {Colors.GREEN}y, yes{Colors.RESET}     Apply current patch to working buffer")
        self.print(f"  {Colors.YELLOW}n, no{Colors.RESET}      Skip current patch and proceed to next")
        self.print(f"  {Colors.CYAN}e, explain{Colors.RESET} Display full error catalogue entry with causes and examples")
        self.print(f"  {Colors.GREEN}a, all{Colors.RESET}     Apply current patch and all remaining patches automatically")
        self.print(f"  {Colors.CYAN}d, diff{Colors.RESET}    Display expanded 10-line unified diff")
        self.print(f"  {Colors.RED}q, quit{Colors.RESET}    Abort review session immediately and discard all changes\n")
