from __future__ import annotations

import os
import time
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from diffguard.domain import CallStatus
from diffguard.llm.base import ProviderResponse, compute_usage


class GeminiProvider:
    provider_name = "gemini"

    def __init__(self, api_key: str | None = None, client: Any = None) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY") or ""
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        self._client = genai.Client(api_key=self._api_key)
        return self._client

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_cls: type[BaseModel],
        model_name: str = "gemini-2.5-flash",
        temperature: float = 0.1,
        max_output_tokens: int = 4096,
        timeout_seconds: int = 60,
    ) -> ProviderResponse:
        t0 = time.perf_counter()
        try:
            client = self._get_client()
            cfg = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                response_mime_type="application/json",
                response_schema=schema_cls,
            )
            resp = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=cfg,
            )
        except genai_errors.APIError as exc:
            ms = int((time.perf_counter() - t0) * 1000)
            code = getattr(exc, "code", None)
            if code in (408, 504):
                return ProviderResponse(
                    call_status=CallStatus.QUA_HAN,
                    resolved_model_name=model_name,
                    latency_ms=ms,
                    error_detail=str(exc),
                    retryable=True,
                )
            retryable = code in (429, 500, 502, 503)
            return ProviderResponse(
                call_status=CallStatus.LOI_DICH_VU,
                resolved_model_name=model_name,
                latency_ms=ms,
                error_detail=str(exc),
                retryable=retryable,
            )
        except TimeoutError as exc:
            ms = int((time.perf_counter() - t0) * 1000)
            return ProviderResponse(
                call_status=CallStatus.QUA_HAN,
                resolved_model_name=model_name,
                latency_ms=ms,
                error_detail=str(exc),
                retryable=True,
            )
        except Exception as exc:
            ms = int((time.perf_counter() - t0) * 1000)
            return ProviderResponse(
                call_status=CallStatus.LOI_DICH_VU,
                resolved_model_name=model_name,
                latency_ms=ms,
                error_detail=str(exc),
                retryable=False,
            )

        ms = int((time.perf_counter() - t0) * 1000)
        usage = getattr(resp, "usage_metadata", None)
        in_tok, out_tok, u_src = compute_usage(
            getattr(usage, "prompt_token_count", None) if usage else None,
            getattr(usage, "candidates_token_count", None) if usage else None,
        )
        raw_text = getattr(resp, "text", None) or ""
        if not raw_text.strip():
            return ProviderResponse(
                call_status=CallStatus.SAI_SCHEMA,
                resolved_model_name=model_name,
                raw_text=raw_text,
                input_tokens=in_tok,
                output_tokens=out_tok,
                usage_source=u_src,
                latency_ms=ms,
                error_detail="Empty or safety-refused Gemini response",
                retryable=False,
            )
        try:
            parsed = schema_cls.model_validate_json(raw_text)
        except ValidationError as exc:
            return ProviderResponse(
                call_status=CallStatus.SAI_SCHEMA,
                resolved_model_name=model_name,
                raw_text=raw_text,
                input_tokens=in_tok,
                output_tokens=out_tok,
                usage_source=u_src,
                latency_ms=ms,
                error_detail=f"Schema validation failed: {exc.error_count()} errors",
                retryable=False,
            )
        return ProviderResponse(
            call_status=CallStatus.THANH_CONG,
            resolved_model_name=getattr(resp, "model_version", None) or model_name,
            parsed=parsed,
            raw_text=raw_text,
            input_tokens=in_tok,
            output_tokens=out_tok,
            usage_source=u_src,
            latency_ms=ms,
        )
