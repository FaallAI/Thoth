"""Credits read from captions and frame text."""

from __future__ import annotations

from thoth_control_plane.attribution import credit


def test_caption_conventions_name_the_account_and_platform() -> None:
    assert credit.text_rule_credit("Viral [📸 @kreator.asli] lokasi") == (
        "kreator.asli",
        "instagram",
    )
    assert credit.text_rule_credit("cr tt/@abc_def") == ("abc_def", "tiktok")
    assert credit.text_rule_credit("📸 @ig.user tt/tt.user") == ("ig.user", "instagram")
    assert credit.text_rule_credit("📸 @akun") is None
    assert credit.text_rule_credit("scott/plain text") is None


def test_caption_handles_skip_a_reply_target_and_placeholders() -> None:
    text = "Membalas @fan.account video dari @vincentius.christ76. dan @akun @Vincentius.Christ76"

    assert credit.text_handles(text) == ["vincentius.christ76"]
    assert credit.text_handles("mail me at a@b.com") == []


def test_frame_text_yields_at_handles_and_bare_watermark_usernames() -> None:
    lines = ["♪ vincentius.christ76   detikjatim", "www.tiktok.com", "0:15 / 1:30", "@DetikJatim"]

    assert credit.frame_handles(lines) == ["vincentius.christ76", "DetikJatim"]


def test_credit_options_never_offer_the_reposting_account() -> None:
    options = credit.credit_options(
        ["Vincentius.Christ76"], ["vincentius.christ76", "detikjatim", "detik_jatim"], "detikjatim"
    )

    assert options == ["Vincentius.Christ76"]
    assert credit.credit_options([], ["detik.jatim"], "detikjatim") == []


def test_frame_text_tolerates_a_space_after_the_at_sign() -> None:
    assert credit.frame_handles(["TikTok", "@ manicsofficials"]) == ["manicsofficials"]
    assert credit.text_handles("email @ home") == []  # captions keep the strict rule


def test_near_variants_come_only_from_the_evidence() -> None:
    options = ["ferdysambo_offcial", "ferdysambo_official", "other.account", "FerdySambo_Offcial"]

    assert credit.near_variants("ferdysambo_offcial", options) == ["ferdysambo_official"]
    assert credit.near_variants("other.account", options) == []
