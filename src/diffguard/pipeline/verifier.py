from __future__ import annotations

from dataclasses import dataclass, field

from diffguard.context import ContextBundle
from diffguard.domain import (
    CallPurpose,
    CallStatus,
    EvidenceStatus,
    FilterStatus,
    FindingCandidate,
    ModelInvocationRecord,
)
from diffguard.llm import LLMVerifyOutput, RateLimitedRouter
from diffguard.pipeline.grounding import CandidateEnvelope
from diffguard.prompts import PromptSpec, load_prompt_spec, render_verify_prompt


@dataclass
class VerificationResult:
    kept: list[CandidateEnvelope] = field(default_factory=list)
    rejected: list[FindingCandidate] = field(default_factory=list)
    invocations: list[ModelInvocationRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SelectiveVerificationFilter:
    def __init__(
        self,
        router: RateLimitedRouter | None = None,
        enabled: bool = True,
        model_name: str = "",
        temperature: float = 0.1,
        max_output_tokens: int = 2048,
        timeout_seconds: int = 60,
        prompt_spec: PromptSpec | None = None,
        max_candidates_per_call: int = 20,
        max_total_calls: int = 6,
    ) -> None:
        self.router = router
        self.enabled = enabled
        self.model_name = model_name
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        self.prompt_spec = prompt_spec
        self.max_candidates_per_call = max(1, max_candidates_per_call)
        self.max_total_calls = max_total_calls

    def filter(
        self,
        envelopes: list[CandidateEnvelope],
        bundle: ContextBundle,
        attempt_counter: list[int] | None = None,
    ) -> VerificationResult:
        if not self.enabled or not envelopes or self.router is None:
            return VerificationResult(kept=list(envelopes))

        counter = attempt_counter if attempt_counter is not None else [0]
        if counter[0] >= self.max_total_calls:
            return VerificationResult(
                kept=list(envelopes),
                warnings=["Skipped verification filter due to max_llm_calls ceiling"],
            )

        spec = self.prompt_spec or load_prompt_spec("py_verify_v1")
        to_verify = envelopes[: self.max_candidates_per_call]
        remainder = envelopes[self.max_candidates_per_call :]

        indexed = [(idx, env.candidate) for idx, env in enumerate(to_verify)]
        user_prompt = render_verify_prompt(spec, bundle, indexed)

        resp, records = self.router.invoke_structured(
            system_prompt=spec.system_prompt,
            user_prompt=user_prompt,
            schema_cls=LLMVerifyOutput,
            model_name=self.model_name,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            timeout_seconds=self.timeout_seconds,
            call_purpose=CallPurpose.XAC_MINH,
            attempt_counter=counter,
            max_total_calls=self.max_total_calls,
        )

        if resp is None or resp.call_status != CallStatus.THANH_CONG or resp.parsed is None:
            return VerificationResult(
                kept=list(envelopes),
                invocations=records,
                warnings=["Verification pass failed; kept grounded candidates unverified"],
            )

        verify_out = (
            resp.parsed
            if isinstance(resp.parsed, LLMVerifyOutput)
            else LLMVerifyOutput.model_validate(resp.parsed.model_dump())
        )
        decision_map = {d.candidate_index: d for d in verify_out.decisions}

        kept: list[CandidateEnvelope] = []
        rejected: list[FindingCandidate] = []
        for idx, env in enumerate(to_verify):
            dec = decision_map.get(idx)
            if dec is None or dec.verdict == "KEEP":
                kept.append(env)
            elif dec.verdict == "NEEDS_VERIFICATION":
                kept.append(
                    CandidateEnvelope(
                        candidate=env.candidate,
                        evidence_status=EvidenceStatus.CAN_XAC_MINH,
                        hunk_index=env.hunk_index,
                    )
                )
            else:
                rejected.append(
                    env.candidate.model_copy(
                        update={
                            "filter_status": FilterStatus.LOAI_THIEU_CAN_CU,
                            "filter_reason": (dec.reason or "verification_drop")[:500],
                        }
                    )
                )

        if remainder:
            kept.extend(remainder)
        return VerificationResult(kept=kept, rejected=rejected, invocations=records)
