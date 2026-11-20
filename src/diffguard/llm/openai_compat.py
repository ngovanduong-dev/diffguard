from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from diffguard.domain import CallStatus
from diffguard.llm.base import ProviderResponse, compute_usage


def _extract_json_block(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s


class OpenAICompatProvider:
    def __init__(
        self,
        provider_name: str = "groq",
        base_url: str = "https://api.groq.com/openai/v1",
        api_key: str | None = None,
        env_var: str = "GROQ_API_KEY",
        http_client: httpx.Client | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key if api_key is not None else os.environ.get(env_var, "")
        self._client = http_client

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_cls: type[BaseModel],
        model_name: str = "llama-3.3-70b-versatile",
        temperature: float = 0.1,
        max_output_tokens: int = 4096,
        timeout_seconds: int = 60,
    ) -> ProviderResponse:
        if not self._api_key and self.provider_name not in ("vllm", "ollama"):
            return ProviderResponse(
                call_status=CallStatus.LOI_DICH_VU,
                resolved_model_name=model_name,
                error_detail=f"Missing API key for provider {self.provider_name}",
                retryable=False,
            )

        schema_json = json.dumps(schema_cls.model_json_schema())
        sys_full = f"{system_prompt}\n\nReturn ONLY valid JSON conforming to schema:\n{schema_json}"
        payload: dict[str, Any] = {
            "model": model_name,
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": sys_full},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        t0 = time.perf_counter()
        client = self._client or httpx.Client(timeout=float(timeout_seconds))
        owns_client = self._client is None
        try:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=float(timeout_seconds),
            )
        except httpx.TimeoutException as exc:
            ms = int((time.perf_counter() - t0) * 1000)
            return ProviderResponse(
                call_status=CallStatus.QUA_HAN,
                resolved_model_name=model_name,
                latency_ms=ms,
                error_detail=str(exc),
                retryable=True,
            )
        except httpx.HTTPError as exc:
            ms = int((time.perf_counter() - t0) * 1000)
            return ProviderResponse(
                call_status=CallStatus.LOI_DICH_VU,
                resolved_model_name=model_name,
                latency_ms=ms,
                error_detail=str(exc),
                retryable=True,
            )
        finally:
            if owns_client:
                client.close()

        ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code in (429, 500, 502, 503, 504):
            status = CallStatus.QUA_HAN if resp.status_code == 504 else CallStatus.LOI_DICH_VU
            return ProviderResponse(
                call_status=status,
                resolved_model_name=model_name,
                latency_ms=ms,
                error_detail=f"HTTP {resp.status_code}: {resp.text[:300]}",
                retryable=True,
            )
        if resp.status_code >= 400:
            return ProviderResponse(
                call_status=CallStatus.LOI_DICH_VU,
                resolved_model_name=model_name,
                latency_ms=ms,
                error_detail=f"HTTP {resp.status_code}: {resp.text[:300]}",
                retryable=False,
            )

        try:
            data = resp.json()
        except ValueError as exc:
            return ProviderResponse(
                call_status=CallStatus.SAI_SCHEMA,
                resolved_model_name=model_name,
                raw_text=resp.text,
                latency_ms=ms,
                error_detail=f"Non-JSON HTTP body: {exc}",
                retryable=False,
            )

        usage = data.get("usage") or {}
        in_tok, out_tok, u_src = compute_usage(usage.get("prompt_tokens"), usage.get("completion_tokens"))
        choices = data.get("choices") or []
        msg = choices[0].get("message", {}) if choices else {}
        if msg.get("refusal"):
            return ProviderResponse(
                call_status=CallStatus.SAI_SCHEMA,
                resolved_model_name=str(data.get("model") or model_name),
                raw_text=str(msg.get("refusal")),
                input_tokens=in_tok,
                output_tokens=out_tok,
                usage_source=u_src,
                latency_ms=ms,
                error_detail="Model refusal",
                retryable=False,
            )
        raw_content = _extract_json_block(str(msg.get("content") or ""))
        if not raw_content:
            return ProviderResponse(
                call_status=CallStatus.SAI_SCHEMA,
                resolved_model_name=str(data.get("model") or model_name),
                input_tokens=in_tok,
                output_tokens=out_tok,
                usage_source=u_src,
                latency_ms=ms,
                error_detail="Empty model completion content",
                retryable=False,
            )
        try:
            parsed = schema_cls.model_validate_json(raw_content)
        except ValidationError as exc:
            return ProviderResponse(
                call_status=CallStatus.SAI_SCHEMA,
                resolved_model_name=str(data.get("model") or model_name),
                raw_text=raw_content,
                input_tokens=in_tok,
                output_tokens=out_tok,
                usage_source=u_src,
                latency_ms=ms,
                error_detail=f"Schema validation error: {exc.error_count()} errors",
                retryable=False,
            )

        return ProviderResponse(
            call_status=CallStatus.THANH_CONG,
            resolved_model_name=str(data.get("model") or model_name),
            parsed=parsed,
            raw_text=raw_content,
            input_tokens=in_tok,
            output_tokens=out_tok,
            usage_source=u_src,
            latency_ms=ms,
        )
