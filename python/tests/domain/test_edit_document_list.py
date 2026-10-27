"""The label a Studio document is listed under."""

from thoth_control_plane.domain.edit_document_list import document_label, document_state


def test_the_label_is_the_first_non_empty_text_heading() -> None:
    document = {
        "clips": [
            {"kind": "video"},
            {"kind": "text", "heading": "  "},
            {"kind": "text", "heading": " Kucing buka kulkas "},
        ]
    }
    assert document_label(document) == "Kucing buka kulkas"


def test_no_heading_is_untitled_and_long_headings_are_cut() -> None:
    assert document_label({"clips": []}) == "Untitled draft"
    assert document_label({}) == "Untitled draft"
    assert len(document_label({"clips": [{"kind": "text", "heading": "x" * 300}]})) == 120


def test_a_document_with_no_render_or_review_is_a_draft() -> None:
    assert document_state(3, render=None, decision=None, reviewed=False) == "draft"


def test_review_events_on_the_latest_revision_put_it_in_review_until_approved() -> None:
    assert document_state(3, render=None, decision=None, reviewed=True) == "in_review"
    assert document_state(3, render=None, decision="changes_requested", reviewed=True) == (
        "in_review"
    )
    assert document_state(3, render=None, decision="approved", reviewed=True) == "approved"


def test_a_render_in_progress_wins_whatever_revision_it_renders() -> None:
    for status in ("preparing", "rendering", "finalizing"):
        assert document_state(3, render=(status, 2), decision="approved", reviewed=True) == (
            "rendering"
        )


def test_only_a_finished_render_of_the_latest_revision_counts_as_rendered() -> None:
    assert document_state(3, render=("completed", 3), decision=None, reviewed=False) == "rendered"
    # An older revision's video no longer shows this draft.
    assert document_state(3, render=("completed", 2), decision=None, reviewed=False) == "draft"
    for status in ("failed", "cancelled"):
        assert document_state(3, render=(status, 3), decision="approved", reviewed=True) == (
            "approved"
        )
