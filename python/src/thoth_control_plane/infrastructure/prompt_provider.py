"""Safe catalog projection and the one-request OpenAI-compatible adapter (C2)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from thoth_control_plane import metering
from thoth_control_plane.application.prompt_proposal_ports import (
    ProviderInvalidOutput,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from thoth_control_plane.config import PromptProviderRuntimeDefinition, Settings
from thoth_control_plane.domain.prompt_proposals import (
    PromptProviderDefinition,
    ProviderPromptRequest,
    ProviderPromptResult,
)

REQUEST_TIMEOUT_SECONDS = 120.0


def _loads_answer(content: str) -> Any:
    """The answer's JSON, unwrapped from one markdown code fence if the model added it.

    DeepSeek V3.1 on OpenRouter fences its JSON even when told to answer with JSON only.
    """
    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def public_prompt_provider_catalog(
    settings: Settings,
) -> tuple[PromptProviderDefinition, ...]:
    """Project the runtime catalog onto the browser-safe shape; no endpoints or credentials."""
    public: list[PromptProviderDefinition] = []
    for runtime in settings.THOTH_PROMPT_PROVIDER_CATALOG:
        if not runtime.enabled:
            continue
        public.append(
            PromptProviderDefinition.model_validate(
                {
                    "provider_id": runtime.provider_id,
                    "label": runtime.label,
                    "enabled": True,
                    "models": [model.model_dump(mode="json") for model in runtime.models],
                }
            )
        )
    return tuple(public)


class OpenAICompatiblePromptProvider:
    """Perform exactly one OpenAI-compatible chat-completions request per invocation."""

    def __init__(
        self,
        *,
        runtime_catalog: tuple[PromptProviderRuntimeDefinition, ...],
        secrets: dict[str, Any],
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        follow_redirects: bool = False,
    ) -> None:
        self._runtime_catalog = tuple(
            item
            if isinstance(item, PromptProviderRuntimeDefinition)
            else PromptProviderRuntimeDefinition.model_validate(item)
            for item in runtime_catalog
        )
        self._secrets = secrets
        self._transport = transport
        self._timeout = timeout
        self._follow_redirects = follow_redirects

    @property
    def request_timeout_seconds(self) -> float:
        return self._timeout

    @property
    def follow_redirects_enabled(self) -> bool:
        return self._follow_redirects

    async def propose(self, request: ProviderPromptRequest) -> ProviderPromptResult:
        runtime = self._resolve_runtime(request.provider_id)
        self._enforce_catalog(runtime, request)
        content = await self._chat(runtime, request.model_id, self._build_payload(request))
        return self._validate_output(request, content)

    async def complete_json(
        self, *, provider_id: str, model_id: str, system: str, user: str
    ) -> dict[str, Any]:
        """Story Assist (spec 2026-10-27, 7): one call answered with one JSON object.

        The model must offer `improve`, the capability Prompt Lab's rewrites use.
        """
        runtime = self._resolve_runtime(provider_id)
        model = next((model for model in runtime.models if model.model_id == model_id), None)
        if model is None:
            raise ProviderUnavailable()
        if "improve" not in model.capabilities or len(user) > model.max_input_chars:
            raise ProviderInvalidOutput()
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": f"{system}\nRespond with JSON only."},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
        content = await self._chat(runtime, model_id, payload)
        try:
            parsed = _loads_answer(content)
        except ValueError as error:
            raise ProviderInvalidOutput() from error
        if not isinstance(parsed, dict):
            raise ProviderInvalidOutput()
        return parsed

    async def _chat(
        self, runtime: PromptProviderRuntimeDefinition, model_id: str, payload: dict[str, Any]
    ) -> str:
        """Exactly one chat-completions request, metered; the answer's text content."""
        credential = self._secrets.get(runtime.credential_id)
        if credential is None or not credential.get_secret_value().strip():
            raise ProviderUnavailable()
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=self._follow_redirects,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{runtime.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {credential.get_secret_value()}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException as error:
            raise ProviderTimeout() from error
        except httpx.HTTPError as error:
            raise ProviderUnavailable() from error
        if response.status_code == 429:
            raise ProviderRateLimited()
        if response.status_code >= 400:
            raise ProviderUnavailable()
        usage = _usage(response)
        await metering.record_call(
            model_id,
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
        )
        return self._extract_content(response)

    def _resolve_runtime(self, provider_id: str) -> PromptProviderRuntimeDefinition:
        for runtime in self._runtime_catalog:
            if runtime.provider_id == provider_id and runtime.enabled:
                return runtime
        raise ProviderUnavailable()

    @staticmethod
    def _enforce_catalog(
        runtime: PromptProviderRuntimeDefinition, request: ProviderPromptRequest
    ) -> None:
        for model in runtime.models:
            if model.model_id == request.model_id:
                if request.kind not in model.capabilities:
                    raise ProviderInvalidOutput()
                total_chars = sum(len(text) for text in request.text_by_layer.values())
                if total_chars > model.max_input_chars:
                    raise ProviderInvalidOutput()
                return
        raise ProviderUnavailable()

    @staticmethod
    def _build_payload(request: ProviderPromptRequest) -> dict[str, Any]:
        layers_block = "\n\n".join(
            f"[{layer}]\n{text}" for layer, text in request.text_by_layer.items()
        )
        if request.kind == "translate":
            task = (
                f"Translate every labeled prompt layer into {request.target_language}. "
                "Return a JSON object whose keys are exactly the layer labels shown and "
                "whose values are the translated layer text."
            )
        else:
            task = (
                "Improve the labeled prompt layer. Return a JSON object whose keys are "
                "exactly the layer labels shown and whose values are the improved layer text."
            )
        instructions = (
            f"Improvement instructions: {request.improvement_instructions}"
            if request.improvement_instructions
            else ""
        )
        system = f"{request.hidden_instruction}\n{task}\nRespond with JSON only."
        user = f"{layers_block}\n{instructions}".strip()
        return {
            "model": request.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }

    @staticmethod
    def _extract_content(response: httpx.Response) -> str:
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ProviderInvalidOutput()
            return content
        except ProviderInvalidOutput:
            raise
        except Exception as error:
            raise ProviderInvalidOutput() from error

    def _validate_output(
        self, request: ProviderPromptRequest, content: str
    ) -> ProviderPromptResult:
        try:
            parsed = _loads_answer(content)
            if not isinstance(parsed, dict):
                raise ProviderInvalidOutput()
            if set(parsed) != set(request.text_by_layer):
                raise ProviderInvalidOutput()
            for layer in request.text_by_layer:
                if not isinstance(parsed[layer], str):
                    raise ProviderInvalidOutput()
            text_by_layer = {layer: parsed[layer] for layer in request.text_by_layer}
            return ProviderPromptResult.model_validate({"text_by_layer": text_by_layer})
        except ProviderInvalidOutput:
            raise
        except Exception as error:
            raise ProviderInvalidOutput() from error


def _usage(response: httpx.Response) -> dict[str, Any]:
    """The token counts an OpenAI-compatible provider reported, when it did."""
    try:
        usage = response.json().get("usage")
    except (ValueError, AttributeError):
        return {}
    return usage if isinstance(usage, dict) else {}
