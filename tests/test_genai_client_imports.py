"""Tripwire for the PR #180 regression class.

PR #180 replaced direct google-genai client construction with make_genai_client(...)
across the codebase but did not add the import everywhere, leaving silent runtime
NameErrors (swallowed by broad except blocks) in video analysis, image analysis, the
classifier, congruence analysis, brand research, instagram analysis, and more — found
and fixed in four separate waves. This static scan makes a fifth wave impossible: any
module that CALLS make_genai_client( must IMPORT it (or define it).

Run with: pytest tests/test_genai_client_imports.py -v
"""
from __future__ import annotations

from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "viraltracker"


def test_every_make_genai_client_call_site_imports_it():
    offenders = []
    for path in PKG.rglob("*.py"):
        src = path.read_text(encoding="utf-8", errors="ignore")
        if "make_genai_client(" not in src:
            continue
        defines = "def make_genai_client" in src
        imports = "genai_client import make_genai_client" in src
        if not (defines or imports):
            offenders.append(str(path.relative_to(PKG.parent)))
    assert not offenders, (
        "make_genai_client( called without importing it (PR #180 regression class) in: "
        + ", ".join(sorted(offenders))
    )
