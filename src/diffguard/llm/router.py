from __future__ import annotations

import hashlib
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from diffguard.domain import CallPurpose, CallStatus, ModelInvocationRecord, UsageSource
from diffguard.llm.base import LLMProvider, ProviderResponse


class RateLimitedRouter:
    def __init__(
        self,
        provider: LLMProvider,
        rpm_limit: int = 12,
        max_retries: int = 2,
        base_backoff_seconds: float = 0.5,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.provider = provider
        self.rpm_limit = max(1, rpm_limit)
        self.max_retries = max(0, max_retries)
        self.base_backoff_seconds = base_backoff_seconds
        self._sleep = sleep_fn
        self._clock = clock_fn
        self._timestamps: deque[float] = deque()

    def _pace(self) -> None:
        now = self._clock()
        while self._timestamps and now - self._timestamps[0] >= 60.0:
            self._timestamps.popleft()
        if len(self._timestamps) >= self.rpm_limit:
            wait = 60.0 - (now - self._timestamps[0]) + 0.05
            if wait > 0:
                self._sleep(wait)
        self._timestamps.append(self._clock())

    def invoke_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_cls: type[BaseModel],
        model_name: str,
        temperature: float = 0.1,
        max_output_tokens: int = 4096,
        timeout_seconds: int = 60,
        call_purpose: CallPurpose = CallPurpose.REVIEW,
        attempt_counter: list[int] | None = None,
        max_total_calls: int = 6,
        hunk_index: int | None = None,
    ) -> tuple[ProviderResponse | None, list[ModelInvocationRecord]]:
        counter = attempt_counter if attempt_counter is not None else [0]
        records: list[ModelInvocationRecord] = []
        payload_hash = hashlib.sha256(f"{system_prompt}\n{user_prompt}".encode()).hexdigest()

        last_resp: ProviderResponse | None = None
        for retry_idx in range(self.max_retries + 1):
            if counter[0] >= max_total_calls:
                break
            self._pace()
            counter[0] += 1
            attempt_no = counter[0]
            purpose = call_purpose if retry_idx == 0 else CallPurpose.THU_LAI
            started = datetime.now(UTC)

            resp = self.provider.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_cls=schema_cls,
                model_name=model_name,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                timeout_seconds=timeout_seconds,
            )
            finished = datetime.now(UTC)
            records.append(
                ModelInvocationRecord(
                    attempt_number=attempt_no,
                    call_purpose=purpose,
                    provider_name=self.provider.provider_name,
                    resolved_model_name=resp.resolved_model_name,
                    payload_hash=payload_hash,
                    call_status=resp.call_status,
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                    usage_source=resp.usage_source,
                    estimated_cost_usd=0.0 if resp.usage_source != UsageSource.KHONG_CO else None,
                    latency_ms=resp.latency_ms,
                    started_at=started,
                    finished_at=finished,
                    hunk_index=hunk_index,
                )
            )
            last_resp = resp
            if resp.call_status == CallStatus.THANH_CONG:
                return resp, records
            if not resp.retryable or retry_idx >= self.max_retries:
                return resp, records
            self._sleep(self.base_backoff_seconds * (2**retry_idx))

        return last_resp, records
