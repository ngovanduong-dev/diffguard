from pathlib import Path
from unittest.mock import patch

from diffguard.analyzers import DifferentialStaticEngine, run_ast_probes_on_source, run_ruff
from diffguard.domain import FilterStatus, Severity
from diffguard.ingest import ingest_snapshot_pair


def test_differential_isolates_preexisting_vs_new_issues() -> None:
    base_code = "def legacy_bad(items=[]):\n    return items\n\ndef ok(x):\n    return x + 1\n"
    head_code = (
        "def legacy_bad(items=[]):\n"
        "    return items\n"
        "\n"
        "def ok(x):\n"
        "    unused = 99\n"
        "    return x + 1\n"
        "\n"
        "def run_q(cur, uid):\n"
        "    cur.execute(f'SELECT * FROM u WHERE id={uid}')\n"
    )
    ing = ingest_snapshot_pair(
        "org/demo",
        base_files={"svc.py": base_code},
        head_files={"svc.py": head_code},
    )
    engine = DifferentialStaticEngine()
    out = engine.analyze(ing.parsed_files, ing.base_contents, ing.head_contents)
    assert out.errors == []

    kept = [c for c in out.candidates if c.filter_status == FilterStatus.GIU_LAI]
    old = [c for c in out.candidates if c.filter_status == FilterStatus.LOI_CU]
    assert any(c.rule_code == "AST01" for c in old)
    assert any(c.rule_code == "F841" for c in kept)
    assert any(c.rule_code in {"B608", "AST04", "S608"} for c in kept)


def test_rule_disable_and_severity_override() -> None:
    ing = ingest_snapshot_pair(
        "org/demo",
        base_files={"m.py": "def f():\n    pass\n"},
        head_files={"m.py": "def f(x=[]):\n    return x\n"},
    )
    engine = DifferentialStaticEngine(
        disabled_rules={"B006"},
        severity_overrides={"AST01": Severity.THAP},
    )
    out = engine.analyze(ing.parsed_files, ing.base_contents, ing.head_contents)
    codes = {c.rule_code for c in out.candidates}
    assert "B006" not in codes
    ast_cands = [c for c in out.candidates if c.rule_code == "AST01"]
    assert ast_cands and ast_cands[0].severity == Severity.THAP


def test_ast_probes_handle_syntax_error_and_probes() -> None:
    bad = run_ast_probes_on_source("broken.py", "def bad(:\n")
    assert len(bad.errors) == 1

    src = (
        "import re\n"
        "def scan(lines):\n"
        "    f = open('a.txt')\n"
        "    for ln in lines:\n"
        "        re.compile(r'a+')\n"
        "    try:\n"
        "        return f.read()\n"
        "    except:\n"
        "        assert len(lines) > 0\n"
        "        return ''\n"
    )
    out = run_ast_probes_on_source("app.py", src)
    codes = {c.rule_code for c in out.candidates}
    assert {"AST02", "AST03", "AST05", "AST06"}.issubset(codes)


def test_ruff_crash_returns_tool_error(tmp_path: Path) -> None:
    with patch("diffguard.analyzers.ruff_adapter.subprocess.run") as mrun:
        mrun.return_value.returncode = 2
        mrun.return_value.stderr = "invalid config"
        mrun.return_value.stdout = ""
        out = run_ruff(tmp_path)
        assert out.candidates == []
        assert len(out.errors) == 1
