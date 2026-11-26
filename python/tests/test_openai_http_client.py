"""openai 3 moved to HTTPX2, while agno 3.2 passes on only an `httpx` client and drops any other
with a warning (2026-11-26). Our provider adapters own an `httpx.AsyncClient` so it closes on the
loop that made it; these tests prove openai 3 still sends through it, the path openai calls its
legacy client. When a bump breaks this, move the adapters to `httpx2` and agno's support for it."""

import httpx
import pytest

openai = pytest.importorskip("openai")
like = pytest.importorskip("agno.models.openai.like")

COMPLETION = {
    "id": "c",
    "object": "chat.completion",
    "created": 0,
    "model": "m",
    "choices": [
        {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}
    ],
}


async def test_agno_hands_our_httpx_client_to_openai_and_openai_sends_through_it() -> None:
    seen: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=COMPLETION)

    http = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    model = like.OpenAILike(id="m", api_key="k", base_url="http://llm.test/v1", http_client=http)
    client = model.get_async_client()
    try:
        assert client._client is http
        reply = await client.chat.completions.create(
            model="m", messages=[{"role": "user", "content": "hi"}]
        )
    finally:
        await http.aclose()
    assert reply.choices[0].message.content == "ok"
    assert seen == ["http://llm.test/v1/chat/completions"]
