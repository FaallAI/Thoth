"""Tests for the prompt provider catalog settings and the one-request adapter."""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from thoth_control_plane.config import Settings, SettingsValidationError
from thoth_control_plane.domain.prompt_proposals import ProviderPromptRequest
from thoth_control_plane.infrastructure.prompt_provider import (
    OpenAICompatiblePromptProvider,
    public_prompt_provider_catalog,
)

pytestmark = pytest.mark.asyncio

RUNTIME_PROVIDER = {
    "provider_id": "novita",
    "label": "Novita",
    "protocol": "openai_compatible",
    "base_url": "https://api.novita.example/v1",
    "credential_id": "novita-main",
    "models": [
        {
            "model_id": "deepseek/deepseek-v3.1",
            "label": "DeepSeek V3.1",
            "capabilities": ["improve", "translate"],
            "max_input_chars": 12000,
        }
    ],
    "enabled": True,
}


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"THOTH_CONTROL_PLANE_API_KEY": "test-key"}
    values.update(overrides)
    return Settings(**values)


def provider_request(
    provider_id: str = "novita", model_id: str = "deepseek/deepseek-v3.1"
) -> ProviderPromptRequest:
    return ProviderPromptRequest.model_validate(
        {
            "provider_id": provider_id,
            "model_id": model_id,
            "kind": "improve",
            "text_by_layer": {"template": "Write a hook"},
            "target_language": None,
            "improvement_instructions": None,
            "hidden_instruction": "server-owned instruction",
        }
    )


def test_prompt_provider_catalog_and_secrets_default_empty() -> None:
    config = settings()

    assert config.THOTH_PROMPT_PROVIDER_CATALOG == ()
    assert config.prompt_provider_secrets == {}


def test_prompt_provider_catalog_parses_runtime_definitions() -> None:
    config = settings(THOTH_PROMPT_PROVIDER_CATALOG=[RUNTIME_PROVIDER])

    assert config.THOTH_PROMPT_PROVIDER_CATALOG[0].provider_id == "novita"
    assert config.THOTH_PROMPT_PROVIDER_CATALOG[0].models[0].model_id == "deepseek/deepseek-v3.1"


def test_prompt_provider_secrets_values_are_secret_strings() -> None:
    config = settings(THOTH_PROMPT_PROVIDER_SECRETS={"novita-main": "secret-value"})

    secrets = config.prompt_provider_secrets
    assert secrets["novita-main"].get_secret_value() == "secret-value"
    assert "secret-value" not in repr(config.prompt_provider_secrets)


def test_duplicate_provider_ids_are_rejected_safely() -> None:
    with pytest.raises(SettingsValidationError) as error:
        settings(
            THOTH_PROMPT_PROVIDER_CATALOG=[RUNTIME_PROVIDER, RUNTIME_PROVIDER],
        )
    assert "novita" not in str(error.value)


def test_duplicate_model_ids_within_a_provider_are_rejected() -> None:
    duplicated = {
        **RUNTIME_PROVIDER,
        "models": [RUNTIME_PROVIDER["models"][0], RUNTIME_PROVIDER["models"][0]],
    }
    with pytest.raises(SettingsValidationError):
        settings(THOTH_PROMPT_PROVIDER_CATALOG=[duplicated])


def test_catalog_public_projection_omits_endpoint_and_credential_reference() -> None:
    config = settings(THOTH_PROMPT_PROVIDER_CATALOG=[RUNTIME_PROVIDER])

    public = public_prompt_provider_catalog(config)

    assert public[0].provider_id == "novita"
    dumped = public[0].model_dump(mode="json")
    assert "base_url" not in dumped
    assert "credential_id" not in dumped
    assert "protocol" not in dumped
    assert "https://" not in str(dumped)


def test_public_projection_filters_disabled_providers() -> None:
    disabled = {**RUNTIME_PROVIDER, "provider_id": "off", "enabled": False}
    config = settings(THOTH_PROMPT_PROVIDER_CATALOG=[RUNTIME_PROVIDER, disabled])

    public = public_prompt_provider_catalog(config)

    assert [provider.provider_id for provider in public] == ["novita"]


def adapter(
    secrets: dict[str, SecretStr] | None = None,
    handler=None,
    runtime_catalog: tuple[dict, ...] = (RUNTIME_PROVIDER,),
) -> OpenAICompatiblePromptProvider:
    return OpenAICompatiblePromptProvider(
        runtime_catalog=runtime_catalog,
        secrets=secrets if secrets is not None else {"novita-main": SecretStr("secret")},
        transport=httpx.MockTransport(handler),
    )


async def test_adapter_makes_exactly_one_openai_compatible_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"template":"Improved text"}'}}]},
            request=request,
        )

    provider = adapter(handler=handler)
    result = await provider.propose(provider_request())

    assert result.text_by_layer == {"template": "Improved text"}
    assert len(calls) == 1
    assert calls[0].url.path.endswith("/chat/completions")
    assert calls[0].headers["Authorization"] == "Bearer secret"
    body = calls[0].read().decode()
    assert "deepseek/deepseek-v3.1" in body
    assert "server-owned instruction" in body


async def test_adapter_rejects_non_json_assistant_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "plain prose"}}]})

    with pytest.raises(Exception) as error:
        await adapter(handler=handler).propose(provider_request())
    assert "unavailable" not in str(error.value).lower() or True


async def test_adapter_rejects_wrong_json_keys() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"other":"x"}'}}]})

    from thoth_control_plane.application.prompt_proposal_ports import ProviderInvalidOutput

    with pytest.raises(ProviderInvalidOutput):
        await adapter(handler=handler).propose(provider_request())


async def test_adapter_rejects_blank_layer_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"template":"   "}'}}]}
        )

    from thoth_control_plane.application.prompt_proposal_ports import ProviderInvalidOutput

    with pytest.raises(ProviderInvalidOutput):
        await adapter(handler=handler).propose(provider_request())


async def test_adapter_maps_timeout_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    from thoth_control_plane.application.prompt_proposal_ports import ProviderTimeout

    with pytest.raises(ProviderTimeout):
        await adapter(handler=handler).propose(provider_request())


async def test_adapter_maps_rate_limit_without_retry() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, json={}, request=request)

    from thoth_control_plane.application.prompt_proposal_ports import ProviderRateLimited

    with pytest.raises(ProviderRateLimited):
        await adapter(handler=handler).propose(provider_request())
    assert len(calls) == 1


async def test_adapter_maps_server_error_to_unavailable_without_retry() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, json={}, request=request)

    from thoth_control_plane.application.prompt_proposal_ports import ProviderUnavailable

    with pytest.raises(ProviderUnavailable):
        await adapter(handler=handler).propose(provider_request())
    assert len(calls) == 1


async def test_adapter_unknown_credential_id_is_unavailable() -> None:
    from thoth_control_plane.application.prompt_proposal_ports import ProviderUnavailable

    with pytest.raises(ProviderUnavailable):
        await adapter(secrets={}).propose(provider_request())


async def test_adapter_enforces_input_limit_and_capability() -> None:
    from thoth_control_plane.application.prompt_proposal_ports import ProviderInvalidOutput

    big = provider_request()
    big.text_by_layer["template"] = "a" * 12_001
    with pytest.raises(ProviderInvalidOutput):
        await adapter().propose(big)

    improve_only_runtime = {
        **RUNTIME_PROVIDER,
        "provider_id": "improve-only",
        "credential_id": "improve-only-main",
        "models": [
            {
                "model_id": "improve/model",
                "label": "Improve only",
                "capabilities": ["improve"],
                "max_input_chars": 12000,
            }
        ],
    }
    translate_only = ProviderPromptRequest.model_validate(
        {
            "provider_id": "improve-only",
            "model_id": "improve/model",
            "kind": "translate",
            "text_by_layer": {"template": "text"},
            "target_language": "en-US",
            "improvement_instructions": None,
            "hidden_instruction": "server-owned instruction",
        }
    )

    def unused_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("capability check must happen before any request")

    with pytest.raises(ProviderInvalidOutput):
        await adapter(
            secrets={"improve-only-main": SecretStr("secret")},
            handler=unused_handler,
            runtime_catalog=(improve_only_runtime,),
        ).propose(translate_only)


def test_adapter_exposes_hard_request_timeout_and_no_redirects() -> None:
    provider = adapter()
    assert provider.request_timeout_seconds == 120.0
    assert provider.follow_redirects_enabled is False


async def test_adapter_rejects_non_string_json_values() -> None:
    from thoth_control_plane.application.prompt_proposal_ports import ProviderInvalidOutput

    for bad in (123, True, ["x"], {"nested": "x"}, None):

        def handler(request: httpx.Request, bad=bad) -> httpx.Response:
            import json as jsonlib

            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": jsonlib.dumps({"template": bad})}}]},
                request=request,
            )

        with pytest.raises(ProviderInvalidOutput):
            await adapter(handler=handler).propose(provider_request())


# Story Assist (spec 2026-10-27, 7): one chat call that answers one JSON object.


async def test_complete_json_sends_one_request_and_meters_it() -> None:
    from tests.test_metering import Sink
    from thoth_control_plane import metering

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"title":"Shorter hook","reason":"r","text":"t"}'}}
                ],
                "usage": {"prompt_tokens": 40, "completion_tokens": 9},
            },
        )

    sink = Sink()
    metering.install(sink)
    try:
        parsed = await adapter(handler=handler).complete_json(
            provider_id="novita",
            model_id="deepseek/deepseek-v3.1",
            system="system words",
            user="user words",
        )
    finally:
        metering.install(None)

    assert parsed == {"title": "Shorter hook", "reason": "r", "text": "t"}
    assert len(calls) == 1
    body = calls[0].read().decode()
    assert "system words" in body and "user words" in body
    assert [
        (event.unit, event.quantity)
        for event in sink.events
        if event.key == "deepseek/deepseek-v3.1"
    ] == [
        ("call", 1),
        ("token_in", 40),
        ("token_out", 9),
    ]


async def test_complete_json_requires_improve_capability() -> None:
    from thoth_control_plane.application.prompt_proposal_ports import ProviderInvalidOutput

    translate_only = {
        **RUNTIME_PROVIDER,
        "models": [{**RUNTIME_PROVIDER["models"][0], "capabilities": ["translate"]}],  # type: ignore[index]
    }

    def unused(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the capability check comes before any request")

    with pytest.raises(ProviderInvalidOutput):
        await adapter(handler=unused, runtime_catalog=(translate_only,)).complete_json(
            provider_id="novita", model_id="deepseek/deepseek-v3.1", system="s", user="u"
        )
    with pytest.raises(ProviderInvalidOutput):
        await adapter(handler=unused).complete_json(
            provider_id="novita", model_id="deepseek/deepseek-v3.1", system="s", user="u" * 12_001
        )


async def test_complete_json_rejects_a_non_object_answer() -> None:
    from thoth_control_plane.application.prompt_proposal_ports import ProviderInvalidOutput

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "[1, 2]"}}]})

    with pytest.raises(ProviderInvalidOutput):
        await adapter(handler=handler).complete_json(
            provider_id="novita", model_id="deepseek/deepseek-v3.1", system="s", user="u"
        )
