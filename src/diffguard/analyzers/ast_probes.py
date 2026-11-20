from __future__ import annotations

import ast
from pathlib import Path

from diffguard.analyzers.ruff_adapter import StaticToolOutput
from diffguard.domain import Category, DiffSide, FindingCandidate, Severity, SourceType


def _is_mutable_default(node: ast.expr | None) -> bool:
    if node is None:
        return False
    if isinstance(node, (ast.List, ast.Dict, ast.Set)):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in {"list", "dict", "set"}
    return False


def _is_dynamic_sql(node: ast.expr) -> bool:
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "format":
            return True
    return False


def _is_open_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open"


def run_ast_probes_on_source(file_path: str, source: str) -> StaticToolOutput:
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError as exc:
        return StaticToolOutput(errors=[f"AST parse error in {file_path}:{exc.lineno}: {exc.msg}"])

    lines = source.splitlines()
    candidates: list[FindingCandidate] = []
    is_test_file = Path(file_path).name.startswith("test_") or "/tests/" in f"/{file_path}"

    def evidence_at(ln: int) -> str:
        if 1 <= ln <= len(lines):
            return lines[ln - 1].strip()
        return ""

    with_open_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if _is_open_call(item.context_expr):
                    with_open_ids.add(id(item.context_expr))

    def visit(node: ast.AST, in_loop: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            all_defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
            for d in all_defaults:
                if _is_mutable_default(d):
                    ln = d.lineno
                    candidates.append(
                        FindingCandidate(
                            file_path=file_path,
                            source_type=SourceType.AST_CUSTOM,
                            diff_side=DiffSide.RIGHT,
                            start_line=ln,
                            end_line=getattr(d, "end_lineno", ln) or ln,
                            category=Category.CHUC_NANG,
                            severity=Severity.CAO,
                            title="[AST01] Mutable default argument",
                            raw_message=(
                                f"Function `{node.name}` uses mutable default argument, "
                                "which is shared across calls."
                            ),
                            code_evidence=evidence_at(ln),
                            rule_code="AST01",
                        )
                    )
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            ln = node.lineno
            candidates.append(
                FindingCandidate(
                    file_path=file_path,
                    source_type=SourceType.AST_CUSTOM,
                    diff_side=DiffSide.RIGHT,
                    start_line=ln,
                    end_line=ln,
                    category=Category.CHUC_NANG,
                    severity=Severity.TRUNG_BINH,
                    title="[AST02] Bare except clause",
                    raw_message="Bare `except:` catches SystemExit and KeyboardInterrupt.",
                    code_evidence=evidence_at(ln),
                    rule_code="AST02",
                )
            )
        elif isinstance(node, ast.Assert) and not is_test_file:
            ln = node.lineno
            candidates.append(
                FindingCandidate(
                    file_path=file_path,
                    source_type=SourceType.AST_CUSTOM,
                    diff_side=DiffSide.RIGHT,
                    start_line=ln,
                    end_line=getattr(node, "end_lineno", ln) or ln,
                    category=Category.BAO_MAT,
                    severity=Severity.THAP,
                    title="[AST05] Assert statement in non-test code",
                    raw_message="`assert` is stripped when running Python with `-O`.",
                    code_evidence=evidence_at(ln),
                    rule_code="AST05",
                )
            )
        elif isinstance(node, ast.Call):
            if _is_open_call(node) and id(node) not in with_open_ids:
                ln = node.lineno
                candidates.append(
                    FindingCandidate(
                        file_path=file_path,
                        source_type=SourceType.AST_CUSTOM,
                        diff_side=DiffSide.RIGHT,
                        start_line=ln,
                        end_line=getattr(node, "end_lineno", ln) or ln,
                        category=Category.BAO_TRI,
                        severity=Severity.TRUNG_BINH,
                        title="[AST03] File opened without context manager",
                        raw_message="`open()` called outside `with` risks descriptor leaks.",
                        code_evidence=evidence_at(ln),
                        rule_code="AST03",
                    )
                )
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"execute", "executemany"}:
                if node.args and _is_dynamic_sql(node.args[0]):
                    ln = node.lineno
                    candidates.append(
                        FindingCandidate(
                            file_path=file_path,
                            source_type=SourceType.AST_CUSTOM,
                            diff_side=DiffSide.RIGHT,
                            start_line=ln,
                            end_line=getattr(node, "end_lineno", ln) or ln,
                            category=Category.BAO_MAT,
                            severity=Severity.CAO,
                            title="[AST04] Dynamic string SQL query execution",
                            raw_message="SQL built via interpolation/concatenation passed to execute().",
                            code_evidence=evidence_at(ln),
                            rule_code="AST04",
                        )
                    )
            if (
                in_loop
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "re"
                and node.func.attr == "compile"
            ):
                ln = node.lineno
                candidates.append(
                    FindingCandidate(
                        file_path=file_path,
                        source_type=SourceType.AST_CUSTOM,
                        diff_side=DiffSide.RIGHT,
                        start_line=ln,
                        end_line=getattr(node, "end_lineno", ln) or ln,
                        category=Category.HIEU_NANG,
                        severity=Severity.THAP,
                        title="[AST06] Regex compiled inside loop",
                        raw_message="`re.compile()` inside a loop wastes repeated compilation work.",
                        code_evidence=evidence_at(ln),
                        rule_code="AST06",
                    )
                )

        next_in_loop = in_loop or isinstance(node, (ast.For, ast.AsyncFor, ast.While))
        for child in ast.iter_child_nodes(node):
            visit(child, next_in_loop)

    visit(tree, False)
    return StaticToolOutput(candidates=candidates)
