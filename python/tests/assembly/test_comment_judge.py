"""The comment judge (spec 2026-10-24, D2): Jev's relevant comments only, the noise check as
its fallback, never a failed content set."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from tests.assembly.support import comment, report
from tests.assembly.test_service import build
from thoth_control_plane.assembly.adapters.comment_judge import CRITERIA, JevCommentJudge
from thoth_control_plane.assembly.comment_judge import (
    KEEP_THRESHOLD,
    MAX_CANDIDATES,
    judge_inputs,
    judged,
)
from thoth_control_plane.assembly.comments import merge_comments
from thoth_control_plane.attribution.adapters.jev import JEV_MODEL, JEV_URL

RELEVANT = "Udara di Palangkaraya makin parah karena kebakaran lahan"
OFF_TOPIC = "Promo pulsa murah hubungi nomor ini sekarang juga"


class Judge:
    def __init__(self, answer: list[float] | Exception | None) -> None:
        self.answer, self.calls = answer, []

    async def keep_probabilities(self, post, headline, comments):
        self.calls.append((post, headline, list(comments)))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _candidates(count: int = 3):
    items = [comment(f"user{n}", f"{RELEVANT} {n}", likes=1000 - n) for n in range(count)]
    return merge_comments([("input", report(comments=items))], limit=MAX_CANDIDATES)


def test_the_inputs_are_the_texts_up_to_the_cap() -> None:
    # One report holds at most 50 comments; a replaced main merges two reports' worth.
    def items(prefix: str):
        return [
            comment(f"{prefix}{n}", f"{RELEVANT} {prefix}{n}", likes=500 - n) for n in range(40)
        ]

    reports = [("original", report(comments=items("o"))), ("input", report(comments=items("i")))]
    texts = judge_inputs("Kabut asap", "", merge_comments(reports, limit=80))
    assert texts is not None and len(texts) == MAX_CANDIDATES
    assert texts[0] == f"{RELEVANT} o0"


def test_no_post_text_or_no_comments_is_nothing_to_judge() -> None:
    assert judge_inputs("", " ", _candidates()) is None
    assert judge_inputs("Kabut asap", "", []) is None


def test_the_threshold_keeps_the_likes_order() -> None:
    candidates = _candidates(4)
    kept = judged(candidates, [0.9, KEEP_THRESHOLD - 0.01, KEEP_THRESHOLD, 0.1])
    assert [c.author for c in kept] == ["user0", "user2"]


@pytest.mark.parametrize(
    "answer", [None, RuntimeError("provider down"), [0.9]], ids=["none", "error", "short"]
)
def test_the_assembler_falls_back_to_the_noise_check(
    tmp_path, caplog: pytest.LogCaptureFixture, answer
) -> None:
    caplog.set_level(logging.WARNING)
    main = report(comments=[comment("a", RELEVANT, 5), comment("b", OFF_TOPIC, 9)])
    content = build(tmp_path, main, comments=Judge(answer))
    assert [c.author for c in content.comments] == ["b", "a"]
    assert any("comment judge unavailable" in r.getMessage() for r in caplog.records)


def test_the_assembler_keeps_only_what_jev_keeps(tmp_path) -> None:
    main = report(comments=[comment("a", RELEVANT, 5), comment("b", OFF_TOPIC, 9)])
    judge = Judge([0.04, 0.93])  # likes order: b (9) first, then a (5)
    content = build(tmp_path, main, comments=judge)
    assert [c.author for c in content.comments] == ["a"]
    assert judge.calls[0][2] == [OFF_TOPIC, RELEVANT]


def test_without_a_judge_port_the_noise_check_decides(tmp_path) -> None:
    main = report(comments=[comment("a", RELEVANT, 5), comment("b", "wkwkwk", 9)])
    assert [c.author for c in build(tmp_path, main).comments] == ["a"]


def _client(*responses: httpx.Response) -> tuple[httpx.AsyncClient, list[dict]]:
    sent: list[dict] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), sent


def _answers(*probabilities: float) -> httpx.Response:
    answers = {f"c{i}": {"noul": p} for i, p in enumerate(probabilities)}
    usage = {"input_tokens": 476, "output_tokens": 70, "cost": 0.00002}
    return httpx.Response(200, json={"answers": answers, "usage": usage})


@pytest.mark.asyncio
async def test_jev_gets_one_noul_question_per_comment_over_one_state() -> None:
    client, sent = _client(_answers(0.8, 0.1))
    judge = JevCommentJudge("synthetic-key", client)

    assert await judge.keep_probabilities("post", "headline", ["one", "two"]) == [0.8, 0.1]

    body = sent[0]
    assert body["model"] == JEV_MODEL
    assert body["state"]["comments"] == {"c0": "one", "c1": "two"}
    assert set(body["questions"]) == {"c0", "c1"}
    assert all(
        q["type"] == "noul" and q["criteria"] == CRITERIA for q in body["questions"].values()
    )
    assert "c1" in body["questions"]["c1"]["instructions"]
    assert JEV_URL.endswith("/decisions")


@pytest.mark.asyncio
async def test_jev_retries_once_then_answers_none() -> None:
    client, sent = _client(httpx.Response(500, json={}))
    judge = JevCommentJudge("synthetic-key", client)

    assert await judge.keep_probabilities("post", "", ["one"]) is None
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_a_missing_answer_is_retried_and_recovers() -> None:
    client, sent = _client(_answers(0.7), _answers(0.7, 0.2))
    judge = JevCommentJudge("synthetic-key", client)

    assert await judge.keep_probabilities("post", "", ["one", "two"]) == [0.7, 0.2]
    assert len(sent) == 2
