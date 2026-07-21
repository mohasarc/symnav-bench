from __future__ import annotations

from pathlib import Path


def grade_script_source() -> str:
    return (Path(__file__).parent / "grade_script.py").read_text(encoding="utf-8")
