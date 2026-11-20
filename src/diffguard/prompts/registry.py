from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from diffguard.context import ContextBundle
from diffguard.domain import FindingCandidate

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "configs" / "prompts"


def _sanitize_fence(text: str) -> str:
    return text.replace("</untrusted_diff_and_ast>", "</untrusted-block>").replace(
        "</untrusted_context>", "</untrusted-block>"
    )


@dataclass(frozen=True)
class PromptSpec:
    prompt_code: str
    version_tag: str
    strategy_desc: str
    system_prompt: str
    user_template: str
    prompt_hash: str


def load_prompt_spec(name: str, prompts_dir: Path | None = None) -> PromptSpec:
    base = prompts_dir or PROMPTS_DIR
    path = base / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw_hash = hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()
    return PromptSpec(
        prompt_code=str(data["prompt_code"]),
        version_tag=str(data["version_tag"]),
        strategy_desc=str(data["strategy_desc"]),
        system_prompt=str(data["system_prompt"]).strip(),
        user_template=str(data["user_template"]).strip(),
        prompt_hash=raw_hash,
    )


def render_review_prompt(
    spec: PromptSpec,
    bundle: ContextBundle,
    static_candidates: list[FindingCandidate] | None = None,
) -> str:
    pr_section = ""
    if bundle.pr_intent_text:
        pr_section = (
            f"<untrusted_pr_intent>\n{_sanitize_fence(bundle.pr_intent_text)}\n</untrusted_pr_intent>\n"
        )

    static_section = ""
    if static_candidates:
        lines = [
            f"- {c.file_path}:L{c.start_line}-{c.end_line} "
            f"[{c.source_type.value}/{c.rule_code}] {c.raw_message}"
            for c in static_candidates
        ]
        static_section = "<static_signals>\n" + "\n".join(lines) + "\n</static_signals>\n"

    chunks_text_parts: list[str] = []
    for ch in bundle.chunks:
        block = f"--- {ch.file_path} (hunk {ch.hunk_index}, reason={ch.selection_reason}) ---\n{ch.diff_text}"
        if ch.ast_context_text:
            block += f"\n\n[AST Context]\n{ch.ast_context_text}"
        chunks_text_parts.append(_sanitize_fence(block))

    chunks_text = "\n\n".join(chunks_text_parts)
    rendered = spec.user_template.replace("{{PR_INTENT_SECTION}}", pr_section)
    rendered = rendered.replace("{{STATIC_SIGNALS_SECTION}}", static_section)
    rendered = rendered.replace("{{CONTEXT_CHUNKS}}", chunks_text)
    return rendered.strip()


def render_verify_prompt(
    spec: PromptSpec,
    bundle: ContextBundle,
    candidates: list[tuple[int, FindingCandidate]],
) -> str:
    chunks_text = "\n\n".join(
        _sanitize_fence(f"--- {ch.file_path} ---\n{ch.diff_text}\n{ch.ast_context_text or ''}".strip())
        for ch in bundle.chunks
    )
    cand_payload = [
        {
            "candidate_index": idx,
            "file_path": c.file_path,
            "diff_side": c.diff_side.value,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "source_type": c.source_type.value,
            "rule_code": c.rule_code,
            "title": c.title,
            "raw_message": c.raw_message,
            "code_evidence": c.code_evidence,
        }
        for idx, c in candidates
    ]
    rendered = spec.user_template.replace("{{CONTEXT_CHUNKS}}", chunks_text)
    rendered = rendered.replace("{{CANDIDATES_JSON}}", json.dumps(cand_payload, indent=2))
    return rendered.strip()
