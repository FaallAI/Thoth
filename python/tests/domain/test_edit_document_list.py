"""The label a Studio document is listed under."""

from thoth_control_plane.domain.edit_document_list import document_label


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
