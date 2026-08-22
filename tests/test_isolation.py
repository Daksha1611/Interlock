"""Structural safety tests. These assert the architecture's central claim —
the agent cannot reach the money — by static inspection, not by trusting
that nobody happens to call the wrong function today.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


def _imported_top_level_modules(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module.split(".")[0])
    return modules


def test_agent_has_no_import_path_to_gate_or_world():
    agent_files = list((SRC / "agent").rglob("*.py"))
    assert agent_files, "expected agent/ source files to exist"
    offenders = {}
    for f in agent_files:
        mods = _imported_top_level_modules(f)
        forbidden = mods & {"gate", "world"}
        if forbidden:
            offenders[str(f.relative_to(SRC))] = forbidden
    assert not offenders, (
        f"agent/ must have no import path to gate/ or world/ (it proposes; it cannot dispose): {offenders}"
    )


def test_world_has_no_import_path_to_agent():
    world_files = list((SRC / "world").rglob("*.py"))
    assert world_files, "expected world/ source files to exist"
    offenders = {}
    for f in world_files:
        mods = _imported_top_level_modules(f)
        if "agent" in mods:
            offenders[str(f.relative_to(SRC))] = mods
    assert not offenders, f"world/ must not import agent/ — this is the integrity boundary: {offenders}"


def test_gate_has_no_model_call():
    """The gate is ordinary Python reading YAML. No LLM client anywhere in
    its decision path."""
    gate_files = list((SRC / "gate").rglob("*.py"))
    banned_tokens = ["openai", "anthropic", "OpenAI(", "chat.completions", "messages.create"]
    offenders = {}
    for f in gate_files:
        text = f.read_text()
        hits = [tok for tok in banned_tokens if tok in text]
        if hits:
            offenders[str(f.relative_to(SRC))] = hits
    assert not offenders, f"gate/ must contain no model call: {offenders}"


def test_only_executor_mutates_ledger_money_state():
    """ledger.record_attempt / record_contact / record_mandate_presentation
    are the only ways money or contact state changes. Only gate/executor.py
    may call them — everything else only reads the ledger via get_context()."""
    pattern = re.compile(r"\.record_(attempt|contact|mandate_presentation)\(")
    offenders = {}
    for f in SRC.rglob("*.py"):
        if f.name in ("ledger.py",):
            continue  # method definitions live here, not calls
        if f == SRC / "gate" / "executor.py":
            continue  # the one allowed caller
        text = f.read_text()
        hits = pattern.findall(text)
        if hits:
            offenders[str(f.relative_to(SRC))] = hits
    assert not offenders, f"only gate/executor.py may mutate ledger state: {offenders}"
