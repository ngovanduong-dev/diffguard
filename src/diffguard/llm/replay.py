from __future__ import annotations

import hashlib
from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from diffguard.domain import CallStatus, UsageSource
from diffguard.llm.base import ProviderResponse


class ReplayProvider:
    provider_name = "replay"

    def __init__(
        self,
        responses_by_hash: dict[str, str] | None = None,
        queued_responses: list[ProviderResponse | str] | None = None,
        dynamic_fn: Callable[[str, str, type[BaseModel]], ProviderResponse] | None = None,
    ) -> None:
        self.responses_by_hash = responses_by_hash or {}
        self.queued_responses = list(queued_responses or [])
        self.dynamic_fn = dynamic_fn
        self.calls: list[tuple[str, str, str]] = []

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_cls: type[BaseModel],
        model_name: str = "replay-v1",
        temperature: float = 0.0,
        max_output_tokens: int = 4096,
        timeout_seconds: int = 60,
    ) -> ProviderResponse:
        p_hash = hashlib.sha256(f"{system_prompt}\n{user_prompt}".encode()).hexdigest()
        self.calls.append((p_hash, model_name, user_prompt))

        if self.dynamic_fn is not None:
            return self.dynamic_fn(system_prompt, user_prompt, schema_cls)

        raw: ProviderResponse | str | None = self.responses_by_hash.get(p_hash)
        if raw is None and self.queued_responses:
            raw = self.queued_responses.pop(0)
        if raw is None:
            parsed = schema_cls.model_validate({})
            return ProviderResponse(
                call_status=CallStatus.THANH_CONG,
                resolved_model_name=model_name,
                parsed=parsed,
                raw_text=parsed.model_dump_json(),
                input_tokens=max(1, len(user_prompt) // 4),
                output_tokens=16,
                usage_source=UsageSource.UOC_TINH,
                latency_ms=1,
            )
        if isinstance(raw, ProviderResponse):
            return raw
        try:
            parsed = schema_cls.model_validate_json(raw)
        except ValidationError as exc:
            return ProviderResponse(
                call_status=CallStatus.SAI_SCHEMA,
                resolved_model_name=model_name,
                raw_text=raw,
                usage_source=UsageSource.KHONG_CO,
                latency_ms=1,
                error_detail=f"Replay schema mismatch: {exc.error_count()} errors",
                retryable=False,
            )
        return ProviderResponse(
            call_status=CallStatus.THANH_CONG,
            resolved_model_name=model_name,
            parsed=parsed,
            raw_text=raw,
            input_tokens=max(1, len(user_prompt) // 4),
            output_tokens=max(1, len(raw) // 4),
            usage_source=UsageSource.UOC_TINH,
            latency_ms=1,
        )
