from __future__ import annotations

import ast
import builtins
import keyword
import re
import sys
from dataclasses import dataclass, field

from diffguard.context import FileAstIndex
from diffguard.diff import ParsedFileDiff
from diffguard.domain import (
    CodeSnapshot,
    DiffSide,
    EvidenceStatus,
    FilterStatus,
    FindingCandidate,
    SourceType,
)
from diffguard.llm import LLMCandidateItem

_BUILTIN_NAMES = frozenset(dir(builtins)) | frozenset(keyword.kwlist)
_STDLIB_MODULES = sys.stdlib_module_names
_BACKTICK_CALL_RE = re.compile(r"`((?:[A-Za-z_][A-Za-z0-9_]*\.)*)([A-Za-z_][A-Za-z0-9_]*)\(\)`")
_DEF_CLASS_RE = re.compile(r"\b(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\b")
_DIFF_PREFIX_RE = re.compile(r"^[+-](?![+-])")
_REMEDIATION_LEAD_INS = (
    "use ",
    "prefer ",
    "replace with ",
    "instead use ",
    "switch to ",
    "consider ",
)


@dataclass
class CandidateEnvelope:
    candidate: FindingCandidate
    evidence_status: EvidenceStatus
    hunk_index: int | None = None


@dataclass
class GroundingResult:
    kept: list[CandidateEnvelope] = field(default_factory=list)
    rejected: list[FindingCandidate] = field(default_factory=list)
    unmapped_rejections: list[tuple[FindingCandidate, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def llm_items_to_envelopes(
    items: list[LLMCandidateItem],
    invocation_attempt: int,
) -> tuple[list[CandidateEnvelope], set[int]]:
    envelopes: list[CandidateEnvelope] = []
    invalid_order: set[int] = set()
    for idx, item in enumerate(items):
        end_line = item.end_line
        if end_line < item.start_line:
            invalid_order.add(idx)
            end_line = item.start_line
        cand = FindingCandidate(
            file_path=item.file_path,
            source_type=SourceType.LLM,
            diff_side=item.diff_side,
            start_line=item.start_line,
            end_line=end_line,
            category=item.category,
            finding_kind=item.finding_kind,
            severity=item.severity,
            title=item.title[:300],
            raw_message=item.explanation,
            code_evidence=item.code_evidence,
            suggested_fix=item.suggested_fix,
            rule_code=None,
            invocation_attempt=invocation_attempt,
            filter_status=FilterStatus.GIU_LAI,
        )
        envelopes.append(CandidateEnvelope(candidate=cand, evidence_status=item.evidence_status))
    return envelopes, invalid_order


def _collect_ast_identifiers(contents: dict[str, str]) -> tuple[set[str], set[str]]:
    known: set[str] = set()
    errored_files: set[str] = set()
    for path, src in contents.items():
        if not src.strip() or not path.endswith((".py", ".pyi")):
            continue
        try:
            tree = ast.parse(src, filename=path)
        except SyntaxError:
            errored_files.add(path)
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                known.add(node.name)
            elif isinstance(node, ast.Name):
                known.add(node.id)
            elif isinstance(node, ast.Attribute):
                known.add(node.attr)
            elif isinstance(node, ast.arg):
                known.add(node.arg)
            elif isinstance(node, ast.alias):
                known.add(node.asname or node.name.split(".")[0])
    return known, errored_files


def _normalize_ws(text: str) -> str:
    return " ".join(text.split())


def _strip_diff_markers(evidence: str) -> str:
    cleaned = [_DIFF_PREFIX_RE.sub("", ln) for ln in evidence.splitlines()]
    return _normalize_ws("\n".join(cleaned))


def _evidence_matches_slice(evidence: str, target_lines: list[str], start: int, end: int) -> bool:
    actual_slice = "\n".join(target_lines[start - 1 : end])
    norm_actual = _normalize_ws(actual_slice)
    if not norm_actual:
        return False
    norm_ev = _strip_diff_markers(evidence)
    if not norm_ev:
        return False
    if "..." in norm_ev:
        parts = [p.strip() for p in norm_ev.split("...") if p.strip()]
        if not parts:
            return False
        pos = 0
        for part in parts:
            idx = norm_actual.find(part, pos)
            if idx < 0:
                return False
            pos = idx + len(part)
        return True
    if norm_ev in norm_actual:
        return True
    return len(norm_actual) >= 8 and norm_actual in norm_ev


def _resolve_snapshot_path(raw_path: str, alias_map: dict[str, str]) -> str | None:
    cleaned = raw_path.strip().replace("\\", "/")
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if cleaned in alias_map:
        return alias_map[cleaned]
    if cleaned.startswith(("a/", "b/")) and cleaned[2:] in alias_map:
        return alias_map[cleaned[2:]]
    return None


def _extract_referenced_symbols(prose: str) -> set[str]:
    referenced: set[str] = set(_DEF_CLASS_RE.findall(prose))
    for match in _BACKTICK_CALL_RE.finditer(prose):
        prefix, sym = match.group(1), match.group(2)
        if prefix and prefix.split(".")[0] in _STDLIB_MODULES:
            continue
        lead_window = prose[max(0, match.start() - 30) : match.start()].lower()
        if any(lead_window.endswith(lead) for lead in _REMEDIATION_LEAD_INS):
            continue
        referenced.add(sym)
    return referenced


class DeterministicGroundingGate:
    def __init__(self, check_diff_scope: bool = True, check_ast_symbols: bool = True) -> None:
        self.check_diff_scope = check_diff_scope
        self.check_ast_symbols = check_ast_symbols

    def verify(
        self,
        envelopes: list[CandidateEnvelope],
        snapshot: CodeSnapshot,
        parsed_files: list[ParsedFileDiff],
        base_contents: dict[str, str],
        head_contents: dict[str, str],
        ast_indexes: dict[str, FileAstIndex] | None = None,
        invalid_order_indices: set[int] | None = None,
    ) -> GroundingResult:
        result = GroundingResult()
        parsed_map: dict[str, ParsedFileDiff] = {pf.display_path: pf for pf in parsed_files}
        alias_map: dict[str, str] = {}
        for pf in parsed_files:
            alias_map[pf.display_path] = pf.display_path
            if pf.old_path:
                alias_map.setdefault(pf.old_path, pf.display_path)
        changed_map = {cf.display_path: cf for cf in snapshot.files}
        invalid_orders = invalid_order_indices or set()

        head_ids, head_err = _collect_ast_identifiers(head_contents)
        base_ids, base_err = _collect_ast_identifiers(base_contents)
        all_ast_ids = head_ids | base_ids
        if ast_indexes:
            for idx_obj in ast_indexes.values():
                all_ast_ids.update(idx_obj.symbols)

        for idx, env in enumerate(envelopes):
            cand = env.candidate
            resolved_path = _resolve_snapshot_path(cand.file_path, alias_map)
            if resolved_path is None or resolved_path not in changed_map:
                rejected = cand.model_copy(
                    update={
                        "filter_status": FilterStatus.LOAI_SAI_DONG,
                        "filter_reason": "file_not_in_snapshot",
                    }
                )
                result.unmapped_rejections.append((rejected, "file_not_in_snapshot"))
                result.warnings.append(f"Dropped ungrounded candidate on non-snapshot file {cand.file_path}")
                continue

            if resolved_path != cand.file_path:
                cand = cand.model_copy(update={"file_path": resolved_path})
                env = CandidateEnvelope(
                    candidate=cand,
                    evidence_status=env.evidence_status,
                    hunk_index=env.hunk_index,
                )

            pf = parsed_map[resolved_path]
            cf = changed_map[resolved_path]
            if not cf.is_supported or pf.is_binary:
                result.rejected.append(
                    cand.model_copy(
                        update={
                            "filter_status": FilterStatus.LOAI_SAI_DONG,
                            "filter_reason": "unsupported_or_binary_file",
                        }
                    )
                )
                continue

            if idx in invalid_orders:
                result.rejected.append(
                    cand.model_copy(
                        update={
                            "filter_status": FilterStatus.LOAI_SAI_DONG,
                            "filter_reason": "end_line_before_start_line",
                        }
                    )
                )
                continue

            if cand.diff_side == DiffSide.RIGHT:
                content_key = resolved_path
                raw_text = head_contents.get(content_key)
                default_max = cf.new_line_count
            else:
                if resolved_path in base_contents:
                    content_key = resolved_path
                    raw_text = base_contents[resolved_path]
                elif pf.old_path and pf.old_path in base_contents:
                    content_key = pf.old_path
                    raw_text = base_contents[pf.old_path]
                else:
                    content_key = pf.old_path or resolved_path
                    raw_text = None
                default_max = cf.old_line_count

            if raw_text is not None:
                lines = raw_text.splitlines()
                max_line = len(lines)
            else:
                lines = []
                max_line = default_max

            if cand.start_line < 1 or cand.end_line > max_line:
                result.rejected.append(
                    cand.model_copy(
                        update={
                            "filter_status": FilterStatus.LOAI_SAI_DONG,
                            "filter_reason": "line_out_of_file_bounds",
                        }
                    )
                )
                continue

            matched_hunk: int | None = None
            target_range = set(range(cand.start_line, cand.end_line + 1))
            for hk in pf.hunks:
                hunk_lines = hk.right_lines if cand.diff_side == DiffSide.RIGHT else hk.left_lines
                if hunk_lines & target_range:
                    matched_hunk = hk.hunk_index
                    break

            if self.check_diff_scope and cand.source_type == SourceType.LLM and pf.hunks:
                if matched_hunk is None:
                    result.rejected.append(
                        cand.model_copy(
                            update={
                                "filter_status": FilterStatus.LOAI_SAI_DONG,
                                "filter_reason": "line_outside_diff_hunks",
                            }
                        )
                    )
                    continue

            if cand.source_type == SourceType.LLM:
                if not cand.code_evidence.strip():
                    result.rejected.append(
                        cand.model_copy(
                            update={
                                "filter_status": FilterStatus.LOAI_THIEU_CAN_CU,
                                "filter_reason": "missing_code_evidence",
                            }
                        )
                    )
                    continue
                if lines and not _evidence_matches_slice(
                    cand.code_evidence, lines, cand.start_line, cand.end_line
                ):
                    result.rejected.append(
                        cand.model_copy(
                            update={
                                "filter_status": FilterStatus.LOAI_THIEU_CAN_CU,
                                "filter_reason": "code_evidence_mismatch",
                            }
                        )
                    )
                    continue

                err_set = head_err if cand.diff_side == DiffSide.RIGHT else base_err
                if self.check_ast_symbols and content_key not in err_set and all_ast_ids:
                    prose = f"{cand.title} {cand.raw_message}"
                    referenced = _extract_referenced_symbols(prose)
                    missing_sym = next(
                        (s for s in sorted(referenced) if s not in _BUILTIN_NAMES and s not in all_ast_ids),
                        None,
                    )
                    if missing_sym is not None:
                        result.rejected.append(
                            cand.model_copy(
                                update={
                                    "filter_status": FilterStatus.LOAI_THIEU_CAN_CU,
                                    "filter_reason": f"unknown_ast_symbol:{missing_sym}",
                                }
                            )
                        )
                        continue

            result.kept.append(
                CandidateEnvelope(
                    candidate=cand,
                    evidence_status=env.evidence_status,
                    hunk_index=matched_hunk if matched_hunk is not None else env.hunk_index,
                )
            )
        return result
