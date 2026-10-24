"""Which comments are more than noise: the free deterministic check (spec 2026-10-24, D1)."""

from __future__ import annotations

import pytest

from thoth_control_plane.acquisition.substance import is_substantive


@pytest.mark.parametrize(
    "text",
    [
        "FYI, ISPU 1533 itu juga setelah salah satu parameter dihide",
        "masih parahh yaa mint 🥀 kasihan warganya",
        "@fadlizon Udah dibuatin puisi sama bapak ini",
        # Short but meaningful, and among the most liked on stored reports (2026-10-24 data).
        "dibayar itu",
        "curiga suaminya",
        "Negara aneh😂",
        "Astaghfirullah😢",
        "maksudnya gimana?",
        "kaltim juga ni",
    ],
)
def test_a_comment_with_a_real_word_passes(text: str) -> None:
    assert is_substantive(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "wkwkwkwk",
        "WKWK HAHAHA awokawok",
        "😂😂😂😂",
        "👏👏👏",
        "first",
        "Mantap",
        "mantap keren semangat",
        "omg🔥",
        "👏 yes",
        "@user_001 @user_002",
        "@rockygerungmenulis hahhahaha",
        "https://x.com/bagindo_kopi/status/2113210000000000000",
    ],
)
def test_noise_does_not(text: str) -> None:
    assert not is_substantive(text)
