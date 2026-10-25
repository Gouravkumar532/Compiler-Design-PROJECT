"""Canonical file-identity helpers shared by every compiler stage.

A *physical* file is identified by one canonical key: the normalised absolute
path (case-folded on case-insensitive platforms).  Sentinel names such as
``<stdin>``, ``<test>`` or ``<sandbox>`` are virtual buffers and are returned
unchanged.  Display paths are kept separate (see ``PreprocessResult``).
"""

import os
from typing import Optional


def is_sentinel(name: Optional[str]) -> bool:
    """True for virtual buffer names such as ``<stdin>`` or ``<sandbox>``."""
    return bool(name) and name.startswith("<") and name.endswith(">")


def canonical_path(path: Optional[str]) -> str:
    """Return the single canonical identity key for ``path``."""
    if path is None:
        return "<stdin>"
    if is_sentinel(path):
        return path
    return os.path.normcase(os.path.abspath(path))


def same_file(a: Optional[str], b: Optional[str]) -> bool:
    """True when ``a`` and ``b`` identify the same physical file/buffer."""
    return canonical_path(a) == canonical_path(b)


def display_path(path: Optional[str]) -> str:
    """Human friendly (non case-folded) rendering of a path."""
    if path is None:
        return "<stdin>"
    if is_sentinel(path):
        return path
    return os.path.abspath(path)
