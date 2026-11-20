from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from diffguard.domain import (
    CallStatus,
    Category,
    DiffSide,
    EvidenceStatus,
    FindingKind,
    Severity,
    UsageSource,
)


class LLMCandidateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_path: str
    diff_side: DiffSide
    start_line: int = Field(gt=0)
    end_line: int = Field(gt=0)
    category: Category
    finding_kind: FindingKind
    severity: Severity
    evidence_status: EvidenceStatus
    title: str
    explanation: str
    code_evidence: str
    suggested_fix: str | None = None


class LLMReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[LLMCandidateItem] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class LLMVerifyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_index: int = Field(ge=0)
    verdict: Literal["KEEP", "DROP", "NEEDS_VERIFICATION"]
    reason: str


class LLMVerifyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[LLMVerifyDecision] = Field(default_factory=list)


@dataclass
class ProviderResponse:
    call_status: CallStatus
    resolved_model_name: str
    parsed: BaseModel | None = None
    raw_text: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    usage_source: UsageSource = UsageSource.KHONG_CO
    latency_ms: int = 0
    error_detail: str | None = None
    retryable: bool = False


class LLMProvider(Protocol):
    provider_name: str

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_cls: type[BaseModel],
        model_name: str,
        temperature: float = 0.1,
        max_output_tokens: int = 4096,
        timeout_seconds: int = 60,
    ) -> ProviderResponse: ...


def compute_usage(in_tok: Any, out_tok: Any) -> tuple[int | None, int | None, UsageSource]:
    if isinstance(in_tok, int) and not isinstance(in_tok, bool) and in_tok >= 0:
        if isinstance(out_tok, int) and not isinstance(out_tok, bool) and out_tok >= 0:
            return in_tok, out_tok, UsageSource.THUC_TE
    return None, None, UsageSource.KHONG_CO
