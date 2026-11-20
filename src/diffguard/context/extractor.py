from __future__ import annotations

import ast
from dataclasses import dataclass, field

from diffguard.diff import ParsedFileDiff, ParsedHunk
from diffguard.domain import ContextPolicy


@dataclass
class SymbolSpan:
    name: str
    qualname: str
    start_line: int
    end_line: int
    signature: str
    snippet: str
    callees: set[str] = field(default_factory=set)


@dataclass
class FileAstIndex:
    symbols: set[str] = field(default_factory=set)
    imports: list[str] = field(default_factory=list)
    spans: list[SymbolSpan] = field(default_factory=list)
    parse_error: str | None = None

    def span_at_line(self, line: int) -> SymbolSpan | None:
        best: SymbolSpan | None = None
        for sp in self.spans:
            if sp.start_line <= line <= sp.end_line:
                if best is None or (sp.end_line - sp.start_line) < (best.end_line - best.start_line):
                    best = sp
        return best


def _collect_callees(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                names.add(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                names.add(child.func.attr)
    return names


def extract_ast_index(source: str, file_path: str = "<string>") -> FileAstIndex:
    if not source.strip():
        return FileAstIndex()
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError as exc:
        return FileAstIndex(parse_error=f"{exc.msg} (line {exc.lineno})")

    lines = source.splitlines()
    symbols: set[str] = set()
    imports: list[str] = []
    spans: list[SymbolSpan] = []

    def slice_lines(start: int, end: int) -> str:
        lo = max(0, start - 1)
        hi = min(len(lines), end)
        return "\n".join(f"{idx}: {lines[idx - 1]}" for idx in range(lo + 1, hi + 1))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                    symbols.add(arg.arg)
                if node.args.vararg:
                    symbols.add(node.args.vararg.arg)
                if node.args.kwarg:
                    symbols.add(node.args.kwarg.arg)
        elif isinstance(node, ast.Name):
            symbols.add(node.id)
        elif isinstance(node, ast.Attribute):
            symbols.add(node.attr)
        elif isinstance(node, ast.alias):
            symbols.add(node.asname or node.name.split(".")[0])

    def walk_defs(node: ast.AST, prefix: str = "") -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                ln = child.lineno
                if 1 <= ln <= len(lines):
                    imports.append(lines[ln - 1].strip())
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = f"{prefix}.{child.name}" if prefix else child.name
                start = child.lineno
                end = getattr(child, "end_lineno", start) or start
                sig_line = lines[start - 1].strip() if 1 <= start <= len(lines) else child.name
                spans.append(
                    SymbolSpan(
                        name=child.name,
                        qualname=qual,
                        start_line=start,
                        end_line=end,
                        signature=sig_line,
                        snippet=slice_lines(start, min(end, start + 60)),
                        callees=_collect_callees(child),
                    )
                )
                walk_defs(child, qual)

    walk_defs(tree)
    return FileAstIndex(symbols=symbols, imports=imports[:20], spans=spans)


def build_hunk_context(
    parsed_file: ParsedFileDiff,
    hunk: ParsedHunk,
    base_source: str | None,
    head_source: str | None,
    context_policy: ContextPolicy,
    all_indexes: dict[str, FileAstIndex] | None = None,
) -> tuple[str | None, str | None, str]:
    if context_policy in (ContextPolicy.DIFF_ONLY, ContextPolicy.KHONG_AP_DUNG):
        return hunk.header_context, None, "diff-only"

    use_left = parsed_file.new_path is None or (hunk.new_line_span == 0 and hunk.old_line_span > 0)
    target_src = base_source if use_left else head_source
    side_tag = "LEFT" if use_left else "RIGHT"
    if not target_src:
        return hunk.header_context, None, f"missing-{side_tag}-source"

    idx = (all_indexes or {}).get(parsed_file.display_path)
    if idx is None or use_left:
        idx = extract_ast_index(target_src, parsed_file.display_path)

    if idx.parse_error:
        return hunk.header_context, f"[AST fallback: {idx.parse_error}]", f"syntax-fallback-{side_tag}"

    anchor = hunk.old_start_line if use_left else hunk.new_start_line
    if not use_left and hunk.added_lines:
        anchor = min(hunk.added_lines)
    elif use_left and hunk.deleted_lines:
        anchor = min(hunk.deleted_lines)

    enclosing = idx.span_at_line(anchor)
    parts: list[str] = []
    if idx.imports:
        parts.append("Imports:\n" + "\n".join(idx.imports[:10]))

    symbol_name = hunk.header_context
    reason = f"imports-{side_tag}"
    if enclosing is not None:
        symbol_name = enclosing.qualname
        reason = f"ast-enclosing:{enclosing.qualname}({side_tag})"
        parts.append(
            f"Enclosing {enclosing.qualname} [{side_tag} L{enclosing.start_line}-{enclosing.end_line}]:\n"
            f"{enclosing.snippet}"
        )
        seen = {enclosing.name}
        callee_sigs: list[str] = []
        for other_path, other_idx in (all_indexes or {}).items():
            for sp in other_idx.spans:
                if sp.name in enclosing.callees and sp.name not in seen:
                    seen.add(sp.name)
                    callee_sigs.append(f"{other_path}:L{sp.start_line}: {sp.signature}")
                if len(callee_sigs) >= 8:
                    break
        if callee_sigs:
            parts.append("Referenced signatures:\n" + "\n".join(callee_sigs))

    ctx_text = "\n\n".join(parts) if parts else None
    return symbol_name, ctx_text, reason
