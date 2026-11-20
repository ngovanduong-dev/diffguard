from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from diffguard.domain.enums import (
    AssessmentStatus,
    CallPurpose,
    CallStatus,
    Category,
    ChangeType,
    ContextPolicy,
    DiffSide,
    EvidenceStatus,
    ExecutionMode,
    FeedbackLabel,
    FilterStatus,
    FindingKind,
    FixVerificationStatus,
    InputSource,
    PatchStatus,
    RunStatus,
    Severity,
    SourceType,
    UsageSource,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DiffHunk(StrictModel):
    hunk_index: Annotated[int, Field(gt=0)]
    old_start_line: Annotated[int, Field(ge=0)]
    old_line_span: Annotated[int, Field(ge=0)]
    new_start_line: Annotated[int, Field(ge=0)]
    new_line_span: Annotated[int, Field(ge=0)]
    ast_symbol_name: str | None = None
    patch_content: str | None = None
    ast_context_snippet: str | None = None
    estimated_tokens: Annotated[int, Field(ge=0)] = 0


class ChangedFile(StrictModel):
    old_path: str | None = None
    new_path: str | None = None
    change_type: ChangeType
    patch_status: PatchStatus = PatchStatus.CO_PATCH
    language: str = "Python"
    old_line_count: Annotated[int, Field(ge=0)] = 0
    new_line_count: Annotated[int, Field(ge=0)] = 0
    additions_count: Annotated[int, Field(ge=0)] = 0
    deletions_count: Annotated[int, Field(ge=0)] = 0
    is_supported: bool = True
    hunks: list[DiffHunk] = Field(default_factory=list)

    @property
    def display_path(self) -> str:
        return self.new_path or self.old_path or ""

    @model_validator(mode="after")
    def validate_paths(self) -> ChangedFile:
        if self.change_type == ChangeType.THEM_MOI:
            if self.old_path is not None or not self.new_path:
                raise ValueError("THEM_MOI requires old_path=None and non-empty new_path")
        elif self.change_type == ChangeType.XOA:
            if not self.old_path or self.new_path is not None:
                raise ValueError("XOA requires non-empty old_path and new_path=None")
        elif not self.old_path or not self.new_path:
            raise ValueError("CHINH_SUA/DOI_TEN requires both old_path and new_path")
        return self


class CodeSnapshot(StrictModel):
    repo_full_name: str
    input_source: InputSource
    base_commit_sha: str
    head_commit_sha: str
    merge_base_sha: str
    diff_hash: str
    total_files: Annotated[int, Field(ge=0)]
    total_additions: Annotated[int, Field(ge=0)]
    total_deletions: Annotated[int, Field(ge=0)]
    files: list[ChangedFile] = Field(default_factory=list)
    pr_number: Annotated[int, Field(gt=0)] | None = None
    pr_title: str | None = None
    pr_description: str | None = None


class ReviewPolicy(StrictModel):
    max_files_limit: Annotated[int, Field(gt=0)] = 10
    max_diff_lines: Annotated[int, Field(gt=0)] = 800
    max_snapshot_bytes: Annotated[int, Field(gt=0)] = 5_242_880
    max_input_tokens: Annotated[int, Field(ge=0)] = 12_000
    max_output_tokens: Annotated[int, Field(ge=0)] = 8_000
    max_llm_calls: Annotated[int, Field(ge=0)] = 6
    timeout_seconds: Annotated[int, Field(gt=0)] = 300
    temperature: Annotated[float, Field(ge=0.0, le=2.0)] = 0.1
    allow_external_llm: bool = False
    auto_publish_pr: bool = False
    exclude_globs: list[str] = Field(default_factory=list)
    rubric_version: str = "rubric-v1"


class ReviewRequest(StrictModel):
    repo_full_name: str
    execution_mode: ExecutionMode
    context_policy: ContextPolicy = ContextPolicy.DIFF_AST_INTENT
    config_version: Annotated[int, Field(gt=0)] = 1
    policy: ReviewPolicy = Field(default_factory=ReviewPolicy)
    llm_model_name: str | None = None
    prompt_code: str | None = None
    prompt_version: str | None = None
    benchmark_sample_id: str | None = None
    benchmark_manifest_hash: str | None = None


class ModelInvocationRecord(StrictModel):
    attempt_number: Annotated[int, Field(gt=0)]
    call_purpose: CallPurpose = CallPurpose.REVIEW
    provider_name: str
    resolved_model_name: str
    payload_hash: str
    call_status: CallStatus
    input_tokens: Annotated[int, Field(ge=0)] | None = None
    output_tokens: Annotated[int, Field(ge=0)] | None = None
    usage_source: UsageSource = UsageSource.KHONG_CO
    estimated_cost_usd: Annotated[float, Field(ge=0.0)] | None = None
    latency_ms: Annotated[int, Field(ge=0)] | None = None
    started_at: datetime
    finished_at: datetime | None = None
    hunk_index: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def validate_usage(self) -> ModelInvocationRecord:
        if self.usage_source == UsageSource.KHONG_CO:
            if self.input_tokens is not None or self.output_tokens is not None:
                raise ValueError("KHONG_CO requires input_tokens=None and output_tokens=None")
        elif self.input_tokens is None or self.output_tokens is None:
            raise ValueError("THUC_TE/UOC_TINH requires both input_tokens and output_tokens")
        return self


class FindingCandidate(StrictModel):
    file_path: str
    source_type: SourceType
    diff_side: DiffSide
    start_line: Annotated[int, Field(gt=0)]
    end_line: Annotated[int, Field(gt=0)]
    category: Category
    finding_kind: FindingKind = FindingKind.LOI_TIEM_AN
    severity: Severity
    title: str
    raw_message: str
    code_evidence: str = ""
    suggested_fix: str | None = None
    rule_code: str | None = None
    invocation_attempt: Annotated[int, Field(gt=0)] | None = None
    filter_status: FilterStatus = FilterStatus.GIU_LAI
    filter_reason: str | None = None
    merged_fingerprint: str | None = None

    @model_validator(mode="after")
    def validate_candidate(self) -> FindingCandidate:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        if self.source_type == SourceType.LLM:
            if self.invocation_attempt is None or self.rule_code is not None:
                raise ValueError("LLM candidate requires invocation_attempt and rule_code=None")
        else:
            if not self.rule_code or self.invocation_attempt is not None:
                raise ValueError("Static candidate requires rule_code and invocation_attempt=None")
        return self


class ReviewFinding(StrictModel):
    issue_fingerprint: str
    file_path: str
    diff_side: DiffSide
    start_line: Annotated[int, Field(gt=0)]
    end_line: Annotated[int, Field(gt=0)]
    hunk_index: Annotated[int, Field(gt=0)] | None = None
    category: Category
    finding_kind: FindingKind
    severity: Severity
    evidence_status: EvidenceStatus
    title: str
    explanation: str
    code_evidence: str
    suggested_fix: str | None = None
    fix_verification_status: FixVerificationStatus = FixVerificationStatus.CHUA_KIEM_CHUNG
    sources: list[SourceType] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_lines(self) -> ReviewFinding:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self


class QualityAssessment(StrictModel):
    dimension_name: Category
    rubric_version: str
    assessment_status: AssessmentStatus
    is_scope_complete: bool
    summary_rationale: str


class ReviewReport(StrictModel):
    run_id: Annotated[int, Field(gt=0)] | None = None
    idempotency_key: str
    snapshot: CodeSnapshot
    execution_mode: ExecutionMode
    context_policy: ContextPolicy
    run_status: RunStatus
    is_full_coverage: bool
    termination_reason: str | None = None
    findings: list[ReviewFinding] = Field(default_factory=list)
    candidates: list[FindingCandidate] = Field(default_factory=list)
    quality_assessments: list[QualityAssessment] = Field(default_factory=list)
    invocations: list[ModelInvocationRecord] = Field(default_factory=list)
    omitted_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    benchmark_sample_id: str | None = None
    benchmark_manifest_hash: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class FindingFeedback(StrictModel):
    finding_id: Annotated[int, Field(gt=0)]
    user_id: Annotated[int, Field(gt=0)]
    revision_no: Annotated[int, Field(gt=0)]
    feedback_label: FeedbackLabel
    reason_note: str | None = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_reason(self) -> FindingFeedback:
        if self.feedback_label == FeedbackLabel.SAI:
            if not self.reason_note or not self.reason_note.strip():
                raise ValueError("reason_note is required when feedback_label is SAI")
        return self
