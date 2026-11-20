from __future__ import annotations

from dataclasses import dataclass, field

from diffguard.context.extractor import FileAstIndex, build_hunk_context, extract_ast_index
from diffguard.diff import ParsedFileDiff
from diffguard.domain import ContextPolicy, ReviewPolicy


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


@dataclass
class ContextChunk:
    file_path: str
    hunk_index: int
    diff_text: str
    ast_symbol_name: str | None
    ast_context_text: str | None
    selection_reason: str
    estimated_tokens: int


@dataclass
class ContextBundle:
    chunks: list[ContextChunk] = field(default_factory=list)
    pr_intent_text: str | None = None
    total_estimated_tokens: int = 0
    is_full_coverage: bool = True
    omitted_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def pack_context_budget(
    parsed_files: list[ParsedFileDiff],
    base_contents: dict[str, str],
    head_contents: dict[str, str],
    context_policy: ContextPolicy,
    policy: ReviewPolicy,
    pr_title: str | None = None,
    pr_description: str | None = None,
    static_signals_tokens: int = 0,
    prompt_overhead_tokens: int = 500,
) -> ContextBundle:
    indexes: dict[str, FileAstIndex] = {}
    for path, src in head_contents.items():
        if path.endswith((".py", ".pyi")):
            indexes[path] = extract_ast_index(src, path)
    for pf in parsed_files:
        if pf.display_path not in indexes:
            src = base_contents.get(pf.old_path or "")
            if src:
                indexes[pf.display_path] = extract_ast_index(src, pf.display_path)

    pr_intent: str | None = None
    intent_tokens = 0
    if context_policy == ContextPolicy.DIFF_AST_INTENT and (pr_title or pr_description):
        desc = (pr_description or "").strip()[:1200]
        pr_intent = f"PR Title: {pr_title or ''}\nPR Description:\n{desc}".strip()
        intent_tokens = estimate_tokens(pr_intent)

    reserved = prompt_overhead_tokens + static_signals_tokens + intent_tokens
    available = max(0, policy.max_input_tokens - reserved)

    candidates: list[ContextChunk] = []
    for pf in parsed_files:
        b_src = base_contents.get(pf.old_path) if pf.old_path else None
        h_src = head_contents.get(pf.new_path) if pf.new_path else None
        for hk in pf.hunks:
            sym, ast_ctx, reason = build_hunk_context(
                pf, hk, b_src, h_src, context_policy, all_indexes=indexes
            )
            diff_txt = f"File: {pf.display_path}\n{hk.patch_content}"
            tok = estimate_tokens(diff_txt) + estimate_tokens(ast_ctx or "")
            candidates.append(
                ContextChunk(
                    file_path=pf.display_path,
                    hunk_index=hk.hunk_index,
                    diff_text=diff_txt,
                    ast_symbol_name=sym,
                    ast_context_text=ast_ctx,
                    selection_reason=reason,
                    estimated_tokens=tok,
                )
            )

    kept: list[ContextChunk] = []
    omitted_files: set[str] = set()
    used_tokens = reserved
    full_cov = True
    warnings: list[str] = []

    for chunk in candidates:
        if used_tokens - reserved + chunk.estimated_tokens <= available:
            kept.append(chunk)
            used_tokens += chunk.estimated_tokens
            continue
        diff_only_tok = estimate_tokens(chunk.diff_text)
        if chunk.ast_context_text and used_tokens - reserved + diff_only_tok <= available:
            trimmed = ContextChunk(
                file_path=chunk.file_path,
                hunk_index=chunk.hunk_index,
                diff_text=chunk.diff_text,
                ast_symbol_name=chunk.ast_symbol_name,
                ast_context_text=None,
                selection_reason="budget-trimmed-to-diff",
                estimated_tokens=diff_only_tok,
            )
            kept.append(trimmed)
            used_tokens += diff_only_tok
            full_cov = False
            warnings.append(
                f"Trimmed AST context for {chunk.file_path}#hunk{chunk.hunk_index} due to token budget"
            )
        else:
            full_cov = False
            omitted_files.add(chunk.file_path)
            warnings.append(
                f"Omitted {chunk.file_path}#hunk{chunk.hunk_index} "
                f"exceeding max_input_tokens={policy.max_input_tokens}"
            )

    return ContextBundle(
        chunks=kept,
        pr_intent_text=pr_intent,
        total_estimated_tokens=used_tokens,
        is_full_coverage=full_cov,
        omitted_files=sorted(omitted_files),
        warnings=warnings,
    )
