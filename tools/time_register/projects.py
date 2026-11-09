"""Project of a session (from its working folder) and the project level (from the "Рівень" line of its card)."""
import os
import re

from .patterns import WORKSPACE


def project_of(cwd, dirname):
    if not cwd:
        return dirname
    cwd = re.split(r"/\.claude/worktrees/", cwd)[0]
    if cwd.startswith(("/private/tmp/", "/tmp/", "/private/var/", "/var/folders/")):
        return "(scratch)"
    rel = os.path.relpath(cwd, WORKSPACE)
    if rel == ".":
        return os.path.basename(WORKSPACE)
    if not rel.startswith(".."):
        return rel.split(os.sep)[0]
    return os.path.basename(cwd.rstrip("/")) or cwd


_levels = {}


def project_level(project):
    """Compact "T2 R1 V0 A" from the first "Рівень ..." line of the project card, "?" when there is none."""
    if project not in _levels:
        _levels[project] = "?"
        for name in ("CLAUDE.local.md", "AGENTS.md", "CLAUDE.md"):
            try:
                with open(os.path.join(WORKSPACE, project, name), encoding="utf-8") as f:
                    m = re.search(r"^Рівень[^\n]*", f.read(), re.M)
            except OSError:
                continue
            if m:
                line = m.group(0)
                parts = [re.search(p, line) for p in (r"\bT[0-3]\b", r"Ризик (R[0-2])", r"Дані (V[0-2])", r"UI (none|[ABC])")]
                _levels[project] = " ".join(p.group(p.lastindex or 0) for p in parts if p) or "?"
                break
    return _levels[project]
